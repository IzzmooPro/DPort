"""
core/startup_manager.py
Windows kayıt defteri üzerinden başlangıç kaydı oluşturur/siler.
"""
import sys
import os

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False

APP_NAME = "DPort"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_exe_path() -> str:
    """Çalışan EXE veya betik yolunu döndürür."""
    if getattr(sys, "frozen", False):
        return sys.executable  # PyInstaller EXE
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}"'


def enable_startup() -> bool:
    if not _HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, _get_exe_path())
        return True
    except Exception as e:
        print(f"[Startup] Etkinleştirme hatası: {e}")
        return False


def disable_startup() -> bool:
    if not _HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, APP_NAME)
        return True
    except FileNotFoundError:
        return True  # Zaten yoktu
    except Exception as e:
        print(f"[Startup] Devre dışı bırakma hatası: {e}")
        return False


def is_startup_enabled() -> bool:
    if not _HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
            return bool(val)
    except FileNotFoundError:
        return False
    except Exception:
        return False
