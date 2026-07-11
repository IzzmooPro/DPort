"""
core/discord_manager.py
Discord kurulumunu bulur ve Discord'un kendi updater yolu ile acilmasini saglar.
"""
import os
import subprocess
import time
from datetime import datetime
from typing import Dict, Optional, Tuple


DISCORD_ROOT_NAMES = ("Discord", "DiscordCanary", "DiscordPTB")


def _discord_roots():
    local = os.environ.get("LOCALAPPDATA", "")
    return [os.path.join(local, name) for name in DISCORD_ROOT_NAMES]


def find_discord_update() -> Optional[str]:
    for root in _discord_roots():
        path = os.path.join(root, "Update.exe")
        if os.path.exists(path):
            return path
    return None


def find_discord_exe() -> Optional[str]:
    candidates = []
    for root in _discord_roots():
        if not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                if not name.startswith("app-"):
                    continue
                exe = os.path.join(root, name, "Discord.exe")
                if os.path.exists(exe):
                    candidates.append((name, exe))
        except OSError:
            continue

    if not candidates:
        return None

    candidates.sort(reverse=True)
    return candidates[0][1]


def installed_discord_version() -> Optional[str]:
    """Kurulu en yuksek Discord surumunu dondurur (or. '1.0.9244')."""
    best = None
    for root in _discord_roots():
        if not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                if name.startswith("app-") and os.path.exists(
                    os.path.join(root, name, "Discord.exe")
                ):
                    ver = name[4:]
                    if best is None or _ver_tuple(ver) > _ver_tuple(best):
                        best = ver
        except OSError:
            continue
    return best


def _ver_tuple(ver: str):
    parts = []
    for p in ver.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def is_discord_running() -> bool:
    return get_discord_process_info()["running"]


def get_discord_process_info() -> Dict:
    try:
        result = subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-Process Discord -ErrorAction SilentlyContinue | "
                "Select-Object Id,MainWindowTitle,Path | ConvertTo-Json -Compress",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {"running": False, "count": 0, "has_window": False, "paths": []}

        import json

        raw = json.loads(result.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        paths = sorted({item.get("Path") for item in raw if item.get("Path")})
        has_window = any((item.get("MainWindowTitle") or "").strip() for item in raw)
        return {
            "running": bool(raw),
            "count": len(raw),
            "has_window": has_window,
            "paths": paths,
        }
    except Exception:
        return {"running": False, "count": 0, "has_window": False, "paths": []}


def launch_discord(use_updater: bool = True, ensure_closed: bool = True) -> Tuple[bool, str]:
    """ensure_closed=True (varsayilan, eski guvenli davranis): Update.exe
    yoluna girmeden once kendi close_discord_processes() + 1 sn bekleme
    adimini calistirir. Cagiran taraf sureclerin KAPANDIGINI ZATEN dogrulamis
    kapatilmasi zaten (ornegin _wait_discord_closed ile) ise ensure_closed=False
    verip bu ikinci/gereksiz kapatma adimini atlayabilir."""
    if not use_updater:
        ok, msg = launch_discord_direct()
        if ok:
            return ok, msg

    update_exe = find_discord_update()
    if update_exe:
        try:
            if ensure_closed:
                close_discord_processes()
                time.sleep(1)
            subprocess.Popen(
                [update_exe, "--processStart", "Discord.exe"],
                cwd=os.path.dirname(update_exe),
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            return True, f"Update.exe ile baslatildi | {update_exe}"
        except Exception as e:
            return False, str(e)

    discord_exe = find_discord_exe()
    if not discord_exe:
        return False, "Discord.exe veya Update.exe bulunamadi."

    try:
        subprocess.Popen(
            [discord_exe],
            cwd=os.path.dirname(discord_exe),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, f"Discord.exe dogrudan baslatildi | {discord_exe}"
    except Exception as e:
        return False, str(e)


def launch_discord_direct() -> Tuple[bool, str]:
    discord_exe = find_discord_exe()
    if not discord_exe:
        return False, "Discord.exe bulunamadi."

    try:
        subprocess.Popen(
            [discord_exe],
            cwd=os.path.dirname(discord_exe),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return True, f"Discord.exe dogrudan baslatildi | {discord_exe}"
    except Exception as e:
        return False, str(e)


def get_discord_update_status(
    max_age_seconds: int = 120,
    since_epoch: Optional[float] = None,
) -> Tuple[str, str]:
    log_path = _discord_updater_log_path()
    if not log_path or not os.path.exists(log_path):
        return "unknown", "Discord updater logu bulunamadi."

    try:
        age = time.time() - os.path.getmtime(log_path)
        if age > max_age_seconds:
            return "unknown", f"Discord updater logu eski ({int(age)} sn)."

        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-500:]
    except Exception as e:
        return "unknown", f"Discord updater logu okunamadi: {e}"

    latest = None
    saw_current_attempt = False
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        line_epoch = _log_line_epoch(line)
        if since_epoch is not None and line_epoch is not None and line_epoch < since_epoch - 1:
            continue
        if "Update to latest complete" in line:
            latest = ("ok", "Discord update kontrolu tamamlandi.")
        elif "Already up to date" in line:
            latest = ("progress", "Discord guncel gorunuyor, tamamlanma bekleniyor.")
        elif "Starting update to latest" in line or "Requesting manifest" in line:
            saw_current_attempt = True
            latest = ("progress", "Discord update kontrol ediyor.")
        elif "SetManifests(Running" in line:
            saw_current_attempt = True
            latest = ("progress", "Discord update manifesti alindi.")
        elif "Executing download tasks" in line:
            latest = ("progress", "Discord update indiriyor.")
        elif "Host to be installed" in line:
            latest = ("progress", "Discord ana guncelleme paketi bulundu.")
        elif "Requesting installation of module" in line:
            latest = ("progress", "Discord modulleri yukleniyor.")
        elif "Install of module" in line and "finished successfully" in line:
            latest = ("progress", "Discord modulleri yukleniyor.")
        elif "ERROR [updater_client]" in line:
            latest = ("error", _compact_log_line(line))
        elif "Failed " in line and "Failed to remove Windows arch transition flag" not in line:
            latest = ("error", _compact_log_line(line))

    if latest:
        return latest
    if saw_current_attempt:
        return "progress", "Discord update kontrol ediyor."
    return "unknown", "Discord updater sonucu henuz net degil."


def _discord_updater_log_path() -> Optional[str]:
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        return None
    return os.path.join(appdata, "discord", "logs", "Discord_updater_rCURRENT.log")


def _compact_log_line(line: str, limit: int = 260) -> str:
    text = " ".join(line.split())
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _log_line_epoch(line: str) -> Optional[float]:
    if not line.startswith("[") or "]" not in line:
        return None
    raw = line[1 : line.index("]")]
    # Ornek: 2026-07-02 03:26:03.514138 +03:00
    raw = raw.split(" +", 1)[0].split(" -", 1)[0]
    try:
        dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f")
    except ValueError:
        try:
            dt = datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None
    return time.mktime(dt.timetuple()) + (dt.microsecond / 1_000_000)


def close_discord_processes() -> Tuple[bool, str]:
    """Yalnizca _discord_roots() (LocalAppData\\Discord|DiscordPTB|DiscordCanary)
    altindaki Discord.exe/Update.exe sureclerini kapatir; eslesme surecin gercek
    .Path'inin bu koklerden biriyle basladigina bakar. Sistemdeki BASKA bir
    uygulamaya ait Update.exe (or. farkli bir Squirrel tabanli app) asla hedef
    alinmaz. Donus: (komut hatasiz calisti mi, kac surece sinyal gonderildigi/ozet)."""
    roots = [root for root in _discord_roots() if os.path.isdir(root)]
    if not roots:
        return True, "Discord kurulum klasoru bulunamadi, kapatilacak surec yok."

    ps_roots = ", ".join("'" + root.replace("'", "''") + "'" for root in roots)
    command = (
        f"$roots=@({ps_roots}); $hit=0; "
        "Get-Process -Name Discord,Update -ErrorAction SilentlyContinue | ForEach-Object { "
        "$path=$_.Path; if (-not $path) { return }; "
        "foreach ($root in $roots) { "
        "if ($path.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) { "
        "Stop-Process -Id $_.Id -Force -ErrorAction SilentlyContinue; $hit++; break "
        "} } }; "
        "Write-Output $hit"
    )
    try:
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
            timeout=8,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        if result.returncode != 0:
            return False, f"PowerShell hatasi: {(result.stderr or result.stdout).strip()}"
        hit = (result.stdout or "0").strip() or "0"
        return True, f"{hit} Discord/Update surecine kapatma sinyali gonderildi."
    except Exception as e:
        return False, str(e)
