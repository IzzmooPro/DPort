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
# DPort'a özgü istek/yanıt. Yalnızca porta bağlanabilmek YETMEZ: 49317'yi başka
# bir program tutuyorsa (ya da bir port tarayıcı bağlantı kabul ediyorsa) DPort
# çalışıyor sanılıp açılış sessizce iptal edilirdi. Bu yüzden sunucu tam ve
# geçerli isteğe sabit bir ACK döner; istemci ACK'i doğrulamadan var saymaz.
IPC_MAGIC = b"DPORT-IPC-1"
IPC_REQUEST = IPC_MAGIC + b" SHOW\n"
IPC_ACK = IPC_MAGIC + b" OK\n"
IPC_TIMEOUT = 1.5
MUTEX_NAME = "DPort_SingleInstance_v1"


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def elevate() -> bool:
    """Mevcut süreci yönetici olarak yeniden başlatır.

    Dönüş: yükseltme BAŞLATILABİLDİ mi. ShellExecuteW 32'den küçük/eşit bir
    değer döndürürse işlem BAŞARISIZDIR (örn. kullanıcı UAC'yi reddetti ->
    SE_ERR_ACCESSDENIED = 5). Eskiden dönüş değeri yok sayılıyordu; yükseltme
    başarısız olsa bile süreç 0 koduyla, hiçbir şey olmamış gibi kapanıyordu."""
    params = (" ".join(f'"{a}"' for a in sys.argv[1:])
              if getattr(sys, "frozen", False)
              else " ".join(f'"{a}"' for a in sys.argv))
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", sys.executable, params, None, 1)
        return int(rc) > 32
    except Exception:
        return False


def signal_existing() -> bool:
    """Çalışan bir DPort örneği varsa ona 'kendini göster' der.

    Yalnızca doğru ACK alınırsa True döner. Bağlantıyı kabul eden ama DPort
    olmayan bir dinleyici False verir ve normal açılış sürer.

    İstek yazıldıktan sonra yazma tarafı kapatılır: sunucu bunu mesaj sonu
    (EOF) olarak görür ve fazladan bayt gönderilmediğini kesin olarak
    doğrulayabilir (bkz. gui/app.py serve_ipc_connection)."""
    try:
        with socket.create_connection((IPC_HOST, IPC_PORT), timeout=IPC_TIMEOUT) as s:
            s.settimeout(IPC_TIMEOUT)
            s.sendall(IPC_REQUEST)
            s.shutdown(socket.SHUT_WR)   # mesaj çerçevesi: istek bitti
            ack = b""
            while len(ack) < len(IPC_ACK):
                chunk = s.recv(len(IPC_ACK) - len(ack))
                if not chunk:
                    break
                ack += chunk
        return ack == IPC_ACK
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

    # Güvenlik ağı: logon görevi bu bayrakla çağırır. YALNIZCA işaretli
    # DPort/legacy hosts bloğunu temizler ve görevin kendisini düşürür; arayüz
    # AÇMAZ, DNS'e dokunmaz, röle/Discord/tek-örnek kodunu yüklemez.
    #
    # Görev kalıcı değildir: hosts yönlendirmesi gerçekten kalktığında bu göreve
    # de gerek kalmaz, bu yüzden kendini kaldırır. Temizlik doğrulanamazsa görev
    # KORUNUR ki bir sonraki logon'da yeniden denensin.
    #
    # Çıkış kodları:
    #   0 = hosts temizliği DOĞRULANDI ve görev(ler) uzlaştırıldı (kaldırıldı)
    #   1 = hosts temizlenemedi -> göreve DOKUNULMADI (yeniden denenecek)
    #   2 = hosts temizlendi fakat görev KONTROLLÜ biçimde kaldırılamadı
    #   3 = beklenmeyen istisna (hangi adımda olursa olsun)
    if "--cleanup-hosts" in sys.argv:
        def _note(text):
            """Konsolsuz derlemede stdout olmayabilir; sessizce geç."""
            try:
                if sys.stdout is not None:
                    print(text, flush=True)
            except Exception:
                pass

        try:
            try:
                from core.discord_unblock import remove_hosts_redirect
                hosts_cleared = bool(remove_hosts_redirect())
            except Exception as exc:
                # hosts durumu BİLİNMİYOR: yönlendirme duruyor olabilir, bu
                # yüzden göreve dokunulmaz (kod 1, kod 3 değil).
                _note(f"HOSTS_CLEANUP_ERROR {exc} TASK_NOT_TOUCHED")
                sys.exit(1)

            if not hosts_cleared:
                _note("HOSTS_CLEANUP_FAILED TASK_NOT_TOUCHED")
                sys.exit(1)

            # Görev yaşam döngüsünün TEK karar noktası; burada hosts temizliği
            # doğrulandığı için sonuç "tüm görev adlarını kaldır"dır.
            from core.failsafe import reconcile_failsafe_task, last_failsafe_error
            if reconcile_failsafe_task(True):
                _note("HOSTS_CLEANED TASK_REMOVED")
                sys.exit(0)
            _note(f"HOSTS_CLEANED TASK_REMOVE_FAILED {last_failsafe_error()}")
            sys.exit(2)
        except SystemExit:
            raise
        except BaseException as exc:
            _note(f"CLEANUP_UNEXPECTED_ERROR {exc}")
            sys.exit(3)

    # 1) UAC'siz ön-kontrol: uygulama zaten açıksa onu öne getir ve çık.
    if signal_existing():
        sys.exit(0)

    # 2) Yönetici değilse yükselt. Yükseltme başarısızsa (UAC reddedildi vb.)
    # sessizce kapanma: kullanıcı neden hiçbir şey olmadığını anlamalı.
    if not is_admin():
        if not elevate():
            fatal("DPort yönetici izniyle başlatılamadı.\n\n"
                  "Yönetici onayı verilmediyse tekrar deneyip “Evet” seçin.\n"
                  "DPort, DNS ve hosts ayarlarını değiştirdiği için bu izin "
                  "olmadan çalışamaz.")
            sys.exit(1)
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
