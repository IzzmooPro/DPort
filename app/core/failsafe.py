"""
core/failsafe.py

hosts-yonlendirmesi guvenlik agi.

Discord'un engelli host'lari (discord.com, gateway... vb.) program calisirken
127.0.0.1'e yonlendiriliyor. Program NORMAL kapanmadan olurse (cokme, Gorev
Yoneticisi'nden kapatma, ani elektrik, mavi ekran) bu satirlar hosts'ta kalir ve
Discord + tarayicidan discord.com TAMAMEN acilmaz.

Bu modul, her oturum acilista (logon) YUKSEK YETKIYLE sessizce calisan bir
zamanlanmis gorev kurar. Gorev, programin kendisini `--cleanup-hosts` ile
cagirir; o da hosts'taki isaretli blogu siler. Boylece program bir daha hic
acilmasa bile Discord en gec bir sonraki oturumda tekrar normale doner.
"""
import os
import sys
import subprocess

TASK_NAME = "DPortHostsFailsafe"
_LEGACY_TASKS = ("DiscordConnectHostsFailsafe",)

_FLAGS = subprocess.CREATE_NO_WINDOW


def _cleanup_command() -> str:
    """hosts temizleyiciyi calistiran komut satiri (frozen exe veya betik)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}" --cleanup-hosts'
    return f'"{sys.executable}" "{os.path.abspath(sys.argv[0])}" --cleanup-hosts'


def _exe_in_protected_location() -> bool:
    """Calisan exe, standart kullanicinin YAZAMADIGI korumali bir konumda mi
    (Program Files vb.)? Yuksek-yetkili logon gorevi yalnizca boyle bir konumdaki
    exe'ye baglanmali; aksi halde (Masaustu/Indirilenler/AppData gibi yazilabilir
    klasordeki portable exe) yonetici-olmayan bir surec exe'yi degistirip gorevle
    yuksek yetkiyle calistirabilirdi (yerel yetki yukseltme)."""
    try:
        exe = os.path.normcase(os.path.abspath(sys.executable))
        for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
            root = os.environ.get(var)
            if root:
                root = os.path.normcase(os.path.abspath(root)) + os.sep
                if exe.startswith(root):
                    return True
    except Exception:
        pass
    return False


def install_logon_failsafe() -> bool:
    """Logon'da yuksek yetkiyle hosts temizleyen zamanlanmis gorevi kurar.
    Once eski surumden kalmis gorevleri siler (isim degistiyse artik kalmasin).

    GUVENLIK: Gorev YALNIZCA paketlenmis (frozen) exe icin kurulur. Kaynaktan
    calisirken gorev, yazilabilir bir .py betigine HIGHEST yetkiyle isaret ederdi;
    yonetici-olmayan bir surec o betigi degistirip bir sonraki oturum acilisinda
    yuksek yetkiyle calistirabilirdi (yerel yetki yukseltme). Bu yuzden kaynak
    modunda gorev KURULMAZ — calisirken watchdog ve acilis self-heal zaten korur.

    Ek olarak exe yalnizca KORUMALI konumdaysa (Program Files) gorev kurulur;
    yazilabilir klasordeki portable exe icin kurulmaz (ayni LPE riski). Installer
    ile Program Files'a kurulan surumler etkilenmez."""
    if not getattr(sys, "frozen", False) or not _exe_in_protected_location():
        return False
    for old in _LEGACY_TASKS:
        try:
            subprocess.run(["schtasks", "/Delete", "/TN", old, "/F"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", timeout=15, creationflags=_FLAGS)
        except Exception:
            pass
    try:
        r = subprocess.run(
            ["schtasks", "/Create", "/TN", TASK_NAME,
             "/TR", _cleanup_command(),
             "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=15, creationflags=_FLAGS,
        )
        return r.returncode == 0
    except Exception:
        return False


def remove_logon_failsafe() -> bool:
    try:
        subprocess.run(
            ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=15, creationflags=_FLAGS,
        )
        return True
    except Exception:
        return False


def failsafe_installed() -> bool:
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=15, creationflags=_FLAGS,
        )
        return r.returncode == 0
    except Exception:
        return False
