"""
Common helper functions for the Adaptive Stealth Network.

Provides YAML loading, UUID generation, timestamp formatting,
and other shared utilities.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


def load_yaml(path: str | Path) -> dict[str, Any]:
    """
    Load and parse a YAML configuration file.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed YAML content as a dictionary.

    Raises:
        FileNotFoundError: If the file does not exist.
        yaml.YAMLError:    If parsing fails.
    """
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"YAML file not found: {file_path}")

    with open(file_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    return data if isinstance(data, dict) else {}


def save_yaml(data: dict[str, Any], path: str | Path) -> None:
    """
    Save a dictionary to a YAML file.

    Args:
        data: Data to serialize.
        path: Output file path.
    """
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, default_flow_style=False, allow_unicode=True)


def generate_id() -> str:
    """
    Generate a new UUID4 string.

    Returns:
        UUID string (e.g., ``"a1b2c3d4-e5f6-7890-abcd-ef1234567890"``).
    """
    return str(uuid.uuid4())


def timestamp_now() -> str:
    """
    Get the current UTC timestamp in ISO 8601 format.

    Returns:
        ISO timestamp string (e.g., ``"2025-03-20T12:00:00+00:00"``).
    """
    return datetime.now(timezone.utc).isoformat()


def clamp(value: float, min_val: float, max_val: float) -> float:
    """
    Clamp a value within a range.

    Args:
        value:   The value to clamp.
        min_val: Minimum allowed value.
        max_val: Maximum allowed value.

    Returns:
        Clamped value.
    """
    return max(min_val, min(max_val, value))


def format_bytes(size_bytes: int) -> str:
    """
    Format byte count as human-readable string.

    Args:
        size_bytes: Number of bytes.

    Returns:
        Formatted string (e.g., ``"1.5 MB"``).
    """
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size_bytes) < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"
