"""
core/startup_manager.py
Windows kayıt defteri üzerinden başlangıç kaydı oluşturur/siler.
"""
import os
import subprocess
import sys

try:
    import winreg
    _HAS_WINREG = True
except ImportError:
    _HAS_WINREG = False

APP_NAME = "DPort"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def _get_exe_path() -> str:
    """Başlangıç kaydına yazılacak komut satırı.

    Tırnaklama Windows kurallarına göre `subprocess.list2cmdline` ile yapılır.
    Frozen EXE eskiden TIRNAKSIZ yazılıyordu; `C:\\Program Files\\DPort\\DPort.exe`
    gibi boşluklu bir yol Windows tarafından `C:\\Program` + argümanlar diye
    ayrıştırılır ve başlangıç sessizce çalışmaz."""
    if getattr(sys, "frozen", False):
        return subprocess.list2cmdline([sys.executable])
    return subprocess.list2cmdline([sys.executable, os.path.abspath(sys.argv[0])])


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
    """Başlangıç kaydı VAR MI değil, GÜNCEL beklenen komutla EŞLEŞİYOR MU.

    Yalnızca "değer dolu mu" bakmak yanıltıcıydı: eski bir sürümün yazdığı
    tırnaksız/bozuk ya da artık var olmayan bir konumu gösteren kayıt da
    "etkin" görünüyordu. Böyle bir kayıtta ayar açık sanılır ama Windows
    programı başlangıçta gerçekte çalıştıramaz."""
    if not _HAS_WINREG:
        return False
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_READ
        ) as key:
            val, _ = winreg.QueryValueEx(key, APP_NAME)
    except FileNotFoundError:
        return False
    except Exception:
        return False

    if not val:
        return False
    # Windows yolları büyük/küçük harf duyarsızdır; kayıt boşlukla yazılmış olabilir.
    return os.path.normcase(str(val).strip()) == os.path.normcase(_get_exe_path())
