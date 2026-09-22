import sys
import os
import time
import logging
import threading
from datetime import datetime


logger = logging.getLogger(__name__)


class TimeSyncManager:
    """
    ระบบบริหารจัดการการซิงค์เวลากับเซิร์ฟเวอร์ (Time Sync Manager) - Singleton Pattern
    """
    _instance = None
    
    def __new__(cls, *args, **kwargs):
        """Ensure singleton pattern for TimeSyncManager"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, data_adapter=None, config=None):
        """Initialize with time sync configuration."""
        if hasattr(self, '_initialized') and self._initialized:
            if data_adapter is not None and self.data_adapter is None:
                self.data_adapter = data_adapter
            return
            
        self._initialized = True
        self.data_adapter = data_adapter
        if config is None:
            from config_setting.config_loader import get_time_sync_manager_config
            config = get_time_sync_manager_config()
        
        self.time_offset = 0
        self._synced = False
        self.sync_interval = config.get("sync_interval", 30)
        self.max_sync_attempts = config.get("max_sync_attempts", 3)
        self._sync_thread = None
        self._is_running = False

        # หากมี data_adapter ตั้งแต่ init ให้ทำการซิงค์เวลา 1 ครั้ง
        if self.data_adapter is not None:
            self.sync_server_time()

    def sync_server_time(self, data_adapter=None):
        """
        ดึงเวลาจาก broker server timestamp และคำนวณ time_offset = server_time - local_time
        หากยิงขอเวลาไม่สำเร็จ ให้ระเบิด Fail-Fast: raise RuntimeError("FAIL-FAST: Failed to get server time offset from broker")
        """
        if data_adapter is not None:
            self.data_adapter = data_adapter

        if self.data_adapter is None:
            logger.error("Failed to get server time offset: data_adapter is None")
            raise RuntimeError("FAIL-FAST: Failed to get server time offset from broker")

        try:
            server_time = self.data_adapter.get_server_timestamp()
            if server_time is None:
                raise ValueError("get_server_timestamp returned None")
            local_time = int(time.time())
            self.time_offset = server_time - local_time
            logger.info(f"[TIME SYNC] Server time offset: {self.time_offset} seconds (Synced at {datetime.now().strftime('%H:%M:%S.%f')[:-3]})")
            self._synced = True
        except RuntimeError:
            raise
        except Exception as e:
            logger.exception("Failed to get server time offset")
            raise RuntimeError("FAIL-FAST: Failed to get server time offset from broker") from e

    def start_time_sync_thread(self):
        """
        เริ่มต้น Daemon Thread เพื่อทำการ resync เวลา ณ วินาทีที่ 30 (:30) ของทุกนาที
        """
        if self._is_running and self._sync_thread is not None and self._sync_thread.is_alive():
            logger.debug("[TIME SYNC] Time resync thread is already running.")
            return

        self._is_running = True
        self._sync_thread = threading.Thread(
            target=self._time_sync_loop,
            daemon=True,
            name="TimeSyncDaemonThread"
        )
        self._sync_thread.start()
        logger.info("[TIME SYNC] Daemon thread started (auto-resync at second :30 of every minute)")

    def stop_time_sync_thread(self):
        """
        หยุดการทำงานของ Daemon Thread
        """
        self._is_running = False

    def _time_sync_loop(self):
        """
        Loop ของ Daemon Thread คอยตรวจวัดเวลาและสั่ง sync_server_time() ณ วินาทีที่ 30 ของทุกนาที
        """
        while self._is_running:
            try:
                now = datetime.now()
                current_sec = now.second + now.microsecond / 1_000_000.0
                if current_sec < 30.0:
                    sleep_time = 30.0 - current_sec
                else:
                    sleep_time = 60.0 - current_sec + 30.0

                time.sleep(sleep_time)

                if not self._is_running:
                    break

                if self.data_adapter is not None:
                    logger.info("[TIME SYNC] Executing auto resync at second :30...")
                    self.sync_server_time()

                # Sleep 1.0 วินาทีเพื่อป้องกันการทำงานซ้ำในวินาทีที่ 30 เดียวกัน
                time.sleep(1.0)
            except Exception as e:
                logger.exception("[TIME SYNC] Error in auto resync thread loop")
                time.sleep(5.0)

    def get_broker_epoch(self) -> float:
        """
        คืนค่า time.time() + self.time_offset สำหรับส่งต่อให้ระบบดึงข้อมูลแท่งเทียน
        """
        if not self._synced:
            logger.error("[TIME SYNC] get_broker_epoch called before time sync completed")
            raise RuntimeError("FAIL-FAST: Broker time not synced — call sync_server_time() first")
        return time.time() + self.time_offset

    @staticmethod
    def calculate_time_block(broker_epoch: float, timeframe_seconds: int) -> int:
        """
        คำนวณ time block จาก broker epoch และ timeframe
        """
        return int(broker_epoch) // timeframe_seconds
    
    @staticmethod
    def get_local_time() -> int:
        """
        คืนค่า local time เวลาปัจจุบัน
        """
        return int(time.time())