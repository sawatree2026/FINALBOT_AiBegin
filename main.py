"""
FINALBOT — Main Entry Point
===========================
Main launcher for the FINALBOT automated trading system.
"""

import sys
import traceback
from monitoring.console_dashboard import ConsoleUI, setup_logging
from runner import PureAIRunner


def main():
    """Main execution entry point."""
    setup_logging()
    ConsoleUI.show_startup()

    bot = PureAIRunner()
    ConsoleUI.show_live_mode_start()
    bot.start()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        ConsoleUI.show_stopping()
        sys.exit(0)
    except Exception as e:
        print(f"\n[FATAL ERROR] {e}")
        traceback.print_exc()
        sys.exit(1)