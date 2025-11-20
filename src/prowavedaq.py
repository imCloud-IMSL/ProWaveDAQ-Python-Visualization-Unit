#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ProWaveDAQ Python版本
振動數據採集系統 - 使用Modbus RTU通訊協議
"""

import os
import re
import time
import threading
import configparser
from typing import List, Optional
import glob
import sys
import queue

try:
    # 嘗試pymodbus 3.6.0+的新import路徑
    from pymodbus.client import ModbusSerialClient
except ImportError:
    print("Error: Unable to find compatible pymodbus version")
    print("Please ensure pymodbus is installed: pip install pymodbus>=3.6.0")
    print("Or try reinstalling: pip uninstall pymodbus && pip install pymodbus>=3.6.0")
    sys.exit(1)


class ProWaveDAQ:
    """ProWaveDAQ振動數據採集類別"""

    def __init__(self):
        """初始化ProWaveDAQ物件"""
        self.client: Optional[ModbusSerialClient] = None
        self.serial_port = "/dev/ttyUSB0"
        self.baud_rate = 3000000
        self.sample_rate = 7812
        self.slave_id = 1
        self.counter = 0
        self.reading = False
        self.reading_thread: Optional[threading.Thread] = None
        self.latest_data: List[float] = []
        self.data_mutex = threading.Lock()
        # 新增：數據佇列用於避免重複讀取
        self.data_queue = queue.Queue(maxsize=1000)
        self.queue_mutex = threading.Lock()

    def scan_devices(self) -> None:
        """掃描可用的Modbus設備"""
        devices = []
        usb_pattern = re.compile(r'/dev/ttyUSB[0-9]+')

        # 掃描/dev/目錄中的ttyUSB設備
        try:
            for entry in glob.glob('/dev/ttyUSB*'):
                if usb_pattern.match(entry):
                    devices.append(entry)
        except Exception as e:
            print(f"[Error] Error scanning devices: {e}")
            return

        # 如果沒有找到設備
        if not devices:
            print("[Error] No Modbus devices found!")
            return

        # 顯示可用設備
        print("[Debug] Available Modbus devices:")
        for i, device in enumerate(devices, 1):
            print(f"({i}) {device}")

    def init_devices(self, filename: str) -> None:
        """從INI檔案初始化設備"""
        print("[Debug] Loading settings from INI file...")

        try:
            config = configparser.ConfigParser()
            config.read(filename, encoding='utf-8')

            # 讀取設定值
            self.serial_port = config.get(
                'ProWaveDAQ', 'serialPort', fallback='/dev/ttyUSB0')
            self.baud_rate = config.getint(
                'ProWaveDAQ', 'baudRate', fallback=3000000)
            self.sample_rate = config.getint(
                'ProWaveDAQ', 'sampleRate', fallback=7812)
            self.slave_id = config.getint('ProWaveDAQ', 'slaveID', fallback=1)

            print(f"[Debug] Settings loaded from INI file:\n"
                  f"Serial Port: {self.serial_port}\n"
                  f"Baud Rate: {self.baud_rate}\n"
                  f"Sample Rate: {self.sample_rate}\n"
                  f"Slave ID: {self.slave_id}")

        except Exception as e:
            print(f"[Error] Error parsing INI file: {e}")
            return

        # 步驟1：建立Modbus連線
        print("[Debug] Establishing Modbus connection...")
        try:
            # pymodbus 3.11.3版本的初始化方式
            self.client = ModbusSerialClient(
                port=self.serial_port,
                baudrate=self.baud_rate,
                timeout=1,
                parity='N',
                stopbits=1,
                bytesize=8,
                framer="rtu"
            )

            if not self.client.connect():
                print("[Error] Failed to establish Modbus connection!")
                return

            self.client.unit_id = self.slave_id

            print("[Debug] Modbus connection established successfully.")

        except Exception as e:
            print(f"[Error] Error establishing Modbus connection: {e}")
            return

        # 步驟2：設定從站ID
        print("[Debug] Setting Modbus slave ID...")
        # pymodbus會自動處理從站ID，在讀取時指定

        # 步驟3：讀取晶片ID
        try:
            result = self.client.read_input_registers(address=0x80, count=3)
            if result.isError():
                print("[Error] Failed to read chip ID!")
            else:
                chip_id = result.registers
                print(
                    f"[Debug] Chip ID: {hex(chip_id[0])}, {hex(chip_id[1])}, {hex(chip_id[2])}")
        except Exception as e:
            print(f"[Error] Error reading chip ID: {e}")

        # 步驟4：設定取樣率
        print("[Debug] Setting sample rate...")
        try:
            result = self.client.write_register(
                address=0x01, value=self.sample_rate)
            if result.isError():
                print("[Error] Failed to set sample rate!")
            else:
                print("[Debug] Sample rate set successfully.")
        except Exception as e:
            print(f"[Error] Error setting sample rate: {e}")

    def start_reading(self) -> None:
        """開始讀取振動數據（在背景執行緒中執行）"""
        if self.reading:
            print("[Error] Reading is already in progress!")
            return

        self.reading = True
        self.reading_thread = threading.Thread(target=self._read_loop)
        self.reading_thread.daemon = True
        self.reading_thread.start()

    def stop_reading(self) -> None:
        """停止讀取振動數據"""
        if self.reading:
            self.reading = False
            if self.reading_thread and self.reading_thread.is_alive():
                self.reading_thread.join()

        # 重置計數器和清空佇列
        self.counter = 0
        while not self.data_queue.empty():
            try:
                self.data_queue.get_nowait()
            except queue.Empty:
                break

        if self.client:
            self.client.close()

    def _reconnect(self) -> bool:
        """重新連線到 Modbus 設備"""
        try:
            if self.client:
                # 先關閉舊連線
                try:
                    self.client.close()
                except:
                    pass

            # 重新建立連線
            self.client = ModbusSerialClient(
                port=self.serial_port,
                baudrate=self.baud_rate,
                timeout=1,
                parity='N',
                stopbits=1,
                bytesize=8,
                framer="rtu"
            )

            if not self.client.connect():
                return False

            self.client.unit_id = self.slave_id
            print("[Info] Modbus connection re-established")
            return True
        except Exception as e:
            print(f"[Error] Reconnection failed: {e}")
            return False

    def _read_loop(self) -> None:
        """讀取振動數據（主要讀取迴圈）"""
        max_size = 41 * 3
        vib_data = [0] * (max_size + 1)
        consecutive_errors = 0
        max_consecutive_errors = 5

        try:
            # 讀取數據長度
            if not self.client:
                print("[Error] Modbus connection not established")
                return

            # 檢查連線狀態（pymodbus 3.x 使用 is_connected 方法）
            try:
                if not self.client.is_connected():
                    print("[Error] Modbus connection not established")
                    return
            except AttributeError:
                # 如果沒有 is_connected 方法，嘗試檢查連線
                pass

            result = self.client.read_input_registers(address=0x02, count=1)
            if result.isError():
                print("[Error] Failed to read data length")
                return

            this_len = result.registers[0]
            # print(f"[Debug] Initial data length: {this_len}")

            # print("[Debug] Read loop started...")
            while self.reading:
                # 檢查連線狀態
                is_connected = False
                if self.client:
                    try:
                        is_connected = self.client.is_connected()
                    except AttributeError:
                        # 如果沒有 is_connected 方法，假設連線正常
                        is_connected = True

                if not is_connected:
                    print(
                        "[Warning] Modbus connection lost, attempting to reconnect...")
                    consecutive_errors += 1
                    if consecutive_errors >= max_consecutive_errors:
                        print(
                            f"[Error] {max_consecutive_errors} consecutive connection failures, stopping read")
                        self.reading = False
                        break

                    if self._reconnect():
                        consecutive_errors = 0
                        # 重新讀取數據長度
                        result = self.client.read_input_registers(
                            address=0x02, count=1)
                        if result.isError():
                            print(
                                "[Error] Failed to read data length after reconnection")
                            time.sleep(0.1)
                            continue
                        this_len = result.registers[0]
                    else:
                        time.sleep(1.0)  # 等待1秒後再試
                        continue

                lest_len = this_len

                try:
                    if vib_data[0] >= max_size:
                        result = self.client.read_input_registers(
                            address=0x02, count=max_size + 1)
                        if not result.isError():
                            vib_data = result.registers
                            this_len = max_size
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                print(
                                    f"[Error] {max_consecutive_errors} consecutive read failures, connection may be lost")
                                break
                            time.sleep(0.01)
                            continue
                    elif vib_data[0] <= 6:
                        time.sleep(0.001)  # 1ms
                        result = self.client.read_input_registers(
                            address=0x02, count=1)
                        if not result.isError():
                            vib_data = result.registers
                            this_len = vib_data[0]
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                print(
                                    f"[Error] {max_consecutive_errors} consecutive read failures, connection may be lost")
                                break
                        continue
                    else:
                        result = self.client.read_input_registers(
                            address=0x02, count=vib_data[0] + 1)
                        if not result.isError():
                            vib_data = result.registers
                            this_len = vib_data[0]
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                            if consecutive_errors >= max_consecutive_errors:
                                print(
                                    f"[Error] {max_consecutive_errors} consecutive read failures, connection may be lost")
                                break
                            time.sleep(0.01)
                            continue

                    # 處理數據並放入佇列
                    processed_data = []

                    # 確保索引不超出範圍
                    actual_len = min(lest_len, len(vib_data) - 1)
                    if actual_len > 0:
                        # print(f"[Debug] Processing data: lest_len={lest_len}, vib_data length={len(vib_data)}, actual_len={actual_len}")
                        for i in range(1, actual_len + 1):
                            # 將16位元有符號整數轉換為浮點數
                            value = vib_data[i] if vib_data[i] < 32768 else vib_data[i] - 65536
                            processed_data.append(value / 8192.0)

                        # 將處理後的數據放入佇列
                        try:
                            self.data_queue.put_nowait(processed_data)
                        except queue.Full:
                            # 佇列滿了，移除最舊的數據
                            try:
                                self.data_queue.get_nowait()
                                self.data_queue.put_nowait(processed_data)
                            except queue.Empty:
                                pass
                    else:
                        print(
                            f"[Warning] Skipping data processing: lest_len={lest_len}, vib_data length={len(vib_data)}")

                    self.counter += 1

                except Exception as e:
                    consecutive_errors += 1
                    error_msg = str(e)
                    if "Connection" in error_msg or "Failed to connect" in error_msg:
                        print(f"[Error] Modbus connection error: {error_msg}")
                        # 標記連線為斷開
                        if self.client:
                            try:
                                self.client.close()
                            except:
                                pass
                    else:
                        print(f"[Error] Error reading data: {e}")

                    if consecutive_errors >= max_consecutive_errors:
                        print(
                            f"[Error] {max_consecutive_errors} consecutive errors, stopping read")
                        break

                    time.sleep(0.1)  # 等待後再試

        except Exception as e:
            print(f"[Error] Critical error in read loop: {e}")

    def get_data(self) -> List[float]:
        """取得最新的振動數據（從佇列中取出）"""
        try:
            return self.data_queue.get_nowait()
        except queue.Empty:
            return []

    def get_data_blocking(self, timeout: float = 0.1) -> List[float]:
        """阻塞式取得振動數據"""
        try:
            return self.data_queue.get(timeout=timeout)
        except queue.Empty:
            return []

    def get_counter(self) -> int:
        """取得數據讀取次數"""
        return self.counter

    def reset_counter(self) -> None:
        """重置計數器"""
        self.counter = 0

    def get_sample_rate(self) -> int:
        """取得取樣率"""
        return self.sample_rate

    def __del__(self):
        """解構函數"""
        self.stop_reading()