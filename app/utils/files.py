"""File operations, safe streaming I/O, and fast hashing."""

import os
import hashlib
import json
import tempfile
from typing import Any, Dict, List, Optional


def compute_file_hash(file_path: str, chunk_size_mb: int = 16) -> str:
    """Compute a fast deterministic hash of a media file without reading huge files into memory.
    
    Hashes the file size, first chunk, and last chunk.
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    file_size = os.path.getsize(file_path)
    hasher = hashlib.sha256()
    hasher.update(str(file_size).encode("utf-8"))
    
    chunk_bytes = chunk_size_mb * 1024 * 1024
    with open(file_path, "rb") as f:
        # First chunk
        first_chunk = f.read(chunk_bytes)
        hasher.update(first_chunk)
        
        # Last chunk (if file is larger than 1 chunk)
        if file_size > chunk_bytes:
            f.seek(max(0, file_size - chunk_bytes))
            last_chunk = f.read(chunk_bytes)
            hasher.update(last_chunk)

    return hasher.hexdigest()[:16]


def safe_write_json(file_path: str, data: Any, indent: int = 2) -> None:
    """Atomically write JSON data to file to prevent corruptions."""
    dir_name = os.path.dirname(os.path.abspath(file_path))
    os.makedirs(dir_name, exist_ok=True)
    
    temp_fd, temp_path = tempfile.mkstemp(dir=dir_name, prefix=".tmp_json_")
    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent, ensure_ascii=False)
        os.replace(temp_path, file_path)
    except Exception:
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def safe_read_json(file_path: str, default: Optional[Any] = None) -> Any:
    """Read JSON file with error handling."""
    if not os.path.isfile(file_path):
        if default is not None:
            return default
        raise FileNotFoundError(f"JSON file not found: {file_path}")
    
    with open(file_path, "r", encoding="utf-8") as f:
        return json.load(f)


def ensure_dir(dir_path: str) -> str:
    """Ensure directory exists and return absolute path."""
    abs_path = os.path.abspath(os.path.expanduser(dir_path))
    os.makedirs(abs_path, exist_ok=True)
    return abs_path


def list_media_files(directory: str, extensions: Optional[List[str]] = None) -> List[str]:
    """List all supported video files in a directory."""
    if extensions is None:
        extensions = [".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v"]
    
    ext_set = {ext.lower() for ext in extensions}
    dir_path = os.path.abspath(os.path.expanduser(directory))
    if not os.path.isdir(dir_path):
        return []

    found = []
    for entry in sorted(os.listdir(dir_path)):
        full_path = os.path.join(dir_path, entry)
        if os.path.isfile(full_path):
            _, ext = os.path.splitext(entry)
            if ext.lower() in ext_set:
                found.append(full_path)
    return found
