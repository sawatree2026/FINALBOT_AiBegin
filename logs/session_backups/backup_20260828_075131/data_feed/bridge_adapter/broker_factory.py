"""
Broker Factory

Orchestrates the selection and instantiation of the correct broker adapter
based on configuration.
"""
import logging
from typing import Dict, Any

from data_feed.bridge_adapter.abstract_class import IDataSource
from data_feed.bridge_adapter.bridge_iq_adapter.bridge_iq_adapter import IQOptionAdapter
from data_feed.bridge_adapter.bridge_quotex_adapter.bridge_quotex_adapter import QuotexAdapter
from data_feed.bridge_adapter.bridge_pocket_adapter.bridge_pocket_adapter import PocketAdapter

logger = logging.getLogger(__name__)

class BrokerFactory:
    @staticmethod
    def create_raw_broker(config: Dict[str, Any]) -> IDataSource:
        """Instantiates the underlying low-level broker adapter."""
        active_broker = "IQ_OPTION"  # Default fallback
        if "active_broker" in config and config["active_broker"]:
            active_broker = str(config["active_broker"]).upper()
        
        logger.info(f"[BrokerFactory] Initializing raw broker adapter for: {active_broker}")
        
        if active_broker == "IQ_OPTION":
            return IQOptionAdapter(config=config)
        elif active_broker == "QUOTEX":
            return QuotexAdapter(config=config)
        elif active_broker == "POCKET_OPTION":
            return PocketAdapter(config=config)
        else:
            logger.warning(f"[BrokerFactory] Unknown broker '{active_broker}', falling back to IQ_OPTION")
            return IQOptionAdapter(config=config)

    @staticmethod
    def create_broker(config: Dict[str, Any]) -> Any:
        """
        Creates and returns the Commander of Part 1 (DataAdapter) configured with
        underlying broker adapter, TimeSyncManager, and CSV storage.
        """
        from data_feed.data_adapter import DataAdapter
        from data_feed.csv_time_sync import TimeSyncManager
        from config_setting.config_loader import get_csv_manager_config

        raw_broker = BrokerFactory.create_raw_broker(config=config)

        # Initialize time sync manager
        time_sync_mgr = TimeSyncManager(data_adapter=raw_broker)
        time_sync_mgr.sync_server_time(raw_broker)
        time_sync_mgr.start_time_sync_thread()

        # Resolve base dir for CSV manager
        csv_mgr_cfg = get_csv_manager_config()
        base_dir = csv_mgr_cfg.get("base_dir", "data_feed/ohclv_output/iq_option")

        data_adapter = DataAdapter(
            broker_adapter=raw_broker,
            time_sync_manager=time_sync_mgr,
            base_dir=base_dir,
            config=config
        )
        return data_adapter
