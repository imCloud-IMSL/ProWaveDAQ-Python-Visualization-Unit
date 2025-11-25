#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV寫入器 - 用於將振動數據寫入CSV檔案
"""

import os
import csv
import time
from datetime import datetime, timedelta
from typing import List

# 導入統一日誌系統
try:
    from logger import info, debug, error, warning
except ImportError:
    # 如果無法導入，使用簡單的 fallback
    def info(msg): print(f"[INFO] {msg}")
    def debug(msg): print(f"[Debug] {msg}")
    def error(msg): print(f"[Error] {msg}")
    def warning(msg): print(f"[Warning] {msg}")


class CSVWriter:
    """CSV寫入器類別"""

    def __init__(self, channels: int, output_dir: str, label: str, sample_rate: int = 7812):
        """
        初始化CSV寫入器

        Args:
            channels: 通道數量
            output_dir: 輸出目錄
            label: 標籤名稱
            sample_rate: 取樣率（Hz），用於計算時間戳記
        """
        self.channels = channels
        self.output_dir = output_dir
        self.label = label
        self.sample_rate = sample_rate
        self.file_counter = 1
        self.current_file = None
        self.writer = None
        self.current_filename = None  # 當前檔名（不含路徑和 .csv 後綴）
        # 追蹤全局起始時間和已寫入的樣本總數（確保分檔時時間戳記連續）
        self.global_start_time = datetime.now()
        self.global_sample_count = 0
        self._create_output_directory()
        self._create_new_file()

    def _create_output_directory(self) -> None:
        """建立輸出目錄"""
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception as e:
            error(f"Error creating output directory: {e}")

    def _create_new_file(self) -> None:
        """建立新的CSV檔案"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{self.label}_{self.file_counter:03d}.csv"
        filepath = os.path.join(self.output_dir, filename)
        
        # 儲存當前檔名（不含路徑和 .csv 後綴），用於 SQL 表名
        self.current_filename = f"{timestamp}_{self.label}_{self.file_counter:03d}"

        try:
            self.current_file = open(
                filepath, 'w', newline='', encoding='utf-8')
            self.writer = csv.writer(self.current_file)

            # 寫入標題行
            # 通道對應：Channel_1 = X, Channel_2 = Y, Channel_3 = Z
            headers = ['Timestamp', 'Channel_1(X)', 'Channel_2(Y)', 'Channel_3(Z)']
            self.writer.writerow(headers)
            self.current_file.flush()

            info(f"New CSV file created: {filename}")

        except Exception as e:
            error(f"Error creating CSV file: {e}")
    
    def get_current_filename(self) -> str:
        """
        取得當前檔名（不含路徑和 .csv 後綴）
        
        此檔名可用於 SQL 表名，格式與 CSV 檔名一致。
        
        Returns:
            str: 當前檔名，例如 "20251124232158_ThisIsMe_001"
        """
        return self.current_filename if self.current_filename else ""

    def add_data_block(self, data: List[float]) -> None:
        """
        新增數據區塊到CSV檔案
        
        此方法會將資料按通道分組（每 3 個為一組：X, Y, Z），
        並為每個樣本計算精確的時間戳記。
        
        時間戳記計算方式：
        - 從全局起始時間（global_start_time）開始
        - 根據全局樣本計數（global_sample_count）和取樣率計算時間
        - 確保分檔時時間戳記連續（不會因為分檔而重置時間）
        
        Args:
            data: 振動數據列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        
        注意：
            - 如果資料長度不是 channels 的倍數，不足的部分會填充 0.0
            - 每次寫入後會立即刷新檔案緩衝區，確保資料即時寫入磁碟
            - 時間戳記使用 ISO 8601 格式（例如：2025-11-24T23:21:58.123456）
        """
        if not self.writer or not data:
            return

        try:
            # ========== 計算每個樣本的時間間隔 ==========
            # 取樣率是每秒的樣本數，每個樣本間隔 = 1 / sample_rate 秒
            # 例如：取樣率 7812 Hz，每個樣本間隔 = 1/7812 ≈ 0.000128 秒
            sample_interval = 1.0 / self.sample_rate

            # ========== 將數據按通道分組並寫入 CSV ==========
            # 資料格式：[X1, Y1, Z1, X2, Y2, Z2, ...]
            # 每 channels 個資料為一組（一個樣本）
            for i in range(0, len(data), self.channels):
                # 計算當前樣本的時間戳記
                # 從全局起始時間開始，根據全局樣本計數計算時間
                # 這樣可以確保分檔時時間戳記連續（不會因為分檔而重置時間）
                elapsed_time = self.global_sample_count * sample_interval
                timestamp = self.global_start_time + timedelta(seconds=elapsed_time)
                
                # 建立 CSV 行：時間戳記 + 各通道資料
                row = [timestamp.isoformat()]  # ISO 8601 格式的時間戳記
                for j in range(self.channels):
                    if i + j < len(data):
                        row.append(data[i + j])  # 添加通道資料
                    else:
                        row.append(0.0)  # 如果數據不足，填充 0.0

                # 寫入 CSV 行
                self.writer.writerow(row)
                # 增加全局樣本計數（用於計算下一個樣本的時間戳記）
                self.global_sample_count += 1

            # 立即刷新檔案緩衝區，確保資料即時寫入磁碟
            self.current_file.flush()

        except Exception as e:
            error(f"Error writing CSV data: {e}")

    def update_filename(self) -> None:
        """更新檔案名稱（建立新檔案）"""
        if self.current_file:
            self.current_file.close()

        self.file_counter += 1
        self._create_new_file()

    def close(self) -> None:
        """關閉CSV檔案"""
        if self.current_file:
            self.current_file.close()
            self.current_file = None
            self.writer = None

    def __del__(self):
        """解構函數"""
        self.close()
