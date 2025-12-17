#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ 即時資料可視化系統 - 主控制程式
整合 DAQ、Web、CSV 三者運作

版本：4.0.0
"""

import os
import sys
import time
import threading
import configparser
import logging
import argparse
import csv
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

app = Flask(__name__, template_folder='templates')
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)
realtime_data: List[float] = []
data_lock = threading.Lock()
is_collecting = False
collection_thread: Optional[threading.Thread] = None
daq_instance: Optional[ProWaveDAQ] = None
csv_writer_instance: Optional[CSVWriter] = None
sql_uploader_instance: Optional[SQLUploader] = None
data_counter = 0
target_size = 0
current_data_size = 0
sql_target_size = 0
sql_current_data_size = 0
sql_data_buffer: List[float] = []
sql_buffer_max_size = 0
sql_enabled = False
sql_config: Dict[str, str] = {}
sql_upload_interval = 0
sql_temp_dir = None
sql_current_temp_file = None
sql_temp_file_lock = threading.Lock()
sql_sample_count = 0
sql_start_time: Optional[datetime] = None
last_data_request_time = 0
data_request_lock = threading.Lock()
DATA_REQUEST_TIMEOUT = 5.0


def update_realtime_data(data: List[float]) -> None:
    """
    更新即時資料緩衝區（供前端顯示）
    
    此函數採用智慧緩衝區更新機制：
    - 僅在有活躍前端連線時更新即時資料緩衝區，節省 CPU 和記憶體資源
    - 無活躍連線時跳過緩衝區更新，但計數器仍正常更新
    - 資料點計數器始終更新，用於狀態顯示
    
    Args:
        data: 要添加的資料列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
    
    注意：
        - 使用執行緒鎖確保資料一致性
        - 活躍連線判斷：5 秒內有 /data API 請求視為活躍
    """
    global realtime_data, data_counter, last_data_request_time
    
    with data_request_lock:
        has_active_connection = (time.time() - last_data_request_time) < DATA_REQUEST_TIMEOUT
    
    with data_lock:
        if has_active_connection:
            realtime_data.extend(data)
        data_counter += len(data)


def get_realtime_data() -> List[float]:
    """
    取得即時資料的副本（供前端 API 使用）
    
    Returns:
        List[float]: 即時資料的副本，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
    
    注意：
        - 返回副本以避免前端修改原始資料
        - 使用執行緒鎖確保資料一致性
    """
    with data_lock:
        return realtime_data.copy()


# Flask 路由
@app.route('/')
def index():
    """主頁：顯示設定表單、Label 輸入、開始/停止按鈕與折線圖"""
    return render_template('index.html')


@app.route('/files_page')
def files_page():
    """檔案瀏覽頁面"""
    return render_template('files.html')


@app.route('/data')
def get_data():
    """
    回傳目前最新資料 JSON 給前端
    
    此 API 端點用於前端輪詢取得即時資料（每 200ms 請求一次）。
    同時會更新最後請求時間，用於判斷是否有活躍的前端連線。
    
    Returns:
        JSON 回應，包含：
        - success: 是否成功
        - data: 即時資料列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        - counter: 資料點計數器（總資料點數）
    
    注意：
        - 前端會將資料按每 3 個一組分離為 X, Y, Z 三個通道
        - 請求時間會用於智慧緩衝區更新機制
    """
    global last_data_request_time
    with data_request_lock:
        last_data_request_time = time.time()
    
    data = get_realtime_data()
    global data_counter
    return jsonify({
        'success': True,
        'data': data,
        'counter': data_counter
    })


@app.route('/status')
def get_status():
    """
    檢查資料收集狀態（用於前端狀態恢復）
    
    當前端頁面載入時，會呼叫此 API 檢查後端狀態。
    如果後端正在收集資料，前端會自動恢復狀態並開始更新圖表。
    
    Returns:
        JSON 回應，包含：
        - success: 是否成功
        - is_collecting: 是否正在收集資料
        - counter: 資料點計數器（總資料點數）
    
    使用場景：
        - 頁面重新載入時恢復狀態
        - 從其他頁面返回主頁時同步狀態
    """
    global is_collecting, data_counter
    return jsonify({
        'success': True,
        'is_collecting': is_collecting,
        'counter': data_counter
    })


@app.route('/sql_config')
def get_sql_config():
    """
    取得 SQL 設定（從 sql.ini 檔案讀取）
    
    前端會使用此 API 讀取 SQL 設定，用於預填表單或判斷是否啟用 SQL 上傳。
    
    Returns:
        JSON 回應，包含：
        - success: 是否成功
        - sql_config: SQL 設定字典，包含：
            - enabled: 是否啟用 SQL 上傳
            - host: SQL 伺服器位置
            - port: 連接埠
            - user: 使用者名稱
            - password: 密碼
            - database: 資料庫名稱
        - message: 錯誤訊息（如果失敗）
    
    注意：
        - 如果讀取失敗，返回預設設定（enabled=False）
        - 密碼會以明文返回（前端需要顯示在表單中）
    """
    try:
        ini_file_path = "API/sql.ini"
        config = configparser.ConfigParser()
        config.read(ini_file_path, encoding='utf-8')

        sql_config = {
            'enabled': False,
            'host': 'localhost',
            'port': '3306',
            'user': 'root',
            'password': '',
            'database': 'prowavedaq'
        }

        if config.has_section('SQLServer'):
            sql_config['enabled'] = config.getboolean('SQLServer', 'enabled', fallback=False)
            sql_config['host'] = config.get('SQLServer', 'host', fallback='localhost')
            sql_config['port'] = config.get('SQLServer', 'port', fallback='3306')
            sql_config['user'] = config.get('SQLServer', 'user', fallback='root')
            sql_config['password'] = config.get('SQLServer', 'password', fallback='')
            sql_config['database'] = config.get('SQLServer', 'database', fallback='prowavedaq')

        return jsonify({
            'success': True,
            'sql_config': sql_config
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'message': str(e),
            'sql_config': {
                'enabled': False,
                'host': 'localhost',
                'port': '3306',
                'user': 'root',
                'password': '',
                'database': 'prowavedaq'
            }
        })


@app.route('/config', methods=['GET', 'POST'])
def config():
    """
    顯示與修改設定檔（ProWaveDAQ.ini、Master.ini、sql.ini）
    
    GET 請求：
        讀取三個設定檔的內容並顯示在編輯頁面（固定輸入框模式）。
    
    POST 請求：
        接收表單資料並寫入三個設定檔。
    
    Returns:
        GET: 渲染 config.html 模板，包含三個設定檔的內容
        POST: JSON 回應，包含 success 和 message
    
    注意：
        - 使用固定輸入框模式，防止使用者誤刪參數
        - 所有設定檔使用 UTF-8 編碼
    """
    ini_dir = "API"
    prodaq_ini = os.path.join(ini_dir, "ProWaveDAQ.ini")
    master_ini = os.path.join(ini_dir, "Master.ini")
    sql_ini = os.path.join(ini_dir, "sql.ini")

    if request.method == 'POST':
        try:
            # 讀取 ProWaveDAQ.ini 設定
            prodaq_config = configparser.ConfigParser()
            prodaq_config.read(prodaq_ini, encoding='utf-8')
            if not prodaq_config.has_section('ProWaveDAQ'):
                prodaq_config.add_section('ProWaveDAQ')
            
            prodaq_config.set('ProWaveDAQ', 'serialPort', request.form.get('prodaq_serialPort', '/dev/ttyUSB0'))
            prodaq_config.set('ProWaveDAQ', 'baudRate', request.form.get('prodaq_baudRate', '3000000'))
            prodaq_config.set('ProWaveDAQ', 'sampleRate', request.form.get('prodaq_sampleRate', '7812'))
            prodaq_config.set('ProWaveDAQ', 'slaveID', request.form.get('prodaq_slaveID', '1'))

            # 讀取 Master.ini 設定
            master_config = configparser.ConfigParser()
            master_config.read(master_ini, encoding='utf-8')
            if not master_config.has_section('SaveUnit'):
                master_config.add_section('SaveUnit')
            
            master_config.set('SaveUnit', 'second', request.form.get('master_second', '600'))
            master_config.set('SaveUnit', 'sql_upload_interval', request.form.get('master_sql_upload_interval', '600'))

            # 讀取 sql.ini 設定
            sql_config = configparser.ConfigParser()
            sql_config.read(sql_ini, encoding='utf-8')
            if not sql_config.has_section('SQLServer'):
                sql_config.add_section('SQLServer')
            
            sql_config.set('SQLServer', 'enabled', request.form.get('sql_enabled', 'false'))
            sql_config.set('SQLServer', 'host', request.form.get('sql_host', 'localhost'))
            sql_config.set('SQLServer', 'port', request.form.get('sql_port', '3306'))
            sql_config.set('SQLServer', 'user', request.form.get('sql_user', 'root'))
            sql_config.set('SQLServer', 'password', request.form.get('sql_password', ''))
            sql_config.set('SQLServer', 'database', request.form.get('sql_database', 'prowavedaq'))

            # 寫入檔案
            with open(prodaq_ini, 'w', encoding='utf-8') as f:
                prodaq_config.write(f)
            
            with open(master_ini, 'w', encoding='utf-8') as f:
                master_config.write(f)
            
            with open(sql_ini, 'w', encoding='utf-8') as f:
                sql_config.write(f)

            return jsonify({'success': True, 'message': '設定檔已儲存'})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)})

    # GET 請求：讀取設定檔並顯示編輯頁面
    prodaq_config = configparser.ConfigParser()
    try:
        prodaq_config.read(prodaq_ini, encoding='utf-8')
    except:
        pass
    
    prodaq_data = {
        'serialPort': prodaq_config.get('ProWaveDAQ', 'serialPort', fallback='/dev/ttyUSB0'),
        'baudRate': prodaq_config.get('ProWaveDAQ', 'baudRate', fallback='3000000'),
        'sampleRate': prodaq_config.get('ProWaveDAQ', 'sampleRate', fallback='7812'),
        'slaveID': prodaq_config.get('ProWaveDAQ', 'slaveID', fallback='1')
    }

    # 讀取 Master.ini
    master_config = configparser.ConfigParser()
    try:
        master_config.read(master_ini, encoding='utf-8')
    except:
        pass
    
    master_data = {
        'second': master_config.get('SaveUnit', 'second', fallback='600'),
        'sql_upload_interval': master_config.get('SaveUnit', 'sql_upload_interval', fallback='600')
    }

    # 讀取 sql.ini
    sql_config_parser = configparser.ConfigParser()
    try:
        sql_config_parser.read(sql_ini, encoding='utf-8')
    except:
        pass
    
    sql_data = {
        'enabled': sql_config_parser.getboolean('SQLServer', 'enabled', fallback=False),
        'host': sql_config_parser.get('SQLServer', 'host', fallback='localhost'),
        'port': sql_config_parser.get('SQLServer', 'port', fallback='3306'),
        'user': sql_config_parser.get('SQLServer', 'user', fallback='root'),
        'password': sql_config_parser.get('SQLServer', 'password', fallback=''),
        'database': sql_config_parser.get('SQLServer', 'database', fallback='prowavedaq')
    }

    return render_template('config.html',
                           prodaq_data=prodaq_data,
                           master_data=master_data,
                           sql_data=sql_data)


@app.route('/start', methods=['POST'])
def start_collection():
    """
    啟動資料收集（DAQ、CSVWriter、SQLUploader 與即時顯示）
    
    此函數會：
    1. 驗證請求參數（label 必須提供）
    2. 載入設定檔（Master.ini、ProWaveDAQ.ini、sql.ini）
    3. 初始化 DAQ 設備並建立 Modbus 連線
    4. 計算 CSV 分檔和 SQL 上傳的目標大小
    5. 建立輸出目錄並初始化 CSV Writer
    6. 初始化 SQL Uploader（如果啟用）
    7. 啟動資料收集執行緒和 DAQ 讀取執行緒
    
    請求格式：
        JSON，包含：
        - label: 資料標籤（必需）
        - sql_enabled: 是否啟用 SQL 上傳（可選）
        - sql_host, sql_port, sql_user, sql_password, sql_database: SQL 設定（可選）
    
    Returns:
        JSON 回應，包含：
        - success: 是否成功
        - message: 回應訊息（包含取樣率、分檔間隔、SQL 上傳間隔等資訊）
    
    注意：
        - 如果已在收集中，返回錯誤
        - SQL 設定可以從 sql.ini 讀取，也可以由前端提供（覆蓋 INI 設定）
        - 輸出目錄格式：output/ProWaveDAQ/{timestamp}_{label}/
    """
    global is_collecting, collection_thread, daq_instance, csv_writer_instance
    global target_size, current_data_size, realtime_data, data_counter
    global sql_uploader_instance, sql_target_size, sql_current_data_size, sql_enabled, sql_config
    global sql_upload_interval, sql_temp_dir, sql_current_temp_file
    global sql_start_time, sql_sample_count, last_data_request_time

    if is_collecting:
        return jsonify({'success': False, 'message': '資料收集已在執行中'})

    try:
        data = request.get_json()
        label = data.get('label', '') if data else ''

        if not label:
            return jsonify({'success': False, 'message': '請提供資料標籤'})

        with data_lock:
            realtime_data = []
            data_counter = 0
            current_data_size = 0
            sql_current_data_size = 0
            sql_data_buffer = []
        with data_request_lock:
            last_data_request_time = 0
            sql_sample_count = 0
            sql_start_time = None

        ini_file_path = "API/Master.ini"
        config = configparser.ConfigParser()
        config.read(ini_file_path, encoding='utf-8')

        if not config.has_section('SaveUnit'):
            return jsonify({'success': False, 'message': '無法讀取 Master.ini'})

        save_unit = config.getint('SaveUnit', 'second', fallback=5)
        sql_upload_interval = config.getint('SaveUnit', 'sql_upload_interval', fallback=0)
        if sql_upload_interval <= 0:
            sql_upload_interval = save_unit

        sql_ini_file_path = "API/sql.ini"
        sql_config_parser = configparser.ConfigParser()
        sql_config_parser.read(sql_ini_file_path, encoding='utf-8')
        
        sql_enabled_ini = False
        sql_config_ini = {
            'host': 'localhost',
            'port': '3306',
            'user': 'root',
            'password': '',
            'database': 'prowavedaq'
        }
        
        if sql_config_parser.has_section('SQLServer'):
            sql_enabled_ini = sql_config_parser.getboolean('SQLServer', 'enabled', fallback=False)
            sql_config_ini['host'] = sql_config_parser.get('SQLServer', 'host', fallback='localhost')
            sql_config_ini['port'] = sql_config_parser.get('SQLServer', 'port', fallback='3306')
            sql_config_ini['user'] = sql_config_parser.get('SQLServer', 'user', fallback='root')
            sql_config_ini['password'] = sql_config_parser.get('SQLServer', 'password', fallback='')
            sql_config_ini['database'] = sql_config_parser.get('SQLServer', 'database', fallback='prowavedaq')

        if data and 'sql_enabled' in data:
            sql_enabled = data.get('sql_enabled', False)
            if sql_enabled:
                sql_config = {
                    'host': data.get('sql_host', sql_config_ini['host']),
                    'port': data.get('sql_port', sql_config_ini['port']),
                    'user': data.get('sql_user', sql_config_ini['user']),
                    'password': data.get('sql_password', sql_config_ini['password']),
                    'database': data.get('sql_database', sql_config_ini['database'])
                }
            else:
                sql_config = sql_config_ini.copy()
        else:
            sql_enabled = sql_enabled_ini
            sql_config = sql_config_ini.copy()

        daq_instance = ProWaveDAQ()
        daq_instance.init_devices("API/ProWaveDAQ.ini")
        sample_rate = daq_instance.get_sample_rate()
        channels = 3

        expected_samples_per_second = sample_rate * channels
        target_size = save_unit * expected_samples_per_second
        sql_target_size = sql_upload_interval * expected_samples_per_second

        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        folder = f"{timestamp}_{label}"
        output_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ", folder)
        os.makedirs(output_path, exist_ok=True)

        csv_writer_instance = CSVWriter(channels, output_path, label, sample_rate)

        # 初始化 SQL 上傳相關變數
        sql_uploader_instance = None
        sql_temp_dir = None
        sql_current_temp_file = None
        sql_start_time = datetime.now()  # 初始化起始時間
        sql_sample_count = 0  # 初始化樣本計數
        sql_current_data_size = 0  # 初始化 SQL 資料量計數器
        
        if sql_enabled:
            try:
                sql_uploader_instance = SQLUploader(channels, label, sql_config)
                
                # 建立暫存檔案目錄
                sql_temp_dir = os.path.join(output_path, ".sql_temp")
                os.makedirs(sql_temp_dir, exist_ok=True)
                
                # 建立第一個暫存檔案
                temp_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                temp_filename = f"{temp_timestamp}_sql_temp.csv"
                sql_current_temp_file = os.path.join(sql_temp_dir, temp_filename)
                
                # 建立 CSV 檔案並寫入標題
                with open(sql_current_temp_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f)
                    writer.writerow(['Timestamp', 'Channel_1(X)', 'Channel_2(Y)', 'Channel_3(Z)'])
                
                info(f"SQL 暫存檔案已建立: {temp_filename}")
                
            except Exception as e:
                return jsonify({'success': False, 'message': f'SQL 上傳器初始化失敗: {str(e)}'})

        is_collecting = True
        collection_thread = threading.Thread(
            target=collection_loop, daemon=True)
        collection_thread.start()

        daq_instance.start_reading()

        sql_status = f', SQL 上傳間隔: {sql_upload_interval} 秒' if sql_enabled else ''
        return jsonify({
            'success': True,
            'message': f'資料收集已啟動 (取樣率: {sample_rate} Hz, 分檔間隔: {save_unit} 秒{sql_status})'
        })

    except Exception as e:
        is_collecting = False
        return jsonify({'success': False, 'message': f'啟動失敗: {str(e)}'})


@app.route('/stop', methods=['POST'])
def stop_collection():
    """
    停止資料收集（停止所有執行緒、安全關閉，並上傳剩餘資料）
    
    此函數會：
    1. 停止資料收集執行緒（設定 is_collecting = False）
    2. 停止 DAQ 讀取執行緒
    3. 上傳 SQL 緩衝區中的剩餘資料（如果啟用 SQL）
    4. 關閉 CSV Writer 和 SQL Uploader
    
    Returns:
        JSON 回應，包含：
        - success: 是否成功
        - message: 回應訊息
    
    注意：
        - 如果未在收集中，返回錯誤
        - 停止時會自動上傳 SQL 緩衝區中的剩餘資料（即使未達到門檻）
        - 所有檔案和連線會安全關閉
    """
    global is_collecting, daq_instance, csv_writer_instance, sql_uploader_instance
    global current_data_size, sql_current_data_size, sql_enabled
    global sql_temp_dir, sql_current_temp_file

    if not is_collecting:
        return jsonify({'success': False, 'message': '資料收集未在執行中'})

    try:
        is_collecting = False

        if daq_instance:
            daq_instance.stop_reading()

        # 立即返回成功回應，讓前端知道已停止
        # 剩餘的上傳工作在背景執行
        response_message = '資料收集已停止'
        
        # 在背景執行緒中處理剩餘的上傳工作（避免阻塞前端）
        def finalize_upload():
            time.sleep(0.1)  # 等待收集執行緒完成當前處理
            
            # 處理 SQL 暫存檔案
            if sql_uploader_instance and sql_enabled and sql_temp_dir:
                try:
                    # 上傳當前暫存檔案
                    with sql_temp_file_lock:
                        current_temp = sql_current_temp_file
                    
                    if current_temp and os.path.exists(current_temp):
                        # 從檔名推斷表名
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
                    
                    # 檢查並上傳所有剩餘的暫存檔案
                    if os.path.exists(sql_temp_dir):
                        temp_files = [f for f in os.listdir(sql_temp_dir) if f.endswith('_sql_temp.csv')]
                        for temp_file in temp_files:
                            temp_file_path = os.path.join(sql_temp_dir, temp_file)
                            if os.path.exists(temp_file_path):
                                # 從檔名推斷表名
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
                        
                        # 如果目錄為空，嘗試刪除目錄
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
        
        # 在背景執行緒中執行最終清理工作
        cleanup_thread = threading.Thread(target=finalize_upload, daemon=True)
        cleanup_thread.start()
        
        return jsonify({'success': True, 'message': response_message})

    except Exception as e:
        return jsonify({'success': False, 'message': f'停止失敗: {str(e)}'})


@app.route('/files')
def list_files():
    """
    列出 output 目錄中的檔案和資料夾
    
    此 API 用於檔案瀏覽功能，可以瀏覽 output/ProWaveDAQ/ 目錄下的所有檔案和資料夾。
    
    查詢參數：
        path (可選): 要瀏覽的子目錄路徑
    
    Returns:
        JSON 回應，包含：
        - success: 是否成功
        - items: 檔案和資料夾列表，每個項目包含：
            - name: 名稱
            - type: 類型（'directory' 或 'file'）
            - path: 相對路徑
            - size: 檔案大小（僅檔案有）
        - current_path: 當前路徑
        - message: 錯誤訊息（如果失敗）
    
    安全機制：
        - 路徑標準化檢查，防止目錄遍歷攻擊
        - 只允許存取 output/ProWaveDAQ/ 目錄下的檔案
    """
    try:
        path = request.args.get('path', '')
        base_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ")
        
        if path:
            full_path = os.path.join(base_path, path)
            full_path = os.path.normpath(full_path)
            base_path_norm = os.path.normpath(os.path.abspath(base_path))
            full_path_abs = os.path.abspath(full_path)
            
            if not full_path_abs.startswith(base_path_norm):
                return jsonify({'success': False, 'message': '無效的路徑'})
        else:
            full_path = base_path
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'message': '路徑不存在'})
        
        items = []
        try:
            for item in sorted(os.listdir(full_path)):
                item_path = os.path.join(full_path, item)
                relative_path = os.path.join(path, item) if path else item
                relative_path = relative_path.replace('\\', '/')
                
                if os.path.isdir(item_path):
                    items.append({
                        'name': item,
                        'type': 'directory',
                        'path': relative_path
                    })
                else:
                    size = os.path.getsize(item_path)
                    items.append({
                        'name': item,
                        'type': 'file',
                        'path': relative_path,
                        'size': size
                    })
        except PermissionError:
            return jsonify({'success': False, 'message': '沒有權限讀取此目錄'})
        
        return jsonify({
            'success': True,
            'items': items,
            'current_path': path
        })
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


@app.route('/download')
def download_file():
    """
    下載檔案
    
    此 API 用於下載 output/ProWaveDAQ/ 目錄下的 CSV 檔案。
    
    查詢參數：
        path (必需): 要下載的檔案路徑（相對於 output/ProWaveDAQ/）
    
    Returns:
        檔案下載響應（如果成功）
        或 JSON 錯誤回應（如果失敗）
    
    安全機制：
        - 路徑標準化檢查，防止目錄遍歷攻擊
        - 只允許下載 output/ProWaveDAQ/ 目錄下的檔案
        - 不允許下載資料夾
    """
    try:
        path = request.args.get('path', '')
        if not path:
            return jsonify({'success': False, 'message': '請提供檔案路徑'})
        
        base_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ")
        full_path = os.path.join(base_path, path)
        
        full_path = os.path.normpath(full_path)
        base_path_norm = os.path.normpath(os.path.abspath(base_path))
        full_path_abs = os.path.abspath(full_path)
        
        if not full_path_abs.startswith(base_path_norm):
            return jsonify({'success': False, 'message': '無效的路徑'})
        
        if not os.path.exists(full_path):
            return jsonify({'success': False, 'message': '檔案不存在'})
        
        if os.path.isdir(full_path):
            return jsonify({'success': False, 'message': '無法下載資料夾'})
        
        directory = os.path.dirname(full_path)
        filename = os.path.basename(full_path)
        
        return send_from_directory(directory, filename, as_attachment=True)
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})


def _create_new_temp_file() -> Optional[str]:
    """
    建立新的暫存檔案
    
    Returns:
        str: 新暫存檔案的路徑，如果失敗則返回 None
    """
    global sql_temp_dir, sql_current_temp_file
    
    if not sql_temp_dir:
        return None
    
    try:
        temp_timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        temp_filename = f"{temp_timestamp}_sql_temp.csv"
        new_temp_file = os.path.join(sql_temp_dir, temp_filename)
        
        with open(new_temp_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Timestamp', 'Channel_1(X)', 'Channel_2(Y)', 'Channel_3(Z)'])
        
        with sql_temp_file_lock:
            sql_current_temp_file = new_temp_file
        
        info(f"新的 SQL 暫存檔案已建立: {temp_filename}")
        return new_temp_file
    except Exception as e:
        error(f"建立新暫存檔案失敗: {e}")
        return None


def _write_to_temp_file(data: List[float], sample_rate: int, start_time: datetime, sample_count: int) -> int:
    """
    將資料寫入暫存檔案
    
    Args:
        data: 振動數據列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        sample_rate: 取樣率
        start_time: 全局起始時間
        sample_count: 當前樣本計數
    
    Returns:
        int: 更新後的樣本計數
    """
    global sql_current_temp_file
    
    if not sql_current_temp_file or not os.path.exists(sql_current_temp_file):
        return sample_count
    
    try:
        with sql_temp_file_lock:
            current_file = sql_current_temp_file
            if not current_file or not os.path.exists(current_file):
                return sample_count
            
            with open(current_file, 'a', newline='', encoding='utf-8') as f:
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
    """
    檢查並上傳暫存檔案（如果資料量達到門檻）
    
    當累積的資料量達到 sql_target_size 時，會：
    1. 上傳當前暫存檔案到 SQL
    2. 刪除暫存檔案
    3. 建立新的暫存檔案
    4. 重置資料量計數器（保留超出部分的資料量）
    """
    global sql_uploader_instance, sql_current_temp_file, sql_temp_dir, csv_writer_instance
    global sql_current_data_size, sql_target_size
    
    if not sql_uploader_instance or not sql_current_temp_file:
        return False
    
    # 檢查資料量是否達到門檻
    if sql_current_data_size < sql_target_size:
        return False
    
    # 資料量達到門檻，準備上傳
    with sql_temp_file_lock:
        temp_file_to_upload = sql_current_temp_file
    
    if not temp_file_to_upload or not os.path.exists(temp_file_to_upload):
        return False
    
    try:
        # 記錄當前資料量（用於日誌）
        current_data_size_before_upload = sql_current_data_size
        
        # 從檔名推斷表名（使用對應的 CSV 檔名）
        if csv_writer_instance:
            csv_filename = csv_writer_instance.get_current_filename()
            if csv_filename:
                table_name = csv_filename
            else:
                # 如果沒有 CSV 檔名，使用暫存檔名
                table_name = os.path.splitext(os.path.basename(temp_file_to_upload))[0]
        else:
            table_name = None
        
        # 上傳檔案
        if sql_uploader_instance.upload_from_csv_file(temp_file_to_upload, table_name):
            # 計算筆數（資料點數 / 通道數）
            channels = 3
            rows_count = current_data_size_before_upload // channels
            target_rows = sql_target_size // channels
            
            # 上傳成功，刪除暫存檔
            try:
                os.remove(temp_file_to_upload)
                info(f"暫存檔案已上傳並刪除: {os.path.basename(temp_file_to_upload)} (筆數: {rows_count} 筆, 目標: {target_rows} 筆)")
            except Exception as e:
                warning(f"刪除暫存檔案失敗: {e}")
            
            # 建立新的暫存檔案
            _create_new_temp_file()
            
            # 計算超出部分的資料量（用於下一個暫存檔案）
            excess_data_size = current_data_size_before_upload - sql_target_size
            
            # 重置資料量計數器，保留超出部分的資料量
            sql_current_data_size = excess_data_size
            
            if excess_data_size > 0:
                excess_rows = excess_data_size // channels
                debug(f"保留超出部分的資料量: {excess_rows} 筆 ({excess_data_size} 個資料點) 到新暫存檔案")
            
            return True
        else:
            error(f"上傳暫存檔案失敗: {os.path.basename(temp_file_to_upload)}")
            # 上傳失敗，保留檔案等待下次重試
            return False
            
    except Exception as e:
        error(f"上傳暫存檔案時發生錯誤: {e}")
        return False


def collection_loop():
    """
    資料收集主迴圈（在獨立執行緒中執行）
    
    此函數是整個系統的核心資料處理迴圈，負責：
    1. 從 DAQ 設備讀取資料（非阻塞方式）
    2. 更新即時顯示緩衝區（智慧緩衝區更新機制）
    3. 將資料寫入 CSV 檔案（自動分檔，確保樣本邊界）
    4. 將資料上傳至 SQL 伺服器（如果啟用，獨立緩衝區）
    
    資料流程：
        DAQ 設備 → DAQ 佇列 → collection_loop → CSV/SQL/即時顯示
    
    重要設計原則：
        - CSV 分檔：確保切斷位置在樣本邊界（3的倍數），避免通道錯位
        - SQL 上傳：使用獨立的緩衝區，與 CSV 分檔邏輯完全獨立
        - 記憶體保護：SQL 緩衝區有最大大小限制，超過時強制上傳
        - 資料保護：SQL 上傳失敗時保留資料在緩衝區，等待重試
    
    注意：
        - 此函數在背景執行緒中執行，不會阻塞主執行緒
        - 使用非阻塞方式從 DAQ 取得資料，避免長時間等待
        - 每次處理後會短暫休息（10ms），避免 CPU 過載
    """
    global is_collecting, daq_instance, csv_writer_instance, sql_uploader_instance
    global target_size, current_data_size, sql_target_size, sql_current_data_size, sql_enabled
    global sql_sample_count, sql_start_time
    global sql_current_temp_file, sql_temp_dir
    
    channels = 3
    
    # 初始化 SQL 樣本計數和起始時間
    if sql_enabled and sql_start_time is None:
        sql_start_time = datetime.now()
        sql_sample_count = 0
        sql_current_data_size = 0

    while is_collecting:
        try:
            data = daq_instance.get_data()

            while data and len(data) > 0:
                original_data = data.copy()
                data_size = len(data)

                update_realtime_data(data)
                if csv_writer_instance:
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
                                csv_filename = csv_writer_instance.get_current_filename()
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
                if sql_uploader_instance and sql_enabled and sql_current_temp_file:
                    sql_data = original_data.copy()
                    sql_data_size = len(sql_data)
                    
                    # 寫入暫存檔案
                    if sql_start_time is not None:
                        sample_rate = csv_writer_instance.sample_rate if csv_writer_instance else 7812
                        channels = 3
                        
                        # 處理資料寫入，確保不超過目標值
                        remaining_data = sql_data
                        
                        while len(remaining_data) > 0:
                            # 計算當前檔案的剩餘空間
                            remaining_space = sql_target_size - sql_current_data_size
                            
                            if remaining_space <= 0:
                                # 當前檔案已滿，先上傳
                                if not _upload_temp_file_if_needed():
                                    # 上傳失敗，將剩餘資料寫入當前檔案（避免資料遺失）
                                    sql_sample_count = _write_to_temp_file(remaining_data, sample_rate, sql_start_time, sql_sample_count)
                                    sql_current_data_size += len(remaining_data)
                                    break
                                # 上傳成功，重新計算剩餘空間
                                remaining_space = sql_target_size - sql_current_data_size
                            
                            # 計算可以寫入的資料量（確保是 channels 的倍數）
                            write_size = min(len(remaining_data), remaining_space)
                            write_size = (write_size // channels) * channels
                            
                            if write_size > 0:
                                # 寫入部分資料到當前檔案
                                data_to_write = remaining_data[:write_size]
                                sql_sample_count = _write_to_temp_file(data_to_write, sample_rate, sql_start_time, sql_sample_count)
                                sql_current_data_size += write_size
                                
                                # 更新剩餘資料
                                remaining_data = remaining_data[write_size:]
                                
                                # 檢查當前檔案是否已滿
                                if sql_current_data_size >= sql_target_size:
                                    if not _upload_temp_file_if_needed():
                                        # 上傳失敗，跳出迴圈
                                        break
                            else:
                                # 剩餘空間不足一個完整樣本，先上傳
                                if not _upload_temp_file_if_needed():
                                    # 上傳失敗，將剩餘資料寫入當前檔案（避免資料遺失）
                                    sql_sample_count = _write_to_temp_file(remaining_data, sample_rate, sql_start_time, sql_sample_count)
                                    sql_current_data_size += len(remaining_data)
                                    break
                                # 上傳成功，繼續處理剩餘資料

                data = daq_instance.get_data()

            time.sleep(0.01)

        except Exception as e:
            error(f"Data collection loop error: {e}")
            time.sleep(0.1)


def run_flask_server(port: int = 8080):
    """
    在獨立執行緒中執行 Flask 伺服器
    
    此函數會在背景執行緒中啟動 Flask Web 伺服器，提供 HTTP API 和 Web 介面。
    
    Args:
        port: Flask 伺服器監聽的埠號（預設為 8080）
    
    注意：
        - 監聽所有網路介面（0.0.0.0），允許遠端存取
        - 禁用除錯模式和重新載入器（避免與執行緒衝突）
        - 禁用 Flask 的 HTTP 請求日誌，只顯示應用程式日誌
    """
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def main():
    """
    主函數（程式入口點）
    
    此函數會：
    1. 解析命令行參數（埠號）
    2. 驗證埠號範圍
    3. 在背景執行緒中啟動 Flask 伺服器
    4. 主執行緒進入等待迴圈，等待使用者中斷
    5. 收到中斷信號時安全關閉所有資源
    
    命令行參數：
        -p, --port: Flask 伺服器監聽的埠號（預設: 8080）
    
    範例：
        python src/main.py              # 使用預設 port 8080
        python src/main.py --port 3000  # 使用自訂 port 3000
        python src/main.py -p 9000      # 使用自訂 port 9000
    
    注意：
        - 埠號範圍必須在 1-65535 之間
        - 使用 Ctrl+C 可以安全關閉伺服器
        - 關閉時會自動停止資料收集並關閉所有連線
    """
    parser = argparse.ArgumentParser(
        description='ProWaveDAQ Real-time Data Visualization System',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
範例：
  python src/main.py              # 使用預設 port 8080
  python src/main.py --port 3000  # 使用自訂 port 3000
  python src/main.py -p 9000       # 使用自訂 port 9000
        """
    )
    parser.add_argument(
        '-p', '--port',
        type=int,
        default=8080,
        help='Flask 伺服器監聽的埠號（預設: 8080）'
    )
    
    args = parser.parse_args()
    port = args.port
    
    if not (1 <= port <= 65535):
        error(f"無效的埠號: {port}，請使用 1-65535 之間的數字")
        sys.exit(1)
    
    info("=" * 60)
    info("ProWaveDAQ Real-time Data Visualization System")
    info("=" * 60)
    info(f"Web interface will be available at http://0.0.0.0:{port}/")
    info("Press Ctrl+C to stop the server")
    info("=" * 60)

    flask_thread = threading.Thread(target=run_flask_server, args=(port,), daemon=True)
    flask_thread.start()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        info("\nShutting down server...")
        global is_collecting, daq_instance, csv_writer_instance, sql_uploader_instance
        if is_collecting:
            is_collecting = False
            if daq_instance:
                daq_instance.stop_reading()
            if csv_writer_instance:
                csv_writer_instance.close()
            if sql_uploader_instance:
                sql_uploader_instance.close()
        info("Server has been shut down")


if __name__ == "__main__":
    main()