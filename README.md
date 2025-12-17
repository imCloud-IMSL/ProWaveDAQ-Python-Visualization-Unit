# ProWaveDAQ 即時資料可視化系統

## 系統概述

ProWaveDAQ 即時資料可視化系統是一個基於 Python 的振動數據採集與可視化平台，用於從 **ProWaveDAQ**（Modbus RTU）設備取得振動數據，並在瀏覽器中即時顯示所有資料點的連續曲線，同時自動進行 CSV 儲存和 SQL 資料庫上傳。

本系統提供完整的 Web 介面，讓使用者可以透過瀏覽器操作，不需進入終端機，即可：
- 修改設定檔（`ProWaveDAQ.ini`、`Master.ini`、`sql.ini`）
- 輸入資料標籤（Label）
- 設定 SQL 伺服器上傳（可選）
- 按下「開始讀取」即啟動採集與即時顯示
- 系統同時自動分檔儲存資料（根據 `Master.ini` 的秒數）
- 按下「停止」即可安全結束，並自動上傳剩餘資料

## 功能特性

### 核心功能
- **即時資料採集**：透過 Modbus RTU 協議從 ProWaveDAQ 設備讀取振動數據
- **即時資料可視化**：使用 Chart.js 在瀏覽器中顯示多通道連續曲線圖
- **自動 CSV 儲存**：根據設定檔自動分檔儲存資料
- **SQL 資料庫上傳**：可選的 SQL 伺服器上傳功能，支援 MySQL/MariaDB
- **Web 介面控制**：完整的瀏覽器操作介面，無需終端機
- **設定檔管理**：透過 Web 介面使用固定輸入框編輯設定檔（防止誤刪參數）

### 技術特性
- 使用 Flask 提供 Web 服務
- 使用 Chart.js 實現即時圖表（每 200ms 更新）
- 多執行緒架構，確保資料採集與 Web 服務不互相干擾
- 記憶體中資料傳遞，高效能即時處理
- 支援多通道資料顯示（預設 3 通道：X, Y, Z）
- 智慧緩衝區管理，優化記憶體使用
- 資料保護機制，確保資料不遺失（重試機制、失敗保留）
- 統一日誌系統，自動時間戳記和日誌級別管理
- 通道錯位保護機制，確保資料順序正確
- 時間戳記精確計算，根據取樣率自動計算每個樣本的時間

## 系統需求

### 硬體需求
- ProWaveDAQ 設備（透過 Modbus RTU 連接）
- 串列埠（USB 轉串列埠或直接串列埠）
- 支援 Python 3.9+ 的系統（建議 DietPi 或其他 Debian-based 系統）
- （可選）SQL 伺服器（MySQL/MariaDB）用於資料上傳

### 軟體需求
- Python 3.9 或更高版本
- 支援的作業系統：
  - DietPi（建議）
  - Debian-based Linux 發行版
  - Ubuntu
  - Raspberry Pi OS

### Python 套件依賴
請參考 `requirements.txt` 檔案，主要依賴包括：
- `pymodbus>=3.11.3` - Modbus 通訊
- `pyserial>=3.5` - 串列埠通訊
- `Flask>=3.1.2` - Web 伺服器
- `pymysql>=1.0.2` - SQL 資料庫連線（MySQL/MariaDB）

## 安裝說明

### 1. 克隆或下載專案
```bash
cd /path/to/ProWaveDAQ_Python_Visualization_Unit
```

### 簡易安裝指令
```bash
./deploy.sh
```

**注意**：`deploy.sh` 腳本在以下情況需要 `sudo` 權限：
- 系統未安裝 Python 3、pip3 或 venv 模組時（需要安裝系統套件）
- 需要將用戶加入 `dialout` 群組以存取串列埠時

如果系統已安裝 Python 環境且用戶已在 `dialout` 群組中，則不需要 `sudo`。

若需要 `sudo`，請執行：
```bash
sudo ./deploy.sh
```

### 2. 安裝 Python 依賴套件
```bash
pip install -r requirements.txt
```

或使用 pip3：
```bash
pip3 install -r requirements.txt
```

### 3. 設定權限
確保 Python 腳本有執行權限：
```bash
chmod +x src/main.py
chmod +x src/prowavedaq.py
chmod +x src/csv_writer.py
chmod +x src/sql_uploader.py
```

### 4. 設定串列埠權限（Linux）
如果使用 USB 轉串列埠設備，可能需要將使用者加入 dialout 群組：
```bash
sudo usermod -a -G dialout $USER
```
然後重新登入或執行：
```bash
newgrp dialout
```

### 5. 確認設定檔
檢查 `API/` 目錄下的設定檔：
- `API/ProWaveDAQ.ini` - ProWaveDAQ 設備設定
- `API/Master.ini` - CSV 和 SQL 上傳間隔設定
- `API/sql.ini` - SQL 伺服器連線設定

### 6. 設定 SQL 資料庫（可選）
如果啟用 SQL 上傳功能，需要在 MariaDB/MySQL 中建立資料表：

```sql
CREATE TABLE IF NOT EXISTS vibration_data (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    timestamp DATETIME NOT NULL,
    label VARCHAR(255) NOT NULL,
    channel_1 DOUBLE NOT NULL,
    channel_2 DOUBLE NOT NULL,
    channel_3 DOUBLE NOT NULL,
    INDEX idx_timestamp (timestamp),
    INDEX idx_label (label)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

**注意**：如果資料表不存在，程式會在首次連線時自動建立。

## 使用說明

### 啟動系統

#### 方式 1：使用啟動腳本（推薦）

**使用預設 port 8080：**
```bash
./run.sh
```

**指定自訂 port：**
```bash
./run.sh 3000    # 使用 port 3000
./run.sh 9000    # 使用 port 9000
```

**使用日誌記錄功能：**
```bash
./run_with_logs.sh          # 使用預設 port 8080，並保存日誌
./run_with_logs.sh 3000     # 使用 port 3000，並保存日誌
```

#### 方式 2：直接執行 Python 程式

**使用預設 port 8080：**
```bash
cd src
python3 main.py
```

**指定自訂 port：**
```bash
cd src
python3 main.py --port 3000    # 使用 port 3000
python3 main.py -p 9000        # 使用 port 9000（簡短形式）
```

**查看所有可用選項：**
```bash
python3 src/main.py --help
```

啟動成功後，您會看到類似以下的訊息：
```
============================================================
ProWaveDAQ Real-time Data Visualization System
============================================================
Web interface will be available at http://0.0.0.0:8080/
Press Ctrl+C to stop the server
============================================================
```

### 使用 Web 介面

1. **開啟瀏覽器**
   - 在本地機器：開啟 `http://localhost:<port>/`（預設為 8080）
   - 在遠端機器：開啟 `http://<設備IP>:<port>/`（預設為 8080）

   **範例：**
   - 使用預設 port：`http://localhost:8080/`
   - 使用自訂 port 3000：`http://localhost:3000/`

2. **輸入資料標籤**
   - 在「資料標籤 (Label)」欄位輸入本次測量的標籤名稱
   - 例如：`test_001`、`vibration_20240101` 等

3. **設定 SQL 上傳（可選）**
   - 勾選「啟用 SQL 伺服器上傳」
   - 選擇「使用 INI 檔案設定」或「手動輸入設定」
   - 如果選擇使用 INI 設定，系統會自動讀取 `sql.ini` 中的設定
   - 如果選擇手動輸入，可以覆蓋 INI 設定

4. **開始資料收集**
   - 點擊「開始讀取」按鈕
   - 系統會自動：
     - 連接 ProWaveDAQ 設備
     - 開始讀取資料
     - 即時顯示資料曲線
     - 自動儲存 CSV 檔案
     - （如果啟用）自動上傳資料至 SQL 伺服器

5. **查看即時資料**
   - 即時曲線圖會自動更新（每 200ms）
   - 可以同時查看三個通道的資料
   - 資料點數會即時顯示

6. **停止資料收集**
   - 點擊「停止讀取」按鈕
   - 系統會安全地停止採集並關閉連線
   - 自動上傳剩餘資料至 SQL 伺服器（如果啟用）

7. **管理設定檔**
   - 點擊「設定檔管理」連結
   - 使用固定輸入框編輯設定檔（防止誤刪參數）
   - 可以編輯 `ProWaveDAQ.ini`、`Master.ini` 和 `sql.ini`
   - 修改後點擊「儲存設定檔」

8. **瀏覽和下載檔案**
   - 點擊「檔案瀏覽」連結
   - 可以瀏覽 `output/ProWaveDAQ/` 目錄中的所有資料夾和檔案
   - 點擊資料夾名稱或「進入」按鈕可以進入資料夾
   - 點擊「下載」按鈕可以下載 CSV 檔案
   - 使用麵包屑導航可以返回上層目錄

### 設定檔說明

#### ProWaveDAQ.ini
```ini
[ProWaveDAQ]
serialPort = /dev/ttyUSB0    # 串列埠路徑
baudRate = 3000000           # 鮑率
sampleRate = 7812            # 取樣率（Hz）
slaveID = 1                  # Modbus 從站 ID
```

#### Master.ini
```ini
[SaveUnit]
second = 600                 # 每個 CSV 檔案的資料時間長度（秒）
sql_upload_interval = 600    # SQL 上傳間隔（秒），運作方式與 second 相同
```

**分檔邏輯說明**：
- 系統會根據 `sampleRate × channels × second` 計算每個 CSV 檔案應包含的資料點數
- 當累積的資料點數達到目標值時，自動建立新檔案
- 例如：取樣率 7812 Hz，3 通道，600 秒 → 每個檔案約 14,061,600 個資料點

**SQL 上傳邏輯說明**：
- SQL 上傳採用暫存檔案機制，資料先寫入暫存 CSV 檔案
- 系統會建立暫存檔案目錄（`.sql_temp`），檔案命名格式：`{timestamp}_sql_temp.csv`
- 每 `sql_upload_interval` 秒定時檢查並上傳暫存檔案
- 上傳成功後自動刪除暫存檔案，並立即建立新暫存檔案（避免資料溢出）
- 停止時會檢查並上傳所有剩餘暫存檔案
- 例如：取樣率 7812 Hz，3 通道，600 秒 → 每 600 秒上傳一次暫存檔案

#### sql.ini
```ini
[SQLServer]
enabled = false             # 是否啟用 SQL 上傳（true/false）
host = 192.168.9.13         # SQL 伺服器位置
port = 3306                 # 連接埠
user = raspberrypi          # 使用者名稱
password = Raspberry@Pi     # 密碼
database = daq-data         # 資料庫名稱
```

**SQL 設定說明**：
- `enabled`：控制是否啟用 SQL 上傳功能
- 如果 `enabled = true`，前端會自動勾選「啟用 SQL 伺服器上傳」
- 前端可以選擇使用 INI 設定或手動輸入（覆蓋 INI 設定）

### 輸出檔案

#### CSV 檔案
CSV 檔案會儲存在 `output/ProWaveDAQ/` 目錄下，檔案命名格式：
```
YYYYMMDDHHMMSS_<Label>_001.csv
YYYYMMDDHHMMSS_<Label>_002.csv
...
```

每個 CSV 檔案包含：
- `Timestamp` - 時間戳記（根據取樣率精確計算）
- `Channel_1(X)` - 通道 1 資料（對應 X 軸）
- `Channel_2(Y)` - 通道 2 資料（對應 Y 軸）
- `Channel_3(Z)` - 通道 3 資料（對應 Z 軸）

**資料格式說明**：
- 資料格式：`[長度, X, Y, Z, X, Y, Z, ...]`
- 從設備讀取時，第0格為長度，之後依序為 X, Y, Z 循環
- 時間戳記根據取樣率自動計算，確保每個樣本的時間間隔正確

#### SQL 資料庫
如果啟用 SQL 上傳，資料會儲存在 `vibration_data` 資料表中，包含：
- `id` - 自動遞增主鍵
- `timestamp` - 資料時間戳記
- `label` - 資料標籤
- `channel_1` - 通道 1 資料
- `channel_2` - 通道 2 資料
- `channel_3` - 通道 3 資料

## 檔案架構

```
ProWaveDAQ_Python_Visualization_Unit/
│
├── API/
│   ├── ProWaveDAQ.ini      # ProWaveDAQ 設備設定檔
│   ├── Master.ini           # CSV 和 SQL 上傳間隔設定檔
│   └── sql.ini              # SQL 伺服器連線設定檔
│
├── output/
│   └── ProWaveDAQ/         # CSV 輸出目錄
│       └── YYYYMMDDHHMMSS_<Label>/
│           ├── YYYYMMDDHHMMSS_<Label>_*.csv
│           └── .sql_temp/  # SQL 暫存檔案目錄（如果啟用 SQL）
│               └── YYYYMMDDHHMMSS_sql_temp.csv
│
├── src/
│   ├── prowavedaq.py       # ProWaveDAQ 核心模組（Modbus 通訊）
│   ├── csv_writer.py       # CSV 寫入器模組
│   ├── sql_uploader.py     # SQL 上傳器模組
│   ├── logger.py           # 統一日誌系統模組
│   ├── main.py             # 主控制程式（Web 介面）
│   ├── requirements.txt    # Python 依賴套件列表
│   └── templates/          # HTML 模板目錄
│       ├── index.html      # 主頁模板
│       ├── config.html     # 設定檔管理頁面模板
│       └── files.html      # 檔案瀏覽頁面模板
│
├── README.md               # 本文件
├── deploy.sh               # 部署腳本
└── run.sh                  # 啟動腳本（進入虛擬環境並啟動程式）
```

## API 路由說明

| 路由 | 方法 | 功能說明 |
|------|------|----------|
| `/` | GET | 主頁，顯示設定表單、Label 輸入、SQL 設定、開始/停止按鈕與折線圖 |
| `/data` | GET | 回傳目前最新資料 JSON 給前端 |
| `/status` | GET | 檢查資料收集狀態 |
| `/sql_config` | GET | 取得 SQL 設定（從 sql.ini） |
| `/config` | GET | 顯示設定檔編輯頁面（固定輸入框） |
| `/config` | POST | 儲存修改後的設定檔 |
| `/start` | POST | 啟動 DAQ、CSVWriter、SQLUploader 與即時顯示 |
| `/stop` | POST | 停止所有執行緒、安全關閉，並上傳剩餘資料 |
| `/files_page` | GET | 檔案瀏覽頁面 |
| `/files` | GET | 列出 output 目錄中的檔案和資料夾（查詢參數：path） |
| `/download` | GET | 下載檔案（查詢參數：path） |

### API 回應格式

#### `/data` (GET)
```json
{
  "success": true,
  "data": [0.123, 0.456, 0.789, ...],
  "counter": 12345
}
```

#### `/sql_config` (GET)
```json
{
  "success": true,
  "sql_config": {
    "enabled": false,
    "host": "localhost",
    "port": "3306",
    "user": "root",
    "password": "",
    "database": "prowavedaq"
  }
}
```

#### `/start` (POST)
請求：
```json
{
  "label": "test_001",
  "sql_enabled": true,
  "sql_host": "192.168.9.13",
  "sql_port": "3306",
  "sql_user": "raspberrypi",
  "sql_password": "Raspberry@Pi",
  "sql_database": "daq-data"
}
```

回應：
```json
{
  "success": true,
  "message": "資料收集已啟動 (取樣率: 7812 Hz, 分檔間隔: 600 秒, SQL 上傳間隔: 600 秒)"
}
```

**注意**：
- 如果選擇「使用 INI 檔案設定」，只需傳送 `sql_enabled: true`
- 如果選擇「手動輸入設定」，需要傳送所有 SQL 設定參數

#### `/stop` (POST)
回應：
```json
{
  "success": true,
  "message": "資料收集已停止"
}
```

#### `/status` (GET)
回應：
```json
{
  "success": true,
  "is_collecting": true,
  "counter": 12345
}
```

#### `/files` (GET)
查詢參數：
- `path` (可選)：要瀏覽的子目錄路徑

回應：
```json
{
  "success": true,
  "items": [
    {
      "name": "20240101120000_test_001",
      "type": "directory",
      "path": "20240101120000_test_001"
    },
    {
      "name": "data.csv",
      "type": "file",
      "path": "data.csv",
      "size": 1024
    }
  ],
  "current_path": ""
}
```

#### `/download` (GET)
查詢參數：
- `path` (必需)：要下載的檔案路徑

回應：直接下載檔案

## 資料流程與運作機制

### 整體資料流程

```
ProWaveDAQ 設備 (Modbus RTU)
    ↓
    資料格式：[長度, X, Y, Z, X, Y, Z, ...]
    ↓
ProWaveDAQ._read_loop() [背景執行緒]
    ├─→ 讀取資料長度（第0格）
    ├─→ 讀取完整資料（包含長度）
    ├─→ 處理長度不是3的倍數的情況（remaining_data 機制）
    ├─→ 確保只處理完整的樣本（X, Y, Z 組合）
    └─→ 資料轉換（16位元整數 → 浮點數）
    ↓ (放入佇列)
data_queue (queue.Queue, 最大 1000 筆)
    ↓
collection_loop() [背景執行緒]
    ├─→ update_realtime_data()
    │       ↓
    │   realtime_data (List[float], 最多 10000 點)
    │       ↓
    │   Flask /data API (HTTP GET, 每 200ms)
    │       ↓
    │   前端 Chart.js (templates/index.html)
    │
    ├─→ CSV Writer
    │   ├─→ 根據取樣率計算時間戳記
    │   ├─→ 確保分檔時時間戳記連續
    │   └─→ CSV 檔案 (分檔儲存，確保樣本邊界)
    │
    └─→ SQL Uploader（如果啟用）
            ├─→ 寫入暫存 CSV 檔案
            │   └─→ .sql_temp/{timestamp}_sql_temp.csv
            │
            └─→ 定時上傳執行緒（每 sql_upload_interval 秒）
                ├─→ 讀取暫存檔案
                ├─→ 批次上傳至 SQL
                ├─→ 刪除暫存檔案
                └─→ 建立新暫存檔案
                    ↓
                MariaDB/MySQL 資料庫
```

### 即時資料回傳機制

**機制**：HTTP 輪詢（Polling）

- **請求頻率**：每 200 毫秒（0.2 秒）請求一次
- **資料傳輸**：JSON 格式
- **緩衝區大小**：最多 10000 個資料點
- **優化機制**：智慧緩衝區更新（僅在有活躍連線時更新）

**前端處理**：
```javascript
// 每 200ms 執行一次
setInterval(updateChart, 200);

function updateChart() {
    fetch('/data')
        .then(response => response.json())
        .then(data => {
            // 將資料按通道分組（每3個為一組）
            // 更新 Chart.js 圖表
        });
}
```

### CSV 分檔機制

**觸發方式**：基於資料量

1. **計算目標大小**：
   ```
   target_size = second × sampleRate × channels
   ```

2. **累積計數器**：
   ```python
   current_data_size += len(data)
   ```

3. **分檔邏輯**：
   - 如果 `current_data_size < target_size`：直接寫入當前檔案
   - 如果 `current_data_size >= target_size`：分批處理，建立新檔案
   - **重要**：確保切斷位置在樣本邊界（3的倍數），避免通道錯位

4. **時間戳記計算**：
   - 每個樣本的時間間隔 = 1 / sample_rate 秒
   - 時間戳記 = 全局起始時間 + (樣本計數 × 樣本間隔)
   - 確保分檔時時間戳記連續

### SQL 上傳機制

**觸發方式**：基於時間間隔（定時上傳）

1. **暫存檔案機制**：
   - 資料收集開始時，在輸出目錄下建立 `.sql_temp` 暫存目錄
   - 建立第一個暫存檔案（檔名格式：`{timestamp}_sql_temp.csv`）
   - 所有 SQL 資料直接寫入當前暫存檔案

2. **定時上傳執行緒**：
   - 啟動獨立的背景執行緒（`sql_upload_timer_loop`）
   - 每 `sql_upload_interval` 秒檢查一次
   - 時間到達時：
     - 上傳當前暫存檔案到 SQL 伺服器
     - 上傳成功後刪除暫存檔案
     - 立即建立新的暫存檔案（避免資料溢出）

3. **資料保護機制**：
   - **重試機制**：上傳失敗時最多重試 3 次，遞增延遲（0.1s, 0.2s, 0.3s）
   - **失敗保留**：上傳失敗時暫存檔案保留，等待下次重試
   - **成功確認**：只有上傳成功後才刪除暫存檔案
   - **自動重連**：連線中斷時自動重連

4. **批次插入**：
   - 從暫存 CSV 檔案讀取所有資料
   - 使用 `executemany()` 批次插入，提升效能
   - 自動建立對應的 SQL 資料表（表名與 CSV 檔名對應）

5. **停止時處理**：
   - 停止時上傳當前暫存檔案
   - 檢查並上傳所有剩餘暫存檔案（確保資料不遺失）
   - 上傳成功後刪除所有暫存檔案

**暫存檔案結構**：
```
output/ProWaveDAQ/{timestamp}_{label}/
├── {timestamp}_{label}_001.csv
├── {timestamp}_{label}_002.csv
└── .sql_temp/                    # 暫存檔案目錄
    ├── 20250106120000_sql_temp.csv
    ├── 20250106120600_sql_temp.csv
    └── ...
```

**優勢**：
- 降低記憶體使用：資料直接寫入檔案，不佔用記憶體緩衝區
- 資料持久化：即使程式異常終止，暫存檔案仍保留
- 定時上傳：避免頻繁的 SQL 連線，提升效能
- 自動清理：上傳成功後自動刪除暫存檔案

## 故障排除

### 常見問題

#### 1. 無法連接設備
**症狀**：啟動後無法讀取資料

**解決方法**：
- 檢查串列埠路徑是否正確（`/dev/ttyUSB0` 或其他）
- 確認設備已正確連接
- 檢查使用者是否有串列埠存取權限
- 嘗試使用 `ls -l /dev/ttyUSB*` 確認設備存在

#### 2. Web 介面無法開啟
**症狀**：無法在瀏覽器中開啟網頁

**解決方法**：
- 確認防火牆允許使用的埠號（預設為 8080）
- 檢查是否有其他程式佔用該埠號
- 如果使用自訂 port，請確認瀏覽器中的 URL 使用正確的埠號
- 確認 Python 程式正在執行
- 檢查系統日誌是否有錯誤訊息

#### 3. 資料顯示不正確
**症狀**：圖表顯示異常或資料點不正確

**解決方法**：
- 檢查設定檔中的取樣率是否正確
- 確認通道數設定（預設為 3）
- 檢查瀏覽器控制台是否有 JavaScript 錯誤

#### 4. CSV 檔案未產生
**症狀**：資料收集正常但沒有 CSV 檔案

**解決方法**：
- 檢查 `output/ProWaveDAQ/` 目錄是否有寫入權限
- 確認 Label 已正確輸入
- 檢查磁碟空間是否充足

#### 5. SQL 上傳失敗
**症狀**：SQL 上傳功能無法正常運作

**解決方法**：
- 檢查 `sql.ini` 中的連線設定是否正確
- 確認 SQL 伺服器是否可連線（測試：`mysql -h <host> -P <port> -u <user> -p`）
- 檢查資料庫是否存在
- 確認使用者權限是否足夠（CREATE TABLE、INSERT）
- 查看終端機的錯誤訊息
- 檢查網路連線（特別是跨網段時）

#### 6. 資料採集停止
**症狀**：資料採集中途停止

**解決方法**：
- 檢查 Modbus 連線是否中斷
- 查看終端機的錯誤訊息
- 確認設備是否正常運作
- 檢查 SQL 連線是否正常（如果啟用 SQL 上傳）

#### 7. 記憶體使用過高
**症狀**：系統記憶體使用過高

**解決方法**：
- 檢查 `sql_upload_interval` 設定是否過大
- 系統會自動限制緩衝區大小（最多 10,000,000 個資料點）
- 如果持續出現記憶體問題，可以降低 `sql_upload_interval` 值

#### 8. 通道順序錯位
**症狀**：CSV 檔案或圖表中的通道順序不正確

**解決方法**：
- 系統已自動處理此問題（使用 `remaining_data` 機制）
- 如果仍有問題，檢查：
  - 資料格式是否正確：`[長度, X, Y, Z, X, Y, Z, ...]`
  - 檢查日誌中是否有「Remaining data points」警告
  - 查看 `通道錯誤可能性分析.md` 文件了解詳細情況

### 日誌系統

系統使用統一的日誌系統（`logger.py`），提供以下日誌級別：
- `[INFO]` - 一般資訊訊息
- `[Debug]` - 調試訊息（可透過 `Logger.set_debug_enabled(False)` 關閉）
- `[Error]` - 錯誤訊息
- `[Warning]` - 警告訊息

所有日誌訊息自動包含時間戳記，格式為：
```
[YYYY-MM-DD HH:MM:SS] [LEVEL] 訊息內容
```

**注意**：Flask 的 HTTP 請求日誌已預設隱藏，只顯示應用程式的日誌訊息。

### 除錯模式

如需查看詳細的除錯資訊，可以：
- 查看終端機的日誌輸出
- 使用 `Logger.set_debug_enabled(True)` 啟用 Debug 訊息
- 檢查 `通道錯誤可能性分析.md` 文件了解可能的問題

## 技術架構

### 執行緒設計

| 執行緒 | 功能 | 備註 |
|--------|------|------|
| 主執行緒 | 控制流程、等待使用者中斷 | 同步主控核心 |
| Flask Thread | 提供 HTTP 介面與 API | daemon=True |
| Collection Thread | 資料收集迴圈（處理 CSV 和 SQL） | 在 `/start` 時啟動 |
| DAQ Reading Thread | 從 Modbus 設備讀取資料 | 在 `start_reading()` 時啟動，執行 `_read_loop()`

### 程式碼架構

#### `prowavedaq.py` 模組結構

**公開 API（供外部使用）：**
- `scan_devices()` - 掃描可用的 Modbus 設備
- `init_devices(filename)` - 從 INI 檔案初始化設備並建立連線
- `start_reading()` - 啟動資料讀取（背景執行緒）
- `stop_reading()` - 停止資料讀取並關閉連線
- `get_data()` - 非阻塞取得最新一批資料
- `get_data_blocking(timeout)` - 阻塞取得最新一批資料
- `get_counter()` - 取得讀取批次計數
- `get_sample_rate()` - 取得取樣率

**內部方法（模組內部使用）：**
- `_connect()` - 建立 Modbus RTU 連線
- `_disconnect()` - 關閉 Modbus 連線
- `_ensure_connected()` - 確保連線存在（自動重連）
- `_read_chip_id()` - 讀取晶片 ID（初始化時）
- `_set_sample_rate()` - 設定取樣率（初始化時）
- `_read_registers_with_header()` - 讀取寄存器（包含 Header）
- `_read_normal_data()` - Normal Mode 讀取（Address 0x02）
- `_read_bulk_data()` - Bulk Mode 讀取（Address 0x15）
- `_get_buffer_status()` - 讀取緩衝區狀態
- `_convert_raw_to_float_samples()` - 轉換為浮點數（確保 XYZ 不錯位）
- `_read_loop()` - 主要讀取迴圈（背景執行緒）

**讀取模式：**
- **Normal Mode**：當緩衝區資料量 ≤ 123 時使用，從 Address 0x02 讀取
- **Bulk Mode**：當緩衝區資料量 > 123 時使用，從 Address 0x15 讀取，最多讀取 9 個樣本
- 自動根據緩衝區狀態切換模式，優化讀取效率

**設計原則：**
- 每次讀取只處理完整的 XYZ 三軸組，避免通道錯位
- FIFO buffer size(0x02) 連同資料一起讀出，確保一致性
- 自動重連機制，確保連線穩定性
- 模組化設計，方便未來擴展和維護

### 資料流詳細說明

```
ProWaveDAQ 設備
    ↓ (Modbus RTU)
ProWaveDAQ._read_loop() [背景執行緒]
    ├─ _get_buffer_status()      # 讀取緩衝區狀態（寄存器 0x02）
    ├─ 模式判斷
    │   ├─ buffer_count ≤ 123 → Normal Mode
    │   │   └─ _read_normal_data()  # 從 Address 0x02 讀取
    │   └─ buffer_count > 123 → Bulk Mode
    │       └─ _read_bulk_data()     # 從 Address 0x15 讀取（最多 9 個樣本）
    ├─ _read_registers_with_header() # 讀取 Header + 資料
    └─ _convert_raw_to_float_samples()  # 轉換為浮點數（確保 XYZ 不錯位）
    ↓ (放入佇列)
data_queue (queue.Queue, 最大 10000 筆)
    ↓
collection_loop() [背景執行緒]
    │
    ├─→ update_realtime_data()
    │   │
    │   ▼
    │   realtime_data (List[float], 無限制)
    │   │   - 智慧緩衝區：僅在有活躍連線時更新
    │   │
    │   ▼
    │   Flask /data API (HTTP GET, 每 200ms)
    │   │
    │   ▼
    │   前端 Chart.js (templates/index.html)
    │       - 每 200ms 更新一次
    │       - 限制顯示 5000 個資料點
    │
    ├─→ CSV Writer
    │   │
    │   ▼
    │   分檔邏輯判斷
    │   │
    │   ├─→ current_data_size < target_size
    │   │   └─→ 直接寫入當前檔案
    │   │
    │   └─→ current_data_size >= target_size
    │       ├─→ 寫入完整批次
    │       ├─→ update_filename() (建立新檔案)
    │       └─→ 處理剩餘資料
    │           │
    │           ▼
    │       CSV 檔案
    │       output/ProWaveDAQ/{timestamp}_{label}/{timestamp}_{label}_{001-999}.csv
    │
    └─→ SQL Uploader
        │
        ▼
    資料緩衝區 (sql_data_buffer)
        │
        ├─→ sql_current_data_size < sql_target_size
        │   └─→ 累積資料，不上傳
        │
        └─→ sql_current_data_size >= sql_target_size
            ├─→ 批次上傳 (executemany)
            ├─→ 重試機制 (最多 3 次)
            ├─→ 失敗保留 (資料不遺失)
            └─→ 成功後從緩衝區移除
                │
                ▼
            MariaDB/MySQL 資料庫
            vibration_data 資料表
```

### 技術限制

- 不使用 `asyncio` 或 `WebSocket`
- 不使用檔案中介資料交換
- 所有資料傳遞均在記憶體中完成
- 使用 Python 變數或全域狀態保存資料
- SQL 上傳使用 HTTP 連線，不支援 WebSocket

### 記憶體管理

1. **即時資料緩衝區**：
   - 最多保留 10000 個資料點（約 80 KB）
   - 僅在有活躍前端連線時更新

2. **SQL 資料緩衝區**：
   - 上限：`min(sql_target_size × 2, 10,000,000)` 個資料點
   - 超過上限時強制上傳

3. **DAQ 資料佇列**：
   - 最多 1000 筆（每筆約 123 個點，約 1 MB）

## 開發說明

### 擴展功能

如需擴展系統功能，可以：

1. **修改前端介面**：編輯 `src/templates/index.html` 和 `src/templates/config.html` 模板
2. **調整圖表設定**：在 `src/templates/index.html` 中修改 Chart.js 的配置選項
3. **新增 API 路由**：在 `src/main.py` 中新增路由處理函數
4. **自訂 CSV 格式**：修改 `src/csv_writer.py` 中的寫入邏輯
5. **自訂 SQL 格式**：修改 `src/sql_uploader.py` 中的資料表結構和插入邏輯

### 程式碼結構

- `src/prowavedaq.py`：負責 Modbus RTU 通訊與資料讀取
  - 處理資料格式：`[長度, X, Y, Z, X, Y, Z, ...]`
  - 自動處理長度不是3的倍數的情況（使用 `remaining_data` 機制）
  - 多執行緒安全保護（使用鎖定機制）
  - 資料完整性檢查
- `src/csv_writer.py`：負責 CSV 檔案的建立與寫入
  - 根據取樣率自動計算時間戳記
  - 確保分檔時時間戳記連續
  - 通道標示：Channel_1(X), Channel_2(Y), Channel_3(Z)
- `src/sql_uploader.py`：負責 SQL 資料庫連線與資料上傳
  - 支援 MySQL/MariaDB
  - 重試機制和資料保護
- `src/logger.py`：統一日誌系統
  - 提供統一的日誌格式
  - 支援多種日誌級別
  - 自動時間戳記
- `src/main.py`：整合所有功能，提供 Web 介面（使用 Flask + templates）
  - 分檔邏輯確保樣本邊界（3的倍數）
  - SQL 上傳確保樣本邊界
  - 智慧緩衝區管理
- `src/templates/index.html`：主頁 HTML 模板（包含 Chart.js 圖表、SQL 設定）
- `src/templates/config.html`：設定檔管理頁面模板（固定輸入框）
- `src/templates/files.html`：檔案瀏覽頁面模板

### 關鍵設計決策

1. **資料保護**：
   - SQL 上傳失敗時保留資料在緩衝區
   - 只有上傳成功後才從緩衝區移除
   - 最多重試 3 次，遞增延遲

2. **記憶體保護**：
   - SQL 緩衝區設定上限，防止記憶體溢出
   - 超過上限時強制上傳

3. **設定檔管理**：
   - 使用固定輸入框，防止使用者誤刪參數
   - SQL 設定獨立為 `sql.ini` 檔案

4. **智慧緩衝區**：
   - 僅在有活躍前端連線時更新即時資料緩衝區
   - 節省 CPU 和記憶體資源

## 授權資訊

本專案為內部使用專案，請遵循相關使用規範。

## 聯絡資訊

如有問題或建議，請聯絡專案維護者。

## 更新日誌

### Version 4.1.0
- **重大更新**：SQL 上傳邏輯重構
  - 改為暫存檔案機制：資料先寫入暫存 CSV 檔案，定時上傳
  - 建立暫存檔案目錄（`.sql_temp`），檔案命名格式：`{timestamp}_sql_temp.csv`
  - 新增定時上傳執行緒（`sql_upload_timer_loop`），每 `sql_upload_interval` 秒檢查並上傳
  - 上傳成功後自動刪除暫存檔案，並立即建立新暫存檔案（避免資料溢出）
  - 停止時檢查並上傳所有剩餘暫存檔案
  - 降低記憶體使用：資料直接寫入檔案，不佔用記憶體緩衝區
  - 資料持久化：即使程式異常終止，暫存檔案仍保留
- **新增**：`sql_uploader.py` 新增 `upload_from_csv_file()` 方法
  - 從 CSV 檔案讀取資料並批次上傳至 SQL 伺服器
  - 支援自動建立資料表（如果不存在）
  - 包含錯誤處理與重試機制

### Version 4.0.0
- **改進**：程式碼註解完善
  - 為所有核心模組添加完整的中文註解
  - 所有函數和類別都有詳細的 docstring
  - 說明函數用途、參數、返回值、注意事項
  - 移除所有冗餘註解和步驟標記
  - 提升程式碼可讀性和可維護性
- **改進**：技術文件更新
  - 更新 README.md 和 程式運作說明.md 以符合目前程式碼
  - 確保文件與實際程式碼功能一致

### Version 3.0.0
- **重大更新**：重構資料讀取邏輯
  - 實現 Normal Mode 和 Bulk Mode 自動切換機制
  - 根據緩衝區狀態（buffer_count）動態選擇讀取模式
  - Normal Mode：當 buffer_count ≤ 123 時，從 Address 0x02 讀取
  - Bulk Mode：當 buffer_count > 123 時，從 Address 0x15 讀取（最多 9 個樣本）
  - FIFO buffer size(0x02) 連同資料一起讀出，確保資料一致性
- **改進**：讀取效率優化
  - 一次讀取 Header 和資料，減少 Modbus 通訊次數
  - 使用 `_read_registers_with_header()` 方法統一處理讀取邏輯
  - 參考 LabView 轉換版本（G.py）的實現方式
- **改進**：程式碼清理
  - 移除所有冗餘註解和步驟標記
  - 簡化程式碼結構，提升可讀性
  - 移除不再使用的舊方法（`_read_fifo_length`、`_read_raw_block` 等）
- **改進**：即時資料顯示
  - 移除資料點數限制（原本限制 100000 個資料點）
  - 現在會保留並顯示所有資料
- **改進**：文件更新
  - 更新 README.md 和 程式運作說明.md
  - 詳細說明 Normal Mode 和 Bulk Mode 的運作方式
  - 更新資料流程圖和架構說明

### Version 2.3.0
- **新增**：支援啟動時指定 port
  - 可透過命令行參數 `--port` 或 `-p` 指定 Flask 伺服器埠號
  - 啟動腳本 `run.sh` 和 `run_with_logs.sh` 支援傳遞 port 參數
  - 預設 port 仍為 8080，向後相容
  - 自動驗證 port 範圍（1-65535）

### Version 2.2.0
- **重構**：`prowavedaq.py` 架構優化
  - 重新組織程式碼結構，明確區分公開 API 和內部方法
  - 簡化讀取邏輯，移除 `remaining_data` 機制（每次讀取都是完整批次）
  - 改進 Modbus 連線管理（`_connect`、`_disconnect`、`_ensure_connected`）
  - 新增 Modbus 寄存器常數定義（`REG_SAMPLE_RATE`、`REG_FIFO_LEN` 等）
  - 模組化讀取流程（`_read_fifo_length`、`_read_raw_block`、`_convert_raw_to_float_samples`）
  - 改進錯誤處理和重連邏輯
  - 確保每次讀取只處理完整的 XYZ 三軸組，避免通道錯位
- **改進**：程式碼註解
  - 為所有核心模組添加詳細的中文註解
  - 說明函數用途、參數、返回值、注意事項
  - 解釋關鍵設計決策和資料流程
  - 提升程式碼可讀性和可維護性
- **改進**：日誌系統
  - 統一 Debug 訊息標籤為 `[DEBUG]`（與其他級別一致）
  - 改進日誌輸出格式的一致性

### Version 2.1.0
- **新增**：統一日誌系統 (`logger.py`)
  - 提供統一的日誌格式：`[YYYY-MM-DD HH:MM:SS] [LEVEL] 訊息`
  - 支援 INFO、Debug、Error、Warning 四種級別
  - 自動時間戳記
  - 可控制 Debug 訊息開關
- **修正**：通道錯位問題
  - 處理資料長度不是3的倍數的情況
  - 使用 `remaining_data` 機制追蹤剩餘資料點
  - 確保每次只處理完整的樣本（X, Y, Z 組合）
  - 多執行緒安全保護（使用鎖定機制）
- **修正**：時間戳記計算
  - 根據取樣率自動計算每個樣本的時間戳記
  - 確保分檔時時間戳記連續
  - 每個樣本的時間間隔 = 1 / sample_rate 秒
- **改進**：資料讀取邏輯
  - 添加資料完整性檢查
  - 重新連線時自動清空剩餘資料
  - 停止讀取時處理剩餘資料
- **改進**：分檔邏輯
  - 確保切斷位置在樣本邊界（3的倍數）
  - SQL 上傳時也確保樣本邊界
- **改進**：日誌輸出
  - 隱藏 Flask HTTP 請求日誌
  - 只顯示應用程式的日誌訊息
- **新增**：通道標示
  - CSV 標題明確標示通道對應：Channel_1(X), Channel_2(Y), Channel_3(Z)
- **新增**：分析文檔
  - `通道錯誤可能性分析.md` - 詳細分析可能導致通道錯誤的情況

### Version 2.0.0
- **新增**：SQL 資料庫上傳功能
  - 支援 MySQL/MariaDB
  - 可選的 SQL 上傳功能
  - 獨立的 `sql.ini` 設定檔
  - 前端可選擇使用 INI 設定或手動輸入
- **新增**：資料保護機制
  - SQL 上傳失敗時保留資料在緩衝區
  - 最多重試 3 次，遞增延遲
  - 只有上傳成功後才從緩衝區移除
- **新增**：記憶體保護機制
  - SQL 緩衝區上限設定（最多 10,000,000 個資料點）
  - 超過上限時強制上傳
- **改進**：設定檔管理介面
  - 改為固定輸入框模式，防止誤刪參數
  - 支援三個設定檔：`ProWaveDAQ.ini`、`Master.ini`、`sql.ini`
- **改進**：Master.ini 新增 `sql_upload_interval` 參數
  - 控制 SQL 上傳間隔（秒數）
  - 運作方式與 CSV 的 `second` 參數相同

### Version 1.0.2
- 修復：讀取中進入 config 頁面再回到主畫面時，狀態會自動恢復
- 新增：檔案瀏覽功能，可瀏覽 output 目錄中的資料夾和檔案
- 新增：檔案下載功能

### Version 1.0.1
- 將 HTML 部分改為模板以簡化 Python 程式碼整潔性

### Version 1.0.0
- 初始版本發布
- 實現基本的即時資料採集與可視化功能
- Web 介面控制
- 自動 CSV 分檔儲存

---

**最後更新**：2025年12月17日
**作者**：王建葦  
**當前版本**：4.1.0
