"""
Custom error classes for the Liftbook application.
"""


class LiftbookError(Exception):
    """Base exception for Liftbook."""
    pass


class ParsingError(LiftbookError):
    """Raised when workout data cannot be parsed."""
    pass


class ValidationError(LiftbookError):
    """Raised when input validation fails."""
    pass


class DatabaseError(LiftbookError):
    """Raised when database operations fail."""
    pass


class UserNotFoundError(LiftbookError):
    """Raised when a user is not found."""
    pass
