"""
gui/app.py
Discord Baglanti — Turkiye'deki Discord SNI/DPI engelini asan, Discord'a ozel
tek pencerelik arac. Tek tik: DNS (1.1.1.1) + yerel parcalayici role + guncelleme
+ acilis. Durum panosu ile canli geri bildirim.
"""
import os
import sys
import time
import atexit
import socket
import ssl
import threading
import subprocess
import ctypes
import customtkinter as ctk
from tkinter import messagebox

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

from core.adapter_manager import get_active_adapters
from core.dns_manager import set_dns, reset_to_dhcp, restore_dns, get_dns
from core.config_manager import ConfigManager
from core.discord_manager import (
    get_discord_update_status,
    launch_discord,
    installed_discord_version,
)
from core.discord_unblock import (
    DiscordUnblocker,
    add_hosts_redirect,
    remove_hosts_redirect,
    is_hosts_redirect_active,
    doh_resolve,
    last_hosts_error,
)
from core.failsafe import install_logon_failsafe, failsafe_installed
from core.log_manager import LogManager
from core.startup_manager import enable_startup, disable_startup, is_startup_enabled
from core.lang import L, set_lang, current_lang
from core.paths import resource_path, user_data_path
from core.app_info import (
    APP_EMAIL,
    APP_NAME,
    APP_SIGNATURE,
    APP_VERSION,
    GITHUB_RELEASES_URL,
)
from core.updater import UpdateError, check_latest_release, download_update

# ── Tema — modern derin dark + Discord blurple aksani ───────────────────────
BG        = "#0f1016"   # derin arka plan
CARD      = "#181a21"   # yuzey (kart)
CARD2     = "#20232c"   # yukseltilmis yuzey
BLURPLE   = "#5865f2"   # ana aksan
BLURPLE_H = "#4a54d4"   # hover
BLURPLE_L = "#8b93f8"   # acik aksan (degrade ucu)
INDIGO    = "#3a43b0"   # degrade koyu ucu
GREEN     = "#3ba55d"
GREEN_H   = "#2f8c4d"
GREEN_BG  = "#16311f"   # yesil pill zemini
RED       = "#ed4245"
RED_BG    = "#31191b"
YELL      = "#e5a935"
YELL_BG   = "#322a16"
TEXT      = "#f3f4f7"   # ana metin
SUB       = "#c2c6d2"   # ikincil metin
MUTED     = "#767b89"   # soluk / etiket
BORDER    = "#242833"   # ince kenarlik
WHITE     = "#ffffff"

FONT = "Segoe UI"       # Win11 yerel, keskin ve modern


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
    """Alt pencereyi ana pencerenin sag kenarina BITISIK, ust hizali yerlestirir.
    Ekran sagina sigmiyorsa sola gecirir."""
    try:
        app.update_idletasks()
        x = app.winfo_x() + app.winfo_width()
        y = app.winfo_y()
        if x + w > win.winfo_screenwidth():          # saga sigmazsa sola
            x = max(0, app.winfo_x() - w)
        y = min(y, max(0, win.winfo_screenheight() - h))
        win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception:
        win.geometry(f"{w}x{h}")

# Discord acilirken sistem DNS'i bu degerlere ayarlanir (Cloudflare)
DNS_V4 = ("1.1.1.1", "1.0.0.1")
DNS_V6 = ("2606:4700:4700::1111", "2606:4700:4700::1001")

# Tek-ornek IPC — main.py ile AYNI olmali. Ikinci calistirma bu porta baglanip
# "SHOW" gonderir; calisan ornek kendini tepsiden/gorev cubugundan one getirir.
IPC_HOST = "127.0.0.1"
IPC_PORT = 49317


class DPortApp(ctk.CTk):
    VERSION = APP_VERSION

    def __init__(self):
        self.cfg = ConfigManager(user_data_path("config.json"))
        set_lang(self.cfg.get("language", "tr"))

        ctk.set_appearance_mode("dark")
        super().__init__()

        self.log_mgr = LogManager(
            user_data_path("dport.log"),
            enabled=self.cfg.get("log_enabled", True),
        )
        self._busy = False
        self._ping_ms = None
        self._ping_last = 0.0
        self._unblocker = DiscordUnblocker(
            log=lambda m: self.log_mgr.console(f"unblock: {m}")
        )

        # Onceki oturumdan (cokme/zorla kapatma) kalmis olabilecek hosts
        # yonlendirmesini temizle; role kapaliyken bu satirlar Discord'u bozardi.
        try:
            remove_hosts_redirect()
        except Exception:
            pass
        atexit.register(self._disable_discord_unblock)

        self.log_mgr.console(f"{L['title']} v{self.VERSION} başlatıldı")

        self.title(f"{L['title']}")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self.W, self.H = 360, 522
        w, h = self.W, self.H
        self.update_idletasks()
        x = (self.winfo_screenwidth() - w) // 2
        y = (self.winfo_screenheight() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")

        self._apply_icon()
        self._build()
        self._fit_height()          # icerige gore yuksekligi otomatik ayarla (alt satir kesilmesin)
        self._status_tick()
        # Guvenlik agi: role beklenmedik sekilde olurse hosts'u aninda temizle.
        threading.Thread(target=self._watchdog_loop, daemon=True).start()
        # Tek-ornek dinleyici: ikinci calistirma bu pencereyi one getirir.
        self._start_ipc()
        self.after(2500, self._check_updates_on_start)

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
                try:
                    conn.recv(16)  # "SHOW"
                except OSError:
                    pass
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass
                self.after(0, self._show_window)

        threading.Thread(target=listen, daemon=True).start()

    def _show_window(self):
        """Tepside/gizliyse pencereyi geri getirir ve one alir."""
        try:
            self.deiconify()
            self.lift()
            self.focus_force()
            self.attributes("-topmost", True)
            self.after(400, lambda: self.attributes("-topmost", False))
        except Exception:
            pass

    # ─────────────── Tutarli monokrom ikonlar (emoji yerine) ───────────────
    def _ico(self, kind: str, color: str = MUTED, px: int = 16):
        """Her yerde AYNI kutu boyutu ve cizgi kalinliginda, PIL ile cizilmis
        monokrom ikon dondurur (emojiler OS'a gore farkli boyutta cikiyordu)."""
        cache = getattr(self, "_icon_cache", None)
        if cache is None:
            cache = self._icon_cache = {}
        k = (kind, color, px)
        if k not in cache:
            try:
                cache[k] = self._draw_icon(kind, color, px)
            except Exception:
                cache[k] = None
        return cache[k]

    @staticmethod
    def _draw_icon(kind: str, color: str, px: int):
        import math
        from PIL import Image, ImageDraw
        S = px * 5                                   # 5x ciz, CTkImage kuculterek keskinlestirir
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
        return ctk.CTkImage(light_image=im, dark_image=im, size=(px, px))

    @staticmethod
    def _lock_photo(color: str, px: int):
        """Yonetici pill'i icin kucuk, DOLU kilit (canvas'a create_image ile konur;
        boylece emoji hizasizligi olmaz, tam ortali/orantili durur)."""
        from PIL import Image, ImageDraw, ImageTk
        S = px * 6
        rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        kb = (18, 20, 29, 255)                        # pill zemini (#12141d) = keyhole
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
        body.pack(fill="both", expand=True, padx=16, pady=(12, 12))

        # HERO — buyuk baglanti durum karti (canli durum noktasi + ping gostergesi)
        self.hero = ctk.CTkFrame(body, fg_color=CARD, corner_radius=16,
                                 border_width=1, border_color=BORDER)
        self.hero.pack(fill="x", pady=(0, 11))
        h = ctk.CTkFrame(self.hero, fg_color="transparent")
        h.pack(fill="x", padx=17, pady=15)
        h.grid_columnconfigure(1, weight=1)

        self.hero_dot = ctk.CTkLabel(h, text="●", font=_f(24), text_color=MUTED)
        self.hero_dot.grid(row=0, column=0, rowspan=2, padx=(0, 13))
        self.hero_state = ctk.CTkLabel(h, text=L["hero_off"], font=_f(16, "bold"),
                                       text_color=SUB, anchor="w")
        self.hero_state.grid(row=0, column=1, sticky="sw")
        self.hero_sub = ctk.CTkLabel(h, text=L["hero_hint"], font=_f(10),
                                     text_color=MUTED, anchor="w")
        self.hero_sub.grid(row=1, column=1, sticky="nw")
        self.hero_ping = ctk.CTkLabel(h, text="—", font=_f(21, "bold"),
                                      text_color=MUTED)
        self.hero_ping.grid(row=0, column=2, rowspan=2, sticky="e", padx=(8, 0))

        # Detay karti — ikonlu, ayracli satirlar
        card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=14,
                            border_width=1, border_color=BORDER)
        card.pack(fill="x")
        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=3, pady=3)
        inner.grid_columnconfigure(0, weight=1)
        inner.grid_columnconfigure(1, weight=0)

        self.dash = {}
        rows = [
            ("version", "tile",   L["dash_version"]),
            ("dns",     "globe",  L["dash_dns"]),
            ("servers", "unlock", L["dash_servers"]),
        ]
        r = 0
        for i, (key, icon, label) in enumerate(rows):
            ctk.CTkLabel(
                inner, image=self._ico(icon, MUTED, 16), text=f"   {label}",
                compound="left", font=_f(11), text_color=MUTED, anchor="w",
            ).grid(row=r, column=0, sticky="w", padx=(13, 8), pady=9)
            val = ctk.CTkLabel(
                inner, text=L["val_none"], font=_f(12, "bold"),
                text_color=TEXT, anchor="e",
            )
            val.grid(row=r, column=1, sticky="e", padx=(8, 13))
            self.dash[key] = val
            r += 1
            if i < len(rows) - 1:  # satir ayraci
                ctk.CTkFrame(inner, height=1, fg_color=BORDER).grid(
                    row=r, column=0, columnspan=2, sticky="ew", padx=13)
                r += 1

        # Butonlar — YAN YANA (tek satir). Ana buton (Discord'u Ac) daha genis
        # (3:2), accent + play ikonu; ikincil (Normale Don) ghost.
        BTN_H = 46
        btnrow = ctk.CTkFrame(body, fg_color="transparent")
        btnrow.pack(fill="x", pady=(14, 0))
        btnrow.grid_columnconfigure(0, weight=1, uniform="b")
        btnrow.grid_columnconfigure(1, weight=1, uniform="b")

        self.btn_open = ctk.CTkButton(
            btnrow, text=L["btn_open"], height=BTN_H, corner_radius=12,
            fg_color=BLURPLE, hover_color=BLURPLE_H, text_color=WHITE,
            font=_f(13, "bold"), command=self._open_discord,
        )
        self.btn_open.grid(row=0, column=0, sticky="ew", padx=(0, 5))

        self.btn_restore = ctk.CTkButton(
            btnrow, text=L["btn_restore"], height=BTN_H, corner_radius=12,
            fg_color="transparent", hover_color=CARD2, text_color=SUB,
            border_width=1, border_color=BORDER,
            font=_f(13, "bold"), command=self._restore_normal,
        )
        self.btn_restore.grid(row=0, column=1, sticky="ew", padx=(5, 0))

        # Footer — butonlarin hemen altinda. Ikonlar ORTALI (grup halinde),
        # durum yazisi en altta ortali. Bosluklar dengeli.
        bot = ctk.CTkFrame(body, fg_color="transparent")
        bot.pack(fill="x", pady=(0, 0))

        # 4 ikon — fill YOK; frame icerige gore kuculup yatayda ortalanir.
        iconrow = ctk.CTkFrame(bot, fg_color="transparent")
        iconrow.pack(pady=(14, 0))
        for kind, cmd in (("gear", self._open_settings),
                          ("list", self._open_log),
                          ("help", self._open_help),
                          ("tile", self._check_update_clicked),
                          ("info", self._open_about)):
            ctk.CTkButton(
                iconrow, text="", image=self._ico(kind, SUB, 17),
                width=32, height=32, corner_radius=16,
                fg_color=CARD, hover_color=CARD2,
                border_width=1, border_color=BORDER, command=cmd,
            ).pack(side="left", padx=4)

        # Durum — ortali (uzun mesaj sigacak kadar genis; kirpilmaz cunku pencere fit).
        statusrow = ctk.CTkFrame(bot, fg_color="transparent")
        statusrow.pack(fill="x", pady=(11, 0))
        inner = ctk.CTkFrame(statusrow, fg_color="transparent")
        inner.pack(anchor="center")
        self.status_dot = ctk.CTkLabel(inner, text="●", font=_f(13), text_color=MUTED)
        self.status_dot.pack(side="left", padx=(0, 6))
        self.status_lbl = ctk.CTkLabel(
            inner, text=L["st_ready"], font=_f(12, "bold"), text_color=SUB, anchor="w",
        )
        self.status_lbl.pack(side="left")

    # ── Degradeli baslik bandi ──────────────────────────────────────────────
    def _build_header(self):
        H = 74
        try:
            canvas = ctk.CTkCanvas(self, width=self.W, height=H,
                                   highlightthickness=0, bd=0)
            canvas.pack(fill="x")
            # Koyu, indigo-tonlu ince degrade — renkli uygulama ikonu one ciksin.
            self._draw_gradient(canvas, self.W, H, ["#161826", "#1d2138", "#252a4c"])

            # Gercek uygulama ikonu (icon.ico). Yuklenemezse cizilen logoya dus.
            text_x = 60
            loaded = False
            ico = resource_path("assets", "icon.ico")
            if os.path.exists(ico):
                try:
                    from PIL import Image, ImageTk
                    im = Image.open(ico).convert("RGBA").resize((44, 44), Image.LANCZOS)
                    self._logo_img = ImageTk.PhotoImage(im)
                    canvas.create_image(16, H // 2, anchor="w", image=self._logo_img)
                    text_x = 16 + 44 + 12
                    loaded = True
                except Exception:
                    pass
            if not loaded:
                self._draw_logo(canvas, 18, H // 2, 19)

            canvas.create_text(text_x, H // 2 - 8, anchor="w", text=L["title"],
                               font=(FONT, 18, "bold"), fill=WHITE)
            canvas.create_text(text_x, H // 2 + 12, anchor="w", text=f"v{self.VERSION}",
                               font=(FONT, 9, "bold"), fill=BLURPLE_L)

            # Yonetici durumu — koyu chip + cizilmis kilit ikonu + ortalanmis metin.
            adm = self._is_admin()
            pill_txt = L["admin_yes"] if adm else L["admin_no"]
            col = GREEN if adm else RED
            cy = H // 2
            self._pill_img = None
            try:
                self._pill_img = self._lock_photo(col, 12)
            except Exception:
                pass
            iw = 12 if self._pill_img else 0
            pad_l, gap, pad_r = 10, 5, 12
            tw = len(pill_txt) * 6 + 2                 # metin genisligi (yaklasik)
            pw = pad_l + iw + gap + tw + pad_r
            x2 = self.W - 14
            x1 = x2 - pw
            self._round_rect(canvas, x1, cy - 12, x2, cy + 12, 11,
                             fill="#12141d", outline=col, width=1)
            if self._pill_img:                        # kilit — dikey ortali
                canvas.create_image(x1 + pad_l + iw / 2, cy, image=self._pill_img)
            canvas.create_text(x1 + pad_l + iw + gap, cy, anchor="w",
                               text=pill_txt, font=(FONT, 9, "bold"), fill=col)

            # Alt aksan cizgisi — ince blurple, govdeden ayirir.
            canvas.create_rectangle(0, H - 2, self.W, H, fill=BLURPLE, outline="")
            self._header_canvas = canvas
        except Exception:
            # Guvenli geri donus: duz renk baslik
            hdr = ctk.CTkFrame(self, fg_color=CARD, height=H)
            hdr.pack(fill="x")
            ctk.CTkLabel(hdr, text=f"  {L['title']} v{self.VERSION}", font=_f(16, "bold"),
                         text_color=WHITE).pack(side="left", padx=18, pady=20)

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
        threading.Thread(target=self._do_refresh_status, daemon=True).start()
        # panoyu 6 sn'de bir tazele
        self.after(6000, self._status_tick)

    def _do_refresh_status(self):
        active = self._unblocker.is_active()

        # Discord surumu
        ver = installed_discord_version()
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

        # Gateway gecikmesi — sadece yol aktifken ve ~12 sn'de bir olc
        ping_txt = L["val_none"]
        if active:
            if time.time() - self._ping_last > 12:
                self._ping_ms = self._measure_ping()
                self._ping_last = time.time()
            ping_txt = f"{self._ping_ms} ms" if self._ping_ms else L["val_measuring"]

        self.after(0, lambda: self._apply_status(
            active, ver_txt, dns_txt, ping_txt, ver, self._ping_ms if active else None))

    def _apply_status(self, active, ver_txt, dns_txt, ping_txt, ver=None, ping_ms=None):
        if not self.dash:
            return
        # HERO — canli baglanti durumu + ping
        if active:
            self.hero_dot.configure(text_color=GREEN)
            self.hero_state.configure(text=L["hero_on"], text_color=TEXT)
            self.hero_sub.configure(text=L["hero_sub_on"], text_color=SUB)
            self.hero_ping.configure(text=ping_txt, text_color=self._ping_color(ping_ms))
            self.hero.configure(border_color=GREEN)
        else:
            self.hero_dot.configure(text_color=MUTED)
            self.hero_state.configure(text=L["hero_off"], text_color=SUB)
            self.hero_sub.configure(text=L["hero_hint"], text_color=MUTED)
            self.hero_ping.configure(text="—", text_color=MUTED)
            self.hero.configure(border_color=BORDER)

        self.dash["version"].configure(
            text=ver_txt, text_color=TEXT if ver else MUTED)
        self.dash["dns"].configure(
            text=dns_txt, text_color=GREEN if dns_txt == DNS_V4[0] else TEXT)
        self.dash["servers"].configure(
            text=L["servers_all"] if active else L["val_none"],
            text_color=GREEN if active else MUTED)
        # Geri alinacak bir sey varsa (yol aktif YA DA DNS degistirilmis) buton aktif.
        # Onemli: hosts yazilamayip yol acilmasa bile DNS 1.1.1.1'e cekilmis olabilir;
        # bu durumda kullanici DNS'ini geri alabilmeli.
        can_restore = active or bool(self.cfg.get("dns_backup"))
        self.btn_restore.configure(state="normal" if can_restore else "disabled")

    @staticmethod
    def _ping_color(ms):
        if not ms:
            return SUB
        if ms < 80:
            return GREEN
        if ms < 150:
            return YELL
        return RED

    def _measure_ping(self):
        """gateway.discord.gg'ye TLS el sikismasi suresi (ms). Yol aktifken
        sistem cozumu hosts uzerinden role gider; gercek Discord gecikmesini yansitir."""
        try:
            ctx = ssl.create_default_context()
            raw = socket.create_connection(("gateway.discord.gg", 443), timeout=8)
            t0 = time.time()
            tls = ctx.wrap_socket(raw, server_hostname="gateway.discord.gg")
            dt = (time.time() - t0) * 1000
            tls.close()
            return int(dt)
        except Exception:
            return None

    # ─────────────────────────── Discord'u Ac ───────────────────────────
    def _open_discord(self):
        if self._busy:
            return
        self._busy = True
        self.btn_open.configure(state="disabled", text=L["btn_opening"])
        threading.Thread(target=self._open_discord_w, daemon=True).start()

    def _open_discord_w(self):
        try:
            # 1) Sistem DNS'ini 1.1.1.1 yap — ama once ORIJINALI yedekle
            self._st(L["st_setting_dns"], YELL)
            adapters = get_active_adapters()
            if not adapters:
                self._st(L["st_no_adapter"], RED)
                return
            self._backup_dns(adapters)
            for a in adapters:
                ok, msg = set_dns(a["name"], DNS_V4[0], DNS_V4[1], DNS_V6[0], DNS_V6[1])
                self.log_mgr.write(f"DNS | {a['name']} | {'OK' if ok else msg}")
            self._flushdns()

            # 2) Engel asma yolunu ac (role + hosts)
            self._st(L["st_path_prep"], YELL)
            path_ok = self._enable_discord_unblock()

            # 3) Guncelle + ac
            use_updater = self._discord_should_use_updater() and path_ok
            if use_updater:
                self._st(L["st_updating"], YELL)
            else:
                self._st(L["st_opening_fast"], YELL)

            started_at = time.time()
            ok, msg = launch_discord(use_updater=use_updater)
            if not ok:
                self.log_mgr.write(f"DISCORD | Başlatılamadı | {msg}")
                self._st(f"{L['st_not_found']}: {msg}", RED)
                return

            self.log_mgr.write(f"DISCORD | Başlatıldı | {msg}")
            if use_updater:
                self._st(L["st_update_started"], GREEN)
                threading.Thread(
                    target=self._discord_update_result_w, args=(started_at,), daemon=True
                ).start()
            else:
                self._st(L["st_opened"], GREEN)
        finally:
            self._busy = False
            self.after(0, lambda: self.btn_open.configure(state="normal", text=L["btn_open"]))
            self.after(0, self._status_tick)

    # ─────────────────────────── Normale Don ───────────────────────────
    def _restore_normal(self):
        if self._busy:
            return
        if not messagebox.askyesno(L["dlg_restore_t"], L["dlg_restore_msg"]):
            return
        self._busy = True
        self.btn_restore.configure(state="disabled")
        threading.Thread(target=self._restore_normal_w, daemon=True).start()

    def _restore_normal_w(self):
        try:
            self._st(L["st_restoring"], YELL)
            self._disable_discord_unblock()
            self._restore_dns()
            self._flushdns()
            self._st(L["st_restored"], GREEN)
        finally:
            self._busy = False
            self.after(0, self._status_tick)

    # ─────────────────────────── Unblock motoru ───────────────────────────
    def _enable_discord_unblock(self) -> bool:
        """Yerel parcalayici roleyi baslatir ve engellenen Discord host'larini
        (update + API + gateway + CDN) ona yonlendirir."""
        try:
            # DoH on-kontrol: gercek IP'yi guvenli DNS ile cozemiyorsak (bu agda
            # 1.1.1.1 engelli olabilir) role ise yaramaz — yolu hic acma, hosts'u
            # kirletme. Discord yine acilir (eski davranis), ama sistem bozulmaz.
            try:
                if not doh_resolve("discord.com"):
                    raise RuntimeError("bos yanit")
            except Exception as e:
                self.log_mgr.write(f"UNBLOCK | DoH calismiyor, yol acilmadi | {e}")
                self._st(L["st_fail_doh"], RED)
                return False

            if not self._unblocker.start():
                self.log_mgr.write("UNBLOCK | role baslatilamadi (443 mesgul)")
                self._st(L["st_fail_port"], RED)
                return False
            if not add_hosts_redirect():
                err = last_hosts_error()
                self.log_mgr.write(
                    f"UNBLOCK | hosts yazilamadi | {err or 'yonetici izni veya antivirus (HostsFileHijack) engeli'}")
                self._unblocker.stop()  # role acik kalmasin
                self._st(L["st_fail_admin"], RED)
                return False
            self._flushdns()
            self._ensure_failsafe()
            self.log_mgr.write("UNBLOCK | Baglanti yolu acildi (update+API+gateway+CDN)")
            return True
        except Exception as e:
            self.log_mgr.write(f"UNBLOCK | hata | {e}")
            return False

    def _disable_discord_unblock(self):
        """hosts yonlendirmesini kaldirir ve roleyi durdurur; sistemi eski haline getirir."""
        try:
            remove_hosts_redirect()
        except Exception:
            pass
        try:
            self._unblocker.stop()
        except Exception:
            pass
        try:
            self._flushdns()
        except Exception:
            pass

    def _discord_should_use_updater(self) -> bool:
        last_ok = self.cfg.get("discord_last_update_ok_at")
        try:
            last_ok = float(last_ok)
        except (TypeError, ValueError):
            return True
        return (time.time() - last_ok) > (6 * 60 * 60)

    def _discord_update_result_w(self, started_at: float):
        deadline = time.time() + 90
        last_error = None
        last_message = None

        while time.time() < deadline:
            time.sleep(5)
            status, msg = get_discord_update_status(max_age_seconds=120, since_epoch=started_at)
            if status == "ok":
                self.log_mgr.console(f"Updater sonucu: {msg}", level="INFO")
                self.cfg.set("discord_last_update_ok_at", time.time())
                self._st(L["st_update_ok"], GREEN)
                return
            if status == "error":
                last_error = msg
            elif status == "progress" and msg != last_message:
                last_message = msg
                self.log_mgr.console(f"Updater: {msg}", level="INFO")

        if last_error:
            self.log_mgr.console(f"Updater sonucu: {last_error}", level="ERROR")
            self._st(L["st_update_fail"], RED)
        else:
            self.log_mgr.console("Updater sonucu 90 sn içinde kesinleşmedi.", level="WARN")
        # NOT: unblock burada KAPATILMAZ — Discord acikken API/gateway/CDN de bu
        # role uzerinden gidiyor. Temizlik: DnsAngel kapaninca + acilista self-heal.

    # ─────────────────────────── DNS yedek/geri-yukle ───────────────────────────
    def _backup_dns(self, adapters):
        """DNS'i 1.1.1.1 yapmadan ONCE orijinal ayari (bir kez) yedekle.
        Onceki oturumdan (cokme) zaten bizim degerimiz kalmissa onu ORIJINAL
        sanmayiz — mevcut yedegi ezmeyiz; gercek orijinal korunur."""
        if self.cfg.get("dns_backup"):
            return
        backup = {}
        for a in adapters:
            try:
                snap = get_dns(a["name"])
            except Exception:
                continue
            # bizim enjekte ettigimiz deger orijinal degildir; yedekleme
            if snap.get("ipv4", {}).get("primary") in DNS_V4:
                continue
            backup[a["name"]] = snap
        if backup:
            self.cfg.set("dns_backup", backup)
            self.log_mgr.write(f"DNS | orijinal ayar yedeklendi ({len(backup)} adaptor)")

    def _restore_dns(self):
        """Sistem DNS'ini yedeklenmis ORIJINAL ayara dondurur (statik ise statik,
        DHCP ise DHCP). Yedek yoksa DHCP'ye doner."""
        backup = self.cfg.get("dns_backup") or {}
        try:
            for a in get_active_adapters():
                snap = backup.get(a["name"])
                if snap:
                    ok, msg = restore_dns(a["name"], snap)
                    self.log_mgr.write(f"DNS geri | {a['name']} | {'OK' if ok else msg}")
                else:
                    ok, msg = reset_to_dhcp(a["name"])
                    self.log_mgr.write(f"DHCP | {a['name']} | {'OK' if ok else msg}")
        except Exception as e:
            self.log_mgr.write(f"DNS geri | hata | {e}")
        self.cfg.set("dns_backup", None)

    def _ensure_failsafe(self):
        """Logon hosts-temizleyici gorevini kurar (sessiz guvenlik agi). Gorev
        adi degistiyse eskiyi silip yeniyi kurar (failsafe_installed adla sorgular)."""
        try:
            if failsafe_installed():
                return
            if install_logon_failsafe():
                self.log_mgr.console("failsafe: logon hosts-temizleyici gorevi hazir")
        except Exception:
            pass

    def _watchdog_loop(self):
        """Role beklenmedik sekilde olur de hosts yonlendirmesi kalirsa (Discord'u
        bozacak durum), aninda temizle. Program calistigi surece gorev yapar."""
        while True:
            time.sleep(2)
            try:
                if is_hosts_redirect_active() and not self._unblocker.is_active():
                    remove_hosts_redirect()
                    self._flushdns()
                    self.log_mgr.console(
                        "watchdog: role kapali, hosts yonlendirmesi temizlendi", level="WARN"
                    )
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

        def _apply():
            self.status_lbl.configure(text=txt, text_color=col)
            if hasattr(self, "status_dot"):
                self.status_dot.configure(text_color=col)
        self.after(0, _apply)

    @staticmethod
    def _is_admin():
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    # ─────────────────────────── Pencereler ───────────────────────────
    def _check_updates_on_start(self):
        threading.Thread(target=self._run_update_check, args=(False,), daemon=True).start()

    def _check_update_clicked(self):
        self._st(L["st_update_checking"], YELL)
        threading.Thread(target=self._run_update_check, args=(True,), daemon=True).start()

    def _run_update_check(self, notify_when_current: bool):
        try:
            info = check_latest_release(self.VERSION)
        except UpdateError as exc:
            if notify_when_current:
                self.after(0, lambda: messagebox.showerror(L["update_title"], f"{L['update_failed']}\n\n{exc}"))
                self.after(0, lambda: self._st(L["st_ready"], SUB))
            return

        if info.get("available"):
            version = info.get("version") or ""
            if getattr(self, "_update_prompted_version", None) == version and not notify_when_current:
                return
            self._update_prompted_version = version
            self.after(0, lambda: self._prompt_update(info))
        elif notify_when_current:
            self.after(0, lambda: messagebox.showinfo(
                L["update_title"],
                L["update_current"].format(version=self.VERSION),
            ))
            self.after(0, lambda: self._st(L["st_ready"], SUB))

    def _prompt_update(self, info: dict):
        version = info.get("version") or "?"
        if not info.get("download_url"):
            if messagebox.askyesno(
                L["update_title"],
                L["update_no_asset"].format(version=version),
            ):
                self._open_releases_page()
            return

        if messagebox.askyesno(
            L["update_title"],
            L["update_available"].format(version=version, current=self.VERSION),
        ):
            self._st(L["st_update_downloading"], YELL)
            threading.Thread(target=self._download_and_launch_update, args=(info,), daemon=True).start()

    def _download_and_launch_update(self, info: dict):
        try:
            path = download_update(info, user_data_path("updates"))
        except UpdateError as exc:
            self.after(0, lambda: messagebox.showerror(L["update_title"], f"{L['update_failed']}\n\n{exc}"))
            self.after(0, lambda: self._st(L["st_ready"], SUB))
            return

        def _launch():
            if messagebox.askyesno(L["update_title"], L["update_downloaded"]):
                try:
                    subprocess.Popen([path])
                    self.after(500, self.destroy)
                except Exception as exc:
                    messagebox.showerror(L["update_title"], f"{L['update_failed']}\n\n{exc}")
                    self._st(L["st_ready"], SUB)
            else:
                self._st(L["st_ready"], SUB)

        self.after(0, _launch)

    def _open_releases_page(self):
        try:
            import webbrowser
            webbrowser.open(GITHUB_RELEASES_URL)
        except Exception:
            pass

    def _open_log(self):
        _LogWindow(self)

    def _open_settings(self):
        _SettingsWindow(self)

    def _open_help(self):
        _HelpWindow(self)

    def _open_about(self):
        _AboutWindow(self)

    def apply_language(self):
        """Dil degisince arayuzu yeniden kur."""
        set_lang(self.cfg.get("language", "tr"))
        for w in self.winfo_children():
            w.destroy()
        self.dash = {}
        self.title(L["title"])
        self._build()

    # ─────────────────────────── Kapanis / tepsi ───────────────────────────
    def destroy(self):
        # Tamamen kapanirken yonlendirmeyi geri al, roleyi durdur, IPC'yi kapat.
        try:
            if getattr(self, "_ipc_srv", None):
                self._ipc_srv.close()
        except Exception:
            pass
        self._disable_discord_unblock()
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
            self.withdraw()
            icon_path = resource_path("assets", "icon.ico")
            if os.path.exists(icon_path):
                img = Image.open(icon_path)
            else:
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                ImageDraw.Draw(img).ellipse([4, 4, 60, 60], fill=BLURPLE)

            def on_open(icon, _):
                icon.stop()
                self.after(0, self._show_window)

            def on_quit(icon, _):
                icon.stop()
                self.after(0, self.destroy)

            menu = pystray.Menu(
                pystray.MenuItem(f"{L['title']}", on_open, default=True),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Exit / Cikis", on_quit),
            )
            pystray.Icon("dport", img, L["title"], menu).run_detached()
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
        _place_beside(app, self, 322, 306)

    def _build(self):
        pad = ctk.CTkFrame(self, fg_color=BG)
        pad.pack(fill="both", expand=True, padx=20, pady=18)

        # Logo + isim + surum
        top = ctk.CTkFrame(pad, fg_color="transparent")
        top.pack(fill="x")
        try:
            from PIL import Image
            ic = resource_path("assets", "icon.ico")
            if os.path.exists(ic):
                im = Image.open(ic).convert("RGBA")
                self._img = ctk.CTkImage(light_image=im, dark_image=im, size=(48, 48))
                ctk.CTkLabel(top, image=self._img, text="").pack(side="left")
        except Exception:
            pass
        namebox = ctk.CTkFrame(top, fg_color="transparent")
        namebox.pack(side="left", padx=12)
        ctk.CTkLabel(namebox, text=APP_NAME, font=_f(19, "bold"),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(namebox, text=f"v{self.app.VERSION}", font=_f(10),
                     text_color=MUTED, anchor="w").pack(anchor="w")
        ctk.CTkLabel(namebox, text=f"by {APP_SIGNATURE}", font=_f(10),
                     text_color=BLURPLE_L, anchor="w").pack(anchor="w")

        ctk.CTkFrame(pad, height=1, fg_color=BORDER).pack(fill="x", pady=14)

        # Bilgi karti — Gelistirici / E-posta
        info = ctk.CTkFrame(pad, fg_color=CARD, corner_radius=12,
                            border_width=1, border_color=BORDER)
        info.pack(fill="x")
        info.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(info, text=L["about_dev"], font=_f(11), text_color=MUTED,
                     anchor="w").grid(row=0, column=0, sticky="w", padx=(14, 10), pady=(12, 6))
        ctk.CTkLabel(info, text=L["about_dev_name"], font=_f(11, "bold"), text_color=TEXT,
                     anchor="e").grid(row=0, column=1, sticky="e", padx=(0, 14), pady=(12, 6))
        ctk.CTkLabel(info, text=L["about_email"], font=_f(11), text_color=MUTED,
                     anchor="w").grid(row=1, column=0, sticky="w", padx=(14, 10), pady=(6, 12))
        mail = ctk.CTkLabel(info, text=L["about_email_addr"],
                            font=ctk.CTkFont(FONT, 11, underline=True),
                            text_color=BLURPLE_L, anchor="e", cursor="hand2")
        mail.grid(row=1, column=1, sticky="e", padx=(0, 14), pady=(6, 12))
        mail.bind("<Button-1>", lambda e: self._mail())

        ctk.CTkLabel(info, text=L["about_signature"], font=_f(11), text_color=MUTED,
                     anchor="w").grid(row=2, column=0, sticky="w", padx=(14, 10), pady=(0, 12))
        ctk.CTkLabel(info, text=APP_SIGNATURE, font=_f(11, "bold"), text_color=BLURPLE_L,
                     anchor="e").grid(row=2, column=1, sticky="e", padx=(0, 14), pady=(0, 12))

        # Kisa amac (en alt)
        ctk.CTkLabel(pad, text=L["about_purpose"], font=_f(10), text_color=SUB,
                     anchor="w", justify="left", wraplength=282).pack(anchor="w", pady=(16, 0))

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
        self.result = None
        self.remember = False
        self.title(L["close_title"])
        self.resizable(False, False)
        self.configure(fg_color=BG)
        self.protocol("WM_DELETE_WINDOW", self._cancel)
        _apply_win_icon(self)
        self._build()
        w, h = 344, 212
        app.update_idletasks()
        x = app.winfo_x() + (app.winfo_width() - w) // 2
        y = app.winfo_y() + (app.winfo_height() - h) // 3
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.transient(app)
        self.grab_set()
        self.attributes("-topmost", True)

    def _build(self):
        pad = ctk.CTkFrame(self, fg_color=BG)
        pad.pack(fill="both", expand=True, padx=18, pady=16)
        ctk.CTkLabel(pad, text=L["close_title"], font=_f(15, "bold"),
                     text_color=TEXT, anchor="w").pack(anchor="w")
        ctk.CTkLabel(pad, text=L["close_msg"], font=_f(11), text_color=SUB,
                     anchor="w", justify="left", wraplength=304).pack(anchor="w", pady=(6, 12))
        self._rem = ctk.CTkCheckBox(
            pad, text=L["close_remember"], font=_f(10), text_color=MUTED,
            checkbox_width=18, checkbox_height=18, corner_radius=5,
            fg_color=BLURPLE, hover_color=BLURPLE_H, border_color=BORDER, border_width=2)
        self._rem.pack(anchor="w", pady=(0, 14))
        row = ctk.CTkFrame(pad, fg_color="transparent")
        row.pack(fill="x", side="bottom")
        row.grid_columnconfigure((0, 1), weight=1)
        ctk.CTkButton(row, text=L["close_quit"], height=40, corner_radius=10,
                      fg_color="transparent", hover_color=CARD2, text_color=SUB,
                      border_width=1, border_color=BORDER, font=_f(12),
                      command=lambda: self._choose("quit")).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ctk.CTkButton(row, text=L["close_tray"], height=40, corner_radius=10,
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
        _place_beside(app, self, 384, 470)

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
        self.configure(fg_color=BG)
        _apply_win_icon(self)
        self._build()
        _place_beside(app, self, 480, 440)

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
            fg_color="transparent", hover_color=RED, text_color=SUB,
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
        if messagebox.askyesno(L["log_confirm_t"], L["log_confirm_msg"]):
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
        self.grab_set()
        _apply_win_icon(self)
        self._build()
        _place_beside(app, self, 320, 424)

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
                block, text="", fg_color=CARD2, progress_color=GREEN,
                button_color=WHITE, width=40, switch_width=40, switch_height=20,
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
            command=self._set_lang,
        )
        self.lang_menu.set("Türkçe" if current_lang() == "tr" else "English")
        self.lang_menu.grid(row=0, column=1, sticky="e", padx=(0, 14), pady=10)

        # Loglari Goster (footer'dan buraya tasindi)
        ctk.CTkButton(
            self, text=L["tip_log"], height=34, corner_radius=10,
            fg_color="transparent", hover_color=CARD2, text_color=SUB,
            border_width=1, border_color=BORDER, font=_f(11),
            command=lambda: (self.destroy(), self.app._open_log()),
        ).pack(fill="x", padx=20, pady=(12, 4))

        ctk.CTkButton(
            self, text=L["update_check"], height=34, corner_radius=10,
            fg_color="transparent", hover_color=CARD2, text_color=SUB,
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
            messagebox.showerror("Hata", "Başlangıç kaydı değiştirilemedi.")
            self.switches["startup"].deselect() if val else self.switches["startup"].select()

    def _set_lang(self, choice):
        code = "tr" if choice.startswith("Tür") else "en"
        self.app.cfg.set("language", code)
        self.destroy()
        self.app.apply_language()
