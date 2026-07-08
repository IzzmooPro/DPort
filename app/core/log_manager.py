"""
core/log_manager.py
Zaman damgalı DNS değişiklik logu.
"""
import os
import sys
from datetime import datetime
from typing import List


class LogManager:
    # Log dosyasi bu boyutu asinca son yarisi tutulur, eskisi atilir (sinirsiz
    # buyumeyi onler; son kayitlar her zaman elde kalir).
    MAX_BYTES = 1_000_000  # ~1 MB

    def __init__(self, log_path: str, enabled: bool = True, mirror_console: bool = True,
                 max_bytes: int = MAX_BYTES):
        self.log_path = log_path
        self.enabled = enabled
        self.mirror_console = mirror_console
        self.max_bytes = max_bytes
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

    def write(self, message: str):
        now = datetime.now()
        file_ts = now.strftime("%d.%m.%Y %H:%M:%S")
        console_ts = now.strftime("%H:%M:%S")
        line = f"[{file_ts}] {message}"
        self.console(message, ts=console_ts)

        if not self.enabled:
            return
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
            self._rotate_if_needed()
        except Exception:
            pass

    def _rotate_if_needed(self):
        """Dosya MAX_BYTES'i asarsa son yarisini tutup basini atar (satir
        butunlugu korunur). Boylece log sinirsiz buyumez, son kayitlar kalir."""
        try:
            if self.max_bytes <= 0 or os.path.getsize(self.log_path) <= self.max_bytes:
                return
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            keep = lines[len(lines) // 2:]          # son yariyi tut
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("".join(keep))
        except Exception:
            pass

    def console(self, message: str, level: str = "INFO", ts: str | None = None):
        if not self.mirror_console or sys.stdout is None:
            return
        try:
            stamp = ts or datetime.now().strftime("%H:%M:%S")
            print(f"[{stamp}] [{level}] {message}", flush=True)
        except Exception:
            pass

    def read_lines(self, last_n: int = 200) -> List[str]:
        if not os.path.exists(self.log_path):
            return []
        try:
            with open(self.log_path, "r", encoding="utf-8") as f:
                lines = f.readlines()
            return lines[-last_n:]
        except Exception:
            return []

    def clear(self):
        try:
            with open(self.log_path, "w", encoding="utf-8") as f:
                f.write("")
        except Exception:
            pass
