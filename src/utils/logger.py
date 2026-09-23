# src/utils/logger.py

import logging
import sys
from typing import Optional


def setup_root_logging(level: int = logging.INFO):
    """
    Configures the root logging format and handlers once.
    Avoids duplicate handlers if already configured.
    """
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        root_logger.setLevel(level)
        
        # Stream handler to stdout
        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setLevel(level)
        
        # Standardized log format
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    Returns a configured logger with the given name.
    Usage in any file:
        from src.utils.logger import get_logger
        logger = get_logger(__name__)
    """
    setup_root_logging()
    return logging.getLogger(name or "ITCYBX")

