"""
Custom error classes for the Liftbook application.
"""


class WorkoutTrackerError(Exception):
    """Base exception for Liftbook."""
    pass


class ParsingError(WorkoutTrackerError):
    """Raised when workout data cannot be parsed."""
    pass


class ValidationError(WorkoutTrackerError):
    """Raised when input validation fails."""
    pass


class DatabaseError(WorkoutTrackerError):
    """Raised when database operations fail."""
    pass


class UserNotFoundError(WorkoutTrackerError):
    """Raised when a user is not found."""
    pass
