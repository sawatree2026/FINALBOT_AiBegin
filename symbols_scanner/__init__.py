"""
symbols_scanner package
=======================
Module for pre-trade 3D quantitative asset screening and ranking.
- main_filter: Single Gateway to broker for Payout filter & multi-TF candle fetching
- secondary_filter: 7 Skills + 4 Edges + S/R quantitative ranking engine
"""

try:
    from .main_filter import main
    from .secondary_filter import rank_tradable_symbols, evaluate_symbol_comprehensive
except (ImportError, ValueError):
    from symbols_scanner.main_filter import main
    from symbols_scanner.secondary_filter import rank_tradable_symbols, evaluate_symbol_comprehensive

__all__ = [
    "main",
    "rank_tradable_symbols",
    "evaluate_symbol_comprehensive",
]
