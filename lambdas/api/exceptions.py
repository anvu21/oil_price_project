"""
Typed application exceptions for the gas price API.

Kept in a separate module to avoid circular imports between main.py
(which registers the exception handlers) and routers/prices.py (which raises them).
"""


class AppError(Exception):
    """Base class for all typed application errors."""


class StateNotFoundError(AppError):
    """Raised when a requested state abbreviation is not recognised or has no data."""


class InvalidPeriodError(AppError):
    """Raised when an invalid period or grade value is supplied."""


class DatabaseUnavailableError(AppError):
    """Raised when the RDS connection fails or a query throws an unexpected error."""
