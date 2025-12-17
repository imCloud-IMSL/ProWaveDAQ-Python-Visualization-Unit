#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQL 上傳器模組

此模組負責將振動數據上傳至 SQL 伺服器（MySQL/MariaDB），支援：
- 動態建立資料表（表名與 CSV 檔名對應）
- 批次插入資料（提升效能）
- 自動重連機制
- 重試機制和資料保護（失敗時保留資料）
- 執行緒安全

版本：4.0.0
"""

import time
import os
import csv
from datetime import datetime
from typing import List, Optional, Dict
import threading

try:
    import pymysql
    PYMySQL_AVAILABLE = True
except ImportError:
    try:
        import mysql.connector
        PYMySQL_AVAILABLE = False
        MYSQL_CONNECTOR_AVAILABLE = True
    except ImportError:
        PYMySQL_AVAILABLE = False
        MYSQL_CONNECTOR_AVAILABLE = False

# 導入統一日誌系統
try:
    from logger import info, debug, error, warning
except ImportError:
    # 如果無法導入，使用簡單的 fallback
    def info(msg): print(f"[INFO] {msg}")
    def debug(msg): print(f"[Debug] {msg}")
    def error(msg): print(f"[Error] {msg}")
    def warning(msg): print(f"[Warning] {msg}")

if not PYMySQL_AVAILABLE and not MYSQL_CONNECTOR_AVAILABLE:
    warning("未安裝 pymysql 或 mysql-connector-python，SQL 上傳功能將無法使用")


class SQLUploader:
    """
    SQL 上傳器類別
    
    此類別負責將振動數據上傳至 SQL 伺服器，支援動態建立資料表和批次插入。
    
    使用方式：
        uploader = SQLUploader(channels=3, label="test", sql_config={...})
        uploader.create_table("20250101_test_001")
        uploader.add_data_block([x1, y1, z1, x2, y2, z2, ...])
        uploader.close()
    """

    def __init__(self, channels: int, label: str, sql_config: Dict[str, str]):
        """
        初始化 SQL 上傳器

        Args:
            channels: 通道數量
            label: 標籤名稱
            sql_config: SQL 伺服器設定字典，包含：
                - host: 伺服器位置
                - port: 連接埠
                - user: 使用者名稱
                - password: 密碼
                - database: 資料庫名稱（可選）
        """
        self.channels = channels
        self.label = label
        self.sql_config = sql_config
        self.connection: Optional[object] = None
        self.cursor: Optional[object] = None
        self.upload_lock = threading.Lock()
        self.is_connected = False
        self.current_table_name = None

    def _get_connection(self):
        """取得資料庫連線（使用 pymysql 或 mysql.connector）"""
        if not PYMySQL_AVAILABLE and not MYSQL_CONNECTOR_AVAILABLE:
            raise ImportError("未安裝 pymysql 或 mysql-connector-python")

        try:
            if PYMySQL_AVAILABLE:
                return pymysql.connect(
                    host=self.sql_config.get('host', 'localhost'),
                    port=int(self.sql_config.get('port', 3306)),
                    user=self.sql_config.get('user', 'root'),
                    password=self.sql_config.get('password', ''),
                    database=self.sql_config.get('database', 'prowavedaq'),
                    charset='utf8mb4',
                    autocommit=False
                )
            else:  # mysql.connector
                return mysql.connector.connect(
                    host=self.sql_config.get('host', 'localhost'),
                    port=int(self.sql_config.get('port', 3306)),
                    user=self.sql_config.get('user', 'root'),
                    password=self.sql_config.get('password', ''),
                    database=self.sql_config.get('database', 'prowavedaq'),
                    autocommit=False
                )
        except Exception as e:
            error(f"SQL 連線失敗: {e}")
            raise

    def _sanitize_table_name(self, table_name: str) -> str:
        """
        清理表名，確保符合 SQL 命名規範
        
        SQL 表名限制：
        - 只能包含字母、數字、底線
        - 不能以數字開頭
        - 不能包含特殊字元
        
        Args:
            table_name: 原始表名（通常與 CSV 檔名相同）
        
        Returns:
            str: 清理後的表名，符合 SQL 命名規範
        """
        # 將不允許的字元替換為底線
        # 保留字母、數字、底線
        import re
        # 替換所有非字母、數字、底線的字元為底線
        sanitized = re.sub(r'[^a-zA-Z0-9_]', '_', table_name)
        # 確保不以數字開頭（如果以數字開頭，在前面加上 't_'）
        if sanitized and sanitized[0].isdigit():
            sanitized = 't_' + sanitized
        # 確保表名不為空
        if not sanitized:
            sanitized = 'vibration_data'
        return sanitized
    
    def create_table(self, table_name: str) -> bool:
        """
        建立新的資料表（表名與 CSV 檔名對應）
        
        每次 CSV 分檔時，會呼叫此方法建立對應的 SQL 表。
        表名會與 CSV 檔名一致（經過清理以符合 SQL 命名規範）。
        
        Args:
            table_name: 表名（通常與 CSV 檔名相同，不含 .csv 後綴）
        
        Returns:
            bool: 建立成功返回 True，失敗返回 False
        
        注意：
            - 表名會自動清理以符合 SQL 命名規範
            - 如果表已存在，不會報錯（使用 CREATE TABLE IF NOT EXISTS）
            - 建立成功後會設定 current_table_name
        """
        try:
            # 清理表名以符合 SQL 命名規範
            sanitized_table_name = self._sanitize_table_name(table_name)
            
            # 確保連線存在
            if not self.connection:
                if not self._reconnect():
                    error("無法建立 SQL 表：連線失敗")
                    return False
            
            # 檢查連線是否有效
            try:
                if PYMySQL_AVAILABLE:
                    self.connection.ping(reconnect=True)
                else:  # mysql.connector
                    if not self.connection.is_connected():
                        if not self._reconnect():
                            return False
            except:
                if not self._reconnect():
                    return False
            
            # 確保游標存在
            if not self.cursor:
                self.cursor = self.connection.cursor()
            
            # 建立資料表的 SQL（使用通用語法）
            # 注意：表名使用清理後的名稱，但欄位中仍保留原始 label
            create_table_sql = f"""
            CREATE TABLE IF NOT EXISTS `{sanitized_table_name}` (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                timestamp DATETIME NOT NULL,
                label VARCHAR(255) NOT NULL,
                channel_1 DOUBLE NOT NULL,
                channel_2 DOUBLE NOT NULL,
                channel_3 DOUBLE NOT NULL,
                INDEX idx_timestamp (timestamp),
                INDEX idx_label (label)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
            """

            self.cursor.execute(create_table_sql)
            self.connection.commit()
            
            # 設定當前表名
            self.current_table_name = sanitized_table_name
            self.is_connected = True
            info(f"SQL 資料表已建立: {sanitized_table_name} (對應 CSV: {table_name})")
            return True

        except Exception as e:
            error(f"建立 SQL 資料表失敗: {e}")
            self.is_connected = False
            return False

    def _reconnect(self) -> bool:
        """重新連線到 SQL 伺服器"""
        try:
            if self.connection:
                try:
                    self.connection.close()
                except:
                    pass

            self.connection = self._get_connection()
            if PYMySQL_AVAILABLE:
                self.cursor = self.connection.cursor()
            else:  # mysql.connector
                self.cursor = self.connection.cursor()
            self.is_connected = True
            info("SQL 連線已重新建立")
            return True
        except Exception as e:
            error(f"SQL 重新連線失敗: {e}")
            self.is_connected = False
            return False

    def add_data_block(self, data: List[float]) -> bool:
        """
        新增數據區塊到 SQL 伺服器
        
        此方法會將資料按通道分組（每 3 個為一組：X, Y, Z），
        並使用批次插入（executemany）提升效能。
        
        錯誤處理機制：
        - 最多重試 3 次
        - 每次重試前會檢查連線狀態，如果斷線則嘗試重連
        - 重試延遲時間遞增（0.1s, 0.2s, 0.3s）
        - 如果所有重試都失敗，返回 False（資料不會遺失，會保留在緩衝區）
        
        Args:
            data: 振動數據列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        
        Returns:
            bool: 上傳成功返回 True，失敗返回 False
        
        注意：
            - 此方法使用執行緒鎖（upload_lock）確保多執行緒安全
            - 如果資料長度不是 channels 的倍數，不足的部分會填充 0.0
            - 所有資料使用相同的時間戳記（當前時間）
            - 使用批次插入（executemany）可以大幅提升插入效能
        """
        if not data or not self.is_connected:
            return False

        # 使用執行緒鎖確保多執行緒安全
        with self.upload_lock:
            max_retries = 3  # 最多重試 3 次
            retry_count = 0
            
            while retry_count < max_retries:
                try:
                    if not self.connection:
                        if not self._reconnect():
                            retry_count += 1
                            time.sleep(0.1 * retry_count)
                            continue

                    try:
                        if PYMySQL_AVAILABLE:
                            self.connection.ping(reconnect=True)
                        else:
                            if not self.connection.is_connected():
                                if not self._reconnect():
                                    retry_count += 1
                                    time.sleep(0.1 * retry_count)
                                    continue
                    except:
                        if not self._reconnect():
                            retry_count += 1
                            time.sleep(0.1 * retry_count)
                            continue

                    if not self.current_table_name:
                        error("SQL 表名未設定，無法插入資料。請先呼叫 create_table() 建立表")
                        return False
                    
                    insert_sql = f"""
                    INSERT INTO `{self.current_table_name}` (timestamp, label, channel_1, channel_2, channel_3)
                    VALUES (%s, %s, %s, %s, %s)
                    """

                    timestamp = datetime.now()
                    rows_to_insert = []

                    for i in range(0, len(data), self.channels):
                        row_data = [
                            timestamp,
                            self.label,
                            data[i] if i < len(data) else 0.0,
                            data[i + 1] if i + 1 < len(data) else 0.0,
                            data[i + 2] if i + 2 < len(data) else 0.0
                        ]
                        rows_to_insert.append(tuple(row_data))

                    if rows_to_insert:
                        if not self.cursor:
                            self.cursor = self.connection.cursor()
                        self.cursor.executemany(insert_sql, rows_to_insert)
                        self.connection.commit()
                        
                        return True

                except Exception as e:
                    error(f"SQL 寫入資料失敗 (嘗試 {retry_count + 1}/{max_retries}): {e}")
                    try:
                        if self.connection:
                            self.connection.rollback()
                    except:
                        pass
                    
                    self.is_connected = False
                    retry_count += 1
                    
                    if retry_count < max_retries:
                        time.sleep(0.1 * retry_count)
                        if not self._reconnect():
                            continue
                    else:
                        error(f"SQL 寫入資料失敗，已重試 {max_retries} 次，放棄此次上傳")
                        return False
            
            return False

    def upload_from_csv_file(self, csv_file_path: str, table_name: Optional[str] = None) -> bool:
        """
        從 CSV 檔案讀取資料並上傳至 SQL 伺服器
        
        此方法會讀取 CSV 檔案中的所有資料，並批次上傳至 SQL 伺服器。
        如果未指定表名，會從 CSV 檔名自動推斷（去除路徑和 .csv 後綴）。
        
        Args:
            csv_file_path: CSV 檔案路徑
            table_name: 目標表名（可選，如果不提供則從檔名推斷）
        
        Returns:
            bool: 上傳成功返回 True，失敗返回 False
        
        注意：
            - CSV 檔案格式應為：Timestamp, Channel_1(X), Channel_2(Y), Channel_3(Z)
            - 第一行會被視為標題行並跳過
            - 使用批次插入提升效能
            - 如果表不存在，會自動建立
        """
        if not os.path.exists(csv_file_path):
            error(f"CSV 檔案不存在: {csv_file_path}")
            return False
        
        # 如果未指定表名，從檔名推斷
        if not table_name:
            filename = os.path.basename(csv_file_path)
            table_name = os.path.splitext(filename)[0]
        
        # 清理表名
        sanitized_table_name = self._sanitize_table_name(table_name)
        
        # 確保表存在
        if sanitized_table_name != self.current_table_name:
            if not self.create_table(table_name):
                error(f"無法建立 SQL 表: {sanitized_table_name}")
                return False
        
        # 讀取 CSV 檔案
        try:
            rows_to_insert = []
            with open(csv_file_path, 'r', encoding='utf-8') as f:
                reader = csv.reader(f)
                next(reader)  # 跳過標題行
                
                for row in reader:
                    if len(row) < 4:
                        continue
                    
                    try:
                        timestamp_str = row[0]
                        channel_1 = float(row[1])
                        channel_2 = float(row[2])
                        channel_3 = float(row[3])
                        
                        # 解析時間戳記
                        try:
                            timestamp = datetime.fromisoformat(timestamp_str)
                        except:
                            timestamp = datetime.now()
                        
                        rows_to_insert.append((
                            timestamp,
                            self.label,
                            channel_1,
                            channel_2,
                            channel_3
                        ))
                    except (ValueError, IndexError) as e:
                        warning(f"跳過無效的 CSV 行: {row}, 錯誤: {e}")
                        continue
            
            if not rows_to_insert:
                warning(f"CSV 檔案中沒有有效資料: {csv_file_path}")
                return True  # 檔案為空，視為成功
            
            # 批次上傳
            with self.upload_lock:
                max_retries = 3
                retry_count = 0
                
                while retry_count < max_retries:
                    try:
                        if not self.connection:
                            if not self._reconnect():
                                retry_count += 1
                                time.sleep(0.1 * retry_count)
                                continue
                        
                        try:
                            if PYMySQL_AVAILABLE:
                                self.connection.ping(reconnect=True)
                            else:
                                if not self.connection.is_connected():
                                    if not self._reconnect():
                                        retry_count += 1
                                        time.sleep(0.1 * retry_count)
                                        continue
                        except:
                            if not self._reconnect():
                                retry_count += 1
                                time.sleep(0.1 * retry_count)
                                continue
                        
                        if not self.cursor:
                            self.cursor = self.connection.cursor()
                        
                        insert_sql = f"""
                        INSERT INTO `{sanitized_table_name}` (timestamp, label, channel_1, channel_2, channel_3)
                        VALUES (%s, %s, %s, %s, %s)
                        """
                        
                        # 批次插入
                        self.cursor.executemany(insert_sql, rows_to_insert)
                        self.connection.commit()
                        
                        info(f"成功從 CSV 檔案上傳 {len(rows_to_insert)} 筆資料至 SQL 表: {sanitized_table_name}")
                        return True
                        
                    except Exception as e:
                        error(f"從 CSV 檔案上傳資料失敗 (嘗試 {retry_count + 1}/{max_retries}): {e}")
                        try:
                            if self.connection:
                                self.connection.rollback()
                        except:
                            pass
                        
                        self.is_connected = False
                        retry_count += 1
                        
                        if retry_count < max_retries:
                            time.sleep(0.1 * retry_count)
                            if not self._reconnect():
                                continue
                        else:
                            error(f"從 CSV 檔案上傳資料失敗，已重試 {max_retries} 次")
                            return False
                
                return False
                
        except Exception as e:
            error(f"讀取 CSV 檔案時發生錯誤: {e}")
            return False

    def close(self) -> None:
        """關閉 SQL 連線"""
        with self.upload_lock:
            try:
                if self.cursor:
                    self.cursor.close()
                    self.cursor = None
                if self.connection:
                    self.connection.close()
                    self.connection = None
                self.is_connected = False
                info("SQL 連線已關閉")
            except Exception as e:
                error(f"關閉 SQL 連線時發生錯誤: {e}")

    def __del__(self):
        """解構函數"""
        self.close()