"""
Logging configuration for the Liftbook application.
"""
import logging
import sys
from typing import Optional


def setup_logger(name: str = 'liftbook', level: int = logging.INFO) -> logging.Logger:
    """Set up and configure application logger."""
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Avoid duplicate handlers
    if logger.handlers:
        return logger
    
    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    
    # Formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(formatter)
    
    logger.addHandler(console_handler)
    
    return logger


# Global logger instance
logger = setup_logger()
