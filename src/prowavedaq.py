#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ 設備通訊模組

此模組負責與 ProWaveDAQ 設備進行 Modbus RTU 通訊，讀取振動數據。
使用標準的 Modbus RTU 協議，符合原廠 RS485 Modbus RTU 手冊規範。

主要功能：
    - 建立 Modbus RTU 連線
    - 設定設備取樣率
    - 從設備讀取振動數據（三通道：X, Y, Z）
    - 資料格式轉換（16位元整數 → 浮點數）
    - 將資料放入佇列供其他模組使用

版本：4.0.0
"""

import time
import threading
import configparser
import queue
from typing import List, Optional

from pymodbus.client import ModbusSerialClient

try:
    from logger import info, debug, warning, error
except ImportError:
    def info(m): print(f"[INFO] {m}")
    def debug(m): print(f"[DEBUG] {m}")
    def warning(m): print(f"[WARN] {m}")
    def error(m): print(f"[ERROR] {m}")


class ProWaveDAQ:
    """
    ProWaveDAQ 設備通訊類別
    
    此類別封裝了與 ProWaveDAQ 設備的所有通訊功能，包括：
    - Modbus RTU 連線管理
    - 設備初始化與設定
    - 資料讀取與轉換
    - 多執行緒安全的資料佇列管理
    
    使用方式：
        daq = ProWaveDAQ()
        daq.init_devices("API/ProWaveDAQ.ini")
        daq.start_reading()
        data = daq.get_data()  # 非阻塞取得資料
        daq.stop_reading()
    """
    
    # Modbus 寄存器位址（原廠定義）
    REG_SAMPLE_RATE = 0x01      # 取樣率設定寄存器
    REG_FIFO_LEN = 0x02         # FIFO 緩衝區長度寄存器
    REG_RAW_DATA_START = 0x03   # 原始資料起始寄存器

    CHANNELS = 3                # 通道數量（固定為 3：X, Y, Z）
    MAX_READ_WORDS = 123        # 單次讀取的最大字數（Modbus 手冊上限）

    def __init__(self):
        """
        初始化 ProWaveDAQ 類別
        
        設定預設參數並初始化內部狀態變數。
        實際的設備設定會從 INI 檔案讀取（在 init_devices() 中）。
        """
        self.serial_port = "/dev/ttyUSB0"    # 預設串列埠路徑
        self.baud_rate = 3_000_000           # 預設鮑率（3 Mbps）
        self.sample_rate = 7812              # 預設取樣率（Hz）
        self.slave_id = 1                    # 預設 Modbus 從站 ID

        self.client: Optional[ModbusSerialClient] = None  # Modbus 連線物件
        self.reading = False                              # 讀取狀態旗標
        self.thread: Optional[threading.Thread] = None   # 讀取執行緒

        self.queue: "queue.Queue[List[float]]" = queue.Queue(maxsize=5000)  # 資料佇列（執行緒安全）

    def init_devices(self, ini_path: str):
        """
        從 INI 設定檔初始化設備並建立 Modbus 連線
        
        此方法會：
        1. 讀取 INI 設定檔（ProWaveDAQ.ini）
        2. 設定設備參數（串列埠、鮑率、取樣率、從站 ID）
        3. 建立 Modbus RTU 連線
        4. 設定設備取樣率
        
        Args:
            ini_path: INI 設定檔路徑（例如："API/ProWaveDAQ.ini"）
        
        Raises:
            RuntimeError: 如果 Modbus 連線失敗
        
        注意：
            - INI 檔案必須包含 [ProWaveDAQ] 區段
            - 如果參數不存在，使用預設值
        """
        cfg = configparser.ConfigParser()
        cfg.read(ini_path, encoding="utf-8")

        self.serial_port = cfg.get("ProWaveDAQ", "serialPort", fallback=self.serial_port)
        self.baud_rate = cfg.getint("ProWaveDAQ", "baudRate", fallback=self.baud_rate)
        self.sample_rate = cfg.getint("ProWaveDAQ", "sampleRate", fallback=self.sample_rate)
        self.slave_id = cfg.getint("ProWaveDAQ", "slaveID", fallback=self.slave_id)

        if not self._connect():
            raise RuntimeError("Modbus connect failed")

        self._set_sample_rate()

    def _connect(self) -> bool:
        """
        建立 Modbus RTU 連線
        
        此方法會建立 ModbusSerialClient 並連線到設備。
        
        Returns:
            bool: 連線成功返回 True，失敗返回 False
        
        注意：
            - 連線參數：無同位位元（N）、1 個停止位元、8 個資料位元
            - 超時時間設定為 1 秒
            - 使用 RTU 框架格式
        """
        self.client = ModbusSerialClient(
            port=self.serial_port,
            baudrate=self.baud_rate,
            parity="N",
            stopbits=1,
            bytesize=8,
            timeout=1,
            framer="rtu",
        )
        if not self.client.connect():
            return False
        self.client.unit_id = self.slave_id
        info("Modbus connection established")
        return True

    def _set_sample_rate(self):
        """
        設定設備取樣率
        
        此方法會寫入取樣率到設備的設定寄存器。
        
        注意：
            - 取樣率必須符合設備支援的範圍
            - 如果設定失敗，會輸出錯誤訊息但不會拋出例外
        """
        r = self.client.write_register(self.REG_SAMPLE_RATE, self.sample_rate)
        if r.isError():
            error("Failed to set sample rate")
        else:
            debug(f"Sample rate set to {self.sample_rate} Hz")

    def start_reading(self):
        """
        啟動資料讀取（在背景執行緒中執行）
        
        此方法會建立並啟動一個背景執行緒，持續從設備讀取資料。
        如果已經在讀取中，則不會重複啟動。
        
        注意：
            - 執行緒設定為 daemon=True，主程式結束時自動終止
            - 讀取的資料會放入 queue 中，供 get_data() 取得
        """
        if self.reading:
            return
        self.reading = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        info("ProWaveDAQ reading started")

    def stop_reading(self):
        """
        停止資料讀取並清理資源
        
        此方法會：
        1. 設定 reading = False（停止讀取迴圈）
        2. 等待讀取執行緒結束
        3. 關閉 Modbus 連線
        
        注意：
            - 此方法會阻塞直到讀取執行緒結束
            - 連線關閉後需要重新呼叫 init_devices() 才能再次使用
        """
        self.reading = False
        if self.thread:
            self.thread.join()
        if self.client:
            self.client.close()
        info("ProWaveDAQ reading stopped")

    def get_data(self) -> List[float]:
        """
        非阻塞式取得資料（從佇列取出）
        
        此方法會從資料佇列中取得一批資料。如果佇列為空，立即返回空列表。
        
        Returns:
            List[float]: 資料列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
                        如果佇列為空，返回空列表 []
        
        注意：
            - 此方法是非阻塞的，不會等待資料
            - 資料格式：每 3 個為一組（X, Y, Z）
            - 建議在迴圈中持續呼叫此方法以取得所有資料
        """
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return []

    def get_sample_rate(self) -> int:
        """
        取得當前設定的取樣率
        
        Returns:
            int: 取樣率（Hz）
        """
        return self.sample_rate

    def _read_loop(self):
        """
        資料讀取主迴圈（在背景執行緒中執行）
        
        此迴圈會持續從設備讀取資料，直到 reading 旗標為 False。
        
        運作流程：
        1. 讀取 FIFO 緩衝區長度
        2. 如果緩衝區為空，等待 2ms 後繼續
        3. 計算要讀取的資料量（最多 123 個字，且必須是 3 的倍數）
        4. 讀取原始資料（16 位元整數）
        5. 轉換為浮點數
        6. 放入資料佇列
        
        注意：
            - 確保每次讀取的資料量是 3 的倍數，避免通道錯位
            - 如果讀取失敗，會等待 100ms 後繼續
            - 此迴圈在背景執行緒中執行，不會阻塞主執行緒
        """
        debug("Read loop started")

        while self.reading:
            try:
                fifo_words = self._read_fifo_size()
                if fifo_words <= 0:
                    time.sleep(0.002)
                    continue

                read_words = min(fifo_words, self.MAX_READ_WORDS)
                read_words = (read_words // self.CHANNELS) * self.CHANNELS
                if read_words == 0:
                    continue

                raw = self._read_raw_data(read_words)
                if not raw:
                    continue

                samples = self._convert_to_float(raw)
                if samples:
                    self._push(samples)

            except Exception as e:
                error(f"Read loop error: {e}")
                time.sleep(0.1)

        debug("Read loop exited")

    def _read_fifo_size(self) -> int:
        """
        讀取 FIFO 緩衝區長度
        
        此方法會讀取設備的 FIFO 緩衝區長度寄存器，取得當前可讀取的資料量。
        
        Returns:
            int: FIFO 緩衝區中的資料字數（0 表示緩衝區為空）
        
        注意：
            - 如果讀取失敗，返回 0
            - 此方法用於判斷是否有資料可讀
        """
        r = self.client.read_input_registers(
            address=self.REG_FIFO_LEN,
            count=1
        )
        if r.isError() or not r.registers:
            return 0
        return r.registers[0]

    def _read_raw_data(self, words: int) -> List[int]:
        """
        讀取原始資料（16 位元整數）
        
        此方法會從設備的原始資料寄存器讀取指定數量的資料。
        
        Args:
            words: 要讀取的字數（必須是 3 的倍數）
        
        Returns:
            List[int]: 原始資料列表（16 位元無符號整數）
                      如果讀取失敗，返回空列表 []
        
        注意：
            - words 參數必須是 3 的倍數，確保讀取完整的樣本（X, Y, Z）
            - 讀取失敗時會輸出警告訊息
        """
        r = self.client.read_input_registers(
            address=self.REG_RAW_DATA_START,
            count=words
        )
        if r.isError():
            warning("Raw data read failed")
            return []
        return r.registers

    def _convert_to_float(self, raw: List[int]) -> List[float]:
        """
        將 16 位元整數轉換為浮點數
        
        此方法會將設備返回的 16 位元無符號整數轉換為有符號整數，
        然後除以 8192.0 進行正規化。
        
        轉換公式：
            - 如果值 < 32768：視為正數
            - 如果值 >= 32768：視為負數（減去 65536）
            - 正規化：除以 8192.0
        
        Args:
            raw: 原始資料列表（16 位元無符號整數，範圍 0-65535）
        
        Returns:
            List[float]: 轉換後的浮點數列表
        
        範例：
            輸入：[0, 16384, 32768, 49152]
            輸出：[0.0, 2.0, -4.0, -2.0]
        """
        out: List[float] = []
        for v in raw:
            signed = v if v < 32768 else v - 65536
            out.append(signed / 8192.0)
        return out

    def _push(self, data: List[float]):
        """
        將資料放入佇列（執行緒安全）
        
        此方法會將處理後的資料放入資料佇列。如果佇列已滿，
        會移除最舊的資料（FIFO），然後放入新資料。
        
        Args:
            data: 要放入的資料列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        
        注意：
            - 使用 put_nowait() 非阻塞放入，避免阻塞讀取迴圈
            - 佇列滿時會丟棄最舊的資料，確保最新資料優先處理
            - 佇列最大容量為 5000 筆
        """
        try:
            self.queue.put_nowait(data)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(data)
            except queue.Empty:
                pass
