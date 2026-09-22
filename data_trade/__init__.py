"""Part 4 trade execution package.

Submodules are intentionally not imported eagerly.  Eager imports create
cross-part cycles when a decision engine imports the shared payload sanitizer.
Use the concrete module paths (for example ``data_trade.executor_manager``).
"""
