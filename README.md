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
- 支援多通道資料顯示（預設 3 通道）
- 智慧緩衝區管理，優化記憶體使用
- 資料保護機制，確保資料不遺失（重試機制、失敗保留）

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

執行主程式：
```bash
cd src
python3 main.py
```

或直接執行：
```bash
cd src
./main.py
```

或是執行：
```bash
./run.sh
```
直接進入虛擬環境並啟動程式

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
   - 在本地機器：開啟 `http://localhost:8080/`
   - 在遠端機器：開啟 `http://<設備IP>:8080/`

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
- SQL 上傳間隔運作方式與 CSV 分檔相同，都是根據資料量計算
- 系統會累積資料到緩衝區，達到 `sql_upload_interval` 對應的資料量時才上傳
- 例如：取樣率 7812 Hz，3 通道，600 秒 → 累積 14,061,600 個資料點後上傳

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
- `Timestamp` - 時間戳記
- `Channel_1` - 通道 1 資料
- `Channel_2` - 通道 2 資料
- `Channel_3` - 通道 3 資料

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
│       └── YYYYMMDDHHMMSS_<Label>_*.csv
│
├── src/
│   ├── prowavedaq.py       # ProWaveDAQ 核心模組（Modbus 通訊）
│   ├── csv_writer.py       # CSV 寫入器模組
│   ├── sql_uploader.py     # SQL 上傳器模組
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
ProWaveDAQ._read_loop() [背景執行緒]
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
    │       ↓
    │   CSV 檔案 (分檔儲存)
    │
    └─→ SQL Uploader
            ↓
        SQL 資料緩衝區 (累積到門檻)
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

### SQL 上傳機制

**觸發方式**：基於資料量（與 CSV 分檔邏輯相同）

1. **計算目標大小**：
   ```
   sql_target_size = sql_upload_interval × sampleRate × channels
   ```

2. **資料緩衝區**：
   - 資料先累積到 `sql_data_buffer` 緩衝區
   - 達到 `sql_target_size` 時才上傳

3. **記憶體保護**：
   - 緩衝區上限：`min(sql_target_size × 2, 10,000,000)` 個資料點
   - 超過上限時強制上傳部分資料

4. **資料保護機制**：
   - **重試機制**：上傳失敗時最多重試 3 次，遞增延遲（0.1s, 0.2s, 0.3s）
   - **失敗保留**：上傳失敗時資料保留在緩衝區，等待下次重試
   - **成功確認**：只有上傳成功後才從緩衝區移除資料
   - **自動重連**：連線中斷時自動重連

5. **批次插入**：
   - 使用 `executemany()` 批次插入，提升效能
   - 每次上傳一個 `sql_target_size` 的資料量

6. **停止時處理**：
   - 停止時自動上傳緩衝區中所有剩餘資料（即使未達到門檻）

**記憶體使用估算**：

| sql_upload_interval | 資料點數 | 記憶體使用 | 緩衝區上限 | 實際最大記憶體 |
|---------------------|---------|-----------|-----------|--------------|
| 60 秒 | 1,406,160 | ~34 MB | 2,812,320 | ~67 MB |
| 300 秒 | 7,030,800 | ~169 MB | 10,000,000 | ~240 MB |
| 600 秒 | 14,061,600 | ~337 MB | 10,000,000 | ~240 MB |
| 1200 秒 | 28,123,200 | ~675 MB | 10,000,000 | ~240 MB |

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
- 確認防火牆允許 8080 埠
- 檢查是否有其他程式佔用 8080 埠
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

### 除錯模式

如需查看詳細的除錯資訊，可以修改程式碼中的 `print` 語句，或使用 Python 的日誌模組。

## 技術架構

### 執行緒設計

| 執行緒 | 功能 | 備註 |
|--------|------|------|
| 主執行緒 | 控制流程、等待使用者中斷 | 同步主控核心 |
| Flask Thread | 提供 HTTP 介面與 API | daemon=True |
| Collection Thread | 資料收集迴圈（處理 CSV 和 SQL） | 在 `/start` 時啟動 |
| DAQ Reading Thread | 從 Modbus 設備讀取資料 | 在 `start_reading()` 時啟動 |

### 資料流詳細說明

```
ProWaveDAQ 設備
    ↓ (Modbus RTU)
ProWaveDAQ._read_loop() [背景執行緒]
    ↓ (放入佇列)
data_queue (queue.Queue, 最大 1000 筆)
    ↓
collection_loop() [背景執行緒]
    │
    ├─→ update_realtime_data()
    │   │
    │   ▼
    │   realtime_data (List[float], 最多 10000 點)
    │   │   - 智慧緩衝區：僅在有活躍連線時更新
    │   │   - 記憶體管理：超過 10000 點時只保留最近 10000 點
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
- `src/csv_writer.py`：負責 CSV 檔案的建立與寫入
- `src/sql_uploader.py`：負責 SQL 資料庫連線與資料上傳
- `src/main.py`：整合所有功能，提供 Web 介面（使用 Flask + templates）
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

**最後更新**：2025年11月20日  
**作者**：王建葦
