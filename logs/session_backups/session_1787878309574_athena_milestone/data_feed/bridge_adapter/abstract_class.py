"""
IDataSource — Abstract Base Class (ABC) Interface มาตรฐานสำหรับทุก Broker Adapter
data_feed/abstract_class.py

กฎ: Adapter ทุกตัวต้อง implement เมธอดที่ marked @abstractmethod ทั้งหมด
เพื่อให้ DataAdapter (Coordinator) เรียกใช้งานได้ในรูปแบบเดียวกัน ไม่สนว่าดึงมาจากโบรกเกอร์ไหน
กำหนด Abstract Base Class (ABC) สำหรับเป็น Interface มาตรฐานของแหล่งข้อมูล (Data Source)
ไฟล์นี้ทำหน้าที่เป็นสัญญา (Contract) ให้ Adapter ที่จะสร้างขึ้นมาทั้งหมด
ต้องมีเมธอดตามที่กำหนดไว้ เพื่อให้ส่วนอื่นของระบบเรียกใช้งานได้ในรูปแบบเดียวกัน
"""
from abc import ABC, abstractmethod
from typing import Dict, Any, Optional, List
import pandas as pd


class IDataSource(ABC):
    """
    Interface (สัญญา) สำหรับ Data Source Adapter ทุกตัว
    กำหนดเมธอดมาตรฐานที่ทุกโบรกเกอร์ต้อง implement เพื่อให้ DataAdapter เรียกใช้งานได้ในรูปแบบเดียวกัน
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        Initialize with configuration from settings.json.
        
        Args:
            config: Configuration dictionary.
        """
        self.config = config or {}

    # ── Connection ──────────────────────────────────────────────────

    @abstractmethod
    def connect(self) -> None:
        """สร้างการเชื่อมต่อเริ่มต้นไปยังแหล่งข้อมูล"""
        raise NotImplementedError

    @abstractmethod
    def disconnect(self) -> None:
        """ยกเลิกการเชื่อมต่อจากแหล่งข้อมูล"""
        raise NotImplementedError

    @abstractmethod
    def is_connected(self) -> bool:
        """
        ตรวจสอบสถานะการเชื่อมต่อ
        Returns:
            bool: True หากเชื่อมต่อ, False หากไม่ได้เชื่อมต่อ
        """
        raise NotImplementedError

    @abstractmethod
    def get_open_symbols(self, target_symbols: Optional[List[str]] = None) -> List[str]:
        """
        Check and return list of open/tradable symbols from the broker matching target_symbols.
        """
        raise NotImplementedError

    # ── Candle & Stream Data ────────────────────────────────────────

    @abstractmethod
    def get_candles(self, symbol: str, timeframe: str, count: int, end_time: Optional[float] = None) -> pd.DataFrame:
        """
        ดึงข้อมูลแท่งเทียนสำหรับสัญลักษณ์และ timeframe ที่กำหนด

        Args:
            symbol: ชื่อสัญลักษณ์ เช่น 'EURUSD-OTC' (ตาม settings.json)
            timeframe: 'M1', 'M5', 'M15'
            count: จำนวนแท่งเทียนที่ต้องการ
            end_time: epoch timestamp สิ้นสุด (optional)

        Returns:
            DataFrame [open, high, low, close, volume] indexed by UTC datetime
        """
        raise NotImplementedError

    @abstractmethod
    def start_stream(self, symbol: str, timeframe: str, count: int) -> None:
        """
        เริ่มต้นการสตรีมข้อมูลราคาสำหรับสินทรัพย์และ Timeframe ที่กำหนด
        
        Args:
            symbol: ชื่อสัญลักษณ์ เช่น 'EURUSD-OTC'
            timeframe: 'M1', 'M5', 'M15'
            count: จำนวนแท่งเทียนที่ต้องการเก็บใน stream buffer
        """
        raise NotImplementedError

    # ── Server Time ────────────────────────────────────────────────

    @abstractmethod
    def get_server_timestamp(self) -> float:
        """
        ดึงเวลาปัจจุบันจากเซิร์ฟเวอร์โบรกเกอร์
        
        Returns:
            float: server epoch timestamp
        """
        raise NotImplementedError

    # ── Account ─────────────────────────────────────────────────────

    @abstractmethod
    def get_balance(self) -> float:
        """
        ดึงยอดเงินคงเหลือในบัญชี

        Returns:
            float: ยอดเงินคงเหลือ
        """
        raise NotImplementedError

    # ── Optional & Advanced ─────────────────────────────────────────

    @property
    def connected(self) -> bool:
        """Property shortcut สำหรับ self.is_connected()"""
        return self.is_connected()

