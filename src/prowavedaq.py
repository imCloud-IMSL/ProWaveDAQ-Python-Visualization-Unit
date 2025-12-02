#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ Python版本
振動數據採集系統 - 使用Modbus RTU通訊協議

版本：3.0.0

設計目標：
- 對外 API 與原本版本相容（給 main / 前端用）
- 讀取流程模組化，方便未來調整
- 確保 X/Y/Z 通道不會錯位：每次讀取只處理「當次完整的 XYZ 三軸組」
"""

import re
import time
import threading
import configparser
from typing import List, Optional
import glob
import sys
import queue

try:
    from pymodbus.client import ModbusSerialClient
except ImportError:
    print("Error: Unable to find compatible pymodbus version")
    print("Please ensure pymodbus is installed: pip install pymodbus>=3.6.0")
    print("Or try reinstalling: pip uninstall pymodbus && pip install pymodbus>=3.6.0")
    sys.exit(1)

try:
    from logger import info, debug, error, warning
except ImportError:
    def info(msg): print(f"[INFO] {msg}")
    def debug(msg): print(f"[DEBUG] {msg}")
    def error(msg): print(f"[ERROR] {msg}")
    def warning(msg): print(f"[WARN] {msg}")


class ProWaveDAQ:
    """ProWaveDAQ 振動數據採集類別"""

    # Modbus 寄存器定義
    REG_SAMPLE_RATE = 0x01       # 取樣率設定
    REG_FIFO_LEN = 0x02          # FIFO 長度 / Normal Mode 數據和長度讀取的起始地址
    REG_CHIP_ID = 0x80           # 晶片 ID 起始位址
    
    # Bulk Mode 相關定義
    BULK_MODE_ADDRESS = 0x15     # Bulk Mode 數據的起始地址
    MAX_BULK_SIZE = 9            # Bulk Mode 建議的傳輸區塊大小
    BULK_TRIGGER_SIZE = 123      # Normal Mode 的最大讀取上限 / Bulk Mode 的切換門檻

    CHANNEL_COUNT = 3            # X, Y, Z

    def __init__(self):
        """初始化 ProWaveDAQ 物件（只做狀態初始化，不連線）"""
        self.client: Optional[ModbusSerialClient] = None
        self.serial_port = "/dev/ttyUSB0"
        self.baud_rate = 3000000
        self.sample_rate = 7812
        self.slave_id = 1

        self.counter = 0
        self.reading = False
        self.reading_thread: Optional[threading.Thread] = None
        self.buffer_count = 0

        self.data_queue: "queue.Queue[List[float]]" = queue.Queue(maxsize=10000)
        self.latest_data: List[float] = []
        self.data_mutex = threading.Lock()
        self.queue_mutex = threading.Lock()
        self.remaining_data: List[int] = []
        self.remaining_data_lock = threading.Lock()

    def scan_devices(self) -> None:
        """
        掃描 /dev/ttyUSB* 下可用的 Modbus 設備
        
        此方法會掃描系統中所有符合 /dev/ttyUSB* 模式的串列埠設備，
        並在日誌中列出找到的設備。這有助於確認設備是否正確連接。
        
        注意：此方法只掃描設備，不會建立連線。
        """
        devices: List[str] = []
        usb_pattern = re.compile(r'/dev/ttyUSB[0-9]+')

        try:
            for entry in glob.glob('/dev/ttyUSB*'):
                if usb_pattern.match(entry):
                    devices.append(entry)
        except Exception as e:
            error(f"Error scanning devices: {e}")
            return

        if not devices:
            error("No Modbus devices found!")
            return

        debug("Available Modbus devices:")
        for i, dev in enumerate(devices, 1):
            debug(f"({i}) {dev}")

    def init_devices(self, filename: str) -> None:
        """
        從 INI 檔案初始化設備並建立 Modbus 連線
        INI 段落： [ProWaveDAQ]
            serialPort = /dev/ttyUSB0
            baudRate   = 3000000
            sampleRate = 7812
            slaveID    = 1
        """
        debug("Loading settings from INI file...")

        try:
            config = configparser.ConfigParser()
            config.read(filename, encoding="utf-8")

            self.serial_port = config.get(
                "ProWaveDAQ", "serialPort", fallback="/dev/ttyUSB0"
            )
            self.baud_rate = config.getint(
                "ProWaveDAQ", "baudRate", fallback=3000000
            )
            self.sample_rate = config.getint(
                "ProWaveDAQ", "sampleRate", fallback=7812
            )
            self.slave_id = config.getint("ProWaveDAQ", "slaveID", fallback=1)

            debug(
                "Settings loaded from INI file:\n"
                f"  Serial Port: {self.serial_port}\n"
                f"  Baud Rate  : {self.baud_rate}\n"
                f"  Sample Rate: {self.sample_rate}\n"
                f"  Slave ID   : {self.slave_id}"
            )
        except Exception as e:
            error(f"Error parsing INI file: {e}")
            return

        if not self._connect():
            error("Failed to establish Modbus connection!")
            return

        self._read_chip_id()
        self._set_sample_rate()

    def start_reading(self) -> None:
        """開始讀取振動數據（背景執行緒）"""
        if self.reading:
            warning("Reading is already in progress")
            return

        if not self._ensure_connected():
            error("Cannot start reading: Modbus connection not available")
            return

        self.counter = 0
        self.buffer_count = 0
        with self.remaining_data_lock:
            self.remaining_data = []
        self.reading = True
        self.reading_thread = threading.Thread(
            target=self._read_loop, name="ProWaveDAQReadLoop"
        )
        self.reading_thread.daemon = True
        self.reading_thread.start()
        info("ProWaveDAQ reading started")

    def stop_reading(self) -> None:
        """停止讀取振動數據，並關閉連線"""
        if self.reading:
            self.reading = False
            if self.reading_thread and self.reading_thread.is_alive():
                self.reading_thread.join()

        self.counter = 0

        with self.remaining_data_lock:
            if self.remaining_data:
                warning(f"Discarding {len(self.remaining_data)} remaining raw data points on stop")
            self.remaining_data = []

        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        self._disconnect()
        info("ProWaveDAQ reading stopped")

    def get_data(self) -> List[float]:
        """
        非阻塞取得最新一批振動數據
        回傳：
            List[float]，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
            若目前沒有資料則回傳空 list
        """
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return []

    def get_data_blocking(self, timeout: float = 0.1) -> List[float]:
        """
        阻塞取得最新一批振動數據
        timeout:
            最多等待秒數
        回傳：
            List[float]，格式為 [X1, Y1, Z1, ...]
            若 timeout 內無資料則回傳空 list
        """
        try:
            return self.data_queue.get(timeout=timeout)
        except queue.Empty:
            return []

    def get_counter(self) -> int:
        """回傳 read loop 成功處理的批次數"""
        return self.counter

    def reset_counter(self) -> None:
        """重置讀取批次計數器"""
        self.counter = 0

    def get_sample_rate(self) -> int:
        """回傳目前設定的取樣率"""
        return self.sample_rate

    def _connect(self) -> bool:
        """建立 Modbus RTU 連線"""
        try:
            if self.client:
                try:
                    self.client.close()
                except Exception:
                    pass

            self.client = ModbusSerialClient(
                port=self.serial_port,
                baudrate=self.baud_rate,
                timeout=1,
                parity="N",
                stopbits=1,
                bytesize=8,
                framer="rtu",
            )

            if not self.client.connect():
                error("ModbusSerialClient.connect() failed")
                self.client = None
                return False

            self.client.unit_id = self.slave_id
            
            try:
                self.client.framer.skip_encode_mobile = True
                self.client.framer.decode_buffer_size = 2048
            except AttributeError:
                pass
            
            info("Modbus connection established")
            return True
        except Exception as e:
            error(f"Error establishing Modbus connection: {e}")
            self.client = None
            return False

    def _disconnect(self) -> None:
        """關閉 Modbus 連線"""
        try:
            if self.client:
                self.client.close()
        except Exception:
            pass
        finally:
            self.client = None

    def _ensure_connected(self) -> bool:
        """如果連線不存在或中斷，嘗試重連"""
        if not self.client:
            return self._connect()

        try:
            if self.client.is_connected():
                return True
        except AttributeError:
            return True
        except Exception as e:
            warning(f"Error checking connection state: {e}")

        warning("Modbus connection lost, attempting to reconnect...")
        return self._connect()

    def _read_chip_id(self) -> None:
        """讀取晶片 ID"""
        if not self.client:
            return

        try:
            result = self.client.read_input_registers(
                address=self.REG_CHIP_ID, count=3
            )
            if result.isError():
                warning("Failed to read chip ID")
                return

            regs = result.registers
            if len(regs) >= 3:
                debug(f"Chip ID: {hex(regs[0])}, {hex(regs[1])}, {hex(regs[2])}")
            else:
                warning(f"Chip ID read length unexpected: {len(regs)}")
        except Exception as e:
            warning(f"Error reading chip ID: {e}")

    def _set_sample_rate(self) -> None:
        """寫入取樣率到寄存器"""
        if not self.client:
            return

        try:
            result = self.client.write_register(
                address=self.REG_SAMPLE_RATE, value=self.sample_rate
            )
            if result.isError():
                error("Failed to set sample rate")
            else:
                debug(f"Sample rate set to {self.sample_rate} Hz")
        except Exception as e:
            error(f"Error setting sample rate: {e}")

    def _read_registers_with_header(self, address: int, count: int, mode_name: str) -> tuple[List[int], int]:
        """
        執行 Modbus 讀取 (FC=04)，並處理標頭(Header)
        讀取點數是 N + 1（第一個暫存器是 Header，包含剩餘樣本數）
        
        Args:
            address: 起始寄存器地址
            count: 要讀取的資料樣本數（word 數）
            mode_name: 模式名稱（用於錯誤訊息）
        
        Returns:
            tuple[List[int], int]: (payload_data, remaining_samples)
        """
        if not self.client:
            return [], 0
        
        read_count = count + 1
        
        try:
            result = self.client.read_input_registers(
                address=address, count=read_count
            )
            
            if result.isError() or len(result.registers) != read_count:
                warning(f"錯誤或資料長度不符 in {mode_name} Read: expected {read_count}, got {len(result.registers) if not result.isError() else 0}")
                return [], 0
            
            raw_data = result.registers
            payload_data = raw_data[1:]
            remaining_samples = raw_data[0]
            
            return payload_data, remaining_samples
        except Exception as e:
            warning(f"Error in {mode_name} read: {e}")
            return [], 0
    
    def _read_normal_data(self, samples_to_read: int) -> tuple[List[int], int]:
        """
        Normal Mode 讀取 (FC=04, Address 0x02)
        當 buffer_count <= BULK_TRIGGER_SIZE (123) 時使用此模式
        """
        final_read_count = min(samples_to_read, self.BULK_TRIGGER_SIZE)
        return self._read_registers_with_header(
            address=self.REG_FIFO_LEN,
            count=final_read_count,
            mode_name="Normal Mode"
        )
    
    def _read_bulk_data(self, samples_to_read: int) -> tuple[List[int], int]:
        """
        Bulk Mode 讀取 (FC=04, Address 0x15)
        當 buffer_count > BULK_TRIGGER_SIZE (123) 時使用此模式
        """
        bulk_count = min(samples_to_read, self.MAX_BULK_SIZE)
        return self._read_registers_with_header(
            address=self.BULK_MODE_ADDRESS,
            count=bulk_count,
            mode_name="Bulk Mode"
        )
    
    def _get_buffer_status(self) -> int:
        """
        讀取緩衝區樣本數 (FC=04, Address 0x02)
        """
        if not self.client:
            return 0
        
        try:
            result = self.client.read_input_registers(
                address=self.REG_FIFO_LEN, count=1
            )
            if result.isError():
                return 0
            return result.registers[0] if result.registers else 0
        except Exception as e:
            warning(f"Error reading buffer status: {e}")
            return 0

    @staticmethod
    def _convert_raw_to_float_samples(raw_block: List[int]) -> List[float]:
        """
        將一批原始資料轉成浮點數列表，並保證 XYZ 通道不錯位
        
        此方法會：
        1. 只處理完整的 XYZ 三軸組（捨棄不足一組的資料）
        2. 將 16-bit 有符號整數轉換為浮點數（除以 8192.0）
        3. 確保輸出格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        
        Args:
            raw_block: 原始資料列表（16-bit 無符號整數），格式為 [X, Y, Z, X, Y, Z, ...]
        
        Returns:
            List[float]: 轉換後的浮點數列表，格式為 [X1, Y1, Z1, X2, Y2, Z2, ...]
        
        注意：
            - 如果資料長度不是 3 的倍數，會自動捨棄最後不足一組 XYZ 的資料
            - 這是為了避免通道錯位（例如：如果最後只有 1 個值，無法確定是 X、Y 還是 Z）
            - 轉換公式：signed_value = (value < 32768) ? value : value - 65536
            - 最終浮點數 = signed_value / 8192.0
        """
        if not raw_block:
            return []

        sample_word_count = (len(raw_block) // ProWaveDAQ.CHANNEL_COUNT) * ProWaveDAQ.CHANNEL_COUNT
        if sample_word_count <= 0:
            return []

        data_words = raw_block[:sample_word_count]
        float_samples: List[float] = []
        for w in data_words:
            signed = w if w < 32768 else w - 65536
            float_samples.append(signed / 8192.0)

        return float_samples

    def _read_loop(self) -> None:
        """
        主要讀取迴圈（在背景執行緒中執行）
        使用 Normal Mode 和 Bulk Mode 自動切換
        """
        consecutive_errors = 0
        max_consecutive_errors = 5

        debug("Read loop started")

        while self.reading:
            if not self._ensure_connected():
                consecutive_errors += 1
                if consecutive_errors >= max_consecutive_errors:
                    error("Too many connection failures, stopping read loop")
                    break
                time.sleep(0.5)
                continue

            try:
                if self.buffer_count == 0:
                    self.buffer_count = self._get_buffer_status()
                    if self.buffer_count == 0:
                        time.sleep(0.01)
                        continue

                collected_data = []
                remaining = 0
                
                if self.buffer_count <= self.BULK_TRIGGER_SIZE:
                    samples_to_read = self.buffer_count
                    collected_data, remaining = self._read_normal_data(samples_to_read)
                else:
                    samples_to_read = self.buffer_count
                    collected_data, remaining = self._read_bulk_data(samples_to_read)
                
                if collected_data and len(collected_data) % self.CHANNEL_COUNT == 0:
                    samples = self._convert_raw_to_float_samples(collected_data)
                    if not samples:
                        warning("Failed to convert raw data to float samples")
                        self.buffer_count = 0
                        continue
                    
                    try:
                        self.data_queue.put_nowait(samples)
                    except queue.Full:
                        try:
                            self.data_queue.get_nowait()
                            self.data_queue.put_nowait(samples)
                        except queue.Empty:
                            pass
                    
                    self.buffer_count = remaining
                    consecutive_errors = 0
                    self.counter += 1
                    
                elif collected_data:
                    warning(f"Collected data length ({len(collected_data)}) is not a multiple of {self.CHANNEL_COUNT}. Resetting buffer count.")
                    self.buffer_count = 0
                else:
                    self.buffer_count = 0
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        error("Too many read failures, stopping read loop")
                        break
                
                time.sleep(0.0001)

            except Exception as e:
                consecutive_errors += 1
                error(f"Error in read loop: {e}")
                if consecutive_errors >= max_consecutive_errors:
                    error("Too many consecutive errors, stopping read loop")
                    break
                self.buffer_count = 0
                time.sleep(0.1)

        self.reading = False
        debug("Read loop exited")

    def __del__(self):
        try:
            self.stop_reading()
        except Exception:
            pass