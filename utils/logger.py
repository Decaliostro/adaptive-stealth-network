"""
Structured logging utility for the Adaptive Stealth Network.

Provides consistent, formatted logging across all modules with
both console and optional file output.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def setup_logger(
    name: str = "asn",
    level: str = "INFO",
    log_file: str | None = None,
    log_format: str | None = None,
) -> logging.Logger:
    """
    Create and configure a structured logger.

    Args:
        name:       Logger name (dot-separated hierarchy).
        level:      Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL).
        log_file:   Optional file path for log output.
        log_format: Custom format string (uses default if None).

    Returns:
        Configured ``logging.Logger`` instance.

    Example::

        logger = setup_logger("asn.controller", level="DEBUG", log_file="logs/controller.log")
        logger.info("Controller started")
    """
    if log_format is None:
        log_format = "%(asctime)s | %(levelname)-8s | %(name)-24s | %(message)s"

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Avoid duplicate handlers
    if logger.handlers:
        return logger

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(console_handler)

    # File handler (optional)
    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_path), encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(logging.Formatter(log_format, datefmt="%Y-%m-%d %H:%M:%S"))
        logger.addHandler(file_handler)

    return logger


def get_logger(name: str) -> logging.Logger:
    """
    Get or create a child logger under the ASN hierarchy.

    Args:
        name: Logger name (will be prefixed with ``asn.`` if not already).

    Returns:
        ``logging.Logger`` instance.
    """
    if not name.startswith("asn."):
        name = f"asn.{name}"
    return logging.getLogger(name)
