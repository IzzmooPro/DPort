"""
main.py — DPort giriş noktası.
- Tek örnek: ikinci kez çalıştırılırsa açık olanı öne getirir (çift çalıştırma engeli).
- Yönetici hakları yoksa UAC ile yükseltir.
- Konsolsuz (pythonw / windowed exe) çalışırken beklenmeyen hataları MessageBox ile gösterir.
"""
import sys
import os
import ctypes
import socket

# Çalışan örnekle haberleşme — gui/app.py içindekiyle AYNI olmalı.
IPC_HOST = "127.0.0.1"
IPC_PORT = 49317
MUTEX_NAME = "DPort_SingleInstance_v1"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate():
    """Mevcut süreci yönetici olarak yeniden başlatır."""
    params = (" ".join(f'"{a}"' for a in sys.argv[1:])
              if getattr(sys, "frozen", False)
              else " ".join(f'"{a}"' for a in sys.argv))
    ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)


def signal_existing() -> bool:
    """Zaten çalışan bir örnek varsa ona 'kendini göster' de. Varsa True döner."""
    try:
        with socket.create_connection((IPC_HOST, IPC_PORT), timeout=1.5) as s:
            s.sendall(b"SHOW")
        return True
    except OSError:
        return False


def acquire_mutex():
    """Atomik tek-örnek kilidi. (zaten_calisiyor, handle) döndürür."""
    try:
        k = ctypes.windll.kernel32
        h = k.CreateMutexW(None, False, MUTEX_NAME)
        return (k.GetLastError() == 183), h  # 183 = ERROR_ALREADY_EXISTS
    except Exception:
        return False, None


def fatal(msg: str):
    try:
        ctypes.windll.user32.MessageBoxW(None, msg, "DPort — Hata", 0x10)
    except Exception:
        pass


_mutex_handle = None  # süreç ömrü boyunca canlı kalmalı

if __name__ == "__main__":
    base_dir = os.path.dirname(os.path.abspath(__file__))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)

    # Güvenlik ağı: logon görevi bu bayrakla çağırır. Sadece hosts bloğunu
    # temizle ve çık (arayüz açma). Görev yüksek yetkiyle çalıştığı için yazma izni var.
    if "--cleanup-hosts" in sys.argv:
        try:
            from core.discord_unblock import remove_hosts_redirect
            remove_hosts_redirect()
        except Exception:
            pass
        sys.exit(0)

    # 1) UAC'siz ön-kontrol: uygulama zaten açıksa onu öne getir ve çık.
    if signal_existing():
        sys.exit(0)

    # 2) Yönetici değilse yükselt.
    if not is_admin():
        elevate()
        sys.exit(0)

    # 3) Atomik kilit — hızlı çift tıklama yarışlarına karşı son savunma.
    _already, _mutex_handle = acquire_mutex()
    if _already:
        signal_existing()
        sys.exit(0)

    # Görev çubuğu kimliği — ikonun python yerine DPort ikonu olarak görünmesi için.
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DPort.App")
    except Exception:
        pass

    try:
        from gui.app import DPortApp
        app = DPortApp()
        app.mainloop()
    except Exception:
        import traceback
        tb = traceback.format_exc()
        try:
            base = os.environ.get("APPDATA") or os.path.expanduser("~")
            p = os.path.join(base, "DPort", "crash.log")
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "a", encoding="utf-8") as f:
                f.write(tb + "\n")
        except Exception:
            pass
        fatal("Beklenmeyen bir hata oluştu:\n\n" + (tb.strip().splitlines() or ["?"])[-1])
        sys.exit(1)
