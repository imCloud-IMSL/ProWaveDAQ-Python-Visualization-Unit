#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ 即時資料可視化系統 - 主控制程式
整合 DAQ、Web、CSV、SQL 四者運作
"""

import os
import sys
import time
import threading
import queue
import configparser
import logging
import argparse
import csv
import numpy as np
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from flask import Flask, render_template, request, jsonify, send_from_directory

from prowavedaq import ProWaveDAQ
from csv_writer import CSVWriter
from sql_uploader import SQLUploader

try:
    from logger import info, debug, error, warning
except ImportError:
    def info(msg): print(f"[INFO] {msg}")
    def debug(msg): print(f"[Debug] {msg}")
    def error(msg): print(f"[Error] {msg}")
    def warning(msg): print(f"[Warning] {msg}")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
os.chdir(PROJECT_ROOT)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

app = Flask(__name__, template_folder="templates", static_folder="static")
log = logging.getLogger("werkzeug")
log.setLevel(logging.ERROR)

# ==========================================
# 全域變數與資料結構 (優化核心)
# ==========================================

# 1. 網頁顯示專用佇列 (Web Visualization Queue)
web_data_queue: "queue.Queue[List[float]]" = queue.Queue(maxsize=10000)

# 2. 降頻比例 (Downsampling Ratio)
WEB_DOWNSAMPLE_RATIO = 50

# 3. 資料流佇列 (Raw Data Queues)
csv_data_queue: "queue.Queue[List[float]]" = queue.Queue(maxsize=1000)
sql_data_queue: "queue.Queue[List[float]]" = queue.Queue(maxsize=1000)

# 4. 控制旗標與物件
is_collecting = False
data_lock = threading.Lock()

collection_thread: Optional[threading.Thread] = None
csv_writer_thread: Optional[threading.Thread] = None
sql_writer_thread: Optional[threading.Thread] = None

daq_instance: Optional[ProWaveDAQ] = None
csv_writer_instance: Optional[CSVWriter] = None
sql_uploader_instance: Optional[SQLUploader] = None

data_counter = 0
collection_start_time: Optional[datetime] = None
current_sample_rate: int = 7812

target_size = 0
current_data_size = 0
sql_target_size = 0
sql_current_data_size = 0
sql_enabled = False
sql_config: Dict[str, str] = {}
sql_upload_interval = 0
sql_temp_dir = None
sql_current_temp_file = None
sql_temp_file_lock = threading.Lock()
sql_sample_count = 0
sql_start_time: Optional[datetime] = None


# ==========================================
# 核心邏輯：資料更新與處理
# ==========================================

def update_realtime_data(data: List[float]) -> None:
    """
    更新即時資料 (針對 Web 顯示進行降頻處理)
    """
    global web_data_queue, WEB_DOWNSAMPLE_RATIO, data_counter

    if web_data_queue.full():
        try:
            for _ in range(10):
                web_data_queue.get_nowait()
        except queue.Empty:
            pass

    channels = 3
    step = channels * WEB_DOWNSAMPLE_RATIO
    
    downsampled_chunk = []
    
    for i in range(0, len(data), step):
        if i + channels <= len(data):
            downsampled_chunk.extend(data[i : i + channels])

    if downsampled_chunk:
        with data_lock:
            web_data_queue.put(downsampled_chunk)
            
    data_counter += len(data)


# ==========================================
# Flask 路由 (API)
# ==========================================

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/files_page")
def files_page():
    return render_template("files.html")

@app.route("/data")
def get_data():
    """前端輪詢 API"""
    global web_data_queue, current_sample_rate, is_collecting, data_counter, collection_start_time

    new_data = []
    with data_lock:
        while not web_data_queue.empty():
            try:
                chunk = web_data_queue.get_nowait()
                new_data.extend(chunk)
            except queue.Empty:
                break
    
    response_data = {
        "success": True,
        "data": new_data,
        "counter": data_counter,
        "sample_rate": current_sample_rate,
        "is_collecting": is_collecting
    }

    if collection_start_time:
        response_data["start_time"] = collection_start_time.isoformat()

    return jsonify(response_data)

@app.route("/status")
def get_status():
    """頁面重整時恢復狀態用"""
    global is_collecting, data_counter
    return jsonify({
        "success": True, 
        "is_collecting": is_collecting, 
        "counter": data_counter
    })

@app.route("/sql_config")
def get_sql_config():
    """取得 SQL 設定"""
    try:
        ini_file_path = "API/sql.ini"
        config = configparser.ConfigParser()
        config.read(ini_file_path, encoding="utf-8")
        sql_config = {
            "enabled": False, "host": "localhost", "port": "3306",
            "user": "root", "password": "", "database": "prowavedaq",
        }
        if config.has_section("SQLServer"):
            sql_config["enabled"] = config.getboolean("SQLServer", "enabled", fallback=False)
            sql_config["host"] = config.get("SQLServer", "host", fallback="localhost")
            sql_config["port"] = config.get("SQLServer", "port", fallback="3306")
            sql_config["user"] = config.get("SQLServer", "user", fallback="root")
            sql_config["password"] = config.get("SQLServer", "password", fallback="")
            sql_config["database"] = config.get("SQLServer", "database", fallback="prowavedaq")
        return jsonify({"success": True, "sql_config": sql_config})
    except Exception as e:
        return jsonify({"success": False, "message": str(e), "sql_config": {}})

@app.route("/config", methods=["GET", "POST"])
def config():
    """設定檔管理"""
    ini_dir = "API"
    prodaq_ini = os.path.join(ini_dir, "ProWaveDAQ.ini")
    csv_ini = os.path.join(ini_dir, "csv.ini")
    sql_ini = os.path.join(ini_dir, "sql.ini")

    if request.method == "POST":
        try:
            prodaq_config = configparser.ConfigParser()
            prodaq_config.read(prodaq_ini, encoding="utf-8")
            if not prodaq_config.has_section("ProWaveDAQ"):
                prodaq_config.add_section("ProWaveDAQ")
            prodaq_config.set("ProWaveDAQ", "serialPort", request.form.get("prodaq_serialPort", "/dev/ttyUSB0"))
            prodaq_config.set("ProWaveDAQ", "baudRate", request.form.get("prodaq_baudRate", "3000000"))
            prodaq_config.set("ProWaveDAQ", "sampleRate", request.form.get("prodaq_sampleRate", "7812"))
            prodaq_config.set("ProWaveDAQ", "slaveID", request.form.get("prodaq_slaveID", "1"))
            
            csv_config = configparser.ConfigParser()
            csv_config.read(csv_ini, encoding="utf-8")
            if not csv_config.has_section("DumpUnit"):
                csv_config.add_section("DumpUnit")
            csv_config.set("DumpUnit", "second", request.form.get("csv_second", "60"))

            sql_config = configparser.ConfigParser()
            sql_config.read(sql_ini, encoding="utf-8")
            if not sql_config.has_section("SQLServer"):
                sql_config.add_section("SQLServer")
            if not sql_config.has_section("DumpUnit"):
                sql_config.add_section("DumpUnit")
            sql_config.set("SQLServer", "enabled", request.form.get("sql_enabled", "false"))
            sql_config.set("SQLServer", "host", request.form.get("sql_host", "localhost"))
            sql_config.set("SQLServer", "port", request.form.get("sql_port", "3306"))
            sql_config.set("SQLServer", "user", request.form.get("sql_user", "root"))
            sql_config.set("SQLServer", "password", request.form.get("sql_password", ""))
            sql_config.set("SQLServer", "database", request.form.get("sql_database", "prowavedaq"))
            sql_config.set("DumpUnit", "second", request.form.get("sql_second", "600"))

            with open(prodaq_ini, "w", encoding="utf-8") as f:
                prodaq_config.write(f)
            with open(csv_ini, "w", encoding="utf-8") as f:
                csv_config.write(f)
            with open(sql_ini, "w", encoding="utf-8") as f:
                sql_config.write(f)
            return jsonify({"success": True, "message": "設定檔已儲存"})
        except Exception as e:
            return jsonify({"success": False, "message": str(e)})

    # GET 請求
    try:
        prodaq_config = configparser.ConfigParser()
        prodaq_config.read(prodaq_ini, encoding="utf-8")
        prodaq_data = {
            "serialPort": prodaq_config.get("ProWaveDAQ", "serialPort", fallback="/dev/ttyUSB0"),
            "baudRate": prodaq_config.get("ProWaveDAQ", "baudRate", fallback="3000000"),
            "sampleRate": prodaq_config.get("ProWaveDAQ", "sampleRate", fallback="7812"),
            "slaveID": prodaq_config.get("ProWaveDAQ", "slaveID", fallback="1"),
        }

        csv_config = configparser.ConfigParser()
        csv_config.read(csv_ini, encoding="utf-8")
        csv_data = {
            "second": csv_config.get("DumpUnit", "second", fallback="60")
        }

        sql_config_parser = configparser.ConfigParser()
        sql_config_parser.read(sql_ini, encoding="utf-8")
        sql_data = {
            "enabled": sql_config_parser.getboolean("SQLServer", "enabled", fallback=False) if sql_config_parser.has_section("SQLServer") else False,
            "host": sql_config_parser.get("SQLServer", "host", fallback="localhost") if sql_config_parser.has_section("SQLServer") else "localhost",
            "port": sql_config_parser.get("SQLServer", "port", fallback="3306") if sql_config_parser.has_section("SQLServer") else "3306",
            "user": sql_config_parser.get("SQLServer", "user", fallback="root") if sql_config_parser.has_section("SQLServer") else "root",
            "password": sql_config_parser.get("SQLServer", "password", fallback="") if sql_config_parser.has_section("SQLServer") else "",
            "database": sql_config_parser.get("SQLServer", "database", fallback="prowavedaq") if sql_config_parser.has_section("SQLServer") else "prowavedaq",
            "sql_second": sql_config_parser.get("DumpUnit", "second", fallback="600") if sql_config_parser.has_section("DumpUnit") else "600",
        }

        return render_template("config.html", prodaq_data=prodaq_data, csv_data=csv_data, sql_data=sql_data)
    except Exception as e:
        return render_template("config.html", prodaq_data={}, csv_data={}, sql_data={})

@app.route("/start", methods=["POST"])
def start_collection():
    """啟動資料收集"""
    global is_collecting, collection_thread, csv_writer_thread, sql_writer_thread
    global daq_instance, csv_writer_instance, sql_uploader_instance
    global target_size, current_data_size, data_counter
    global sql_target_size, sql_current_data_size, sql_enabled, sql_config
    global sql_upload_interval, sql_temp_dir, sql_current_temp_file
    global sql_start_time, sql_sample_count
    global csv_data_queue, sql_data_queue, web_data_queue
    global collection_start_time, current_sample_rate

    if is_collecting:
        return jsonify({"success": False, "message": "資料收集已在執行中"})

    try:
        data = request.get_json()
        label = data.get("label", "") if data else ""
        csv_enabled = data.get("csv_enabled", True) if data else True

        if not label:
            return jsonify({"success": False, "message": "請提供資料標籤"})

        with data_lock:
            with web_data_queue.mutex:
                web_data_queue.queue.clear()
            with csv_data_queue.mutex:
                csv_data_queue.queue.clear()
            with sql_data_queue.mutex:
                sql_data_queue.queue.clear()
                
            data_counter = 0
            current_data_size = 0
            sql_current_data_size = 0
            collection_start_time = datetime.now()
            sql_sample_count = 0
            sql_start_time = None

        csv_ini_path = "API/csv.ini"
        csv_config = configparser.ConfigParser()
        csv_config.read(csv_ini_path, encoding="utf-8")
        save_unit = csv_config.getint("DumpUnit", "second", fallback=5) if csv_config.has_section("DumpUnit") else 5

        sql_ini_file_path = "API/sql.ini"
        sql_config_parser = configparser.ConfigParser()
        sql_config_parser.read(sql_ini_file_path, encoding="utf-8")
        
        sql_upload_interval = 0
        if sql_config_parser.has_section("DumpUnit"):
            sql_upload_interval = sql_config_parser.getint("DumpUnit", "second", fallback=0)
        if sql_upload_interval <= 0:
            sql_upload_interval = save_unit

        sql_enabled_ini = sql_config_parser.getboolean("SQLServer", "enabled", fallback=False) if sql_config_parser.has_section("SQLServer") else False
        sql_config_ini = {
            "host": "localhost",
            "port": "3306",
            "user": "root",
            "password": "",
            "database": "prowavedaq",
        }

        if sql_config_parser.has_section("SQLServer"):
            sql_config_ini["host"] = sql_config_parser.get("SQLServer", "host", fallback="localhost")
            sql_config_ini["port"] = sql_config_parser.get("SQLServer", "port", fallback="3306")
            sql_config_ini["user"] = sql_config_parser.get("SQLServer", "user", fallback="root")
            sql_config_ini["password"] = sql_config_parser.get("SQLServer", "password", fallback="")
            sql_config_ini["database"] = sql_config_parser.get("SQLServer", "database", fallback="prowavedaq")

        if data and "sql_enabled" in data:
            sql_enabled = data.get("sql_enabled", False)
            if sql_enabled:
                sql_config = {
                    "host": data.get("sql_host", sql_config_ini["host"]),
                    "port": data.get("sql_port", sql_config_ini["port"]),
                    "user": data.get("sql_user", sql_config_ini["user"]),
                    "password": data.get("sql_password", sql_config_ini["password"]),
                    "database": data.get("sql_database", sql_config_ini["database"]),
                }
            else:
                sql_config = sql_config_ini.copy()
        else:
            sql_enabled = sql_enabled_ini
            sql_config = sql_config_ini.copy()

        daq_instance = ProWaveDAQ()
        daq_instance.init_devices("API/ProWaveDAQ.ini")
        sample_rate = daq_instance.get_sample_rate()
        current_sample_rate = sample_rate
        channels = 3

        expected_samples_per_second = sample_rate * channels
        target_size = save_unit * expected_samples_per_second
        sql_target_size = sql_upload_interval * expected_samples_per_second

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        folder = f"{timestamp}_{label}"
        output_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ", folder)
        
        csv_writer_instance = None
        if csv_enabled:
            # 只有在啟用 CSV 時才建立資料夾
            os.makedirs(output_path, exist_ok=True)
            csv_writer_instance = CSVWriter(channels, output_path, label, sample_rate)

        sql_uploader_instance = None
        sql_temp_dir = None
        sql_current_temp_file = None
        sql_start_time = datetime.now()

        if sql_enabled:
            try:
                # 如果 CSV 未啟用但 SQL 啟用，也需要建立資料夾來存放 SQL 暫存檔
                if not csv_enabled:
                    os.makedirs(output_path, exist_ok=True)
                sql_uploader_instance = SQLUploader(channels, label, sql_config)
                sql_temp_dir = os.path.join(output_path, ".sql_temp")
                os.makedirs(sql_temp_dir, exist_ok=True)
                
                temp_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                sql_current_temp_file = os.path.join(sql_temp_dir, f"{temp_timestamp}_sql_temp.csv")
                with open(sql_current_temp_file, "w", newline="", encoding="utf-8") as f:
                    csv.writer(f).writerow(["Timestamp", "Channel_1(X)", "Channel_2(Y)", "Channel_3(Z)"])
            except Exception as e:
                return jsonify({"success": False, "message": f"SQL 上傳器初始化失敗: {str(e)}"})

        is_collecting = True

        collection_thread = threading.Thread(target=collection_loop, daemon=True)
        collection_thread.start()

        if csv_writer_instance:
            csv_writer_thread = threading.Thread(target=csv_writer_loop, daemon=True)
            csv_writer_thread.start()

        if sql_uploader_instance and sql_enabled:
            sql_writer_thread = threading.Thread(target=sql_writer_loop, daemon=True)
            sql_writer_thread.start()

        daq_instance.start_reading()

        return jsonify({
            "success": True,
            "message": f"資料收集已啟動 (Rate: {sample_rate}Hz)"
        })

    except Exception as e:
        is_collecting = False
        error(f"Start failed: {e}")
        return jsonify({"success": False, "message": f"啟動失敗: {str(e)}"})

@app.route("/stop", methods=["POST"])
def stop_collection():
    """停止資料收集"""
    global is_collecting, collection_thread, daq_instance, collection_start_time

    if not is_collecting:
        return jsonify({"success": False, "message": "資料收集未在執行中"})

    try:
        if daq_instance:
            daq_instance.stop_reading()
        
        is_collecting = False
        collection_start_time = None

        cleanup_thread = threading.Thread(target=finalize_upload, daemon=True)
        cleanup_thread.start()

        return jsonify({"success": True, "message": "資料收集已停止"})

    except Exception as e:
        return jsonify({"success": False, "message": f"停止失敗: {str(e)}"})

@app.route("/files")
def list_files():
    """列出檔案和資料夾"""
    try:
        path = request.args.get("path", "")
        base_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ")
        if path:
            full_path = os.path.normpath(os.path.join(base_path, path))
            if not full_path.startswith(os.path.abspath(base_path)):
                return jsonify({"success": False})
        else:
            full_path = base_path
        
        if not os.path.exists(full_path):
            return jsonify({"success": False})
        
        items = []
        for item in sorted(os.listdir(full_path)):
            p = os.path.join(full_path, item)
            rp = os.path.join(path, item).replace("\\", "/") if path else item
            if os.path.isdir(p):
                items.append({"name": item, "type": "directory", "path": rp})
            else:
                items.append({"name": item, "type": "file", "path": rp, "size": os.path.getsize(p)})
        return jsonify({"success": True, "items": items, "current_path": path})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)})

@app.route("/download")
def download_file():
    """下載檔案"""
    try:
        path = request.args.get("path", "")
        if not path:
            return jsonify({"success": False})
        base_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ")
        full_path = os.path.normpath(os.path.join(base_path, path))
        if not full_path.startswith(os.path.abspath(base_path)):
            return jsonify({"success": False})
        if not os.path.exists(full_path) or os.path.isdir(full_path):
            return jsonify({"success": False})
        return send_from_directory(os.path.dirname(full_path), os.path.basename(full_path), as_attachment=True)
    except Exception as e:
        return jsonify({"success": False})

# ==========================================
# 背景工作函式 (Threads)
# ==========================================

def finalize_upload():
    """停止後的清理與剩餘資料上傳"""
    global collection_thread, csv_writer_thread, sql_writer_thread
    global csv_data_queue, sql_data_queue
    global sql_uploader_instance, sql_enabled, sql_temp_dir, sql_current_temp_file
    global csv_writer_instance

    if collection_thread and collection_thread.is_alive():
        collection_thread.join(timeout=2.0)
    
    if csv_writer_thread and csv_writer_thread.is_alive():
        start_t = time.time()
        while not csv_data_queue.empty() and (time.time() - start_t < 5):
            time.sleep(0.1)
    
    if sql_writer_thread and sql_writer_thread.is_alive():
        start_t = time.time()
        while not sql_data_queue.empty() and (time.time() - start_t < 5):
            time.sleep(0.1)

    time.sleep(0.5)

    if sql_uploader_instance and sql_enabled and sql_temp_dir:
        try:
            with sql_temp_file_lock:
                current_temp = sql_current_temp_file

            if current_temp and os.path.exists(current_temp):
                if csv_writer_instance:
                    csv_filename = csv_writer_instance.get_current_filename()
                    if csv_filename:
                        table_name = csv_filename
                    else:
                        table_name = None
                else:
                    table_name = None

                if sql_uploader_instance.upload_from_csv_file(current_temp, table_name):
                    try:
                        os.remove(current_temp)
                        info(f"停止時已上傳並刪除暫存檔案: {os.path.basename(current_temp)}")
                    except Exception as e:
                        warning(f"刪除暫存檔案失敗: {e}")
                else:
                    error(f"停止時上傳暫存檔案失敗: {os.path.basename(current_temp)}")

            if os.path.exists(sql_temp_dir):
                temp_files = [
                    f for f in os.listdir(sql_temp_dir)
                    if f.endswith("_sql_temp.csv")
                ]
                for temp_file in temp_files:
                    temp_file_path = os.path.join(sql_temp_dir, temp_file)
                    if os.path.exists(temp_file_path):
                        if csv_writer_instance:
                            csv_filename = csv_writer_instance.get_current_filename()
                            if csv_filename:
                                table_name = csv_filename
                            else:
                                table_name = None
                        else:
                            table_name = None

                        if sql_uploader_instance.upload_from_csv_file(temp_file_path, table_name):
                            try:
                                os.remove(temp_file_path)
                                info(f"停止時已上傳並刪除暫存檔案: {temp_file}")
                            except Exception as e:
                                warning(f"刪除暫存檔案失敗: {e}")
                        else:
                            error(f"停止時上傳暫存檔案失敗: {temp_file}")

                try:
                    if not os.listdir(sql_temp_dir):
                        os.rmdir(sql_temp_dir)
                except:
                    pass

        except Exception as e:
            error(f"停止時處理 SQL 暫存檔案發生錯誤: {e}")

    if csv_writer_instance:
        csv_writer_instance.close()

    if sql_uploader_instance:
        sql_uploader_instance.close()

    info("所有資源已安全關閉")

def collection_loop():
    """資料收集主迴圈"""
    global is_collecting, daq_instance, csv_data_queue, sql_data_queue
    global csv_writer_instance, sql_uploader_instance, sql_enabled

    while is_collecting:
        try:
            data = daq_instance.get_data()

            while data and len(data) > 0:
                update_realtime_data(data)

                if csv_writer_instance:
                    try:
                        csv_data_queue.put(data.copy(), block=False)
                    except queue.Full:
                        warning("CSV Queue Full")

                if sql_uploader_instance and sql_enabled:
                    try:
                        sql_data_queue.put(data.copy(), block=False)
                    except queue.Full:
                        warning("SQL Queue Full")

                data = daq_instance.get_data()

            time.sleep(0.01)

        except Exception as e:
            error(f"Collection loop error: {e}")
            time.sleep(0.1)

def csv_writer_loop():
    """CSV 寫入迴圈"""
    global is_collecting, csv_writer_instance, sql_uploader_instance, sql_enabled
    global target_size, current_data_size, csv_data_queue

    channels = 3

    while is_collecting or not csv_data_queue.empty():
        try:
            try:
                data = csv_data_queue.get(timeout=1.0)
            except queue.Empty:
                continue

            data_size = len(data)
            current_data_size += data_size

            if current_data_size < target_size:
                csv_writer_instance.add_data_block(data)
            else:
                data_actual_size = data_size
                empty_space = target_size - (current_data_size - data_actual_size)
                empty_space = (empty_space // channels) * channels

                while current_data_size >= target_size:
                    batch = data[:empty_space]
                    csv_writer_instance.add_data_block(batch)
                    csv_writer_instance.update_filename()

                    if sql_uploader_instance and sql_enabled:
                        csv_filename = (
                            csv_writer_instance.get_current_filename()
                            if csv_writer_instance
                            else None
                        )
                        if csv_filename:
                            if sql_uploader_instance.create_table(csv_filename):
                                info(f"SQL 表已建立，對應 CSV: {csv_filename}")
                            else:
                                warning(f"SQL 表建立失敗，對應 CSV: {csv_filename}")

                    current_data_size -= target_size

                    if empty_space < data_actual_size:
                        data = data[empty_space:]
                        data_actual_size = len(data)
                        empty_space = target_size
                        empty_space = (empty_space // channels) * channels
                    else:
                        break

                pending = data_actual_size
                if pending:
                    csv_writer_instance.add_data_block(data)
                    current_data_size = pending
                else:
                    current_data_size = 0

            csv_data_queue.task_done()

        except Exception as e:
            error(f"CSV writer loop error: {e}")
            time.sleep(0.1)

def sql_writer_loop():
    """SQL 寫入迴圈"""
    global is_collecting, sql_uploader_instance, sql_enabled, sql_current_temp_file
    global sql_target_size, sql_current_data_size, sql_sample_count, sql_start_time
    global sql_data_queue, csv_writer_instance, daq_instance

    channels = 3

    sample_rate = 7812
    if csv_writer_instance:
        sample_rate = csv_writer_instance.sample_rate
    elif daq_instance:
        try:
            sample_rate = daq_instance.get_sample_rate()
        except:
            pass

    if sql_start_time is None:
        sql_start_time = datetime.now()
        sql_sample_count = 0
        sql_current_data_size = 0

    while is_collecting or not sql_data_queue.empty():
        try:
            try:
                sql_data = sql_data_queue.get(timeout=1.0)
            except queue.Empty:
                if sql_current_data_size > 0:
                    _upload_temp_file_if_needed()
                continue

            if not sql_current_temp_file:
                continue

            remaining_data = sql_data

            while len(remaining_data) > 0:
                remaining_space = sql_target_size - sql_current_data_size

                if remaining_space <= 0:
                    if not _upload_temp_file_if_needed():
                        sql_sample_count = _write_to_temp_file(
                            remaining_data,
                            sample_rate,
                            sql_start_time,
                            sql_sample_count,
                        )
                        sql_current_data_size += len(remaining_data)
                        break
                    remaining_space = sql_target_size - sql_current_data_size

                write_size = min(len(remaining_data), remaining_space)
                write_size = (write_size // channels) * channels

                if write_size > 0:
                    data_to_write = remaining_data[:write_size]
                    sql_sample_count = _write_to_temp_file(
                        data_to_write, sample_rate, sql_start_time, sql_sample_count
                    )
                    sql_current_data_size += write_size

                    remaining_data = remaining_data[write_size:]

                    if sql_current_data_size >= sql_target_size:
                        if not _upload_temp_file_if_needed():
                            break
                else:
                    if not _upload_temp_file_if_needed():
                        sql_sample_count = _write_to_temp_file(
                            remaining_data,
                            sample_rate,
                            sql_start_time,
                            sql_sample_count,
                        )
                        sql_current_data_size += len(remaining_data)
                        break

            sql_data_queue.task_done()

        except Exception as e:
            error(f"SQL writer loop error: {e}")
            time.sleep(0.1)

def _create_new_temp_file() -> Optional[str]:
    """建立新的暫存檔案"""
    global sql_temp_dir, sql_current_temp_file

    if not sql_temp_dir:
        return None

    try:
        temp_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        temp_filename = f"{temp_timestamp}_sql_temp.csv"
        new_temp_file = os.path.join(sql_temp_dir, temp_filename)

        with open(new_temp_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(
                ["Timestamp", "Channel_1(X)", "Channel_2(Y)", "Channel_3(Z)"]
            )

        with sql_temp_file_lock:
            sql_current_temp_file = new_temp_file

        info(f"新的 SQL 暫存檔案已建立: {temp_filename}")
        return new_temp_file
    except Exception as e:
        error(f"建立新暫存檔案失敗: {e}")
        return None

def _write_to_temp_file(
    data: List[float], sample_rate: int, start_time: datetime, sample_count: int
) -> int:
    """將資料寫入暫存檔案"""
    global sql_current_temp_file

    if not sql_current_temp_file or not os.path.exists(sql_current_temp_file):
        return sample_count

    try:
        with sql_temp_file_lock:
            current_file = sql_current_temp_file
            if not current_file or not os.path.exists(current_file):
                return sample_count

            with open(current_file, "a", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                channels = 3
                sample_interval = 1.0 / sample_rate
                current_count = sample_count

                for i in range(0, len(data), channels):
                    elapsed_time = current_count * sample_interval
                    timestamp = start_time + timedelta(seconds=elapsed_time)

                    row = [timestamp.isoformat()]
                    for j in range(channels):
                        if i + j < len(data):
                            row.append(data[i + j])
                        else:
                            row.append(0.0)

                    writer.writerow(row)
                    current_count += 1

        return current_count
    except Exception as e:
        error(f"寫入暫存檔案失敗: {e}")
        return sample_count

def _upload_temp_file_if_needed():
    """檢查並上傳暫存檔案"""
    global sql_uploader_instance, sql_current_temp_file, sql_temp_dir, csv_writer_instance
    global sql_current_data_size, sql_target_size, sql_sample_count, sql_start_time

    if not sql_uploader_instance or not sql_current_temp_file:
        return False

    if sql_current_data_size < sql_target_size:
        return False

    with sql_temp_file_lock:
        temp_file_to_upload = sql_current_temp_file

    if not temp_file_to_upload or not os.path.exists(temp_file_to_upload):
        return False

    try:
        current_data_size_before_upload = sql_current_data_size

        if csv_writer_instance:
            csv_filename = csv_writer_instance.get_current_filename()
            if csv_filename:
                table_name = csv_filename
            else:
                table_name = None
        else:
            table_name = None

        if sql_uploader_instance.upload_from_csv_file(temp_file_to_upload, table_name):
            try:
                os.remove(temp_file_to_upload)
                info(f"已上傳並刪除暫存檔案: {os.path.basename(temp_file_to_upload)}")
            except Exception as e:
                warning(f"刪除暫存檔案失敗: {e}")

            _create_new_temp_file()

            excess_data_size = current_data_size_before_upload - sql_target_size
            sql_current_data_size = excess_data_size

            if excess_data_size > 0:
                excess_rows = excess_data_size // 3
                debug(f"保留超出部分的資料量: {excess_rows} 筆 ({excess_data_size} 個資料點) 到新暫存檔案")

            return True
        else:
            error(f"上傳暫存檔案失敗: {os.path.basename(temp_file_to_upload)}")
            return False

    except Exception as e:
        error(f"上傳暫存檔案時發生錯誤: {e}")
        return False

# ==========================================
# 主程式入口
# ==========================================

def run_flask_server(port: int = 8080):
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)

def main():
    parser = argparse.ArgumentParser(description="ProWaveDAQ System")
    parser.add_argument("-p", "--port", type=int, default=8080)
    args = parser.parse_args()

    info("=" * 60)
    info(f"System Started. Web: http://0.0.0.0:{args.port}/")
    info("=" * 60)

    flask_thread = threading.Thread(target=run_flask_server, args=(args.port,), daemon=True)
    flask_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        info("Shutting down...")
        stop_collection()
        sys.exit(0)

if __name__ == "__main__":
    main()
