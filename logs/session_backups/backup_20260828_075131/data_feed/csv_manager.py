"""
CSV Manager

Manages paths, directories, and file naming conventions.
"""

import os
from datetime import datetime
import logging
import traceback
from typing import Dict, Any, Optional
from data_feed.csv_writer import read_csv_safe

logger = logging.getLogger(__name__)

class CSVManager:
    """Manages file storage directories and filenames - Singleton Pattern"""
    
    _instance = None
    
    def __new__(cls, base_dir: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
        """Ensure singleton pattern for CSVManager"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, base_dir: Optional[str] = None, config: Optional[Dict[str, Any]] = None):
        """Initialize with manager configuration."""
        if hasattr(self, '_initialized') and self._initialized:
            return
            
        self._initialized = True
        if config is None:
            from config_setting.config_loader import get_csv_manager_config
            config = get_csv_manager_config()
        
        if not base_dir:
            if config and config.get("base_dir"):
                base_dir = config.get("base_dir")
            else:
                from config_setting.config_loader import load_settings
                active_broker = str(load_settings().get("active_broker", "iq_option")).lower()
                base_dir = f"data_base/csv/{active_broker}"
        
        # Load manager configuration
        self.base_dir = config.get("base_dir", base_dir)
        self.naming_convention = config.get("naming_convention", "{symbol}_{timeframe}.csv")
        self.auto_create_dirs = config.get("auto_create_dirs", True)
        self.file_permissions = config.get("file_permissions", "rw-r--r--")
        
        logger.info(f"[CSVManager] Initialized with base_dir: {self.base_dir}")

    def get_file_path(self, symbol: str, timeframe: str, date_str: str = None) -> str:
        """Get the full file path for a symbol and timeframe, ensuring directories exist."""
        if not isinstance(symbol, str):
            raise TypeError(f"symbol must be str, got {type(symbol).__name__}")
        if not isinstance(timeframe, str):
            raise TypeError(f"timeframe must be str, got {type(timeframe).__name__}")
        # Path traversal protection
        if '..' in symbol or '..' in timeframe:
            raise ValueError(f"Path traversal detected in symbol='{symbol}' or timeframe='{timeframe}'")
        if '/' in symbol or '\\' in symbol:
            raise ValueError(f"Invalid characters in symbol: '{symbol}'")
        if not date_str:
            date_str = datetime.now().strftime("%Y_%m_%d")
            
        # Generate filename based on naming convention
        symbol_folder = symbol  # เก็บเป็นเดิม EURUSD-OTC
        filename = self.naming_convention.format(
            symbol=symbol,  # เก็บเป็นเดิม EURUSD-OTC ทั้ง โฟลเดอร์ ทั้งชื่อไฟล์
            timeframe=timeframe,
            date=date_str
        )

        # Create date-based subdirectory with original symbol name
        full_path = os.path.join(self.base_dir, symbol_folder, filename)

        # Ensure base directory exists
        os.makedirs(self.base_dir, exist_ok=True)
        
        if self.auto_create_dirs:
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
        
        return full_path
    
    def ensure_directory_exists(self, path: str) -> None:
        """Ensure the directory for the given path exists."""
        directory = os.path.dirname(path)
        if directory and self.auto_create_dirs:
            os.makedirs(directory, exist_ok=True)
    
    def read_csv(self, symbol: str, timeframe: str, **kwargs) -> Any:
        """Read CSV file for symbol and timeframe using per-file thread lock."""
        file_path = self.get_file_path(symbol, timeframe)
        return read_csv_safe(file_path, **kwargs)

    def get_csv_reader(self) -> Any:
        """Get CSV reader instance to read files."""
        return read_csv_safe
    
    def cleanup_old_files(self, symbol: str, timeframe: str, keep_days: int = 30) -> None:
        """Clean up old CSV files beyond the specified retention period."""
        import glob
        
        symbol_folder = symbol  # เก็บเป็นเดิม EURUSD-OTC
        pattern = f"{symbol}_{timeframe}*.csv"
        search_dir = os.path.join(self.base_dir, symbol_folder, "*")  # Search in OTC folder
        
        for file_path in glob.glob(os.path.join(search_dir, pattern)):
            try:
                file_age_days = (datetime.now() - datetime.fromtimestamp(os.path.getmtime(file_path))).days
                if file_age_days > keep_days:
                    os.remove(file_path)
                    logger.info(f"[CSVManager] Removed old file: {file_path}")
            except Exception as e:
                logger.error(f"[CSVManager] Failed to clean up {file_path}: {e}")
                traceback.print_exc()
