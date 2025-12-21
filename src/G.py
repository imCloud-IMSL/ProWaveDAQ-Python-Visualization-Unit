# 這個是Ｇ哥給的正確讀取程式碼，從 LabView 轉換過來的

import time
import threading
import queue
from pymodbus.client import ModbusSerialClient as ModbusClient
from pymodbus.constants import Endian
from pymodbus.payload import BinaryPayloadDecoder

# 全域參數定義
SLAVE_ID = 1
CHIP_ID_ADDRESS = 0x1B       
SAMPLE_RATE_ADDRESS = 0x01   
BUFFER_STATUS_ADDRESS = 0x02 # Normal Mode 數據和長度讀取的起始地址
BULK_MODE_ADDRESS = 0x15     # 21 (x15), Bulk Mode 數據的起始地址
MAX_BULK_SIZE = 9            # 9, 建議的 Bulk 傳輸區塊大小
BULK_TRIGGER_SIZE = 123      # Normal Mode 的最大讀取上限/ Bulk Mode 的切換門檻
DEFAULT_BAUDRATE = 3000000   # 預設鮑率
TARGET_SAMPLE_RATE = 7812    # 取樣率 7812 Hz

# 執行緒安全的資料佇列，用於後端與前端的通訊
DATA_QUEUE = queue.Queue() 

class VibSensorDriver:
    """
    PWRVT 三軸振動即時採集程式的 Modbus 通訊驅動。
    """
    def __init__(self, port, baudrate=DEFAULT_BAUDRATE, timeout=0.5):
        self.client = ModbusClient(
            method='rtu',
            port=port,
            baudrate=baudrate,
            timeout=timeout
        )
        self.buffer_count = 0  # 用於追蹤緩衝區剩餘資料量
        
        # 啟動連線
        if not self.client.connect():
            raise ConnectionError(f"無法連線到 Modbus 裝置於 {port}")
        
        self.client.framer.skip_encode_mobile = True
        self.client.framer.decode_buffer_size = 2048
        print(f"Modbus 連線成功於 {port} @ {baudrate} bps")

    def read_chip_id(self):
        """
        讀取晶片/UCID (FC=03, Address 0x1B)
        """
        rr = self.client.read_holding_registers(address=CHIP_ID_ADDRESS, count=2, slave=SLAVE_ID)
        if rr.isError():
            return None
        decoder = BinaryPayloadDecoder.fromRegisters(rr.registers, byteorder=Endian.Big, wordorder=Endian.Big)
        return decoder.decode_32bit_int()

    def set_sample_rate(self, sample_rate_value: int):
        """
        設定採樣率 (FC=06, Address 0x01)
        """
        rr = self.client.write_register(address=SAMPLE_RATE_ADDRESS, value=sample_rate_value, slave=SLAVE_ID)
        return not rr.isError()

    def _read_registers_with_header(self, address, count, mode_name):
        """
        執行 Modbus 讀取 (FC=04)，並處理標頭(Header)
        """
        # 讀取點數是 N + 1 (第一個暫存器是 Header)
        read_count = count + 1
        
        # 假設所有 Raw Data 讀取均使用 Read Input Registers (FC=04)
        rr = self.client.read_input_registers(address=address, count=read_count, slave=SLAVE_ID)
        
        if rr.isError() or len(rr.registers) != read_count:
            print(f"錯誤或資料長度不符 in {mode_name} Read: {rr}")
            return [], 0
        
        raw_data = rr.registers
        
        # 刪除 Header
        payload_data = raw_data[1:] 
        
        # 緩衝區剩餘數
        remaining_samples = raw_data[0] 
        
        return payload_data, remaining_samples

    def read_normal_data(self, samples_to_read: int):
        """
        Normal Mode 讀取 (FC=04, Address 0x02)
        """
        return self._read_registers_with_header(
            address=BUFFER_STATUS_ADDRESS, 
            count=samples_to_read, 
            mode_name="Normal Mode"
        )
    
    def read_bulk_data(self, samples_to_read: int):
        """
        Bulk Mode 讀取 (FC=04, Address 0x15)
        """
        # 實際讀取樣本數必須限制在 MAX_BULK_SIZE 內 (9)
        bulk_count = min(samples_to_read, MAX_BULK_SIZE) 
        
        return self._read_registers_with_header(
            address=BULK_MODE_ADDRESS,
            count=bulk_count, 
            mode_name="Bulk Mode"
        )
        
    def acquisition_loop(self):
        """
        持續運行並將資料放入佇列(主採集迴圈 / 生產者)
        """
        print("--- 啟動數據採集迴圈 (Producer Thread) ---")
        
        while True:
            try:
                # 檢視有多少資料
                if self.buffer_count == 0:
                    self.buffer_count = self.get_buffer_status() # 呼叫 FC=04, 讀取 0x02 (長度 1)
                    if self.buffer_count == 0:
                        time.sleep(0.01) # 緩衝區為 0，暫待緩衝區補值
                        continue

                # 判斷並執行讀取模式
                if self.buffer_count <= BULK_TRIGGER_SIZE:
                    # Normal Mode
                    samples_to_read = self.buffer_count
                    
                    # Normal Mode 最大讀取長度必須限制在 samples_to_read <= 123
                    final_read_count = min(samples_to_read, BULK_TRIGGER_SIZE)
                    
                    collected_data, remaining = self.read_normal_data(final_read_count)
            
                else: 
                    # Bulk Mode
                    samples_to_read = self.buffer_count
                    
                    # Bulk Read 必須限制在 MAX_BULK_SIZE (9)
                    final_read_count = min(samples_to_read, MAX_BULK_SIZE)
                    
                    collected_data, remaining = self.read_bulk_data(final_read_count)
                
                
                # 資料解編與輸出
                if collected_data and len(collected_data) % 3 == 0:
                    
                    # X 軸數據：索引 0, 3, 6, ...
                    x_data = collected_data[0::3]  
                    # Y 軸數據：索引 1, 4, 7, ...
                    y_data = collected_data[1::3]  
                    # Z 軸數據：索引 2, 5, 8, ...
                    z_data = collected_data[2::3]  
                    
                    # 將解編後的數據放入佇列供前端使用
                    DATA_QUEUE.put({"x": x_data, "y": y_data, "z": z_data})
                    
                    # 更新緩衝區狀態
                    self.buffer_count = remaining 
                
                elif collected_data:
                     # 讀到的資料點數非 3 的倍數，視為錯誤，下次重新詢問
                    print("Warning: Collected data length is not a multiple of 3. Resetting buffer count.")
                    self.buffer_count = 0 
                
                else:
                    # 讀取失敗，下次重新詢問
                    self.buffer_count = 0
                
                time.sleep(0.0001) 
                
            except Exception as e:
                print(f"Acquisition Loop Error: {e}")
                self.buffer_count = 0 # 發生錯誤時重置狀態
                time.sleep(1)

    def get_buffer_status(self):
        """
        讀取緩衝區樣本數 (FC=04, Address 0x02)
        """
        rr = self.client.read_input_registers(address=BUFFER_STATUS_ADDRESS, count=1, slave=SLAVE_ID)
        return rr.registers[0] if not rr.isError() else 0

    def close(self):
        """關閉連線"""
        self.client.close()


# 啟動函式
def start_driver_thread(com_port, baud_rate):
    """
    初始化驅動並啟動生產者執行緒
    """
    try:
        driver = VibSensorDriver(port=com_port, baudrate=baud_rate)
        
        # 確保設定採樣率
        if not driver.set_sample_rate(TARGET_SAMPLE_RATE):
            print("FATAL ERROR: 無法設定採樣率，請檢查設備是否支援或連線是否正常。")
            return None
        
        # 啟動執行緒
        t = threading.Thread(target=driver.acquisition_loop)
        t.daemon = True 
        t.start()
        
        return driver
    except ConnectionError as e:
        print(f"無法啟動驅動程序：{e}")
        return None