#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CSV 寫入器模組

此模組負責將振動數據寫入 CSV 檔案，支援：
- 自動分檔（根據資料量）
- 精確的時間戳記計算（根據取樣率）
- 確保分檔時時間戳記連續
- 多通道資料寫入（預設 3 通道：X, Y, Z）

版本：4.0.0
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
    """
    CSV 寫入器類別
    
    此類別負責將振動數據寫入 CSV 檔案，支援自動分檔和精確的時間戳記計算。
    
    使用方式：
        writer = CSVWriter(channels=3, output_dir="./output", label="test", sample_rate=7812)
        writer.add_data_block([x1, y1, z1, x2, y2, z2, ...])
        writer.update_filename()  # 建立新檔案
        writer.close()
    """

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
        self.current_filename = None
        self.global_start_time = datetime.now()
        self.global_sample_count = 0
        self._create_output_directory()
        self._create_new_file()

    def _create_output_directory(self) -> None:
        """
        建立輸出目錄
        
        如果目錄不存在，會自動建立。如果目錄已存在，不會報錯。
        
        注意：
            - 使用 exist_ok=True，避免目錄已存在時報錯
            - 如果建立失敗，會輸出錯誤訊息但不會拋出例外
        """
        try:
            os.makedirs(self.output_dir, exist_ok=True)
        except Exception as e:
            error(f"Error creating output directory: {e}")

    def _create_new_file(self) -> None:
        """
        建立新的 CSV 檔案
        
        此方法會建立一個新的 CSV 檔案，檔案命名格式為：
        {timestamp}_{label}_{file_counter:03d}.csv
        
        檔案會包含標題行，並立即刷新到磁碟。
        
        注意：
            - 檔案使用 UTF-8 編碼
            - 檔名會儲存在 current_filename 中（不含路徑和 .csv 後綴），用於 SQL 表名
            - 通道標示：Channel_1 = X, Channel_2 = Y, Channel_3 = Z
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"{timestamp}_{self.label}_{self.file_counter:03d}.csv"
        filepath = os.path.join(self.output_dir, filename)
        
        self.current_filename = f"{timestamp}_{self.label}_{self.file_counter:03d}"

        try:
            self.current_file = open(
                filepath, 'w', newline='', encoding='utf-8')
            self.writer = csv.writer(self.current_file)

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
            sample_interval = 1.0 / self.sample_rate

            for i in range(0, len(data), self.channels):
                elapsed_time = self.global_sample_count * sample_interval
                timestamp = self.global_start_time + timedelta(seconds=elapsed_time)
                
                row = [timestamp.isoformat()]
                for j in range(self.channels):
                    if i + j < len(data):
                        row.append(data[i + j])
                    else:
                        row.append(0.0)

                self.writer.writerow(row)
                self.global_sample_count += 1

            self.current_file.flush()

        except Exception as e:
            error(f"Error writing CSV data: {e}")

    def update_filename(self) -> None:
        """
        更新檔案名稱（建立新檔案）
        
        此方法會關閉當前檔案，遞增檔案計數器，然後建立新檔案。
        用於 CSV 分檔功能。
        
        注意：
            - 檔案計數器會自動遞增（001, 002, 003, ...）
            - 新檔案會使用相同的標籤和時間戳記格式
        """
        if self.current_file:
            self.current_file.close()

        self.file_counter += 1
        self._create_new_file()

    def close(self) -> None:
        """
        關閉 CSV 檔案
        
        此方法會關閉當前開啟的檔案並清理資源。
        建議在完成所有寫入操作後呼叫此方法。
        
        注意：
            - 如果檔案未開啟，此方法不會報錯
            - 關閉後無法再寫入資料
        """
        if self.current_file:
            self.current_file.close()
            self.current_file = None
            self.writer = None

    def __del__(self):
        """
        解構函數
        
        當物件被銷毀時自動關閉檔案，確保資源正確釋放。
        """
        self.close()
