#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SQL 上傳器 - 用於將振動數據上傳至 SQL 伺服器
"""

import time
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
    """SQL 上傳器類別"""

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
        self.current_table_name = None  # 當前使用的表名（與 CSV 檔名對應）
        # 注意：不再在初始化時建立固定表，改為動態建立

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
                    # ========== 步驟 1：確保連線有效 ==========
                    if not self.connection:
                        if not self._reconnect():
                            retry_count += 1
                            time.sleep(0.1 * retry_count)  # 遞增延遲
                            continue

                    # ========== 步驟 2：檢查連線是否還有效 ==========
                    try:
                        if PYMySQL_AVAILABLE:
                            # pymysql: 使用 ping 檢查連線，如果斷線則自動重連
                            self.connection.ping(reconnect=True)
                        else:  # mysql.connector
                            # mysql.connector: 檢查連線狀態
                            if not self.connection.is_connected():
                                if not self._reconnect():
                                    retry_count += 1
                                    time.sleep(0.1 * retry_count)
                                    continue
                    except:
                        # 檢查連線時發生錯誤，嘗試重連
                        if not self._reconnect():
                            retry_count += 1
                            time.sleep(0.1 * retry_count)
                            continue

                    # ========== 步驟 3：確保表存在 ==========
                    # 如果沒有當前表名，無法插入資料
                    if not self.current_table_name:
                        error("SQL 表名未設定，無法插入資料。請先呼叫 create_table() 建立表")
                        return False
                    
                    # ========== 步驟 4：準備 SQL 插入語句 ==========
                    # 使用當前表名（動態表名）
                    insert_sql = f"""
                    INSERT INTO `{self.current_table_name}` (timestamp, label, channel_1, channel_2, channel_3)
                    VALUES (%s, %s, %s, %s, %s)
                    """

                    # 使用當前時間作為時間戳記（所有資料使用相同時間戳記）
                    timestamp = datetime.now()
                    rows_to_insert = []

                    # ========== 步驟 5：將數據按通道分組 ==========
                    # 資料格式：[X1, Y1, Z1, X2, Y2, Z2, ...]
                    # 每 channels 個資料為一組（一個樣本）
                    for i in range(0, len(data), self.channels):
                        row_data = [
                            timestamp,  # 時間戳記
                            self.label,  # 標籤名稱
                            data[i] if i < len(data) else 0.0,  # Channel 1 (X)
                            data[i + 1] if i + 1 < len(data) else 0.0,  # Channel 2 (Y)
                            data[i + 2] if i + 2 < len(data) else 0.0  # Channel 3 (Z)
                        ]
                        rows_to_insert.append(tuple(row_data))

                    # ========== 步驟 6：批次插入資料（提升效能） ==========
                    if rows_to_insert:
                        # 確保游標存在
                        if not self.cursor:
                            self.cursor = self.connection.cursor()
                        # 使用 executemany 批次插入（比逐筆插入快很多）
                        self.cursor.executemany(insert_sql, rows_to_insert)
                        # 提交事務
                        self.connection.commit()
                        
                        # 上傳成功
                        return True

                except Exception as e:
                    # ========== 錯誤處理：記錄錯誤並重試 ==========
                    error(f"SQL 寫入資料失敗 (嘗試 {retry_count + 1}/{max_retries}): {e}")
                    try:
                        # 嘗試回滾事務（如果有的話）
                        if self.connection:
                            self.connection.rollback()
                    except:
                        pass
                    
                    # 標記連線為無效，下次重試時會嘗試重連
                    self.is_connected = False
                    retry_count += 1
                    
                    if retry_count < max_retries:
                        # 等待後重試（遞增延遲：0.1s, 0.2s, 0.3s）
                        time.sleep(0.1 * retry_count)
                        if not self._reconnect():
                            continue
                    else:
                        # 所有重試都失敗
                        error(f"SQL 寫入資料失敗，已重試 {max_retries} 次，放棄此次上傳")
                        return False
            
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