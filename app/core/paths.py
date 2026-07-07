"""
core/paths.py
Kaynak kod ve PyInstaller EXE calisma modlari icin ortak dosya yollari.
"""
import os
import shutil
import sys


APP_NAME = "DPort"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def app_dir() -> str:
    """Kaynak kodda app/ klasorunu dondurur."""
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resource_dir() -> str:
    """
    Paketlenmis EXE'de PyInstaller kaynak klasoru, kaynak kodda app/ klasoru.
    Build script data ve assets klasorlerini EXE kaynak kokune ekliyor.
    """
    if is_frozen():
        return getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    return app_dir()


def resource_path(*parts: str) -> str:
    return os.path.join(resource_dir(), *parts)


def user_data_dir() -> str:
    """
    Kaynak kodla calisirken mevcut app/data davranisini korur.
    EXE'de ise kalici ve kullaniciya ozel AppData klasorunu kullanir.
    """
    if not is_frozen():
        return os.path.join(app_dir(), "data")

    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_NAME)


def user_data_path(*parts: str) -> str:
    return os.path.join(user_data_dir(), *parts)


def ensure_user_data_file(filename: str) -> str:
    """
    Kullanici veri dosyasi yoksa paket/kaynak icindeki varsayilan dosyadan kopyalar.
    Dosya yoksa sadece klasoru hazirlar ve hedef yolu dondurur.
    """
    dst = user_data_path(filename)
    os.makedirs(os.path.dirname(dst), exist_ok=True)

    if os.path.exists(dst):
        return dst

    src = resource_path("data", filename)
    if os.path.exists(src) and os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy2(src, dst)

    return dst
