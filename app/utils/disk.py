"""Disk space and memory safety monitoring."""

import shutil
import os
import psutil
from typing import Tuple, Dict, Any


def get_disk_space_info(path: str = ".") -> Dict[str, float]:
    """Get free, used, and total disk space in Gigabytes (GB)."""
    check_path = path if os.path.exists(path) else os.path.abspath(".")
    total, used, free = shutil.disk_usage(check_path)
    return {
        "total_gb": round(total / (1024 ** 3), 2),
        "used_gb": round(used / (1024 ** 3), 2),
        "free_gb": round(free / (1024 ** 3), 2),
        "free_percent": round((free / total) * 100, 1),
    }


def check_disk_space_sufficient(path: str = ".", min_free_gb: float = 5.0) -> Tuple[bool, str]:
    """Verify that available SSD disk space meets the minimum requirement."""
    info = get_disk_space_info(path)
    if info["free_gb"] < min_free_gb:
        msg = (
            f"Insufficient disk space! Required: {min_free_gb:.1f} GB, "
            f"Available: {info['free_gb']:.1f} GB on {os.path.abspath(path)}. "
            "Please free up disk space before processing."
        )
        return False, msg
    return True, f"Disk space OK: {info['free_gb']:.1f} GB available."


def get_system_memory_info() -> Dict[str, Any]:
    """Get RAM and Swap usage stats."""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()
    return {
        "ram_total_mb": round(mem.total / (1024 ** 2)),
        "ram_available_mb": round(mem.available / (1024 ** 2)),
        "ram_used_percent": mem.percent,
        "swap_total_mb": round(swap.total / (1024 ** 2)),
        "swap_used_percent": swap.percent,
    }


def get_process_memory_mb() -> float:
    """Get current Python process memory footprint in MB."""
    process = psutil.Process(os.getpid())
    return round(process.memory_info().rss / (1024 ** 2), 2)
