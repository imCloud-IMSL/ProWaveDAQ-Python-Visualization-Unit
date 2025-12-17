#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
統一日誌系統模組

此模組提供統一的日誌輸出格式，所有日誌訊息都會自動包含時間戳記。
日誌格式：[YYYY-MM-DD HH:MM:SS] [LEVEL] 訊息內容

支援的日誌級別：
    - INFO: 一般資訊訊息（輸出到 stdout）
    - Debug: 調試訊息（輸出到 stdout，可關閉）
    - Error: 錯誤訊息（輸出到 stderr）
    - Warning: 警告訊息（輸出到 stdout）

使用方式：
    from logger import info, debug, error, warning
    
    info("這是一般資訊")
    debug("這是調試訊息")
    warning("這是警告訊息")
    error("這是錯誤訊息")
    
    # 關閉 Debug 訊息
    from logger import Logger
    Logger.set_debug_enabled(False)

版本：4.0.0
"""

import sys
from datetime import datetime
from typing import Optional


class Logger:
    """
    統一日誌類別
    
    提供統一的日誌輸出格式，包含時間戳記和日誌級別。
    所有日誌訊息格式為：[YYYY-MM-DD HH:MM:SS] [LEVEL] 訊息內容
    """
    
    # ========== 日誌級別常數 ==========
    LEVEL_INFO = "INFO"      # 一般資訊訊息
    LEVEL_DEBUG = "Debug"    # 調試訊息（可關閉）
    LEVEL_ERROR = "Error"    # 錯誤訊息（輸出到 stderr）
    LEVEL_WARNING = "Warning"  # 警告訊息
    
    # ========== 類別變數 ==========
    # 是否啟用 Debug 輸出（預設為 True）
    # 可以透過 set_debug_enabled(False) 關閉 Debug 訊息以減少日誌輸出
    _debug_enabled = True
    
    @classmethod
    def set_debug_enabled(cls, enabled: bool) -> None:
        """
        設定是否啟用 Debug 輸出
        
        Args:
            enabled: True 表示啟用 Debug 訊息，False 表示關閉
        
        使用範例：
            Logger.set_debug_enabled(False)  # 關閉 Debug 訊息
        """
        cls._debug_enabled = enabled
    
    @classmethod
    def _format_message(cls, level: str, message: str) -> str:
        """
        格式化日誌訊息
        
        Args:
            level: 日誌級別（如 "INFO"、"Debug"、"Error"、"Warning"）
            message: 日誌訊息內容
        
        Returns:
            str: 格式化後的日誌訊息，格式為 [YYYY-MM-DD HH:MM:SS] [LEVEL] 訊息內容
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return f"[{timestamp}] [{level}] {message}"
    
    @classmethod
    def info(cls, message: str) -> None:
        """
        輸出 INFO 級別日誌
        
        Args:
            message: 日誌訊息內容
        
        注意：INFO 訊息輸出到 stdout
        """
        formatted = cls._format_message(cls.LEVEL_INFO, message)
        print(formatted, file=sys.stdout)
        sys.stdout.flush()  # 立即刷新緩衝區，確保訊息即時顯示
    
    @classmethod
    def debug(cls, message: str) -> None:
        """
        輸出 Debug 級別日誌
        
        Args:
            message: 日誌訊息內容
        
        注意：
            - Debug 訊息只有在 _debug_enabled 為 True 時才會輸出
            - 可以透過 set_debug_enabled(False) 關閉 Debug 訊息
            - Debug 訊息輸出到 stdout
        """
        if cls._debug_enabled:
            formatted = cls._format_message(cls.LEVEL_DEBUG, message)
            print(formatted, file=sys.stdout)
            sys.stdout.flush()
    
    @classmethod
    def error(cls, message: str) -> None:
        """
        輸出 Error 級別日誌
        
        Args:
            message: 日誌訊息內容
        
        注意：Error 訊息輸出到 stderr（標準錯誤輸出）
        """
        formatted = cls._format_message(cls.LEVEL_ERROR, message)
        print(formatted, file=sys.stderr)
        sys.stderr.flush()  # 立即刷新緩衝區
    
    @classmethod
    def warning(cls, message: str) -> None:
        """
        輸出 Warning 級別日誌
        
        Args:
            message: 日誌訊息內容
        
        注意：Warning 訊息輸出到 stdout
        """
        formatted = cls._format_message(cls.LEVEL_WARNING, message)
        print(formatted, file=sys.stdout)
        sys.stdout.flush()


# 建立全域實例，方便直接使用
def info(message: str) -> None:
    """輸出 INFO 級別日誌"""
    Logger.info(message)


def debug(message: str) -> None:
    """輸出 Debug 級別日誌"""
    Logger.debug(message)


def error(message: str) -> None:
    """輸出 Error 級別日誌"""
    Logger.error(message)


def warning(message: str) -> None:
    """輸出 Warning 級別日誌"""
    Logger.warning(message)

