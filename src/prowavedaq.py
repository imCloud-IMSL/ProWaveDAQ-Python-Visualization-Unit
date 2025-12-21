#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ 設備通訊模組

基於原廠手冊 RS485_ModbusRTU通訊說明_PwDAQ.pdf 第 5 頁規範：
1. 使用 FC04 (Read Input Registers)
2. 起始位址為 0x02 (Raw data FIFO buffer size)
3. 讀取架構：[Size(1 word)] + [Data(N words)]
"""

import time
import threading
import configparser
import queue
from typing import List, Optional, Tuple

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
    ProWaveDAQ 設備通訊類別 (遵守原廠手冊 Page 5 規範)
    """
    
    # ========== 原廠手冊定義暫存器 ==========
    # Page 1[cite: 6]: 取樣率設定 (FC06)
    REG_SAMPLE_RATE = 0x01      
    
    # Page 5[cite: 47, 50]: 資料緩衝區大小與起始位址 (FC04)
    # 說明: 需連同 FIFO buffer size (0x02) 一起讀出 
    REG_FIFO_STATUS = 0x02    
    
    # 單次最大讀取字數 (手冊 Page 1 提到 Raw data range 0x03~0x7D，約 123 words) [cite: 6]
    MAX_READ_WORDS = 123 
    
    CHANNELS = 3

    def __init__(self):
        self.serial_port = "/dev/ttyUSB0"
        self.baud_rate = 3_000_000 # 支援 3M bps 
        self.sample_rate = 7812    # I-type default [cite: 6]
        self.slave_id = 1          # Default ID 

        self.client: Optional[ModbusSerialClient] = None
        self.reading = False
        self.thread: Optional[threading.Thread] = None
        self.queue: "queue.Queue[List[float]]" = queue.Queue(maxsize=5000)

    def init_devices(self, ini_path: str):
        """初始化設備"""
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
        """建立連線，參數參照手冊 Page 1 """
        self.client = ModbusSerialClient(
            port=self.serial_port,
            baudrate=self.baud_rate,
            parity="N",      # Parity: None 
            stopbits=1,      # Stop bit: 1 
            bytesize=8,      # Data bits: 8 
            timeout=0.5,
            framer="rtu",
        )
        if not self.client.connect():
            return False
        self.client.unit_id = self.slave_id
        # 優化讀取效能
        self.client.framer.skip_encode_mobile = True 
        info("Modbus connection established")
        return True

    def _set_sample_rate(self):
        """設定取樣率，使用 FC06 [cite: 4, 15]"""
        # Page 4: Sample rate change [cite: 15]
        r = self.client.write_register(self.REG_SAMPLE_RATE, self.sample_rate)
        if r.isError():
            error("Failed to set sample rate")
        else:
            debug(f"Sample rate set to {self.sample_rate} Hz")

    def start_reading(self):
        if self.reading:
            return
        self.reading = True
        self.thread = threading.Thread(target=self._read_loop, daemon=True)
        self.thread.start()
        info("ProWaveDAQ reading started")

    def stop_reading(self):
        self.reading = False
        if self.thread:
            self.thread.join()
        if self.client:
            self.client.close()
        info("ProWaveDAQ reading stopped")

    def get_data(self) -> List[float]:
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return []
            
    def get_sample_rate(self) -> int:
        return self.sample_rate

    def _read_loop(self):
        """
        資料讀取主迴圈 (遵循手冊 Page 5 流程)
        """
        debug("Read loop started (Manual Page 5 Logic)")

        while self.reading:
            try:
                # 步驟 1: 讀取 0x02 取得目前緩衝區大小 [cite: 47]
                # 手冊 Page 5: 讀取資料緩衝大小
                buffer_size = self._read_fifo_size()
                
                # 如果緩衝區為空，稍作等待
                if buffer_size <= 0:
                    time.sleep(0.002)
                    continue

                # 步驟 2: 計算要讀取的長度
                # 手冊 Page 5: 需連同 FIFO buffer size (0x02) 一起讀出
                # 所以實際讀取長度 = 資料長度 + 1 (Header)
                # 限制單次讀取最大量 [cite: 6]
                read_count = min(buffer_size, self.MAX_READ_WORDS)
                
                # 確保讀取完整的 X,Y,Z (3的倍數)
                read_count = (read_count // self.CHANNELS) * self.CHANNELS
                
                if read_count == 0:
                    continue

                # 步驟 3: 執行讀取 (FC04, Start Address 0x02)
                # Request 讀取 read_count + 1 個 Word
                raw_packet = self._read_data_packet(read_count + 1)
                
                if not raw_packet:
                    continue
                
                # 步驟 4: 解析封包 [Header, Data...]
                # raw_packet[0] 是這一次讀回來時，暫存器 0x02 的值 (剩餘大小)
                # raw_packet[1:] 是實際的資料 (0x03 ~ ...)
                payload_data = raw_packet[1:]
                
                # 步驟 5: 轉換與推送
                samples = self._convert_to_float(payload_data)
                if samples:
                    self._push(samples)

            except Exception as e:
                error(f"Read loop error: {e}")
                time.sleep(0.1)

    def _read_fifo_size(self) -> int:
        """
        讀取暫存器 0x02 (Raw data FIFO buffer size) [cite: 47]
        """
        r = self.client.read_input_registers(address=self.REG_FIFO_STATUS, count=1)
        if r.isError() or not r.registers:
            return 0
        return r.registers[0]

    def _read_data_packet(self, total_words: int) -> List[int]:
        """
        從 0x02 開始讀取指定長度 
        Args:
            total_words: 資料長度 + 1 (Header)
        """
        r = self.client.read_input_registers(address=self.REG_FIFO_STATUS, count=total_words)
        if r.isError() or len(r.registers) != total_words:
            # warning("Packet read failed or incomplete")
            return []
        return r.registers

    def _convert_to_float(self, raw: List[int]) -> List[float]:
        """
        數值轉換
        手冊未明確寫出轉換公式細節，但通常為 Signed 16-bit 轉換。
        沿用原本邏輯，假設 13-bit 解析度或類似規格 (除以 8192.0)。
        """
        out: List[float] = []
        for v in raw:
            # 處理 Signed 16-bit
            signed = v if v < 32768 else v - 65536
            out.append(signed / 8192.0)
        return out

    def _push(self, data: List[float]):
        """將資料推入佇列"""
        try:
            self.queue.put_nowait(data)
        except queue.Full:
            try:
                self.queue.get_nowait()
                self.queue.put_nowait(data)
            except queue.Empty:
                pass
