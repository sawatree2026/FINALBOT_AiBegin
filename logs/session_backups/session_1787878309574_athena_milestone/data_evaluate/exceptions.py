"""
Custom exceptions for data evaluation engine computation flow.
"""

class DataEvaluateError(Exception):
    """Base exception for data_evaluate errors."""
    pass

class InvalidInputError(DataEvaluateError):
    """Raised when input data is invalid, missing, or of wrong type."""
    pass

class ComputationError(DataEvaluateError):
    """Raised when an error occurs during computation in an engine."""
    pass
