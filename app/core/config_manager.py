"""
core/config_manager.py
JSON tabanlı uygulama ayarları yönetimi.
"""
import json
import os
import threading
from typing import Any

DEFAULT_CONFIG = {
    "language": "tr",
    "theme": "dark",
    "minimize_to_tray": True,
    "startup": False,
    "log_enabled": True,
    "apply_to_all_adapters": True,
    "selected_adapter": None,
    "active_provider_id": None,
    "discord_last_update_ok_at": None,
}


class ConfigManager:
    def __init__(self, config_path: str):
        self.config_path = config_path
        self._data: dict = {}
        self._lock = threading.RLock()  # ayni .tmp dosyasina eszamanli set/save cakismasin
        self.load()

    # ------------------------------------------------------------------
    def load(self):
        with self._lock:
            if os.path.exists(self.config_path):
                try:
                    with open(self.config_path, "r", encoding="utf-8") as f:
                        loaded = json.load(f)
                    # Varsayılan değerleri ekle, eksik anahtarları tamamla
                    self._data = {**DEFAULT_CONFIG, **loaded}
                except Exception:
                    self._data = DEFAULT_CONFIG.copy()
            else:
                self._data = DEFAULT_CONFIG.copy()

    def save(self):
        with self._lock:
            os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
            tmp_path = f"{self.config_path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
            os.replace(tmp_path, self.config_path)

    # ------------------------------------------------------------------
    def get(self, key: str, default: Any = None) -> Any:
        with self._lock:
            return self._data.get(key, default)

    def set(self, key: str, value: Any):
        with self._lock:
            self._data[key] = value
            self.save()
