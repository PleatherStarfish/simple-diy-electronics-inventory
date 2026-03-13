from __future__ import annotations

import logging
from collections import deque
from logging.handlers import RotatingFileHandler
from pathlib import Path
from threading import Lock
from typing import Callable


class MemoryLogHandler(logging.Handler):
    """In-memory log handler for UI display and diagnostics."""

    def __init__(self, capacity: int = 500) -> None:
        super().__init__()
        self.capacity = capacity
        self.records: deque[str] = deque(maxlen=capacity)
        self._listeners: list[Callable[[str], None]] = []
        self._lock = Lock()

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        with self._lock:
            self.records.append(message)
            listeners = list(self._listeners)
        for listener in listeners:
            try:
                listener(message)
            except Exception:
                # Logging should never crash the app.
                pass

    def add_listener(self, listener: Callable[[str], None]) -> None:
        with self._lock:
            self._listeners.append(listener)

    def get_messages(self) -> list[str]:
        with self._lock:
            return list(self.records)


def configure_logging(log_dir: Path) -> MemoryLogHandler:
    """Configure process-wide logging and return the memory handler."""
    log_dir.mkdir(parents=True, exist_ok=True)
    logfile = log_dir / "eurorack_inventory.log"

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    file_handler = RotatingFileHandler(
        logfile,
        maxBytes=1_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(logging.INFO)

    memory_handler = MemoryLogHandler()
    memory_handler.setFormatter(formatter)
    memory_handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Avoid duplicate handlers when tests or repeated launches configure logging again.
    root.handlers = []
    root.addHandler(file_handler)
    root.addHandler(memory_handler)

    logging.getLogger(__name__).info("Logging configured at %s", logfile)
    return memory_handler
