#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ 即時資料可視化系統 - 主控制程式
整合 DAQ、Web、CSV 三者運作
"""

import os
import sys
import time
import threading
import configparser
import logging
import argparse
from datetime import datetime
from typing import List, Optional, Dict
from flask import Flask, render_template, request, jsonify, send_from_directory
from prowavedaq import ProWaveDAQ
from csv_writer import CSVWriter
from sql_uploader import SQLUploader

# 導入統一日誌系統
try:
    from logger import info, debug, error, warning
except ImportError:
    # 如果無法導入，使用簡單的 fallback
    def info(msg): print(f"[INFO] {msg}")
    def debug(msg): print(f"[Debug] {msg}")
    def error(msg): print(f"[Error] {msg}")
    def warning(msg): print(f"[Warning] {msg}")

# 設定工作目錄為專案根目錄（src 的上一層）
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
os.chdir(PROJECT_ROOT)

# 將 src 資料夾添加到 Python 路徑，以便導入模組
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

# 全域狀態變數（用於記憶體中資料傳遞）
app = Flask(__name__, template_folder='templates')

# 禁用 Flask/Werkzeug 的 HTTP 請求日誌
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)  # 只顯示錯誤，隱藏 HTTP 請求日誌
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
sql_data_buffer: List[float] = []  # SQL 資料緩衝區
sql_buffer_max_size = 0  # SQL 緩衝區最大大小（防止記憶體溢出）
sql_enabled = False
sql_config: Dict[str, str] = {}
# 追蹤是否有活躍的前端連線（用於優化：無連線時不更新即時資料緩衝區）
last_data_request_time = 0
data_request_lock = threading.Lock()
DATA_REQUEST_TIMEOUT = 5.0  # 5 秒內沒有請求視為無活躍連線


def update_realtime_data(data: List[float]) -> None:
    """更新即時資料（供前端顯示）"""
    global realtime_data, data_counter, last_data_request_time
    
    # 檢查是否有活躍的前端連線
    with data_request_lock:
        has_active_connection = (time.time() - last_data_request_time) < DATA_REQUEST_TIMEOUT
    
    # 只有在有活躍連線時才更新即時資料緩衝區
    # 但始終更新計數器（用於狀態顯示）
    with data_lock:
        if has_active_connection:
            realtime_data.extend(data)
            # 限制記憶體使用，保留最近 10000 個資料點
            if len(realtime_data) > 10000:
                realtime_data = realtime_data[-10000:]
        data_counter += len(data)


def get_realtime_data() -> List[float]:
    """取得即時資料的副本"""
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
    """回傳目前最新資料 JSON 給前端"""
    global last_data_request_time
    # 更新最後請求時間（表示有活躍的前端連線）
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
    """檢查資料收集狀態"""
    global is_collecting, data_counter
    return jsonify({
        'success': True,
        'is_collecting': is_collecting,
        'counter': data_counter
    })


@app.route('/sql_config')
def get_sql_config():
    """取得 SQL 設定（從 sql.ini）"""
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
    """顯示與修改 ProWaveDAQ.ini、Master.ini、sql.ini"""
    ini_dir = "API"
    prodaq_ini = os.path.join(ini_dir, "ProWaveDAQ.ini")
    master_ini = os.path.join(ini_dir, "Master.ini")
    sql_ini = os.path.join(ini_dir, "sql.ini")

    if request.method == 'POST':
        # 儲存設定檔
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
    # 讀取 ProWaveDAQ.ini
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
    """啟動 DAQ、CSVWriter、SQLUploader 與即時顯示"""
    global is_collecting, collection_thread, daq_instance, csv_writer_instance
    global target_size, current_data_size, realtime_data, data_counter
    global sql_uploader_instance, sql_target_size, sql_current_data_size, sql_enabled, sql_config

    if is_collecting:
        return jsonify({'success': False, 'message': '資料收集已在執行中'})

    try:
        data = request.get_json()
        label = data.get('label', '') if data else ''

        if not label:
            return jsonify({'success': False, 'message': '請提供資料標籤'})

        # 重置狀態
        with data_lock:
            realtime_data = []
            data_counter = 0
            current_data_size = 0
            sql_current_data_size = 0
            sql_data_buffer = []
        # 重置請求時間追蹤
        with data_request_lock:
            global last_data_request_time
            last_data_request_time = 0

        # 載入設定檔
        ini_file_path = "API/Master.ini"
        config = configparser.ConfigParser()
        config.read(ini_file_path, encoding='utf-8')

        if not config.has_section('SaveUnit'):
            return jsonify({'success': False, 'message': '無法讀取 Master.ini'})

        save_unit = config.getint('SaveUnit', 'second', fallback=5)
        
        # 讀取 SQL 上傳間隔（如果存在）
        sql_upload_interval = config.getint('SaveUnit', 'sql_upload_interval', fallback=0)
        if sql_upload_interval <= 0:
            sql_upload_interval = save_unit  # 預設與 CSV 相同

        # 從 sql.ini 檔案讀取 SQL 設定（預設值）
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

        # 取得 SQL 設定（前端可以覆蓋 INI 設定）
        # 如果前端有提供 sql_enabled，則使用前端的值；否則使用 INI 的值
        if data and 'sql_enabled' in data:
            sql_enabled = data.get('sql_enabled', False)
            # 如果前端啟用 SQL，則使用前端的設定（如果提供），否則使用 INI 設定
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
            # 前端沒有提供 sql_enabled，使用 INI 設定
            sql_enabled = sql_enabled_ini
            sql_config = sql_config_ini.copy()

        # 初始化 DAQ
        daq_instance = ProWaveDAQ()
        daq_instance.init_devices("API/ProWaveDAQ.ini")
        sample_rate = daq_instance.get_sample_rate()
        channels = 3  # 固定3通道

        # 計算目標大小
        expected_samples_per_second = sample_rate * channels
        target_size = save_unit * expected_samples_per_second
        sql_target_size = sql_upload_interval * expected_samples_per_second
        
        # 設定 SQL 緩衝區最大大小（防止記憶體溢出）
        # 最多保留 2 倍 sql_target_size 的資料，或最多 10,000,000 個資料點（約 240 MB）
        # 取較小值以確保記憶體安全
        sql_buffer_max_size = min(sql_target_size * 2, 10_000_000)

        # 建立輸出目錄（在專案根目錄的 output 資料夾中）
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        folder = f"{timestamp}_{label}"
        output_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ", folder)
        os.makedirs(output_path, exist_ok=True)

        # 初始化 CSV Writer（傳入取樣率以正確計算時間戳記）
        csv_writer_instance = CSVWriter(channels, output_path, label, sample_rate)

        # 初始化 SQL Uploader（如果啟用）
        sql_uploader_instance = None
        if sql_enabled:
            try:
                sql_uploader_instance = SQLUploader(channels, label, sql_config)
                # 注意：不再在初始化時建立固定表，改為在 CSV 分檔時動態建立
                # 建立第一個表（對應第一個 CSV 檔案）
                if csv_writer_instance:
                    first_csv_filename = csv_writer_instance.get_current_filename()
                    if first_csv_filename:
                        if sql_uploader_instance.create_table(first_csv_filename):
                            info(f"SQL 第一個表已建立，對應 CSV: {first_csv_filename}")
                        else:
                            warning(f"SQL 第一個表建立失敗，對應 CSV: {first_csv_filename}")
            except Exception as e:
                return jsonify({'success': False, 'message': f'SQL 上傳器初始化失敗: {str(e)}'})

        # 啟動資料收集執行緒
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
    """停止所有執行緒、安全關閉，並上傳剩餘資料"""
    global is_collecting, daq_instance, csv_writer_instance, sql_uploader_instance
    global current_data_size, sql_current_data_size, sql_enabled

    if not is_collecting:
        return jsonify({'success': False, 'message': '資料收集未在執行中'})

    try:
        is_collecting = False

        # 停止 DAQ
        if daq_instance:
            daq_instance.stop_reading()

        # 等待 collection_loop 完成當前處理（給一點時間讓迴圈處理完剩餘資料）
        time.sleep(0.1)
        
        # 處理剩餘資料
        # CSV 的剩餘資料會保留在檔案中，不需要特別處理
        
        # 處理 SQL 剩餘資料（如果啟用且有剩餘資料）
        if sql_uploader_instance and sql_enabled:
            try:
                # 從 DAQ 取得所有剩餘資料（如果 DAQ 還在運行）
                remaining_data = []
                if daq_instance:
                    # 嘗試取得佇列中剩餘的資料
                    max_attempts = 10
                    for _ in range(max_attempts):
                        data = daq_instance.get_data()
                        if not data or len(data) == 0:
                            break
                        remaining_data.extend(data)
                        time.sleep(0.01)  # 短暫等待
                
                # 將剩餘資料加入緩衝區
                global sql_data_buffer
                if remaining_data:
                    sql_data_buffer.extend(remaining_data)
                
                # 上傳緩衝區中所有剩餘資料（即使未達到門檻）
                # 注意：如果當前沒有表，需要先建立表（對應最後一個 CSV 檔案）
                if sql_data_buffer:
                    # 確保有對應的表（如果 CSV 有檔案，使用最後一個檔名）
                    if csv_writer_instance and not sql_uploader_instance.current_table_name:
                        last_csv_filename = csv_writer_instance.get_current_filename()
                        if last_csv_filename:
                            sql_uploader_instance.create_table(last_csv_filename)
                    
                    if sql_uploader_instance.current_table_name:
                        sql_uploader_instance.add_data_block(sql_data_buffer)
                        info(f"已上傳剩餘資料至 SQL 伺服器 (表: {sql_uploader_instance.current_table_name}): {len(sql_data_buffer)} 個資料點")
                    else:
                        warning("無法上傳剩餘資料：SQL 表未建立")
                    sql_data_buffer = []
                    sql_current_data_size = 0
            except Exception as e:
                error(f"上傳剩餘資料至 SQL 伺服器時發生錯誤: {e}")

        # 關閉 CSV Writer
        if csv_writer_instance:
            csv_writer_instance.close()

        # 關閉 SQL Uploader
        if sql_uploader_instance:
            sql_uploader_instance.close()

        return jsonify({'success': True, 'message': '資料收集已停止'})

    except Exception as e:
        return jsonify({'success': False, 'message': f'停止失敗: {str(e)}'})


@app.route('/files')
def list_files():
    """列出 output 目錄中的檔案和資料夾"""
    try:
        path = request.args.get('path', '')
        # 安全檢查：只允許在專案根目錄的 output/ProWaveDAQ 目錄下瀏覽
        base_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ")
        
        if path:
            # 確保路徑在 base_path 內
            full_path = os.path.join(base_path, path)
            # 標準化路徑以檢查是否在 base_path 內
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
                relative_path = relative_path.replace('\\', '/')  # 統一使用 /
                
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
    """下載檔案"""
    try:
        path = request.args.get('path', '')
        if not path:
            return jsonify({'success': False, 'message': '請提供檔案路徑'})
        
        # 安全檢查：只允許下載專案根目錄的 output/ProWaveDAQ 目錄下的檔案
        base_path = os.path.join(PROJECT_ROOT, "output", "ProWaveDAQ")
        full_path = os.path.join(base_path, path)
        
        # 標準化路徑以檢查是否在 base_path 內
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


def collection_loop():
    """
    資料收集主迴圈（在獨立執行緒中執行）
    
    此函數是整個系統的核心資料處理迴圈，負責：
    1. 從 DAQ 設備讀取資料
    2. 更新即時顯示緩衝區
    3. 將資料寫入 CSV 檔案（自動分檔）
    4. 將資料上傳至 SQL 伺服器（如果啟用）
    
    資料流程：
    DAQ 設備 → DAQ 佇列 → collection_loop → CSV/SQL/即時顯示
    
    重要設計原則：
    - CSV 分檔：確保切斷位置在樣本邊界（3的倍數），避免部分樣本
    - SQL 上傳：使用獨立的緩衝區，與 CSV 分檔邏輯完全獨立
    - 記憶體保護：SQL 緩衝區有最大大小限制，超過時強制上傳
    - 資料保護：SQL 上傳失敗時保留資料在緩衝區，等待重試
    
    注意：
    - 此函數在背景執行緒中執行，不會阻塞主執行緒
    - 使用非阻塞方式從 DAQ 取得資料，避免長時間等待
    """
    global is_collecting, daq_instance, csv_writer_instance, sql_uploader_instance
    global target_size, current_data_size, sql_target_size, sql_current_data_size, sql_enabled
    global sql_data_buffer, sql_buffer_max_size
    
    channels = 3  # 固定3通道（X, Y, Z）

    while is_collecting:
        try:
            # ========== 步驟 1：從 DAQ 取得資料（非阻塞） ==========
            data = daq_instance.get_data()

            # ========== 步驟 2：持續處理佇列中的所有資料 ==========
            # 使用 while 迴圈確保處理完所有可用的資料
            while data and len(data) > 0:
                # 保存原始資料副本（用於 SQL 上傳，避免與 CSV 處理衝突）
                original_data = data.copy()
                data_size = len(data)

                # ========== 步驟 3：更新即時顯示緩衝區 ==========
                update_realtime_data(data)

                # ========== 步驟 4：寫入 CSV 檔案（自動分檔） ==========
                if csv_writer_instance:
                    current_data_size += data_size

                    if current_data_size < target_size:
                        # 資料還未達到分檔門檻，直接寫入當前檔案
                        csv_writer_instance.add_data_block(data)
                    else:
                        # 需要分檔處理（達到或超過目標大小）
                        data_actual_size = data_size  # 保存實際資料大小（防止誤用 current_data_size）
                        # 計算當前檔案還剩多少空間
                        empty_space = target_size - (current_data_size - data_actual_size)

                        # 確保切斷位置在樣本邊界（3的倍數）
                        # 向下取整到最近的樣本邊界，避免部分樣本被切斷
                        empty_space = (empty_space // channels) * channels

                        # 如果累積資料達到或超過目標大小，將資料分批處理
                        while current_data_size >= target_size:
                            # 取出要寫入當前檔案的資料批次
                            batch = data[:empty_space]
                            csv_writer_instance.add_data_block(batch)

                            # 每個完整批次後更新檔案名稱（建立新檔案）
                            csv_writer_instance.update_filename()
                            
                            # ========== SQL 同步分檔：建立新表 ==========
                            # 當 CSV 分檔時，SQL 也要建立對應的新表
                            if sql_uploader_instance and sql_enabled:
                                csv_filename = csv_writer_instance.get_current_filename()
                                if csv_filename:
                                    if sql_uploader_instance.create_table(csv_filename):
                                        info(f"SQL 表已建立，對應 CSV: {csv_filename}")
                                    else:
                                        warning(f"SQL 表建立失敗，對應 CSV: {csv_filename}")

                            # 更新累積資料大小
                            current_data_size -= target_size
                            
                            # 更新 data 和 empty_space 用於下一批次
                            if empty_space < data_actual_size:
                                # 還有剩餘資料，繼續處理
                                data = data[empty_space:]
                                data_actual_size = len(data)
                                empty_space = target_size
                                # 再次確保切斷位置在樣本邊界
                                empty_space = (empty_space // channels) * channels
                            else:
                                # 所有資料都已處理完畢
                                break

                        # 處理剩餘資料（少於 target_size 的部分）
                        pending = data_actual_size
                        if pending:
                            # 將剩餘資料寫入新檔案（作為下一檔案的開頭）
                            csv_writer_instance.add_data_block(data)
                            current_data_size = pending
                        else:
                            current_data_size = 0

                # ========== 步驟 5：上傳至 SQL 伺服器（如果啟用） ==========
                # 注意：SQL 上傳使用原始資料的副本，與 CSV 分檔邏輯完全獨立
                # 邏輯與 CSV 相同：累積資料到緩衝區，達到門檻才上傳
                if sql_uploader_instance and sql_enabled:
                    sql_data = original_data.copy()  # 使用原始資料副本（避免與 CSV 處理衝突）
                    sql_data_size = len(sql_data)
                    
                    # 將資料加入 SQL 緩衝區
                    global sql_data_buffer, sql_buffer_max_size
                    sql_data_buffer.extend(sql_data)
                    sql_current_data_size += sql_data_size

                    # ========== 記憶體保護機制 ==========
                    # 如果緩衝區超過最大大小，強制上傳部分資料（防止記憶體溢出）
                    while len(sql_data_buffer) > sql_buffer_max_size:
                        # 計算要上傳的資料量（至少上傳一個 sql_target_size）
                        upload_size = min(sql_target_size, len(sql_data_buffer))
                        # 確保上傳大小是3的倍數（樣本邊界）
                        upload_size = (upload_size // channels) * channels
                        if upload_size == 0:
                            # 如果計算結果為 0，至少上傳 3 個樣本
                            upload_size = min(channels * 3, len(sql_data_buffer))
                            upload_size = (upload_size // channels) * channels
                        
                        # 從緩衝區取出要上傳的資料（不立即移除，等上傳成功後才移除）
                        sql_batch = sql_data_buffer[:upload_size]
                        
                        # 嘗試上傳，只有成功才從緩衝區移除
                        if sql_uploader_instance.add_data_block(sql_batch):
                            # 上傳成功，從緩衝區移除已上傳的資料
                            sql_data_buffer = sql_data_buffer[upload_size:]
                            sql_current_data_size -= upload_size
                            info(f"SQL 緩衝區超過上限，已成功上傳 {upload_size} 個資料點")
                        else:
                            # 上傳失敗，保留資料在緩衝區，等待下次重試
                            warning(f"SQL 上傳失敗，保留 {upload_size} 個資料點在緩衝區，等待重試")
                            # 如果持續失敗，為了防止記憶體溢出，跳過此次上傳
                            # 但資料仍保留在緩衝區，下次達到門檻時會再次嘗試
                            break

                    # ========== 正常上傳邏輯 ==========
                    # 如果累積資料達到或超過門檻，進行上傳
                    while sql_current_data_size >= sql_target_size and len(sql_data_buffer) > 0:
                        # 計算要上傳的資料量
                        upload_size = min(sql_target_size, len(sql_data_buffer))
                        # 確保上傳大小是3的倍數（樣本邊界）
                        upload_size = (upload_size // channels) * channels
                        if upload_size == 0:
                            # 如果計算結果為 0，至少上傳 3 個樣本
                            upload_size = min(channels * 3, len(sql_data_buffer))
                            upload_size = (upload_size // channels) * channels
                        
                        # 從緩衝區取出要上傳的資料（不立即移除，等上傳成功後才移除）
                        sql_batch = sql_data_buffer[:upload_size]
                        
                        # 嘗試上傳，只有成功才從緩衝區移除
                        if sql_uploader_instance.add_data_block(sql_batch):
                            # 上傳成功，從緩衝區移除已上傳的資料
                            sql_data_buffer = sql_data_buffer[upload_size:]
                            sql_current_data_size -= upload_size
                        else:
                            # 上傳失敗，保留資料在緩衝區，等待下次重試
                            warning(f"SQL 上傳失敗，保留 {upload_size} 個資料點在緩衝區，等待重試")
                            # 跳出迴圈，等待下次資料進入時再次嘗試
                            break

                # ========== 步驟 6：繼續從佇列取得下一筆資料 ==========
                data = daq_instance.get_data()

            # 短暫休息以避免 CPU 過載（10ms）
            time.sleep(0.01)

        except Exception as e:
            # 處理未預期的錯誤
            error(f"Data collection loop error: {e}")
            time.sleep(0.1)  # 發生錯誤時等待 100ms 後繼續


def run_flask_server(port: int = 8080):
    """
    在獨立執行緒中執行 Flask 伺服器
    
    Args:
        port: Flask 伺服器監聽的埠號（預設為 8080）
    """
    # 確保在啟動前禁用 HTTP 請求日誌
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)


def main():
    """主函數"""
    # ========== 解析命令行參數 ==========
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
    
    # 驗證 port 範圍（1-65535）
    if not (1 <= port <= 65535):
        error(f"無效的埠號: {port}，請使用 1-65535 之間的數字")
        sys.exit(1)
    
    info("=" * 60)
    info("ProWaveDAQ Real-time Data Visualization System")
    info("=" * 60)
    info(f"Web interface will be available at http://0.0.0.0:{port}/")
    info("Press Ctrl+C to stop the server")
    info("=" * 60)

    # 在背景執行緒中啟動 Flask 伺服器（使用指定的 port）
    flask_thread = threading.Thread(target=run_flask_server, args=(port,), daemon=True)
    flask_thread.start()

    # 等待使用者中斷
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

# In case I don't see you
# Good afternoon, Good evening, and good night.

# You got the dream
# You gotta protect it.