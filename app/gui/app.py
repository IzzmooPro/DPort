"""
gui/app.py
Discord Baglanti — Turkiye'deki Discord SNI/DPI engelini asan, Discord'a ozel
tek pencerelik arac. Tek tik: DNS (1.1.1.1) + yerel parcalayici role.
DPort Discord'u baslatmaz; kullanici Discord'u diledigi zaman kendi acar.
Durum panosu ile canli geri bildirim.
"""
import os
import sys
import time
import atexit
import socket
import threading
import subprocess
import ctypes
import customtkinter as ctk

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.adapter_manager import get_active_adapters, get_all_adapters
from core.dns_manager import set_dns, restore_dns, get_dns, normalize_snapshot
from core.config_manager import ConfigManager
from core.discord_manager import (
    get_discord_update_status,
    discord_restart_required,
    installed_discord_version,
    running_discord_version,
)
from core.discord_unblock import (
    DiscordUnblocker,
    add_hosts_redirect,
    remove_hosts_redirect,
    is_hosts_redirect_active,
    last_hosts_error,
    last_hosts_winerror,
    last_hosts_retry_info,
)
from core.failsafe import (
    install_logon_failsafe,
    reconcile_failsafe_task,
    verified_failsafe_target,
    last_failsafe_error,
)
from core.log_manager import LogManager
from core.startup_manager import enable_startup, disable_startup, is_startup_enabled
from core.lang import L, set_lang, current_lang
from core.paths import resource_path, user_data_path
from core.app_info import (
    APP_EMAIL,
    APP_NAME,
    APP_VERSION,
    GITHUB_RELEASES_URL,
)
from core import secure_store
from core.update_check import UpdateCheckController
from core.updater import (
    UpdateError,
    check_latest_release,
    download_update,
    launch_verified,
    purge_setup_dir,
)

# ── Tema — TEK KOYU tema (scalar hex; light/dark tuple YOK) ──────────────────
# DPort tek temali: her acilista ayni koyu tasarim. Windows temasi okunmaz/takip
# edilmez. Katmanlar (zemin < kart < yukseltilmis < hover) notr ton farki + ince
# border ile ayrisir; blurple YALNIZ ana eylem/odak icin kullanilir.
BG            = "#0c111b"   # ana zemin (duz siyah degil)
CARD          = "#121926"   # yuzey (kart)
CARD2         = "#182233"   # yukseltilmis yuzey / switch zemini / araç çubuğu
HOVER         = "#202c3f"   # hover katmani (ikincil yuzeyler)
BORDER        = "#2a3648"   # ince kenarlik
BORDER_STRONG = "#3a4960"   # belirgin kenarlik (odak karti)
TEXT          = "#f3f6fb"   # ana metin
SUB           = "#cbd5e1"   # ikincil metin
MUTED         = "#94a3b8"   # soluk / etiket
DISABLED      = "#697586"   # pasif (disabled) metin


def _source_dev_mode() -> bool:
    """Calistir.bat ile acilan yerel kaynak testini ayirt eder.

    Paketlenmis uygulama bu bayragi bilerek yok sayar: uretimde hosts yazmadan
    once dogrulanmis kurulu kurtarma hedefi her zaman zorunludur.
    """
    return (not getattr(sys, "frozen", False)
            and "--source-dev" in sys.argv)
BLURPLE       = "#5865f2"   # ana aksan (yalniz ana eylem/odak)
BLURPLE_H     = "#4752c4"   # hover
BLURPLE_L     = "#aeb8ff"   # aksan / link metni
GREEN         = "#3fb950"   # olumlu durum (success)
RED           = "#ff7b72"   # olumsuz durum (danger)
YELL          = "#d29922"   # uyari / orta gecikme (warning)
WHITE         = "#ffffff"   # aksan buton metni
SWITCH_OFF    = "#343a46"   # kapali track (koyu)
SWITCH_BORDER = "#4b5563"   # track kenarligi (kapaliyken de gorunur)
SWITCH_KNOB   = "#f8fafc"   # dugme (acik)
SWITCH_KNOB_H = "#ffffff"   # dugme hover
DANGER_HOVER  = "#5a2027"   # danger hover yuzeyi (uzerindeki metin okunur kalir)

# ── Header (CTkCanvas manuel cizim) — tek koyu, cok hafif gradient ───────────
HEADER_BG    = "#151a2e"                          # canvas bg (anti-flash) = gradientin koyu ucu
HDR_GRAD     = ["#151a2e", "#1a2140", "#202a55"]  # cok hafif gradient bant
HDR_VERSION  = "#aeb8ff"                          # surum metni
HDR_PILL_BG  = "#101624"                          # yonetici pill zemini + keyhole
HDR_ACCENT   = "#5865f2"                          # alt aksan cizgisi (blurple)
HDR_ADMIN_OK = "#7ee2a8"                          # yonetici olumlu (pill uzerinde yuksek kontrast)
HDR_ADMIN_NO = "#ffb3b6"                          # yonetici olumsuz

_FALLBACK_FONT = "Segoe UI"
_INTER_FONT_FILES = ("Inter-Regular.ttf", "Inter-Bold.ttf")
_FR_PRIVATE = 0x10


def _load_private_ui_font() -> str:
    """Load bundled Inter faces for this process, with a safe system fallback."""
    if os.name != "nt":
        return _FALLBACK_FONT

    loaded = []
    try:
        add_font = ctypes.windll.gdi32.AddFontResourceExW
        add_font.argtypes = [ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_void_p]
        add_font.restype = ctypes.c_int

        for filename in _INTER_FONT_FILES:
            path = os.path.abspath(resource_path("assets", "fonts", filename))
            if not os.path.isfile(path) or add_font(path, _FR_PRIVATE, None) == 0:
                raise OSError(f"Could not load bundled font: {filename}")
            loaded.append(path)
    except Exception:
        # Avoid leaving only one face registered if the second load fails.
        try:
            remove_font = ctypes.windll.gdi32.RemoveFontResourceExW
            for path in loaded:
                remove_font(path, _FR_PRIVATE, None)
        except Exception:
            pass
        return _FALLBACK_FONT

    return "Inter"


FONT = _load_private_ui_font()


def _verify_ui_font():
    """AddFontResourceEx basarili olsa bile Tk fontu gercekten cozemeyebilir
    (nadir). Bir Tk koku olustuktan SONRA cagirilir; FONT Tk tarafindan
    gorulmuyorsa guvenli sekilde Segoe UI'ye doner. Boylece 'erisim basarisiz'
    durumunda da fallback garanti olur."""
    global FONT
    if FONT == _FALLBACK_FONT:
        return
    try:
        from tkinter import font as tkfont
        if FONT not in tkfont.families():
            FONT = _FALLBACK_FONT
    except Exception:
        FONT = _FALLBACK_FONT


def _f(size: int, weight: str = "normal") -> "ctk.CTkFont":
    return ctk.CTkFont(FONT, size, weight)


def _apply_win_icon(win):
    """Alt pencerelerin baslik cubugu/gorev cubugu ikonunu DPort yapar.
    CTkToplevel ikonu ~200ms sonra ezebildigi icin bir kez de gecikmeli uygular."""
    try:
        ico = resource_path("assets", "icon.ico")
        if os.path.exists(ico):
            win.iconbitmap(ico)
            win.after(300, lambda: win.iconbitmap(ico))
    except Exception:
        pass


def _place_beside(app, win, w: int, h: int):
    """Alt pencereyi ana pencerenin sag kenarina BITISIK, ALT KENARI ana
    pencereyle ayni hizada yerlestirir. Ekran sagina sigmiyorsa sola gecirir."""
    try:
        app.update_idletasks()
        x = app.winfo_x() + app.winfo_width()
        if x + w > win.winfo_screenwidth():          # saga sigmazsa sola
            x = max(0, app.winfo_x() - w)
        y = app.winfo_y() + app.winfo_height() - h   # alt kenari ana pencereyle hizala
        y = max(0, min(y, win.winfo_screenheight() - h))
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        win.geometry(f"{w}x{h}")


def _place_beside_top(app, win, w, h):
    """Alt pencereyi ana pencerenin sag kenarina bitisik, UST kenari ana
    pencereyle hizali yerlestirir. Sabitlemek icin (x, y) dondurur."""
    try:
        app.update_idletasks()
        x = app.winfo_x() + app.winfo_width()
        if x + w > win.winfo_screenwidth():          # saga sigmazsa sola
            x = max(0, app.winfo_x() - w)
        y = app.winfo_y()                            # ust kenari ana pencereyle hizala
        y = max(0, min(y, win.winfo_screenheight() - h))
        win.geometry(f"{w}x{h}+{x}+{y}")
        return x, y
    except Exception:
        win.geometry(f"{w}x{h}")
        return None


class _WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", ctypes.c_void_p),
        ("hwndInsertAfter", ctypes.c_void_p),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", ctypes.c_uint),
    ]


_WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint,
                              ctypes.c_void_p, ctypes.c_void_p)
_GWLP_WNDPROC = -4
_WM_WINDOWPOSCHANGING = 0x0046
_SWP_NOMOVE = 0x0002


def _freeze_window(win):
    """Pencereyi TASINAMAZ yapar. Hareketi kaynaginda engeller: her
    WM_WINDOWPOSCHANGING mesajina SWP_NOMOVE ekleyerek konum degisimini iptal
    eder. Boylece kullanici baslik cubugundan surukleyemez ve TITREME olmaz
    (eski 'tasindiktan sonra geri it' yontemi titriyordu)."""
    try:
        win.update()  # dondurmadan ONCE yerlestirme (geometry) tam uygulansin
        u = ctypes.windll.user32
        hwnd = u.GetParent(win.winfo_id()) or win.winfo_id()
        setp = getattr(u, "SetWindowLongPtrW", None) or u.SetWindowLongW
        setp.restype = ctypes.c_void_p
        setp.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_void_p]
        u.CallWindowProcW.restype = ctypes.c_ssize_t
        u.CallWindowProcW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint,
                                      ctypes.c_void_p, ctypes.c_void_p]
        state = {}

        @_WNDPROC
        def _proc(hWnd, msg, wParam, lParam):
            if (msg == _WM_WINDOWPOSCHANGING and lParam
                    and not getattr(win, "_allow_programmatic_move", False)):
                ctypes.cast(lParam, ctypes.POINTER(_WINDOWPOS)).contents.flags |= _SWP_NOMOVE
            return u.CallWindowProcW(state["old"], hWnd, msg, wParam, lParam)

        state["old"] = setp(hwnd, _GWLP_WNDPROC, ctypes.cast(_proc, ctypes.c_void_p))
        # Referanslari canli tut (GC WNDPROC'u toplarsa cokme olur)
        win._wndproc_ref = _proc
        win._old_wndproc = state["old"]
    except Exception:
        pass


def _dock_window(app, win, w: int, h: int, align_top: bool = True):
    """Yan pencereyi ana pencereye bitisik tutar.

    Kullanici yan pencereyi surukleyemez; ana pencere tasindiginda Configure
    olayi tek bir idle callback'e indirgenir ve yan pencere ayni kenara yeniden
    yerlestirilir. Ekranin saginda yer yoksa iki pencere birlikte sol kenardan
    baglanir. Destroy sirasinda bind/after temizlenir.
    """
    place = _place_beside_top if align_top else _place_beside
    place(app, win, w, h)
    _freeze_window(win)

    state = {"after": None, "moving": False}

    def _move_with_parent():
        state["after"] = None
        try:
            if not win.winfo_exists():
                return
            state["moving"] = True
            win._allow_programmatic_move = True
            place(app, win, w, h)
            win.update_idletasks()
        except Exception:
            pass
        finally:
            win._allow_programmatic_move = False
            state["moving"] = False

    def _schedule_move(event=None):
        if event is not None and event.widget is not app:
            return
        if state["moving"] or state["after"] is not None:
            return
        try:
            state["after"] = app.after_idle(_move_with_parent)
        except Exception:
            state["after"] = None

    bind_id = app.bind("<Configure>", _schedule_move, add="+")

    def _cleanup(event):
        if event.widget is not win:
            return
        try:
            if state["after"] is not None:
                app.after_cancel(state["after"])
        except Exception:
            pass
        try:
            app.unbind("<Configure>", bind_id)
        except Exception:
            pass
        state["after"] = None

    win.bind("<Destroy>", _cleanup, add="+")
    win._dock_refs = (_schedule_move, _move_with_parent, _cleanup)

# Discord acilirken sistem DNS'i bu degerlere ayarlanir (Cloudflare)
DNS_V4 = ("1.1.1.1", "1.0.0.1")
DNS_V6 = ("2606:4700:4700::1111", "2606:4700:4700::1001")

# Tek-ornek IPC — main.py ile AYNI olmali. Ikinci calistirma bu porta baglanip
# DPort'a ozgu istegi gonderir; calisan ornek ACK doner ve kendini one getirir.
IPC_HOST = "127.0.0.1"
IPC_PORT = 49317
IPC_MAGIC = b"DPORT-IPC-1"
IPC_REQUEST = IPC_MAGIC + b" SHOW\n"
IPC_ACK = IPC_MAGIC + b" OK\n"
IPC_TIMEOUT = 1.5

# Eski updater yordamları artık GUI akışından çağrılmıyor; bağımsız çekirdek
# testleriyle uyumluluk için sabitleri burada tutuyoruz.
UPD_IDLE_TIMEOUT = 90
UPD_HARD_LIMIT = 600
UPD_POLL = 5

def serve_ipc_connection(conn) -> bool:
    """Tek bir IPC baglantisini isler.

    Donus: TAM ve gecerli SHOW istegi alindi mi. Yalnizca bu durumda sabit ACK
    gonderilir; eksik/yanlis/fazla payload sessizce reddedilir. Boylece bir port
    taramasi veya ilgisiz bir istemci pencereyi one getiremez. Zaman asimi
    sinirlidir; yavas/asili bir istemci dinleyiciyi kilitleyemez.

    MESAJ CERCEVESI: istemci istegi yazdiktan sonra yazma tarafini kapatir
    (shutdown SHUT_WR); sunucu EOF'a kadar okur. Kapasite bilerek
    len(IPC_REQUEST) + 1'dir: bir bayt bile FAZLA veri gelirse istek
    REDDEDILIR. Yalnizca len(IPC_REQUEST) kadar okuyup onek karsilastirmak
    `IPC_REQUEST + b"JUNK"` gibi bir payload'i GECERLI sayiyordu."""
    limit = len(IPC_REQUEST) + 1
    try:
        conn.settimeout(IPC_TIMEOUT)
        data = b""
        while len(data) < limit:
            chunk = conn.recv(limit - len(data))
            if not chunk:
                break                      # EOF -> mesaj tamamlandi
            data += chunk
        if data != IPC_REQUEST:            # eksik, farkli VEYA fazla -> RED
            return False
        conn.sendall(IPC_ACK)
        return True
    except OSError:
        return False


class DPortApp(ctk.CTk):
    VERSION = APP_VERSION

    def __init__(self):
        self.cfg = ConfigManager(user_data_path("config.json"))
        set_lang(self.cfg.get("language", "tr"))

        # DPort tek koyu temali: her acilista sabit koyu. Config'ten tema okunmaz,
        # Windows/System temasi takip edilmez.
        ctk.set_appearance_mode("dark")
        super().__init__()
        _verify_ui_font()   # Inter'e Tk gercekten erisebiliyor mu; degilse Segoe UI

        self.log_mgr = LogManager(
            user_data_path("dport.log"),
            enabled=self.cfg.get("log_enabled", True),
        )

        self._busy = False
        self._connecting = False    # "Discord'u Ac" akisi sirasinda hero "Baglaniyor..." kalir
        self._alive = True          # kapaninca False; arka plan thread'leri Tk'ye dokunmasin
        self._update_download_active = False
        self._update_checks = UpdateCheckController(
            check=lambda: check_latest_release(self.VERSION),
            schedule=self.after, cancel=self.after_cancel,
            deliver=self._deliver_update_check, log=self.log_mgr.write,
        )
        self._status_timer_id = None  # tek periyodik pano zinciri (after id)
        self._status_refreshing = False  # ayni anda tek yenileme thread'i
        self._status_refresh_pending = False  # meşgulken istenen son yenileme kaybolmasin
        self._status_generation = 0  # eski/yavas olcum yeni durumu ekranda ezmesin
        self._tray = None           # aktif tepsi ikonu (cift ikon onlemek icin)
        self._panel = None          # ayni anda tek alt pencere (ayarlar/log/yardim/hakkinda)
        self._active_since = None    # yol kesintisiz ne zamandir aktif (aktif sure)
        self._discord_update_phase = ""
        self._discord_update_notice_until = 0.0
        # DNS kurtarma yedegi ARTIK config.json'da tutulmaz (F4): kullanici-
        # yazilabilir bir dosyadaki deger, yonetici yetkili netsh'e girdi
        # olamaz. Kalici konum secure_store (ACL-korumali %ProgramData%\DPort);
        # orasi hazirlanamazsa yalnizca BELLEK ici yedek kullanilir (bellek de
        # saldirgan tarafindan degistirilemez, yalnizca cokme kurtarmasi kaybolur).
        self._dns_backup_mem = {}
        self._legacy_dns_backup = None
        self._unblocker = DiscordUnblocker(
            log=lambda m: self.log_mgr.console(f"unblock: {m}")
        )

        # Onceki oturumdan (cokme/zorla kapatma) kalmis olabilecek hosts
        # yonlendirmesini temizle; role kapaliyken bu satirlar Discord'u bozardi.
        # Temizlik DOGRULANIRSA failsafe gorevi de artik gereksizdir ve
        # kaldirilir: gorev yalnizca hosts yonlendirmesi olabilecegi surece
        # var olmalidir. Temizlik basarisizsa gorev KORLEMESINE korunmaz:
        # hedefi DOGRULANABILEN gorev korunur (bir sonraki logon'da yeniden
        # denesin), hedefi okunamayan/dogrulanamayan gorev KALDIRILIR.
        try:
            hosts_cleared = remove_hosts_redirect()
        except Exception as e:
            hosts_cleared = False
            self.log_mgr.console(
                f"failsafe: acilista hosts temizligi hata verdi: {e}", level="WARN")
        self._reconcile_failsafe_task(hosts_cleared, "acilis")
        # Eski surumden kalmis, KULLANICI-YAZILABILIR config.json icindeki DNS
        # yedegini once config'ten SOK (bir daha hicbir yol onu okuyamasin), sonra
        # ayri tut. Sessizce yonetici netsh'e GONDERILMEZ; arayuz acildiktan sonra
        # kullaniciya degerleriyle birlikte gosterilip ONAY istenir (bkz.
        # _offer_legacy_dns_restore).
        try:
            legacy = self.cfg.get("dns_backup")
            if legacy:
                self._legacy_dns_backup = legacy
            if legacy is not None:
                self.cfg.set("dns_backup", None)
        except Exception:
            self._legacy_dns_backup = None

        # Cokme kurtarma: onceki oturum DNS'i 1.1.1.1 yapip geri yuklemeden
        # kapandiysa (AYRICALIKLI state'te backup KALMISSA) sistem DNS'ini burada,
        # UI acilmadan ve kullanici etkilesimi baslamadan ONCE orijinaline dondur.
        # Bu veri yalnizca yukseltilmis surecin yazabildigi bir konumda tutuldugu
        # icin otomatik uygulanmasi guvenlidir. Yedek yoksa hicbir sey yapmaz.
        try:
            if secure_store.load_dns_backup():
                self._restore_dns()
                self._flushdns()
        except Exception:
            pass
        atexit.register(self._disable_discord_unblock)

        self.log_mgr.console(f"{L['title']} v{self.VERSION} başlatıldı")

        self.title(f"{L['title']}")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.W, self.H = 348, 522
        w, h = self.W, self.H
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._apply_icon()
        self._build()
        self._fit_height()          # icerige gore yuksekligi otomatik ayarla (alt satir kesilmesin)
        self._status_tick()
        self._uptime_tick()         # aktif sure satiri saniye saniye aksin
        # Guvenlik agi: role beklenmedik sekilde olurse hosts'u aninda temizle.
        threading.Thread(target=self._watchdog_loop, daemon=True).start()
        # Tek-ornek dinleyici: ikinci calistirma bu pencereyi one getirir.
        self._start_ipc()
        # Eski, kullanici-yazilabilir indirme klasorundeki birikmis setup
        # dosyalarini temizle (yalniz DPort'un kendi ad kalibi).
        self.after(1000, self._purge_legacy_downloads)
        # Ilk acilis bilgilendirmesi kapatildiktan sonra diger baslangic
        # pencerelerini sirala; modal pencereler ust uste acilmasin.
        self.after(900, self._run_startup_prompts)

    def _fit_height(self):
        """Pencere yuksekligini icerigin GERCEK gereken yuksekligine esitler
        (hem buyutur hem kucultur; alt bosluk/kesilme olmaz). Genislik sabit."""
        try:
            self.update_idletasks()
            need = self.winfo_reqheight() + 6
            if need != self.H:
                self.H = need
                x = (self.winfo_screenwidth() - self.W) // 2
                y = (self.winfo_screenheight() - self.H) // 2
                self.geometry(f"{self.W}x{self.H}+{x}+{y}")
        except Exception:
            pass

    def _run_startup_prompts(self):
        """Baslangic bilgilendirmelerini birbirinin ustune bindirmeden siralar."""
        if not self.cfg.get("hide_antivirus_notice", False):
            dlg = _ModalDialog(
                self,
                L["av_notice_title"],
                L["av_notice_msg"],
                confirm=False,
                ok_text=L["av_notice_ok"],
                checkbox_text=L["av_notice_hide"],
            )
            self.wait_window(dlg)
            if dlg.result and dlg.option_selected:
                self.cfg.set("hide_antivirus_notice", True)
        if not self._alive:
            return
        # Eski config yedegi varsa kullaniciya sor (asla sessizce uygulama).
        self.after(500, self._offer_legacy_dns_restore)
        self.after(1400, self._check_updates_on_start)

    # ─────────────────────────── Ikon / tek-ornek ───────────────────────────
    def _apply_icon(self):
        """Pencere + gorev cubugu ikonunu ayarlar. CTk ikonu ~200ms sonra kendi
        varsayilaniyla ezebildigi icin bir kez de gecikmeli uygulanir."""
        ico = resource_path("assets", "icon.ico")
        if not os.path.exists(ico):
            return
        self._icon_path = ico
        try:
            self.iconbitmap(ico)
        except Exception:
            pass
        self._set_crisp_icon()
        self.after(300, self._reapply_icon)

    def _reapply_icon(self):
        try:
            self.iconbitmap(getattr(self, "_icon_path", ""))
        except Exception:
            pass
        self._set_crisp_icon()

    def _set_crisp_icon(self):
        """Gorev cubugu ikonunu Windows'a DPI'a uygun boyutlarda (kucuk + buyuk)
        ELLE verir. Tk tek boyutu buyutup bulanik gosterebiliyor; WM_SETICON ile
        Windows ICO'dan istedigi boyutu net secer."""
        try:
            ico = getattr(self, "_icon_path", "")
            if not ico:
                return
            u = ctypes.windll.user32
            u.GetParent.restype = ctypes.c_void_p
            u.GetParent.argtypes = [ctypes.c_void_p]
            u.LoadImageW.restype = ctypes.c_void_p
            u.LoadImageW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint,
                                     ctypes.c_int, ctypes.c_int, ctypes.c_uint]
            u.SendMessageW.restype = ctypes.c_void_p
            u.SendMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint,
                                       ctypes.c_void_p, ctypes.c_void_p]
            hwnd = u.GetParent(self.winfo_id()) or self.winfo_id()
            IMAGE_ICON, LR_LOADFROMFILE, WM_SETICON = 1, 0x10, 0x80
            cx_s = u.GetSystemMetrics(49) or 16     # SM_CXSMICON
            cx_b = u.GetSystemMetrics(11) or 32     # SM_CXICON
            h_small = u.LoadImageW(None, ico, IMAGE_ICON, cx_s, cx_s, LR_LOADFROMFILE)
            h_big = u.LoadImageW(None, ico, IMAGE_ICON, cx_b, cx_b, LR_LOADFROMFILE)
            if h_small:
                u.SendMessageW(hwnd, WM_SETICON, 0, h_small)   # ICON_SMALL
            if h_big:
                u.SendMessageW(hwnd, WM_SETICON, 1, h_big)     # ICON_BIG
        except Exception:
            pass

    def _start_ipc(self):
        def listen():
            try:
                srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                srv.bind((IPC_HOST, IPC_PORT))
                srv.listen(5)
            except OSError:
                return
            self._ipc_srv = srv
            while True:
                try:
                    conn, _ = srv.accept()
                except OSError:
                    break
                show = serve_ipc_connection(conn)
                try:
                    conn.close()
                except OSError:
                    pass
                # Pencere YALNIZCA dogrulanmis istekte one getirilir.
                if show:
                    self.after(0, self._show_window)

        threading.Thread(target=listen, daemon=True).start()

    def _stop_tray(self):
        """Aktif tepsi ikonu varsa durdurur ve referansi temizler.
        Cift tepsi ikonunu onler (IPC/ikinci-ornek ile geri gelince de cagrilir)."""
        tray = getattr(self, "_tray", None)
        if tray is not None:
            try:
                tray.stop()
            except Exception:
                pass
            self._tray = None

    def _show_window(self):
        """Tepside/gizliyse pencereyi geri getirir ve one alir."""
        self._stop_tray()   # geri gelince tepsi ikonu kalmasin
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    # ─────────────── Tutarli monokrom ikonlar (emoji yerine) ───────────────
    def _ico(self, kind: str, color=MUTED, px: int = 16):
        """Tek koyu tema: scalar renkten monokrom ikon (PIL) cizip CTkImage olarak
        onbellekler."""
        cache = getattr(self, "_icon_cache", None)
        if cache is None:
            cache = self._icon_cache = {}
        k = (kind, color, px)
        if k not in cache:
            try:
                im = self._draw_icon_image(kind, color, px)
                cache[k] = ctk.CTkImage(light_image=im, dark_image=im, size=(px, px))
            except Exception:
                cache[k] = None
        return cache[k]

    @staticmethod
    def _draw_icon_image(kind: str, color: str, px: int):
        """Tek renk hex ile bir monokrom ikonu PIL Image olarak cizer (5x cizip
        CTkImage kuculterek keskinlestirir)."""
        import math
        from PIL import Image, ImageDraw
        S = px * 5
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        w = max(2, round(S * 0.075))
        pad = S * 0.16
        cx = cy = S / 2

        if kind == "tile":                            # surum
            d.rounded_rectangle([pad, pad, S - pad, S - pad], radius=S * 0.20,
                                outline=rgb, width=w)
            d.ellipse([cx - S * 0.07, cy - S * 0.07, cx + S * 0.07, cy + S * 0.07], fill=rgb)
        elif kind == "globe":                         # DNS
            d.ellipse([pad, pad, S - pad, S - pad], outline=rgb, width=w)
            d.line([pad, cy, S - pad, cy], fill=rgb, width=w)
            rx = (S - 2 * pad) * 0.28
            d.ellipse([cx - rx, pad, cx + rx, S - pad], outline=rgb, width=w)
        elif kind == "unlock":                        # acilan sunucular
            d.rounded_rectangle([S * 0.30, S * 0.50, S * 0.70, S * 0.82],
                                radius=S * 0.07, outline=rgb, width=w)
            d.ellipse([cx - S * 0.035, cy + S * 0.09, cx + S * 0.035, cy + S * 0.16], fill=rgb)
            d.arc([S * 0.33, S * 0.22, S * 0.60, S * 0.56], start=150, end=360, fill=rgb, width=w)
        elif kind == "gear":                          # ayarlar
            R = S * 0.24
            for a in range(0, 360, 45):
                rad = math.radians(a)
                d.line([cx + math.cos(rad) * R, cy + math.sin(rad) * R,
                        cx + math.cos(rad) * (R + S * 0.12), cy + math.sin(rad) * (R + S * 0.12)],
                       fill=rgb, width=w + 1)
            d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=rgb, width=w)
            d.ellipse([cx - S * 0.08, cy - S * 0.08, cx + S * 0.08, cy + S * 0.08], outline=rgb, width=w)
        elif kind == "list":                          # log
            for yy in (0.34, 0.50, 0.66):
                y = S * yy
                d.ellipse([S * 0.21, y - S * 0.03, S * 0.27, y + S * 0.03], fill=rgb)
                d.line([S * 0.36, y, S * 0.76, y], fill=rgb, width=w)
        elif kind == "help":                          # sorun giderme
            d.ellipse([pad, pad, S - pad, S - pad], outline=rgb, width=w)
            d.arc([S * 0.38, S * 0.30, S * 0.62, S * 0.54], start=150, end=390, fill=rgb, width=w)
            d.line([cx, S * 0.52, cx, S * 0.60], fill=rgb, width=w)
            d.ellipse([cx - S * 0.032, S * 0.66, cx + S * 0.032, S * 0.66 + S * 0.064], fill=rgb)
        elif kind == "info":                          # hakkinda
            d.ellipse([pad, pad, S - pad, S - pad], outline=rgb, width=w)
            d.ellipse([cx - S * 0.035, S * 0.30, cx + S * 0.035, S * 0.30 + S * 0.07], fill=rgb)
            d.line([cx, S * 0.46, cx, S * 0.70], fill=rgb, width=w)
        elif kind == "clock":                         # aktif sure
            d.ellipse([pad, pad, S - pad, S - pad], outline=rgb, width=w)
            d.line([cx, cy, cx, cy - S * 0.24], fill=rgb, width=w)   # dakika ibresi
            d.line([cx, cy, cx + S * 0.17, cy], fill=rgb, width=w)   # saat ibresi
        return im

    @staticmethod
    def _lock_photo(color: str, px: int, bg_hex: str = "#11151f"):
        """Yonetici pill'i icin kucuk, DOLU kilit (canvas'a create_image ile konur;
        boylece emoji hizasizligi olmaz, tam ortali/orantili durur). Keyhole zemini
        pill zeminine (bg_hex) esitlenir; boylece tema degisince oyulmus gorunur."""
        from PIL import Image, ImageDraw, ImageTk
        S = px * 6
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        kb = tuple(int(bg_hex[i:i + 2], 16) for i in (1, 3, 5)) + (255,)  # keyhole = pill zemini
        im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        d = ImageDraw.Draw(im)
        sw = max(2, round(S * 0.12))
        d.arc([S * 0.30, S * 0.14, S * 0.70, S * 0.56], start=180, end=360, fill=rgb, width=sw)
        d.line([S * 0.335, S * 0.34, S * 0.335, S * 0.49], fill=rgb, width=sw)
        d.line([S * 0.665, S * 0.34, S * 0.665, S * 0.49], fill=rgb, width=sw)
        d.rounded_rectangle([S * 0.22, S * 0.46, S * 0.78, S * 0.84], radius=S * 0.12, fill=rgb)
        d.ellipse([S * 0.44, S * 0.56, S * 0.56, S * 0.68], fill=kb)
        d.rectangle([S * 0.47, S * 0.62, S * 0.53, S * 0.76], fill=kb)
        im = im.resize((px, px), Image.LANCZOS)
        return ImageTk.PhotoImage(im)

    # ─────────────────────────── Arayuz ───────────────────────────
    def _build(self):
        # 1) Degradeli baslik bandi (tam genislik, logo + baslik + yonetici pill)
        self._build_header()

        # 2) Govde
        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True, padx=12, pady=(9, 8))

        # HERO — buyuk, sade baglanti durum karti.
        self.hero = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16,
                                 border_width=1, border_color=BORDER)
        self.hero.pack(fill="x", pady=(0, 7))
        h = ctk.CTkFrame(self.hero, fg_color="transparent")
        h.pack(fill="x", padx=17, pady=10)
        h.grid_columnconfigure(1, weight=1)

        # Alt aciklama satirlari kaldirildi: yalnizca durum basligi ve nokta.
        self.hero_dot = ctk.CTkLabel(h, text="●", font=_f(24), text_color=MUTED)
        self.hero_dot.grid(row=0, column=0, padx=(0, 13))
        self.hero_state = ctk.CTkLabel(h, text=L["hero_off"], font=_f(16, "bold"),
                                       text_color=SUB, anchor="w")
        self.hero_state.grid(row=0, column=1, sticky="w")

        # Bilgi alani — 2x2 mini-kart grid (tek duz blok yerine ritimli KPI
        # kartlari). Sira KESIN: [Surum | DNS] ust, [Sunucular | Aktif Sure] alt.
        # Her kart: ust = ikon + etiket (muted), alt = dinamik deger (bold).
        grid = ctk.CTkFrame(body, fg_color="transparent")
        grid.pack(fill="x")
        grid.grid_columnconfigure(0, weight=1, uniform="cell")
        grid.grid_columnconfigure(1, weight=1, uniform="cell")

        self.dash = {}
        cells = [
            (0, 0, "version", "tile",   L["dash_version"]),
            (0, 1, "dns",     "globe",  L["dash_dns"]),
            (1, 0, "servers", "unlock", L["dash_servers"]),
            (1, 1, "uptime",  "clock",  L["dash_uptime"]),
        ]
        for row, col, key, icon, label in cells:
            cell = ctk.CTkFrame(grid, fg_color=CARD, corner_radius=12,
                                border_width=1, border_color=BORDER_STRONG, height=68)
            cell.grid(row=row, column=col, sticky="nsew",
                      padx=(0, 4) if col == 0 else (4, 0),
                      pady=(0, 4) if row == 0 else (4, 0))
            cell.pack_propagate(False)   # tum kartlar esit yukseklikte kalir
            # Icerik kart icinde yatay+dikey ORTALI (expand'li ic cerceve).
            inner = ctk.CTkFrame(cell, fg_color="transparent")
            inner.pack(expand=True, padx=10)
            ctk.CTkLabel(
                inner, image=self._ico(icon, MUTED, 18), text=f"  {label}",
                compound="left", font=_f(10), text_color=MUTED, anchor="center",
            ).pack(anchor="center")
            # Deger: uzun metin (or. Acilan Sunucular degeri) dar kartta 2 satira
            # sarar; metin degismez, kirpma olmaz. 'servers' biraz kucuk font.
            val = ctk.CTkLabel(
                inner, text=L["val_none"],
                font=_f(11, "bold") if key == "servers" else _f(13, "bold"),
                text_color=TEXT, anchor="center", justify="center",
                # servers: kompakt metin tek satira sigsin (sarma esigi genis);
                # digerleri: uzun deger (or. 'Discord kurulu degil') 2 satira sarabilsin.
                wraplength=145 if key == "servers" else 122,
            )
            val.pack(anchor="center", pady=(2, 0))
            self.dash[key] = val

        # Tek durum butonu: kapaliyken yolu etkinlestirir, acikken DPort'un
        # yaptigi degisiklikleri varsayilana dondurur. Discord'u kullanici
        # kendi baslatir.
        BTN_H = 42
        btnrow = ctk.CTkFrame(body, fg_color="transparent")
        btnrow.pack(fill="x", pady=(9, 0))
        btnrow.grid_columnconfigure(0, weight=1)
        self._connection_action_mode = "activate"

        self.btn_open = ctk.CTkButton(
            btnrow, text=L["btn_activate"], height=BTN_H, corner_radius=12,
            fg_color=BLURPLE, hover_color=BLURPLE_H, text_color=WHITE,
            border_width=1, border_color=BLURPLE,
            font=_f(13, "bold"), command=self._handle_connection_action,
        )
        self.btn_open.grid(row=0, column=0, sticky="ew")

        # Footer — butonlarin hemen altinda. Ikonlar ORTALI (grup halinde),
        # durum yazisi en altta ortali. Bosluklar dengeli.
        bot = ctk.CTkFrame(body, fg_color="transparent")
        bot.pack(fill="x", pady=(0, 0))

        # Ikonlar — fill YOK; frame icerige gore kuculup yatayda ortalanir.
        # Daha belirgin: buyuk kutu + parlak (TEXT) ikon + kalin cizgi (px=20).
        iconrow = ctk.CTkFrame(bot, fg_color="transparent")
        iconrow.pack(pady=(8, 0))
        for kind, cmd in (("gear", self._open_settings),
                          ("help", self._open_help),
                          ("info", self._open_about)):
            ctk.CTkButton(
                iconrow, text="", image=self._ico(kind, TEXT, 19),
                width=32, height=32, corner_radius=16,
                fg_color=CARD2, hover_color=HOVER,
                border_width=1, border_color=BORDER, command=cmd,
            ).pack(side="left", padx=4)

        # Durum — iki satirlik alan bastan ayrilir. Yalniz karakter sayisini
        # sinirlamak yeterli degildir: kalin yazi ve Windows DPI olceklemesi ayni
        # metni farkli genislikte cizer. Sabit wraplength, uzun hata mesajlarinin
        # pencerenin saginda kirpilmasini engeller.
        statusrow = ctk.CTkFrame(bot, fg_color="transparent")
        statusrow.pack(fill="x", pady=(7, 0))
        inner = ctk.CTkFrame(statusrow, fg_color="transparent")
        inner.pack(anchor="center")
        self.status_dot = ctk.CTkLabel(inner, text="●", font=_f(13), text_color=MUTED)
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_lbl = ctk.CTkLabel(
            inner, text=L["st_ready"], font=_f(12, "bold"), text_color=SUB,
            width=286, height=38, wraplength=286, justify="left", anchor="w",
        )
        self.status_lbl.pack(side="left")

    # ── Degradeli baslik bandi ──────────────────────────────────────────────
    def _build_header(self):
        H = 66
        try:
            # bg=HEADER_BG: ham CTkCanvas'in varsayilan (acik) arka plani yerine
            # ILK KAREDEN koyu. Yuksek DPI'da (window scaling) canvas gercek
            # genislige (or. 360*1.25=450) esnedigi icin, icerik cizilmeden onceki
            # an bile beyaz bir dikdortgen gorunmez.
            canvas = ctk.CTkCanvas(self, width=self.W, height=H,
                                   highlightthickness=0, bd=0, bg=HEADER_BG)
            canvas.pack(fill="x")
            self._header_canvas = canvas
            self._header_h = H
            self._header_w = 0                 # son cizilen genislik (tekrar cizimi sinirlar)
            self._prepare_header_images(H)     # logo + pill goruntusunu BIR kez uret
            # Ilk cizim mantiksal genislige (self.W) yapilir — %100 gorunum birebir
            # ayni kalir. Gercek (DPI-olcekli) genislik <Configure> ile gelince tam
            # genislige yeniden cizilir; boylece degrade/alt-cizgi/pill sag kenara kadar uzar.
            self._redraw_header(self.W)
            canvas.bind("<Configure>", self._on_header_configure)
        except Exception:
            # Guvenli geri donus: duz renkli bant. HEADER_BG (renkli, iki temada da
            # koyu-yeterli) uzerine WHITE metin -> light'ta da kontrast korunur
            # (CARD beyaz olabildigi icin CARD+WHITE gorunmez kalirdi).
            hdr = ctk.CTkFrame(self, fg_color=HEADER_BG, height=H)
            hdr.pack(fill="x")
            ctk.CTkLabel(hdr, text=f"  {L['title']} v{self.VERSION}", font=_f(16, "bold"),
                         text_color=WHITE).pack(side="left", padx=18, pady=20)

    def _prepare_header_images(self, H):
        """Logo (icon.ico) ve yonetici pill goruntusunu BIR kez uretir; her
        Configure yeniden ciziminde yeniden uretilmez (birikme/yuk olmaz)."""
        self._logo_img = None
        self._pill_img = None
        ico = resource_path("assets", "icon.ico")
        if os.path.exists(ico):
            try:
                from PIL import Image, ImageTk
                # Dosya tanimlayicisi acik kalmasin: convert()/resize() zaten
                # BAGIMSIZ yeni goruntuler uretir, kaynak with ile kapatilir.
                with Image.open(ico) as _src:
                    im = _src.convert("RGBA").resize((44, 44), Image.LANCZOS)
                self._logo_img = ImageTk.PhotoImage(im)
            except Exception:
                self._logo_img = None
        # Yonetici rozeti kaldirildi (program zaten yonetici olarak calisiyor:
        # exe uac_admin + installer PrivilegesRequired=admin + main.py UAC yukseltme).
        self._pill_img = None

    def _on_header_configure(self, event):
        """Canvas gercek genisligi degistiginde (DPI olcegi / ilk yerlesim) tam
        genislige yeniden ciz. Ayni genislikte tekrar cizmez (olay dongusu/birikme yok)."""
        w = event.width
        if w <= 1 or w == self._header_w:
            return
        self._redraw_header(w)

    def _redraw_header(self, width):
        """Baslik bandini VERILEN GERCEK genislige gore bir kez cizer. delete('all')
        ile onceki ogeler silinir (birikme olmaz); degrade ve alt cizgi tam genisligi
        kaplar, yonetici pill sag kenara hizalanir."""
        c = self._header_canvas
        H = self._header_h
        self._header_w = width
        c.delete("all")
        # Tek koyu, cok hafif gradient — tam genislik.
        self._draw_gradient(c, width, H, HDR_GRAD)

        # Sol: logo + baslik + surum
        text_x = 60
        if self._logo_img is not None:
            c.create_image(16, H // 2, anchor="w", image=self._logo_img)
            text_x = 16 + 44 + 12
        else:
            self._draw_logo(c, 18, H // 2, 19)
        c.create_text(text_x, H // 2 - 8, anchor="w", text=L["title"],
                      font=(FONT, 18, "bold"), fill=WHITE)
        c.create_text(text_x, H // 2 + 12, anchor="w", text=f"v{self.VERSION}",
                      font=(FONT, 9, "bold"), fill=HDR_VERSION)

        # (Yonetici rozeti kaldirildi — program zaten yonetici calisiyor.)

        # Alt aksan cizgisi — tam genislik.
        c.create_rectangle(0, H - 2, width, H, fill=HDR_ACCENT, outline="")

    def _draw_logo(self, canvas, cx, cy, s):
        """Beyaz yuvarlak-kare rozet + blurple simsek (hizli baglanti)."""
        cx += s  # sol kenar hizasi
        self._round_rect(canvas, cx - s, cy - s, cx + s, cy + s, s * 0.42,
                         fill=WHITE, outline="")
        # simsek poligonu (merkeze gore, yukaridan asagi zigzag)
        b = [(0.15, -0.62), (-0.42, 0.06), (-0.04, 0.06),
             (-0.15, 0.62), (0.42, -0.10), (0.04, -0.10)]
        pts = []
        for dx, dy in b:
            pts += [cx + dx * s, cy + dy * s]
        canvas.create_polygon(pts, fill=BLURPLE, outline="")

    @staticmethod
    def _draw_gradient(canvas, w, h, stops):
        """stops renkleri arasinda yatay degrade cizer."""
        def hx(c):
            return tuple(int(c[i:i + 2], 16) for i in (1, 3, 5))
        segs = len(stops) - 1
        pts = [hx(s) for s in stops]
        for x in range(w):
            t = x / max(w - 1, 1)
            si = min(int(t * segs), segs - 1)
            lt = t * segs - si
            a, b = pts[si], pts[si + 1]
            r = int(a[0] + (b[0] - a[0]) * lt)
            g = int(a[1] + (b[1] - a[1]) * lt)
            bl = int(a[2] + (b[2] - a[2]) * lt)
            canvas.create_line(x, 0, x, h, fill=f"#{r:02x}{g:02x}{bl:02x}")

    @staticmethod
    def _round_rect(canvas, x1, y1, x2, y2, rad, **kw):
        pts = [x1 + rad, y1, x2 - rad, y1, x2, y1, x2, y1 + rad, x2, y2 - rad,
               x2, y2, x2 - rad, y2, x1 + rad, y2, x1, y2, x1, y2 - rad,
               x1, y1 + rad, x1, y1]
        return canvas.create_polygon(pts, smooth=True, **kw)

    # ─────────────────────────── Durum panosu ───────────────────────────
    def _status_tick(self):
        """Tek periyodik zincir: yalnizca kendi kendini yeniden zamanlar.
        Baska hicbir yerden cagrilmamali (aksi halde paralel sonsuz zincirler
        birikir) — manuel/olay-tetikli yenileme icin _refresh_status_async
        kullanilir."""
        if not self._alive:
            return
        self._refresh_status_async()
        self._status_timer_id = self.after(6000, self._status_tick)

    def _refresh_status_async(self):
        """Tek seferlik pano yenilemesi baslatir; ayni anda yalnizca bir
        yenileme thread'i calisir. Mesgulken gelen son istek, calisan sistem
        sorgusu bittiginde hemen tekrarlanir; Normale Don durumunun sonraki
        zamanlayici tick'ini beklemesi engellenir."""
        if not self._alive:
            return
        if self._status_refreshing:
            self._status_refresh_pending = True
            return
        self._status_refreshing = True
        generation = self._status_generation
        threading.Thread(
            target=self._do_refresh_status, args=(generation,), daemon=True
        ).start()

    def _uptime_tick(self):
        """Aktif sure satirini saniye saniye canli gunceller (pano 6 sn'de bir
        yenilenirken bu satir kronometre gibi akar)."""
        if "uptime" in self.dash:
            if self._active_since:
                txt, col = self._fmt_uptime(time.time() - self._active_since), GREEN
            else:
                txt, col = L["val_none"], MUTED
            try:
                self.dash["uptime"].configure(text=txt, text_color=col)
            except Exception:
                pass
        self.after(1000, self._uptime_tick)

    def _do_refresh_status(self, generation=None):
        if generation is None:
            generation = self._status_generation
        try:
            active = self._unblocker.is_active()

            # Discord surumu
            ver = installed_discord_version()
            running_ver = running_discord_version()
            ver_txt = ver if ver else L["val_not_installed"]

            # Sistem DNS (ilk aktif adaptor)
            dns_txt = L["val_unknown"]
            try:
                adapters = get_active_adapters()
                if adapters:
                    dns = get_dns(adapters[0]["name"])
                    v4 = dns["ipv4"]
                    if v4["dhcp"] or not v4["primary"]:
                        dns_txt = L["val_auto"]
                    else:
                        dns_txt = v4["primary"]
            except Exception:
                pass

            if (
                not self._alive
                or generation != self._status_generation
            ):   # kapandiysa veya bu olcum eskidiyse panoyu guncelleme
                return
            try:
                self.after(
                    0,
                    lambda g=generation: self._apply_status_if_current(
                        g, active, ver_txt, dns_txt, ver, running_ver
                    ),
                )
            except Exception:
                pass
        finally:
            self._status_refreshing = False
            if self._alive and self._status_refresh_pending:
                self._status_refresh_pending = False
                try:
                    self.after(0, self._refresh_status_async)
                except Exception:
                    pass

    def _apply_status_if_current(self, generation, *args):
        """Kuyruga alinmis eski bir UI sonucunun yeni durumu ezmesini engeller."""
        if self._alive and generation == self._status_generation:
            self._apply_status(*args)

    def _apply_status(
        self, active, ver_txt, dns_txt, ver=None, running_ver=None,
    ):
        if not self.dash:
            return
        # HERO — canli baglanti durumu. Baglanma akisi sirasinda hero
        # "Baglaniyor..." halinde kalir; periyodik refresh onu EZMESIN.
        if not self._connecting:
            if active:
                self.hero_dot.configure(text_color=GREEN)
                self.hero_state.configure(text=L["hero_on"], text_color=TEXT)
                self.hero.configure(border_color=GREEN, border_width=2)
            else:
                self.hero_dot.configure(text_color=MUTED)
                self.hero_state.configure(text=L["hero_off"], text_color=SUB)
                self.hero.configure(border_color=BORDER, border_width=1)

        ver_txt, ver_color = self._discord_version_tile(ver, running_ver, ver_txt)
        self.dash["version"].configure(
            text=ver_txt,
            text_color=ver_color,
            font=_f(11, "bold") if "\n" in ver_txt else _f(13, "bold"),
        )
        self.dash["dns"].configure(
            text=dns_txt, text_color=GREEN if dns_txt == DNS_V4[0] else TEXT)
        self.dash["servers"].configure(
            text=L["servers_all"] if active else L["val_none"],
            text_color=GREEN if active else MUTED)
        # Aktif sure — yol kesintisiz ne zamandir acik. Kopunca sifirlanir.
        if active:
            if not self._active_since:
                self._active_since = time.time()
            up_txt = self._fmt_uptime(time.time() - self._active_since)
        else:
            self._active_since = None
            up_txt = L["val_none"]
        if "uptime" in self.dash:
            self.dash["uptime"].configure(
                text=up_txt, text_color=GREEN if active else MUTED)
        # Geri alinacak bir sey varsa (yol aktif YA DA DNS degistirilmis) tek
        # buton geri alma eylemine doner. Hosts yazilamayip yol acilmasa bile
        # DNS yedegi kalabilir; bu durumda kullanici kurtarma eylemini kaybetmez.
        # Onemli: hosts yazilamayip yol acilmasa bile DNS 1.1.1.1'e cekilmis olabilir;
        # bu durumda kullanici DNS'ini geri alabilmeli.
        can_restore = active or bool(self._get_dns_backup())
        if not self._busy:
            self._set_connection_button(active, can_restore)

    def _set_connection_button(self, active: bool, can_restore: bool = False):
        """Tek dugmenin eylem ve gorunumunu dogrulanmis durumla eslestirir."""
        restore_mode = bool(active or can_restore)
        self._connection_action_mode = "restore" if restore_mode else "activate"
        if restore_mode:
            self.btn_open.configure(
                state="normal", text=L["btn_restore"],
                fg_color="transparent", hover_color=HOVER, text_color=SUB,
                border_color=BORDER,
            )
        else:
            self.btn_open.configure(
                state="normal", text=L["btn_activate"],
                fg_color=BLURPLE, hover_color=BLURPLE_H, text_color=WHITE,
                border_color=BLURPLE,
            )

    def _handle_connection_action(self):
        """Tek dugmeyi o anda ekranda ilan edilen eyleme yonlendirir."""
        if self._busy:
            return
        if self._connection_action_mode == "restore":
            self._restore_normal()
        else:
            self._activate_connection()

    def _discord_version_tile(self, installed, running, fallback):
        """Surum karti icin dogru, sade metni ve rengini dondurur."""
        phase = self._discord_update_phase
        needs_restart = discord_restart_required(installed, running)
        if phase == "restart" and not needs_restart:
            if installed and running and installed == running:
                phase = "updated"
                self._discord_update_phase = phase
                self._discord_update_notice_until = time.time() + 5
            elif running:
                phase = ""
                self._discord_update_phase = ""
        if phase == "updated" and time.time() >= self._discord_update_notice_until:
            phase = ""
            self._discord_update_phase = ""
        status = ""
        color = TEXT if installed else MUTED
        if phase == "checking":
            status, color = L["discord_ver_checking"], YELL
        elif phase == "updating":
            status, color = L["discord_ver_updating"], YELL
        elif phase == "restart" or (not phase and needs_restart):
            status, color = L["discord_ver_restart"], YELL
            self._discord_update_phase = "restart"
        elif phase == "updated":
            status, color = L["discord_ver_updated"], GREEN
        base = installed if installed else fallback
        return (f"{base}\n{status}" if status else base), color

    @staticmethod
    def _fmt_uptime(secs) -> str:
        """Saniyeyi kronometre bicimine cevirir: 'd:ss' veya 'sa:dd:ss'."""
        secs = max(0, int(secs))
        h = secs // 3600
        m = (secs % 3600) // 60
        s = secs % 60
        if h > 0:
            return f"{h}:{m:02d}:{s:02d}"
        return f"{m}:{s:02d}"

    # ─────────────────────── Baglantiyi Etkinlestir ───────────────────────
    def _activate_connection(self):
        if self._busy:
            return
        self._busy = True
        # Acilis oncesi baslamis yavas bir durum olcumu, yeni baglanti
        # durumunu eski verilerle ezmesin.
        self._status_generation += 1
        self._connecting = True          # hero "Baglaniyor..." goster (periyodik refresh ezmesin)
        self._set_hero_connecting()
        self.btn_open.configure(state="disabled", text=L["btn_activating"])
        threading.Thread(target=self._activate_connection_w, daemon=True).start()

    def _set_hero_connecting(self):
        """Acilis akisi basinda buyuk baglanti kartini 'Baglaniyor...' (sari) yapar;
        boylece odak karti da alt durum satiriyla uyumlu, canli gorunur. Ana
        thread'den cagrilir."""
        try:
            self.hero_dot.configure(text_color=YELL)
            self.hero_state.configure(text=L["hero_connecting"], text_color=TEXT)
            self.hero.configure(border_color=YELL, border_width=2)
        except Exception:
            pass

    def _activate_connection_w(self):
        """DPort baglanti yolunu hazirlar; Discord surecine dokunmaz.

        Bu calisma yeri bir onceki surumlerde Discord zaten aciksa kapatip
        yeniden baslatabiliyor, kapaliysa da Update.exe/Discord.exe
        calistirabiliyordu. Baglanti yolu artik uygulamadan tamamen bagimsiz:
        kullanici Discord'u ne zaman isterse kendi kisayolundan acar.
        """
        try:
            # 0) SALT-OKUNUR on-kontrol: hosts yonlendirmesini temizleyebilecek
            # DOGRULANMIS bir kurtarma hedefi var mi? Yoksa yol zaten
            # acilamayacak; DNS'i once degistirip sonra geri almak yerine
            # sisteme HIC dokunmadan cikilir (DNS, role, hosts, gorev ve
            # Discord aynen kalir).
            source_dev = _source_dev_mode()
            if not source_dev and not self._preflight_failsafe_target():
                self._st(L["st_fail_no_recovery"], RED)
                return
            if source_dev:
                self.log_mgr.console(
                    "GELISTIRICI MODU | kurulu recovery hedefi aranmaz; "
                    "sert kapanista hosts bir sonraki DPort acilisinda temizlenir",
                    level="WARN")

            # 1) Sisteme dokunmadan guvenli DoH yolunu dogrula. Tum saglayicilar
            # basarisizsa DNS/hosts ve Discord aynen kalir.
            if not self._preflight_discord_unblock():
                self.log_mgr.write(
                    "DISCORD | guvenli DNS on-kontrolu basarisiz, sistem ayarlari degistirilmedi"
                )
                return

            # 2) Sistem DNS'ini 1.1.1.1 yap — ama once ORIJINALI yedekle
            self._st(L["st_setting_dns"], YELL)
            adapters = get_active_adapters()
            if not adapters:
                self._st(L["st_no_adapter"], RED)
                return
            try:
                self._backup_dns(adapters)
            except Exception as exc:
                self.log_mgr.write(f"DNS | yedekleme basarisiz, sisteme dokunulmadi | {exc}")
                self._st(L["st_dns_backup_failed"], RED)
                return
            for a in adapters:
                try:
                    ok, msg = set_dns(a["name"], DNS_V4[0], DNS_V4[1], DNS_V6[0], DNS_V6[1])
                except Exception as exc:
                    ok, msg = False, str(exc)
                self.log_mgr.write(f"DNS | {a['name']} | {'OK' if ok else msg}")
                if not ok:
                    self._restore_dns()
                    self._st(L["st_dns_apply_failed"], RED)
                    return
            self._flushdns()

            # 3) Engel asma yolunu ac (role + hosts)
            self._st(L["st_path_prep"], YELL)
            path_ok = self._enable_discord_unblock()

            if not path_ok:
                # Yol hazirlanamadi: calisan (varsa) Discord'a HIC dokunma.
                # Relay beklenmedik bir istisnayi hosts'a yazdiktan/roleyi
                # baslattiktan SONRA almis olabilir (_enable_discord_unblock
                # normalde kendi hatalarinda zaten temizler, ama garanti
                # olsun diye burada da idempotent temizlik yapilir); once
                # role/isaretli hosts blogunu sok, sonra DNS'i geri al ve
                # flush et.
                self.log_mgr.write(
                    "DISCORD | yol hazirlanamadi, Discord'a dokunulmadi, DPort degisiklikleri geri aliniyor"
                )
                self._disable_discord_unblock()
                self._restore_dns()
                self._flushdns()
                return

            # Buradan sonra Discord'a ait HICBIR surec yonetimi yoktur:
            # kapatma, Update.exe, Discord.exe veya updater log takibi yok.
            self.log_mgr.write(
                "CONNECTION | yol etkin; Discord kullanici tarafindan baslatilacak")
            self._st(L["st_activated"], GREEN)
        finally:
            self._busy = False
            self._connecting = False   # artik gercek durum uygulanabilir (hero cozulur)
            # Dugmenin sonraki eylemi worker varsayimiyla degil, status
            # refresh'in dogruladigi role/DNS durumuyla belirlenir.
            self.after(0, self._refresh_status_async)

    # ─────────────── Temali dialog (native messagebox yerine) ───────────────
    def _ask(self, title, message) -> bool:
        """Uygulama gorunumuyle uyumlu koyu Evet/Hayir onayi. Ana thread'den
        cagrilmali (wait_window). native askyesno ile ayni bool semantigi."""
        dlg = _ModalDialog(self, title, message, confirm=True)
        self.wait_window(dlg)
        return bool(dlg.result)

    def _notify(self, title, message):
        """Uygulama gorunumuyle uyumlu koyu bilgi/hata penceresi (tek Tamam)."""
        dlg = _ModalDialog(self, title, message, confirm=False)
        self.wait_window(dlg)

    # ─────────────────────────── Normale Don ───────────────────────────
    def _restore_normal(self):
        if self._busy:
            return
        if not self._ask(L["dlg_restore_t"], L["dlg_restore_msg"]):
            return
        self._busy = True
        # Baglanti acikken baslamis durum olcumunun gec kalan sonucu,
        # geri alma tamamlandiktan sonra "Baglandi / 1.1.1.1" yazamasin.
        self._status_generation += 1
        self.btn_open.configure(state="disabled", text=L["btn_restoring"])
        threading.Thread(target=self._restore_normal_w, daemon=True).start()

    def _restore_normal_w(self):
        try:
            self._st(L["st_restoring"], YELL)
            # TAM basari UC kosula birden baglidir: hosts yonlendirmesi
            # DOGRULANMIS bicimde kalkti, gorev uzlasmasi basarili ve DNS geri
            # yuklendi. Yalnizca DNS'e bakip "Normale donuldu" demek, hosts hala
            # 127.0.0.1'e yonlenirken kullaniciyi yaniltirdi.
            unblock_ok = self._disable_discord_unblock()
            restored = self._restore_dns()
            self._flushdns()
            fully_restored = bool(unblock_ok and restored)
            status_key = "st_restored" if fully_restored else "st_restore_partial"
            status_color = GREEN if fully_restored else RED
            self._st(L[status_key], status_color)
            dns_txt = self._current_dns_text()
            self.after(
                0,
                lambda d=dns_txt, retry=not fully_restored:
                    self._apply_restored_status(d, can_retry=retry),
            )
        finally:
            self._busy = False
            self.after(0, self._refresh_status_async)

    def _current_dns_text(self):
        """Ilk aktif adaptorun panoda gosterilecek guncel DNS metnini dondurur."""
        try:
            adapters = get_active_adapters()
            if adapters:
                v4 = get_dns(adapters[0]["name"])["ipv4"]
                if v4["dhcp"] or not v4["primary"]:
                    return L["val_auto"]
                return v4["primary"]
        except Exception:
            pass
        return L["val_unknown"]

    def _apply_restored_status(self, dns_txt, can_retry=False):
        """Geri alma bittigi anda bilinen sonucu ekrana uygular.

        Yeni durum taramasi beklenmez; sistem islemleri bu noktada zaten bitmistir.
        Sonraki normal yenileme surum gibi diger alanlari tekrar dogrular.
        """
        if not self.dash:
            return
        self._connecting = False
        self.hero_dot.configure(text_color=MUTED)
        self.hero_state.configure(text=L["hero_off"], text_color=SUB)
        self.hero.configure(border_color=BORDER, border_width=1)
        self.dash["dns"].configure(text=dns_txt, text_color=TEXT)
        self.dash["servers"].configure(text=L["val_none"], text_color=MUTED)
        self._active_since = None
        if "uptime" in self.dash:
            self.dash["uptime"].configure(text=L["val_none"], text_color=MUTED)
        self._set_connection_button(False, can_restore=can_retry)

    # ─────────────────────────── Unblock motoru ───────────────────────────
    def _preflight_discord_unblock(self) -> bool:
        """DNS/hosts degismeden once en az bir strict-HTTPS DoH yolunu dogrula."""
        self._st(L["st_path_prep"], YELL)
        try:
            if not self._unblocker.preflight("discord.com"):
                raise RuntimeError("bos yanit")
            return True
        except Exception as e:
            self.log_mgr.write(f"UNBLOCK | DoH calismiyor, yol acilmadi | {e}")
            self._st(L["st_fail_doh"], RED)
            return False

    def _rollback_after_enable_failure(self, context: str) -> None:
        """Failsafe gorevi KURULDUKTAN sonraki her basarisizlik/istisna yolunda
        sistemi guvenli duruma dondurur.

        Sirasiyla: role durdurulur, hosts yonlendirmesi (yazilmis OLABILIR)
        temizlenmeye calisilir, gorev merkezi siniflandirmayla uzlastirilir.
        Boylece gorev yalnizca temizlik DOGRULANDIYSA ya da hedefi guvensizse
        kaldirilir; hosts durumu belirsiz ve gorev dogrulanmissa KORUNUR.

        Rollback hatalari loglanir; ozgun hata cagiran tarafindan zaten
        yazilmistir ve KAYBOLMAZ."""
        try:
            self._unblocker.stop()
        except Exception as e:
            self.log_mgr.write(f"UNBLOCK | {context}: role durdurulamadi | {e}")
        try:
            hosts_cleared = remove_hosts_redirect()
        except Exception as e:
            hosts_cleared = False
            self.log_mgr.write(f"UNBLOCK | {context}: hosts geri alinamadi | {e}")
        self._reconcile_failsafe_task(hosts_cleared, context)

    def _enable_discord_unblock(self) -> bool:
        """Yerel parcalayici roleyi baslatir ve engellenen Discord host'larini
        (update + API + gateway + CDN) ona yonlendirir."""
        task_installed = False
        try:
            if not self._unblocker.start():
                self.log_mgr.write("UNBLOCK | role baslatilamadi (443 mesgul)")
                self._st(L["st_fail_port"], RED)
                return False
            # Failsafe gorevi hosts YAZILMADAN ONCE kurulur: yonlendirme bir kez
            # yazildiktan sonra cokme olursa temizleyecek bir sey kalmalidir.
            # Gorev kurulamaz veya geri okunarak dogrulanamazsa hosts'a HIC
            # dokunulmaz — aksi halde temizleyicisi olmayan bir yonlendirme
            # birakmis olurduk. Yalniz Calistir.bat'in acikca isaretledigi kaynak
            # gelistirici modunda kurulu EXE yoktur; burada kalici HIGHEST gorev
            # kurmak yerine normal kapanis + watchdog + sonraki acilis temizligi
            # kullanilir. Paketlenmis uygulama bu moda giremez.
            if _source_dev_mode():
                self.log_mgr.write(
                    "FAILSAFE | gelistirici modu; zamanlanmis kurtarma gorevi atlandi")
            else:
                if not self._install_failsafe_before_hosts():
                    self._unblocker.stop()
                    self._st(L["st_fail_failsafe"], RED)
                    return False
                task_installed = True
            if not add_hosts_redirect():
                err = last_hosts_error()
                winerr = last_hosts_winerror()
                self.log_mgr.write(
                    f"UNBLOCK | hosts yazilamadi | {err or 'yonetici izni veya antivirus (HostsFileHijack) engeli'}")
                # Yazma basarisiz: yonlendirmenin YARIM yazilmis olabilecegini
                # VARSAY, temizligi dogrula ve gorevi ona gore uzlastir.
                self._rollback_after_enable_failure("hosts yazilamadi")
                # Yalniz GERCEK yetki reddinde (winerror=5) VE yonetici DEGILSEK
                # "yonetici gerekli" de. Aksi halde (paylasim ihlali/gecici kilit,
                # ya da zaten yoneticiyken access-denied = AV/oyun anti-cheat)
                # sakin "gecici mesgul, tekrar dene" mesaji goster.
                if winerr == 5 and not self._is_admin():
                    self._st(L["st_fail_admin"], RED)
                else:
                    self._st(L["st_fail_hosts_locked"], RED)
                return False
            # Teshis: hosts yazma ilk denemede degil de retry icinde asildiysa,
            # bunu YALNIZ log'a bir kez yaz (ilk-deneme basarida yazma). Dosya
            # icerigi/kullanici verisi/surec adi loglanmaz — sadece deneme sayisi
            # ve gecici hata kodlari.
            attempts, r_errno, r_winerr = last_hosts_retry_info()
            if attempts > 1:
                self.log_mgr.write(
                    f"UNBLOCK | hosts gecici kilidi {attempts}. denemede asildi | "
                    f"errno={r_errno} winerror={r_winerr}")
            self._flushdns()
            self.log_mgr.write("UNBLOCK | Baglanti yolu acildi (update+API+gateway+CDN)")
            return True
        except Exception as e:
            self.log_mgr.write(f"UNBLOCK | hata | {e}")
            if task_installed:
                # Gorev kuruldu ve hosts yazilmis OLABILIR: role + hosts + gorev
                # birlikte guvenli duruma dondurulur.
                self._rollback_after_enable_failure(f"beklenmeyen hata: {e}")
            else:
                try:
                    self._unblocker.stop()
                except Exception as stop_err:
                    self.log_mgr.write(
                        f"UNBLOCK | role durdurulamadi | {stop_err}")
            return False

    def _disable_discord_unblock(self) -> bool:
        """hosts yonlendirmesini kaldirir, failsafe gorevini uzlastirir ve
        roleyi durdurur; sistemi eski haline getirir.

        Donus: TAM basari mi. Yalnizca hosts temizligi DOGRULANDIYSA ve gorev
        uzlasmasi basariliysa True. Cagiran bu degeri yok sayip "normale
        donuldu" DEMEMELIDIR: role dursa bile hosts hala 127.0.0.1'e
        yonlendiriyorsa sistem normal DEGILDIR."""
        try:
            hosts_cleared = remove_hosts_redirect()
        except Exception as e:
            hosts_cleared = False
            self.log_mgr.console(
                f"failsafe: hosts temizligi hata verdi: {e}", level="WARN")
        task_ok = self._reconcile_failsafe_task(hosts_cleared, "kapanis")
        try:
            self._unblocker.stop()
        except Exception:
            pass
        try:
            self._flushdns()
        except Exception:
            pass
        return bool(hosts_cleared and task_ok)

    def _discord_should_use_updater(self) -> bool:
        # HER acilista Discord'un kendi guncelleyicisi (Update.exe) calissin: Discord
        # daima guncel kalir, hicbir acilista guncelleme atlanmaz. Bedeli: Discord
        # zaten guncelken acilis ~1-3 sn daha yavas (updater once kontrol eder), ama
        # acilis yine garanti (kontrol basarisiz olsa bile mevcut surum acilir).
        # Eski 6 saatlik hizli-acilis onbellegi kaldirildi (kullanici tercihi).
        return True

    # Discord updater asama kodu -> gorunur durum satiri (dile gore) metni.
    _UPD_STAGE_KEYS = {
        "checking": "st_upd_checking",
        "downloading": "st_upd_downloading",
        "installing": "st_upd_installing",
        "finishing": "st_upd_finishing",
    }

    def _discord_update_result_w(self, started_at: float, version_before=None):
        began = time.time()
        last_activity = began
        last_error = None
        last_state = None
        last_message = None
        last_stage = None

        while self._alive:
            now = time.time()
            if (now - began >= UPD_HARD_LIMIT
                    or now - last_activity >= UPD_IDLE_TIMEOUT):
                break
            time.sleep(UPD_POLL)
            if not self._alive:   # kapandiysa erken cik (config/Tk'ye dokunma)
                return
            status, msg, stage = get_discord_update_status(max_age_seconds=120, since_epoch=started_at)
            state = (status, msg, stage)
            # AKTIFLIK olcutu: durum DEGISTIYSE ya da hala 'progress' geliyorsa
            # updater calisiyor demektir. Buyuk bir indirme sirasinda updater
            # 100+ saniye boyunca BIREBIR ayni satiri dondurebilir; yalnizca
            # degisiklige bakmak bu durumda basariya ulasmadan idle timeout
            # uretiyordu. get_discord_update_status log bayatsa zaten "unknown"
            # dondugu icin TAZE bir "progress" gercek aktivite demektir.
            # (unknown/error tekrarlari aktiflik SAYILMAZ -> sinirli timeout korunur.)
            if state != last_state or status == "progress":
                last_activity = time.time()
            last_state = state
            if status == "ok":
                self.log_mgr.console(f"Updater sonucu: {msg}", level="INFO")
                self.cfg.set("discord_last_update_ok_at", time.time())
                self._st(L["st_update_ok"], GREEN)
                installed = installed_discord_version()
                running = running_discord_version()
                if discord_restart_required(installed, running):
                    phase = "restart"
                elif installed and installed != version_before:
                    phase = "updated" if installed == running else "restart"
                else:
                    phase = ""
                self.after(0, lambda p=phase: self._set_discord_update_phase(p))
                return
            if status == "error":
                last_error = msg
            elif status == "progress":
                # Yeni bir deneme/ilerleme geldi: ONCEKI hata artik BAYAT.
                # Aksi halde gecici bir hatanin ardindan basariyla ilerleyen
                # guncelleme, sonunda o eski hata yuzunden BASARISIZ raporlanirdi.
                last_error = None
                # Canli ilerleme: asama degistiyse gorunur alt satira da yansit
                # (kullanici gecikmeyi 'calisiyor' diye anlar, donmus sanmaz).
                key = self._UPD_STAGE_KEYS.get(stage)
                if key and stage != last_stage:
                    last_stage = stage
                    self._st(L[key], YELL)
                    phase = "checking" if stage == "checking" else "updating"
                    self.after(0, lambda p=phase: self._set_discord_update_phase(p))
                if msg != last_message:
                    last_message = msg
                    self.log_mgr.console(f"Updater: {msg}", level="INFO")

        if not self._alive:   # kapandi: Tk/config'e DOKUNMA
            return

        if last_error:
            self.log_mgr.console(f"Updater sonucu: {last_error}", level="ERROR")
            self._st(L["st_update_fail"], RED)
            self.after(0, lambda: self._set_discord_update_phase(""))
        else:
            waited = int(time.time() - began)
            self.log_mgr.console(
                f"Updater sonucu {waited} sn içinde kesinleşmedi "
                f"(ilerleme durdu).", level="WARN")
            installed = installed_discord_version()
            running = running_discord_version()
            phase = "restart" if discord_restart_required(installed, running) else ""
            self.after(0, lambda p=phase: self._set_discord_update_phase(p))
        # NOT: unblock burada KAPATILMAZ — Discord acikken API/gateway/CDN de bu
        # role uzerinden gidiyor. Temizlik: DnsAngel kapaninca + acilista self-heal.

    # ─────────────────────────── DNS yedek/geri-yukle ───────────────────────────
    # ── Ayricalikli DNS kurtarma durumu (F4) ────────────────────────────────
    # Bu veri yonetici yetkili `netsh` komutuna girdi oldugu icin standart
    # kullanicinin YAZAMADIGI bir yerde durmalidir. Sira:
    #   1) secure_store  -> %ProgramData%\DPort\dns_state.json (ACL: Users = RX)
    #   2) bellek        -> mevcut oturumda geri alma icin ek kopya;
    #                      tek basina yeni DNS degisikligine izin vermez
    # Kullanici-yazilabilir config.json'a HICBIR KOSULDA dusulmez.
    def _get_dns_backup(self) -> dict:
        try:
            stored = secure_store.load_dns_backup()
        except Exception:
            stored = {}
        return stored or dict(self._dns_backup_mem)

    def _set_dns_backup(self, backup) -> bool:
        data = dict(backup) if backup else {}
        persisted = False
        try:
            persisted = secure_store.save_dns_backup(data or None)
        except Exception:
            persisted = False
        # Bellek kopyasi her zaman guncel tutulur: store calisiyorsa zararsiz
        # yedek, calismiyorsa tek kaynaktir.
        self._dns_backup_mem = data
        if data and not persisted:
            self.log_mgr.console(
                "DNS | korumali kurtarma dosyasi yazilamadi; yedek yalniz bu oturumda "
                "tutuluyor (cokme kurtarmasi devre disi)", level="WARN")
        return bool(persisted)

    def _backup_dns(self, adapters):
        """Read/validate every new adapter before allowing any DNS mutation."""
        backup = dict(self._get_dns_backup())
        for adapter in adapters:
            name = adapter["name"]
            current = get_dns(name)
            if name not in backup:
                backup[name] = current
            backup[name] = normalize_snapshot(backup[name])
            saved_guid = backup[name].get("interface_guid")
            if saved_guid and saved_guid != current.get("interface_guid"):
                raise ValueError("Adaptor kimligi yedekle uyusmuyor")
        if not self._set_dns_backup(backup):
            raise OSError("Korumali DNS kurtarma yedegi kalici olarak dogrulanamadi")
        self.log_mgr.write(f"DNS | orijinal ayar yedeklendi ({len(backup)} adaptor)")

    @staticmethod
    def _sanitize_dns_snapshot(snap):
        # Never convert malformed or incomplete state into DHCP.
        return normalize_snapshot(snap)

    @staticmethod
    def _live_adapter_names():
        """Sistemde SU AN var olan adaptor adlari (set) — alinamazsa None.
        (cagiran taraf ad dogrulamasini ATLAR, yoksa gecici bir listeleme
        hatasi mesru geri yuklemeyi engellerdi)."""
        try:
            names = {
                a.get("name") for a in get_all_adapters()
                if isinstance(a.get("name"), str) and a.get("name")
            }
            return names or None
        except Exception:
            return None

    def _restore_dns(self):
        """YALNIZCA bizim degistirdigimiz (yedekteki) adaptorleri orijinal ayarina
        dondurur — statik ise statik, DHCP ise DHCP. Dokunmadigimiz adaptorlere
        (yedekte olmayan) HIC karisilmaz; kullanicinin manuel DNS'i bozulmaz.
        Basarisiz adaptorler yedekte kalir (bir sonraki denemede tekrar denenir);
        yalnizca basariyla geri yuklenenler yedekten cikarilir.

        Iki katmanli dogrulama (F4):
          1. Adaptor adi CANLI adaptor listesiyle karsilastirilir; sistemde
             olmayan bir ad netsh'e HIC verilmez (yedekte kalir, adaptor geri
             gelirse tekrar denenir).
          2. Snapshot degerleri _sanitize_dns_snapshot ile IP olarak dogrulanir
              (bicimsiz/cop deger gecmez).

        Tum yedekler basariyla geri alindiysa True, tekrar denenmesi gereken
        en az bir adaptor kaldiysa False dondurur."""
        backup = dict(self._get_dns_backup())
        remaining = dict(backup)
        live = self._live_adapter_names()
        for name, snap in backup.items():
            if not isinstance(name, str) or not name.strip():
                self.log_mgr.write("DNS geri | gecersiz adaptor adi; yedek korundu")
                continue
            if live is not None and name not in live:
                # Sistemde boyle bir adaptor yok: netsh'e gonderme. Yedekte
                # BIRAKILIR ki adaptor tekrar takildiginda geri yuklenebilsin.
                self.log_mgr.write(f"DNS geri | {name} | atlandi (adaptor sistemde yok)")
                continue
            try:
                snap = self._sanitize_dns_snapshot(snap)
                ok, msg = restore_dns(name, snap)
            except Exception as e:
                ok, msg = False, str(e)
            self.log_mgr.write(f"DNS geri | {name} | {'OK' if ok else msg}")
            if ok:
                remaining.pop(name, None)
        self._set_dns_backup(remaining)
        return not remaining

    # ── Eski (guvenilmeyen) config yedegi icin onayli gecis ──────────────────
    def _offer_legacy_dns_restore(self):
        """Eski surumden kalan config.json yedegini SESSIZCE uygulamaz.

        Bu veri kullanici-yazilabilir bir dosyadan geldigi icin dogrulugu
        garanti edilemez. Degerler kullaniciya gosterilir; yalnizca acik onayla
        ve normal yolun tum dogrulamalarindan (canli adaptor + IP bicimi)
        gecerek uygulanir. Onay verilmezse veri atilir."""
        legacy, self._legacy_dns_backup = self._legacy_dns_backup, None
        if not legacy or not isinstance(legacy, dict) or not self._alive:
            return
        try:
            details = self._describe_dns_backup(legacy)
            if not details:
                return
            self.log_mgr.write(
                f"DNS | eski config yedegi bulundu ({len(legacy)} adaptor), "
                f"otomatik uygulanmadi, kullaniciya soruldu")
            if not self._ask(L["dlg_legacy_dns_t"],
                             L["dlg_legacy_dns_msg"].format(details=details)):
                self.log_mgr.write("DNS | eski config yedegi kullanici onayi yok, atildi")
                return
            self._set_dns_backup(legacy)
            threading.Thread(target=self._restore_legacy_dns_w, daemon=True).start()
        except Exception as e:
            self.log_mgr.console(f"DNS | eski yedek gecisi basarisiz: {e}", level="WARN")

    def _restore_legacy_dns_w(self):
        self._st(L["st_restoring"], YELL)
        restored = self._restore_dns()
        self._flushdns()
        status_key = "st_restored" if restored else "st_restore_partial"
        status_color = GREEN if restored else RED
        self._st(L[status_key], status_color)
        self.after(0, self._refresh_status_async)

    @staticmethod
    def _describe_dns_backup(backup: dict) -> str:
        """Yedegi kullaniciya gosterilecek kisa metne cevirir. Yalnizca
        DOGRULANMIS degerler gosterilir; kullanici gordugunu onaylar."""
        lines = []
        for name, snap in backup.items():
            if not isinstance(name, str) or not name.strip():
                continue
            clean = DPortApp._sanitize_dns_snapshot(snap)
            v4 = clean["ipv4"]
            if v4["dhcp"] or not v4["primary"]:
                value = L["legacy_dns_dhcp"]
            else:
                value = v4["primary"]
                if v4["secondary"]:
                    value += f", {v4['secondary']}"
            lines.append(f"• {name} → {value}")
        return "\n".join(lines[:6])

    # ── Failsafe gorev yasam dongusu ────────────────────────────────────────
    # Gorev KALICI DEGILDIR. Yalnizca DPort'un isaretli hosts yonlendirmesinin
    # aktif olabilecegi aralikta bulunur:
    #   kur   -> hosts YAZILMADAN hemen once (baglanti yolu)
    #   dusur -> hosts temizligi DOGRULANDIGI her yerde (acilis/kapanis/watchdog)
    # Boylece temiz bir sistemde ONLOGON/HIGHEST bir gorev asilı kalmaz.
    def _preflight_failsafe_target(self) -> bool:
        """SALT-OKUNUR: HIGHEST yetkili gorev icin dogrulanmis bir hedef var mi?

        Hicbir sistem durumunu DEGISTIRMEZ (gorev kurmaz/silmez, DNS/hosts/role
        ve Discord'a dokunmaz). Amaci, basarisiz olacagi belli bir akista
        sistemi once bozup sonra geri almaktan kacinmaktir.

        NOT: Bu on-kontrol SON guvenlik kontrolunun YERINE GECMEZ. Hedef, gorev
        gercekten kurulmadan hemen once `install_logon_failsafe()` icinde
        YENIDEN dogrulanir (TOCTOU); arada hedef bozulursa hosts'a yine
        dokunulmaz."""
        try:
            target = verified_failsafe_target()
        except Exception as e:
            self.log_mgr.write(f"FAILSAFE | recovery on-kontrolu hata verdi | {e}")
            return False
        if target:
            return True
        self.log_mgr.write(
            "FAILSAFE | dogrulanmis kurtarma hedefi yok, sisteme dokunulmadi | "
            f"{last_failsafe_error() or 'Program Files altinda dogrulanmis '
                                        'DPort.exe bulunamadi'}")
        return False

    def _install_failsafe_before_hosts(self) -> bool:
        """hosts yazmadan once dogrulanmis failsafe gorevini kurar.

        Hedefi BURADA yeniden dogrular: `_preflight_failsafe_target()` yalnizca
        erken cikis icindir, son soz bu adimindir (TOCTOU).

        False donerse cagiran hosts'a DOKUNMAMALIDIR."""
        try:
            if install_logon_failsafe():
                self.log_mgr.console("failsafe: logon hosts-temizleyici gorevi kuruldu")
                return True
            err = last_failsafe_error()
            self.log_mgr.write(
                f"FAILSAFE | gorev kurulamadi, hosts'a dokunulmadi | "
                f"{err or 'dogrulanmis kurulum hedefi yok'}")
        except Exception as e:
            self.log_mgr.write(f"FAILSAFE | gorev kurulum hatasi | {e}")
        return False

    def _reconcile_failsafe_task(self, hosts_cleared: bool, context: str) -> bool:
        """Gorevi MERKEZI siniflandirmayla uzlastirir (tek karar noktasi).

        Kaldirma karari yalnizca `hosts_cleared`'a degil, gorevin KAYITLI
        HEDEFINE de baglidir (bkz. core/failsafe.py::reconcile_failsafe_task):
        hosts temizlenemese bile hedefi okunamayan, eski adli veya
        dogrulanamayan bir HIGHEST gorev AYAKTA BIRAKILMAZ.

        Donus: "ayakta guvensiz veya gereksiz gorev yok" garanti edilebiliyor mu.
        Hata sessizce yutulmaz ve basari olarak RAPORLANMAZ."""
        try:
            if reconcile_failsafe_task(hosts_cleared):
                if not hosts_cleared:
                    self.log_mgr.console(
                        f"failsafe: {context}: hosts temizlenemedi; dogrulanmis "
                        f"kurtarma gorevi KORUNDU, guvensiz gorev birakilmadi",
                        level="WARN")
                return True
            self.log_mgr.write(
                f"FAILSAFE | {context}: gorev uzlastirilamadi | "
                f"{last_failsafe_error() or 'bilinmeyen hata'}")
        except Exception as e:
            self.log_mgr.write(f"FAILSAFE | {context}: gorev uzlasma hatasi | {e}")
        return False

    def _watchdog_loop(self):
        """Role beklenmedik sekilde olur de hosts yonlendirmesi kalirsa (Discord'u
        bozacak durum), aninda temizle. Program calistigi surece gorev yapar.

        Basari YALNIZCA gercekten temizlendiginde loglanir; basarisizlik ve
        istisna gorunur kalir (thread yine de olmez, bir sonraki turda tekrar
        dener)."""
        while self._alive:
            time.sleep(2)
            try:
                if is_hosts_redirect_active() and not self._unblocker.is_active():
                    try:
                        hosts_cleared = remove_hosts_redirect()
                    except Exception as e:
                        hosts_cleared = False
                        self.log_mgr.console(
                            f"watchdog: hosts temizligi hata verdi: {e}",
                            level="ERROR")
                    self._flushdns()
                    if hosts_cleared:
                        self.log_mgr.console(
                            "watchdog: role kapali, hosts yonlendirmesi temizlendi",
                            level="WARN")
                    else:
                        self.log_mgr.console(
                            "watchdog: role kapali ama hosts yonlendirmesi "
                            "TEMIZLENEMEDI (Discord acilmayabilir)", level="ERROR")
                    # Gorev, hosts sonucuyla birlikte merkezi olarak uzlastirilir.
                    self._reconcile_failsafe_task(hosts_cleared, "watchdog")
            except Exception as e:
                try:
                    self.log_mgr.console(
                        f"watchdog: beklenmeyen hata: {e}", level="ERROR")
                except Exception:
                    pass

    # ─────────────────────────── Yardimcilar ───────────────────────────
    def _flushdns(self):
        try:
            subprocess.run(
                ["ipconfig", "/flushdns"],
                creationflags=subprocess.CREATE_NO_WINDOW,
                capture_output=True, timeout=8,
            )
        except Exception:
            pass

    def _st(self, txt: str, col: str = SUB):
        if hasattr(self, "log_mgr"):
            self.log_mgr.console(txt, level="STATUS")
        if not getattr(self, "_alive", True):   # kapandiysa Tk'ye dokunma
            return

        def _apply():
            self.status_lbl.configure(text=txt, text_color=col)
            if hasattr(self, "status_dot"):
                self.status_dot.configure(text_color=col)
        try:
            self.after(0, _apply)
        except Exception:
            pass

    @staticmethod
    def _is_admin():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    # ─────────────────────────── Pencereler ───────────────────────────
    def _check_updates_on_start(self):
        self._update_checks.request()

    def _check_update_clicked(self):
        if self._update_download_active:
            return
        self._st(L["st_update_checking"], YELL)
        self._update_checks.request(manual=True)

    def _deliver_update_check(self, info, error, manual):
        if not self._alive or self._update_download_active:
            return
        if error:
            if manual:
                self._notify(L["update_title"], f"{L['update_failed']}\n\n{error}")
            if self._alive and not self._busy:
                self._st(L["st_update_unavailable"], YELL)
            return
        if info.get("available"):
            self._prompt_update(info)
        elif manual:
            self._notify(L["update_title"],
                         L["update_current"].format(version=self.VERSION))
            if self._alive and not self._busy:
                self._st(L["st_ready"], SUB)

    def _download_update_worker(self):
        queued = False
        try:
            queued = self._download_and_launch_update(self._update_download_info)
        finally:
            if not queued:
                self._update_download_active = False

    def _prompt_update(self, info: dict):
        version = info.get("version") or "?"
        if not info.get("download_url"):
            if self._ask(
                L["update_title"],
                L["update_no_asset"].format(version=version),
            ):
                self._open_releases_page()
            return

        if self._ask(
            L["update_title"],
            L["update_available"].format(version=version, current=self.VERSION),
        ):
            self._st(L["st_update_downloading"], YELL)
            self._update_download_active = True
            self._update_download_info = info
            try:
                threading.Thread(target=self._download_update_worker, daemon=True).start()
            except Exception:
                self._update_download_active = False
                raise

    def _download_and_launch_update(self, info: dict):
        # F3: installer ARTIK kullanici-yazilabilir %APPDATA% altina indirilmez.
        # ACL-korumali staging dizini (%ProgramData%\DPort\updates, Users = yalniz
        # oku/calistir) hazirlanamazsa indirme HIC yapilmaz — guvensiz konuma
        # geri DUSULMEZ.
        staging = None
        try:
            staging = secure_store.update_staging_dir()
        except Exception:
            staging = None
        if not staging:
            self.log_mgr.write(
                "UPDATE | korumali staging dizini hazirlanamadi, indirme iptal edildi")
            self.after(0, lambda: self._notify(L["update_title"], L["update_staging_failed"]))
            self.after(0, lambda: self._st(L["st_ready"], SUB))
            return

        try:
            path = download_update(info, staging)
        except UpdateError as exc:
            # Bkz. _run_update_check: `exc` blok sonunda silinir, mesaj ONCEDEN
            # baglanmazsa gecikmeli callback NameError atar.
            message = f"{L['update_failed']}\n\n{exc}"
            self.after(0, lambda m=message: self._notify(L["update_title"], m))
            self.after(0, lambda: self._st(L["st_ready"], SUB))
            return

        def _launch_inner():
            if self._ask(L["update_title"], L["update_downloaded"]):
                # TOCTOU: dosya, hash'i KILITLI HANDLE uzerinden yeniden
                # hesaplanir ve handle ACIKKEN calistirilir. Handle FILE_SHARE_READ
                # ile acildigi icin arada yazma/silme/yeniden adlandirma MUMKUN
                # DEGILDIR: dogrulanan baytlar ile calisan baytlar aynidir.
                # Dogrulama basarisizsa surec HIC baslatilmaz.
                ok, err = launch_verified(path, info.get("digest"))
                if not ok:
                    self.log_mgr.write(f"UPDATE | calistirma engellendi | {err}")
                    self._notify(L["update_title"], L["update_verify_failed"])
                    self._st(L["st_ready"], SUB)
                    return
                self.after(500, self.destroy)
            else:
                self._st(L["st_ready"], SUB)

        def _launch():
            try:
                if self._alive:
                    _launch_inner()
            finally:
                self._update_download_active = False

        self.after(0, _launch)
        return True

    def _purge_legacy_downloads(self):
        """Eski, KULLANICI-YAZILABILIR indirme klasorunde (%APPDATA%\\DPort\\updates)
        birikmis DPort setup dosyalarini siler. Bunlar artik kullanilmiyor ve
        yazilabilir bir konumda duran ikili yigini gereksiz saldiri yuzeyidir.
        Yalnizca DPort'un kendi ad kalibi silinir; baska dosyaya dokunulmaz."""
        def _work():
            try:
                removed = purge_setup_dir(user_data_path("updates"))
                if removed:
                    self.log_mgr.write(
                        f"UPDATE | eski indirme klasorunden {removed} setup dosyasi temizlendi")
            except Exception:
                pass
        threading.Thread(target=_work, daemon=True).start()

    def _open_releases_page(self):
        try:
            import webbrowser
            webbrowser.open(GITHUB_RELEASES_URL)
        except Exception:
            pass

    def _open_panel(self, cls):
        """Alt pencereler ayni anda tek tane acik kalir. Ayni ikona tekrar
        basilirsa acik pencere kapanir (toggle); farkli ikona basilirsa onceki
        kapatilip yenisi acilir."""
        existing = getattr(self, "_panel", None)
        same = False
        if existing is not None:
            try:
                if existing.winfo_exists():
                    same = existing.__class__ is cls
                    existing.destroy()
            except Exception:
                pass
        self._panel = None
        if same:
            return
        try:
            self._panel = cls(self)
        except Exception:
            self._panel = None

    def _open_log(self):
        self._open_panel(_LogWindow)

    def _open_settings(self):
        self._open_panel(_SettingsWindow)

    def _open_help(self):
        self._open_panel(_HelpWindow)

    def _open_about(self):
        self._open_panel(_AboutWindow)

    def apply_language(self):
        """Dil degisince arayuzu yeniden kur."""
        set_lang(self.cfg.get("language", "tr"))
        for w in self.winfo_children():
            w.destroy()
        self.dash = {}
        self.title(L["title"])
        self._build()
        self._fit_height()   # dil degisince metin uzarsa pencere yeniden sigsin

    # ─────────────────────────── Kapanis / tepsi ───────────────────────────
    def destroy(self):
        # Tamamen kapanirken yonlendirmeyi geri al, roleyi durdur, IPC'yi + tepsiyi kapat.
        self._alive = False   # arka plan thread'leri artik Tk'ye dokunmasin
        if hasattr(self, "_update_checks"):
            self._update_checks.close()
        try:
            if self._status_timer_id is not None:
                self.after_cancel(self._status_timer_id)
        except Exception:
            pass
        self._stop_tray()
        try:
            if getattr(self, "_ipc_srv", None):
                self._ipc_srv.close()
        except Exception:
            pass
        self._disable_discord_unblock()
        # Kapanista sistem DNS'ini de orijinaline dondur (README: "kapaninca otomatik
        # geri alinir"). Yalniz yedekledigimiz adaptorler geri yuklenir; yedek yoksa
        # no-op. Kapanisi engellememesi icin hataya dayanikli.
        try:
            self._restore_dns()
        except Exception:
            pass
        super().destroy()

    def _on_close(self):
        # Hatirlanmis tercih varsa dogrudan uygula.
        if not self.cfg.get("ask_on_close", True):
            self._to_tray() if self.cfg.get("minimize_to_tray", True) else self.destroy()
            return
        # Aksi halde temali diyalog: tepside kal / tamamen kapat / iptal.
        dlg = _CloseDialog(self)
        self.wait_window(dlg)
        if dlg.result is None:            # iptal (diyalog X)
            return
        if dlg.remember:
            self.cfg.set("ask_on_close", False)
            self.cfg.set("minimize_to_tray", dlg.result == "tray")
        if dlg.result == "tray":
            self._to_tray()
        else:
            self.destroy()

    def _to_tray(self):
        try:
            import pystray
            from PIL import Image, ImageDraw
            self._stop_tray()   # varsa eski ikonu durdur (cift ikon olmasin)
            self.withdraw()
            icon_path = resource_path("assets", "icon.ico")
            if os.path.exists(icon_path):
                # pystray goruntuyu with blogundan SONRA kullanir; copy() ayni
                # mod/boyutta BAGIMSIZ bir kopya verir (davranis degismez) ve
                # dosya tanimlayicisi acik kalmaz.
                with Image.open(icon_path) as _src:
                    img = _src.copy()
            else:
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                ImageDraw.Draw(img).ellipse([4, 4, 60, 60], fill=BLURPLE)

            def on_open(icon, _):
                icon.stop()
                self._tray = None
                self.after(0, self._show_window)

            def on_quit(icon, _):
                icon.stop()
                self._tray = None
                self.after(0, self.destroy)

            menu = pystray.Menu(
                pystray.MenuItem(f"{L['title']}", on_open, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit / Cikis", on_quit),
            )
            self._tray = pystray.Icon("dport", img, L["title"], menu)
            self._tray.run_detached()
        except Exception:
            self.destroy()


# ═══════════════════════════ Hakkinda penceresi ═══════════════════════════
class _AboutWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(L["about_title"])
        self.resizable(False, False)
        self.configure(fg_color=BG)
        _apply_win_icon(self)
        self._build()
        # Yuksekligi TAM icerige gore ayarla (sabit 306 alt sinir gereksiz bosluk
        # birakiyordu). UST kenar hizali ve sabit.
        self.update_idletasks()
        h = self.winfo_reqheight() + 6
        self.transient(app)
        _dock_window(app, self, 300, h, align_top=True)

    def _build(self):
        pad = ctk.CTkFrame(self, fg_color=BG)
        pad.pack(fill="both", expand=True, padx=20, pady=14)

        # Logo + isim + surum
        top = ctk.CTkFrame(pad, fg_color="transparent")
        top.pack(fill="x")
        try:
            from PIL import Image
            ic = resource_path("assets", "icon.ico")
            if os.path.exists(ic):
                # convert() bagimsiz yeni goruntu uretir; kaynak with ile kapatilir.
                with Image.open(ic) as _src:
                    im = _src.convert("RGBA")
                self._img = ctk.CTkImage(light_image=im, dark_image=im, size=(42, 42))
                ctk.CTkLabel(top, image=self._img, text="").pack(side="left")
        except Exception:
            pass
        namebox = ctk.CTkFrame(top, fg_color="transparent")
        namebox.pack(side="left", padx=12, fill="y")
        ctk.CTkLabel(namebox, text=APP_NAME, font=_f(18, "bold"),
                     text_color=TEXT, anchor="w").pack(anchor="w", expand=True)

        ctk.CTkFrame(pad, height=1, fg_color=BORDER).pack(fill="x", pady=8)

        # Bilgi karti — Surum / Gelistirici / E-posta
        info = ctk.CTkFrame(pad, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=BORDER)
        info.pack(fill="x")
        info.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(info, text=L["about_version"], font=_f(12), text_color=MUTED,
                     anchor="w").grid(row=0, column=0, sticky="w", padx=(14, 10), pady=(9, 4))
        ctk.CTkLabel(info, text=f"v{self.app.VERSION}", font=_f(12, "bold"), text_color=TEXT,
                     anchor="e").grid(row=0, column=1, sticky="e", padx=(0, 14), pady=(9, 4))
        ctk.CTkLabel(info, text=L["about_dev"], font=_f(12), text_color=MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", padx=(14, 10), pady=4)
        ctk.CTkLabel(info, text=L["about_dev_name"], font=_f(12, "bold"), text_color=TEXT,
                     anchor="e").grid(row=1, column=1, sticky="e", padx=(0, 14), pady=4)
        ctk.CTkLabel(info, text=L["about_email"], font=_f(12), text_color=MUTED,
                     anchor="w").grid(row=2, column=0, sticky="w", padx=(14, 10), pady=(4, 9))
        mail = ctk.CTkLabel(info, text=L["about_email_addr"],
                            font=ctk.CTkFont(FONT, 12, underline=True),
                            text_color=BLURPLE_L, anchor="e", cursor="hand2")
        mail.grid(row=2, column=1, sticky="e", padx=(0, 14), pady=(4, 9))
        mail.bind("<Button-1>", lambda e: self._mail())

        # Kisa amac (en alt)
        ctk.CTkLabel(pad, text=L["about_purpose"], font=_f(11), text_color=SUB,
                     anchor="w", justify="left", wraplength=260).pack(anchor="w", pady=(9, 0))

    def _mail(self):
        try:
            import webbrowser
            webbrowser.open(f"mailto:{APP_EMAIL}")
        except Exception:
            pass


# ═══════════════════════════ Kapatma diyalogu ═══════════════════════════
class _CloseDialog(ctk.CTkToplevel):
    """X'e basinca: tepside kal / tamamen kapat / iptal (temali, 'hatirla' secenekli)."""
    def __init__(self, app):
        super().__init__(app)
        # Pencere varsayilan boyut/konumuyla bir an gorunmesin. Tum icerik ve
        # sahiplik hazirlandiktan sonra tek seferde ekrana cikarilir.
        self.withdraw()
        self.result = None
        self.remember = False
        self.title(L["close_title"])
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        _apply_win_icon(self)
        self._build()
        # Yukseklik icerige gore (sabit 212 altta gereksiz bosluk birakiyordu).
        w = 340
        self.update_idletasks()
        h = self.winfo_reqheight() + 4
        app.update_idletasks()
        x = app.winfo_x() + (app.winfo_width() - w) // 2
        y = app.winfo_y() + (app.winfo_height() - h) // 3
        self.transient(app)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.attributes("-topmost", True)
        self.deiconify()
        self.lift()
        self.grab_set()

    def _build(self):
        pad = ctk.CTkFrame(self, fg_color=BG)
        pad.pack(fill="both", expand=True, padx=18, pady=14)
        ctk.CTkLabel(pad, text=L["close_title"], font=_f(15, "bold"),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(pad, text=L["close_msg"], font=_f(11), text_color=SUB,
                     anchor="w", justify="left", wraplength=304).pack(anchor="w", pady=(5, 10))
        self._rem = ctk.CTkCheckBox(
            pad, text=L["close_remember"], font=_f(10), text_color=MUTED,
            checkbox_width=18, checkbox_height=18, corner_radius=5,
            fg_color=BLURPLE, hover_color=BLURPLE_H, border_color=BORDER, border_width=2)
        self._rem.pack(anchor="w", pady=(0, 12))
        row = ctk.CTkFrame(pad, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(row, text=L["close_quit"], height=38, corner_radius=10,
                      fg_color="transparent", hover_color=HOVER, text_color=SUB,
                      border_width=1, border_color=BORDER, font=_f(12),
                      command=lambda: self._choose("quit")).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(row, text=L["close_tray"], height=38, corner_radius=10,
                      fg_color=BLURPLE, hover_color=BLURPLE_H, text_color=WHITE,
                      font=_f(12, "bold"),
                      command=lambda: self._choose("tray")).grid(row=0, column=1, sticky="ew", padx=(5, 0))

    def _choose(self, r):
        self.remember = bool(self._rem.get())
        self.result = r
        self.destroy()

    def _cancel(self):
        self.result = None
        self.destroy()


# ═══════════════════════════ Temali modal dialog ═══════════════════════════
class _ModalDialog(ctk.CTkToplevel):
    """Uygulama gorunumuyle uyumlu koyu modal — native messagebox yerine.
    confirm=True: Evet/Hayir (result True/False); confirm=False: tek Tamam
    (bilgi/hata, result True). Ust hizali degil, ana pencere ortasina yakin."""
    def __init__(self, app, title, message, confirm=True, ok_text=None,
                 cancel_text=None, checkbox_text=None):
        super().__init__(app)
        # CTkToplevel ilk olusturuldugunda Windows onu kisa sure bagimsiz/bos
        # pencere gibi cizebilir. Hazirlik boyunca gizle; ancak geometri,
        # transient sahiplik ve icerik tamamlandiktan sonra goster.
        self.withdraw()
        self.result = False
        self.option_selected = False
        self._option_var = ctk.BooleanVar(value=False)
        self.title(title)
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        _apply_win_icon(self)
        self._build(title, message, confirm, ok_text, cancel_text, checkbox_text)
        self.update_idletasks()
        w, h = 340, self.winfo_reqheight() + 4
        app.update_idletasks()
        x = app.winfo_x() + (app.winfo_width() - w) // 2
        y = app.winfo_y() + (app.winfo_height() - h) // 3
        self.transient(app)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.attributes("-topmost", True)
        self.deiconify()
        self.lift()
        self.grab_set()
        self.bind("<Escape>", lambda e: self._cancel())

    def _build(self, title, message, confirm, ok_text, cancel_text,
               checkbox_text=None):
        pad = ctk.CTkFrame(self, fg_color=BG)
        pad.pack(fill="both", expand=True, padx=18, pady=16)
        ctk.CTkLabel(pad, text=title, font=_f(15, "bold"),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(pad, text=message, font=_f(11), text_color=SUB,
                     anchor="w", justify="left", wraplength=300).pack(
                         anchor="w", pady=(6, 10 if checkbox_text else 14))
        if checkbox_text:
            ctk.CTkCheckBox(
                pad, text=checkbox_text, variable=self._option_var,
                font=_f(11), text_color=SUB, fg_color=BLURPLE,
                hover_color=BLURPLE_H, border_color=BORDER,
            ).pack(anchor="w", pady=(0, 14))
        row = ctk.CTkFrame(pad, fg_color="transparent")
        row.pack(fill="x", side="bottom")
        if confirm:
            row.grid_columnconfigure((0, 1), weight=1)
            ctk.CTkButton(row, text=cancel_text or L["dlg_no"], height=40, corner_radius=10,
                          fg_color="transparent", hover_color=HOVER, text_color=SUB,
                          border_width=1, border_color=BORDER, font=_f(12),
                          command=self._cancel).grid(row=0, column=0, sticky="ew", padx=(0, 5))
            ctk.CTkButton(row, text=ok_text or L["dlg_yes"], height=40, corner_radius=10,
                          fg_color=BLURPLE, hover_color=BLURPLE_H, text_color=WHITE,
                          font=_f(12, "bold"),
                          command=self._ok).grid(row=0, column=1, sticky="ew", padx=(5, 0))
        else:
            row.grid_columnconfigure(0, weight=1)
            ctk.CTkButton(row, text=ok_text or L["dlg_ok"], height=40, corner_radius=10,
                          fg_color=BLURPLE, hover_color=BLURPLE_H, text_color=WHITE,
                          font=_f(12, "bold"),
                          command=self._ok).grid(row=0, column=0, sticky="ew")

    def _ok(self):
        self.option_selected = bool(self._option_var.get())
        self.result = True
        self.destroy()

    def _cancel(self):
        self.result = False
        self.destroy()


# ═══════════════════════════ Sorun giderme penceresi ═══════════════════════════
class _HelpWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(L["help_title"])
        self.resizable(False, False)
        self.configure(fg_color=BG)
        _apply_win_icon(self)
        self._build()
        # Yardim penceresi ana pencereyle ayni yukseklik: alt+ust hizali, icerik
        # kaydirilabilir alani doldurur (bos alan kalmaz). Ust hizali ve sabit.
        app.update_idletasks()
        self.transient(app)
        _dock_window(app, self, 384, max(470, app.winfo_height()), align_top=True)

    def _build(self):
        ctk.CTkLabel(
            self, text=L["help_title"], font=_f(16, "bold"), text_color=TEXT,
        ).pack(padx=18, pady=(16, 2), anchor="w")
        ctk.CTkLabel(
            self, text=L["help_intro"], font=_f(11), text_color=MUTED,
            anchor="w", justify="left", wraplength=344,
        ).pack(padx=18, pady=(0, 8), anchor="w")

        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent")
        scroll.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        for i, (q, a) in enumerate(L["help_items"], 1):
            card = ctk.CTkFrame(scroll, fg_color=CARD, corner_radius=12,
                                border_width=1, border_color=BORDER)
            card.pack(fill="x", pady=5)
            ctk.CTkLabel(
                card, text=f"{i}.  {q}", font=_f(12, "bold"), text_color=TEXT,
                anchor="w", justify="left", wraplength=306,
            ).pack(fill="x", padx=12, pady=(10, 2))
            ctk.CTkLabel(
                card, text=a, font=_f(11), text_color=SUB,
                anchor="w", justify="left", wraplength=306,
            ).pack(fill="x", padx=12, pady=(0, 11))


# ═══════════════════════════ Log penceresi ═══════════════════════════
class _LogWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(L["log_title"])
        self.resizable(False, False)
        self.configure(fg_color=BG)
        _apply_win_icon(self)
        self._build()
        self.transient(app)
        _dock_window(app, self, 480, 440, align_top=False)

    def _build(self):
        top = ctk.CTkFrame(self, fg_color=CARD, corner_radius=0, height=52)
        top.pack(fill="x")
        top.pack_propagate(False)
        ctk.CTkLabel(
            top, text=L["log_title"],
            font=_f(14, "bold"), text_color=TEXT,
        ).pack(side="left", padx=16, pady=10)
        ctk.CTkButton(
            top, text=L["log_clear"], width=88, height=30, corner_radius=8,
            fg_color="transparent", hover_color=DANGER_HOVER, text_color=SUB,
            border_width=1, border_color=BORDER,
            font=_f(11, "bold"), command=self._clear,
        ).pack(side="right", padx=12, pady=10)

        wrap = ctk.CTkFrame(self, fg_color=BG)
        wrap.pack(fill="both", expand=True, padx=12, pady=12)
        self.txt = ctk.CTkTextbox(
            wrap, fg_color=CARD, text_color=SUB,
            font=("Cascadia Code", 10), state="disabled",
            corner_radius=10, wrap="none", border_width=1, border_color=BORDER,
        )
        self.txt.pack(fill="both", expand=True)
        self._load()

    def _load(self):
        lines = self.app.log_mgr.read_lines(300)
        self.txt.configure(state="normal")
        self.txt.delete("1.0", "end")
        self.txt.insert("end", "".join(reversed(lines)) if lines else L["log_empty"])
        self.txt.configure(state="disabled")

    def _clear(self):
        if self.app._ask(L["log_confirm_t"], L["log_confirm_msg"]):
            self.app.log_mgr.clear()
            self._load()


# ═══════════════════════════ Ayarlar penceresi ═══════════════════════════
class _SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(L["settings_title"])
        self.resizable(False, False)
        self.configure(fg_color=BG)
        _apply_win_icon(self)
        self._build()
        # Yuksekligi icerige gore ayarla (altta bosluk kalmasin), UST kenar hizali
        # ve sabit (kullanici tasiyamaz).
        self.update_idletasks()
        h = self.winfo_reqheight() + 6
        self.transient(app)
        _dock_window(app, self, 320, h, align_top=True)

    def _build(self):
        ctk.CTkLabel(
            self, text=L["settings_title"],
            font=_f(16, "bold"), text_color=TEXT,
        ).pack(padx=20, pady=(18, 10), anchor="w")

        block = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12,
                             border_width=1, border_color=BORDER)
        block.pack(fill="x", padx=20, pady=4)
        block.grid_columnconfigure(0, weight=1)

        self.switches = {}
        items = [
            ("set_tray", "minimize_to_tray", None),
            ("set_ask", "ask_on_close", None),
            ("set_startup", "startup", self._toggle_startup),
        ]
        for i, (label_key, cfg_key, cb) in enumerate(items):
            ctk.CTkLabel(
                block, text=L[label_key], font=_f(12),
                text_color=SUB, anchor="w",
            ).grid(row=i, column=0, sticky="w", padx=(14, 10), pady=13)
            sw = ctk.CTkSwitch(
                block, text="", fg_color=SWITCH_OFF, progress_color=GREEN,
                border_color=SWITCH_BORDER, border_width=2,
                button_color=SWITCH_KNOB, button_hover_color=SWITCH_KNOB_H,
                width=44, switch_width=44, switch_height=22, corner_radius=11,
                command=lambda k=cfg_key, c=cb: self._toggle(k, c),
            )
            sw.grid(row=i, column=1, sticky="e", padx=(0, 14), pady=13)
            val = is_startup_enabled() if cfg_key == "startup" else self.app.cfg.get(
                cfg_key, cfg_key in ("minimize_to_tray", "ask_on_close")
            )
            if val:
                sw.select()
            self.switches[cfg_key] = sw

        # Dil secimi
        langrow = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12,
                               border_width=1, border_color=BORDER)
        langrow.pack(fill="x", padx=20, pady=(10, 4))
        langrow.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            langrow, text=L["set_lang"], font=_f(12),
            text_color=SUB, anchor="w",
        ).grid(row=0, column=0, sticky="w", padx=(14, 10), pady=13)
        self.lang_menu = ctk.CTkOptionMenu(
            langrow, values=["Türkçe", "English"], width=116, height=30,
            corner_radius=8, font=_f(11, "bold"),
            fg_color=CARD2, button_color=BLURPLE, button_hover_color=BLURPLE_H,
            text_color=TEXT, dropdown_fg_color=CARD, dropdown_text_color=TEXT,
            dropdown_hover_color=CARD2,
            command=self._set_lang,
        )
        self.lang_menu.set("Türkçe" if current_lang() == "tr" else "English")
        self.lang_menu.grid(row=0, column=1, sticky="e", padx=(0, 14), pady=10)

        # Loglari Goster (footer'dan buraya tasindi)
        ctk.CTkButton(
            self, text=L["tip_log"], height=34, corner_radius=10,
            fg_color="transparent", hover_color=HOVER, text_color=SUB,
            border_width=1, border_color=BORDER, font=_f(11),
            command=lambda: (self.destroy(), self.app._open_log()),
        ).pack(fill="x", padx=20, pady=(12, 4))

        ctk.CTkButton(
            self, text=L["update_check"], height=34, corner_radius=10,
            fg_color="transparent", hover_color=HOVER, text_color=SUB,
            border_width=1, border_color=BORDER, font=_f(11),
            command=lambda: (self.destroy(), self.app._check_update_clicked()),
        ).pack(fill="x", padx=20, pady=(8, 4))

    def _toggle(self, cfg_key, cb):
        val = bool(self.switches[cfg_key].get())
        if cb:
            cb(val)
        else:
            self.app.cfg.set(cfg_key, val)

    def _toggle_startup(self, val):
        ok = enable_startup() if val else disable_startup()
        if not ok:
            self.app._notify("Hata", "Başlangıç kaydı değiştirilemedi.")
            self.switches["startup"].deselect() if val else self.switches["startup"].select()

    def _set_lang(self, choice):
        code = "tr" if choice.startswith("Tür") else "en"
        self.app.cfg.set("language", code)
        self.destroy()
        self.app.apply_language()
