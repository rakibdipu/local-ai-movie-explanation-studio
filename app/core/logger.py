"""Application logging with Rich terminal formatting and log file persistence."""

import logging
import os
import sys
from typing import Optional
from rich.console import Console
from rich.logging import RichHandler

console = Console()
error_console = Console(stderr=True)

_logger: Optional[logging.Logger] = None


def setup_logger(log_file: Optional[str] = None, level: int = logging.INFO) -> logging.Logger:
    """Initialize application logger with console formatting and file output."""
    global _logger
    logger = logging.getLogger("movie_explainer")
    logger.setLevel(level)
    for h in logger.handlers:
        try:
            h.close()
        except Exception:
            pass
    logger.handlers.clear()

    # Rich console handler
    rich_handler = RichHandler(
        console=console,
        show_time=True,
        show_path=False,
        rich_tracebacks=True,
        markup=True
    )
    rich_handler.setLevel(level)
    logger.addHandler(rich_handler)

    # File handler if specified
    if log_file:
        os.makedirs(os.path.dirname(os.path.abspath(log_file)), exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(logging.DEBUG)
        file_format = logging.Formatter(
            "[%(asctime)s] [%(levelname)s] [%(name)s.%(funcName)s:%(lineno)d]: %(message)s"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

    _logger = logger
    return logger


def get_logger() -> logging.Logger:
    """Get active logger instance or initialize default."""
    global _logger
    if _logger is None:
        _logger = setup_logger()
    return _logger
