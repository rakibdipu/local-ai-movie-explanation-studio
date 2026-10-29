"""Temporary files and resource cleanup utilities."""

import os
import shutil
import glob
from typing import List, Optional


class TempFileManager:
    """Tracks and cleans up temporary video/audio/image files."""

    def __init__(self, temp_dir: str):
        self.temp_dir = os.path.abspath(os.path.expanduser(temp_dir))
        os.makedirs(self.temp_dir, exist_ok=True)
        self._registered_files: List[str] = []

    def register(self, file_path: str) -> str:
        """Register a temporary file for tracked management."""
        self._registered_files.append(file_path)
        return file_path

    def cleanup_file(self, file_path: str) -> bool:
        """Remove a single temporary file if it exists."""
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
                return True
        except Exception:
            pass
        return False

    def cleanup_all(self, keep_patterns: Optional[List[str]] = None) -> int:
        """Clean all registered temporary files and temp dir contents."""
        removed_count = 0
        for f in self._registered_files:
            if self.cleanup_file(f):
                removed_count += 1
        self._registered_files.clear()

        # Clean old temp files in temp_dir
        if os.path.exists(self.temp_dir):
            for item in os.listdir(self.temp_dir):
                item_path = os.path.join(self.temp_dir, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                        removed_count += 1
                    elif os.path.isdir(item_path):
                        shutil.rmtree(item_path, ignore_errors=True)
                        removed_count += 1
                except Exception:
                    pass
        return removed_count
