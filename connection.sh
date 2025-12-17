#!/bin/bash
# 自動連線 OVPN 伺服器腳本
# 功能：自動將私鑰密碼、帳號與密碼輸入連線檔並連線

# 設定顏色輸出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 設定檔案路徑
OVPN_FILE="API/imCloud.ovpn"
CONFIG_FILE="API/connection_config.txt"
TEMP_OVPN_FILE="/tmp/imCloud_auto.ovpn"

# 函數：顯示使用說明
show_usage() {
    echo "使用方法："
    echo "  $0                    # 使用設定檔連線"
    echo "  $0 --setup            # 設定連線資訊（私鑰密碼、帳號、密碼）"
    echo "  $0 --disconnect       # 中斷連線"
    echo ""
    echo "設定檔位置：$CONFIG_FILE"
    echo "OVPN 檔案位置：$OVPN_FILE"
}

# 函數：檢查必要工具
check_requirements() {
    if ! command -v openvpn &> /dev/null; then
        echo -e "${RED}錯誤：未安裝 openvpn${NC}"
        echo "請執行：sudo apt-get install openvpn"
        exit 1
    fi
}

# 函數：設定連線資訊
setup_connection() {
    echo -e "${YELLOW}=== 設定 OVPN 連線資訊 ===${NC}"
    echo ""
    
    # 檢查設定檔是否存在
    if [ -f "$CONFIG_FILE" ]; then
        echo "發現現有設定檔，將更新設定..."
        source "$CONFIG_FILE"
    fi
    
    # 讀取私鑰密碼
    if [ -z "$PRIVATE_KEY_PASSWORD" ]; then
        read -sp "請輸入私鑰密碼: " key_password
        echo ""
        PRIVATE_KEY_PASSWORD="$key_password"
    else
        read -sp "請輸入私鑰密碼（按 Enter 保持不變）: " key_password
        echo ""
        if [ -n "$key_password" ]; then
            PRIVATE_KEY_PASSWORD="$key_password"
        fi
    fi
    
    # 讀取帳號
    if [ -z "$OVPN_USERNAME" ]; then
        read -p "請輸入 OVPN 帳號: " username
        OVPN_USERNAME="$username"
    else
        read -p "請輸入 OVPN 帳號（目前：$OVPN_USERNAME，按 Enter 保持不變）: " username
        if [ -n "$username" ]; then
            OVPN_USERNAME="$username"
        fi
    fi
    
    # 讀取密碼
    if [ -z "$OVPN_PASSWORD" ]; then
        read -sp "請輸入 OVPN 密碼: " password
        echo ""
        OVPN_PASSWORD="$password"
    else
        read -sp "請輸入 OVPN 密碼（按 Enter 保持不變）: " password
        echo ""
        if [ -n "$password" ]; then
            OVPN_PASSWORD="$password"
        fi
    fi
    
    # 讀取 OVPN 伺服器位址（可選）
    if [ -z "$OVPN_SERVER" ]; then
        read -p "請輸入 OVPN 伺服器位址（可選，按 Enter 跳過）: " server
        OVPN_SERVER="$server"
    else
        read -p "請輸入 OVPN 伺服器位址（目前：$OVPN_SERVER，按 Enter 保持不變）: " server
        if [ -n "$server" ]; then
            OVPN_SERVER="$server"
        fi
    fi
    
    # 儲存設定檔
    cat > "$CONFIG_FILE" << EOF
# OVPN 連線設定檔
# 此檔案包含敏感資訊，請勿分享或提交到版本控制系統

PRIVATE_KEY_PASSWORD="$PRIVATE_KEY_PASSWORD"
OVPN_USERNAME="$OVPN_USERNAME"
OVPN_PASSWORD="$OVPN_PASSWORD"
OVPN_SERVER="$OVPN_SERVER"
EOF
    
    # 設定檔案權限（僅擁有者可讀寫）
    chmod 600 "$CONFIG_FILE"
    
    echo -e "${GREEN}設定已儲存至 $CONFIG_FILE${NC}"
    echo ""
}

# 函數：建立臨時 OVPN 檔案
create_temp_ovpn() {
    # 檢查原始 OVPN 檔案是否存在
    if [ ! -f "$OVPN_FILE" ]; then
        echo -e "${YELLOW}警告：OVPN 檔案不存在：$OVPN_FILE${NC}"
        echo "正在建立基本 OVPN 設定檔..."
        
        # 建立基本 OVPN 設定檔
        cat > "$OVPN_FILE" << EOF
# OVPN 連線設定檔
client
dev tun
proto udp
resolv-retry infinite
nobind
persist-key
persist-tun
verb 3
EOF
        
        if [ -n "$OVPN_SERVER" ]; then
            echo "remote $OVPN_SERVER 1194" >> "$OVPN_FILE"
        fi
        
        echo ""
        echo -e "${YELLOW}請手動編輯 $OVPN_FILE 以添加完整的 OVPN 設定${NC}"
        echo ""
    fi
    
    # 複製原始 OVPN 檔案到臨時檔案
    cp "$OVPN_FILE" "$TEMP_OVPN_FILE"
    
    # 建立認證檔案（帳號和密碼）
    AUTH_FILE="/tmp/ovpn_auth_$$.txt"
    echo "$OVPN_USERNAME" > "$AUTH_FILE"
    echo "$OVPN_PASSWORD" >> "$AUTH_FILE"
    chmod 600 "$AUTH_FILE"
    
    # 在 OVPN 檔案中添加認證設定
    echo "auth-user-pass $AUTH_FILE" >> "$TEMP_OVPN_FILE"
    
    # 建立私鑰密碼檔案
    KEY_PASS_FILE="/tmp/ovpn_keypass_$$.txt"
    echo "$PRIVATE_KEY_PASSWORD" > "$KEY_PASS_FILE"
    chmod 600 "$KEY_PASS_FILE"
    
    echo "$AUTH_FILE|$KEY_PASS_FILE"  # 返回認證檔案和私鑰密碼檔案路徑，以便後續清理
}

# 函數：連線到 OVPN
connect_ovpn() {
    # 檢查設定檔是否存在
    if [ ! -f "$CONFIG_FILE" ]; then
        echo -e "${RED}錯誤：設定檔不存在：$CONFIG_FILE${NC}"
        echo "請先執行：$0 --setup"
        exit 1
    fi
    
    # 載入設定檔
    source "$CONFIG_FILE"
    
    # 檢查必要變數
    if [ -z "$PRIVATE_KEY_PASSWORD" ] || [ -z "$OVPN_USERNAME" ] || [ -z "$OVPN_PASSWORD" ]; then
        echo -e "${RED}錯誤：設定檔不完整${NC}"
        echo "請執行：$0 --setup"
        exit 1
    fi
    
    # 檢查是否已經連線
    if pgrep -x openvpn > /dev/null; then
        echo -e "${YELLOW}警告：OVPN 連線已存在${NC}"
        read -p "是否要中斷現有連線並重新連線？(y/N): " answer
        if [ "$answer" = "y" ] || [ "$answer" = "Y" ]; then
            disconnect_ovpn
        else
            exit 0
        fi
    fi
    
    echo -e "${GREEN}正在建立 OVPN 連線...${NC}"
    
    # 建立臨時 OVPN 檔案
    FILES=$(create_temp_ovpn)
    AUTH_FILE=$(echo "$FILES" | cut -d'|' -f1)
    KEY_PASS_FILE=$(echo "$FILES" | cut -d'|' -f2)
    
    # 執行 OVPN 連線（背景執行）
    echo "使用設定檔：$TEMP_OVPN_FILE"
    echo "認證檔案：$AUTH_FILE"
    echo "私鑰密碼檔案：$KEY_PASS_FILE"
    echo ""
    
    # 以 root 權限執行（如果需要）
    if [ "$EUID" -eq 0 ]; then
        openvpn --config "$TEMP_OVPN_FILE" --askpass "$KEY_PASS_FILE" --daemon
    else
        echo "嘗試以 sudo 權限執行..."
        sudo openvpn --config "$TEMP_OVPN_FILE" --askpass "$KEY_PASS_FILE" --daemon
    fi
    
    # 等待連線建立
    sleep 2
    
    # 檢查連線狀態
    if pgrep -x openvpn > /dev/null; then
        echo -e "${GREEN}OVPN 連線已啟動${NC}"
        echo "使用 'sudo killall openvpn' 或執行 '$0 --disconnect' 來中斷連線"
        
        # 清理臨時認證檔案（延遲清理，確保 OVPN 已讀取）
        (sleep 5 && rm -f "$AUTH_FILE" "$KEY_PASS_FILE") &
    else
        echo -e "${RED}錯誤：OVPN 連線啟動失敗${NC}"
        echo "請檢查："
        echo "  1. OVPN 設定檔是否正確"
        echo "  2. 私鑰密碼是否正確"
        echo "  3. 帳號和密碼是否正確"
        echo "  4. 系統日誌：sudo journalctl -u openvpn -n 50"
        rm -f "$AUTH_FILE" "$KEY_PASS_FILE" "$TEMP_OVPN_FILE"
        exit 1
    fi
}

# 函數：中斷連線
disconnect_ovpn() {
    echo -e "${YELLOW}正在中斷 OVPN 連線...${NC}"
    
    if pgrep -x openvpn > /dev/null; then
        if [ "$EUID" -eq 0 ]; then
            killall openvpn
        else
            sudo killall openvpn
        fi
        
        sleep 1
        
        if ! pgrep -x openvpn > /dev/null; then
            echo -e "${GREEN}OVPN 連線已中斷${NC}"
        else
            echo -e "${RED}錯誤：無法中斷連線${NC}"
            exit 1
        fi
    else
        echo -e "${YELLOW}沒有活動的 OVPN 連線${NC}"
    fi
    
    # 清理臨時檔案
    rm -f /tmp/ovpn_auth_*.txt /tmp/ovpn_keypass_*.txt "$TEMP_OVPN_FILE"
}

# 主程式
main() {
    # 檢查必要工具
    check_requirements
    
    # 解析命令列參數
    case "$1" in
        --setup|--config)
            setup_connection
            ;;
        --disconnect|--stop)
            disconnect_ovpn
            ;;
        --help|-h)
            show_usage
            ;;
        "")
            connect_ovpn
            ;;
        *)
            echo -e "${RED}錯誤：未知參數：$1${NC}"
            show_usage
            exit 1
            ;;
    esac
}

# 執行主程式
main "$@"
