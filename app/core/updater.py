"""
core/updater.py
Checks GitHub Releases for a newer DPort setup and downloads it on demand.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import ssl
import urllib.error
import urllib.request
from typing import Optional, Tuple

from core.app_info import APP_NAME, GITHUB_LATEST_API_URL, GITHUB_REPO
from core.secure_store import GuardedFile


class UpdateError(RuntimeError):
    def __init__(self, message, *, retryable=False):
        super().__init__(message)
        self.retryable = retryable


def _version_parts(value: str) -> tuple[int, ...]:
    value = (value or "").strip().lower()
    if value.startswith("v"):
        value = value[1:]
    parts = [int(p) for p in re.findall(r"\d+", value)]
    return tuple(parts or [0])


def is_newer_version(latest: str, current: str) -> bool:
    latest_parts = list(_version_parts(latest))
    current_parts = list(_version_parts(current))
    size = max(len(latest_parts), len(current_parts))
    latest_parts += [0] * (size - len(latest_parts))
    current_parts += [0] * (size - len(current_parts))
    return tuple(latest_parts) > tuple(current_parts)


def _request_json(url: str, timeout: int = 10) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{APP_NAME}-Updater",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise UpdateError(f"GitHub release bulunamadi: {GITHUB_REPO}") from exc
        raise UpdateError(
            f"GitHub yaniti: HTTP {exc.code}",
            retryable=exc.code in {408, 429, 500, 502, 503, 504},
        ) from exc
    except urllib.error.URLError as exc:
        raise UpdateError(
            str(exc), retryable=not isinstance(exc.reason, ssl.SSLCertVerificationError)
        ) from exc
    except (TimeoutError, ConnectionError) as exc:
        raise UpdateError(str(exc), retryable=True) from exc
    except Exception as exc:
        raise UpdateError(str(exc)) from exc


def _pick_setup_asset(assets: list[dict]) -> Optional[dict]:
    # Dosya adini SABITLE: yalnizca "DPort-Setup..." adli exe kabul edilir. Boylece
    # release'e alakasiz/kotu niyetli baska bir exe konsa (veya yanlislikla) updater
    # onu SECMEZ. Beklenen asset yoksa None (rastgele exe'ye dusmez).
    named = [
        a for a in assets
        if str(a.get("name", "")).lower().startswith("dport-setup")
        and str(a.get("name", "")).lower().endswith(".exe")
        and a.get("browser_download_url")
    ]
    return named[0] if named else None


def check_latest_release(current_version: str) -> dict:
    release = _request_json(GITHUB_LATEST_API_URL)
    tag = str(release.get("tag_name") or release.get("name") or "").strip()
    latest_version = tag[1:] if tag.lower().startswith("v") else tag
    asset = _pick_setup_asset(release.get("assets") or [])
    available = bool(latest_version and is_newer_version(latest_version, current_version))

    return {
        "available": available,
        "version": latest_version,
        "tag": tag,
        "release_url": release.get("html_url"),
        "asset_name": asset.get("name") if asset else None,
        "download_url": asset.get("browser_download_url") if asset else None,
        # GitHub asset digest'i (or. "sha256:abc..."). Varsa indirmeyi dogrulariz;
        # eski release'lerde bulunmayabilir, o zaman dogrulama atlanir.
        "digest": asset.get("digest") if asset else None,
        "body": release.get("body") or "",
    }


def expected_sha256(digest: Optional[str]) -> Optional[str]:
    """GitHub asset digest'inden ('sha256:<hex>') beklenen hex ozeti cikarir.

    GUVENLIK: digest ZORUNLU. Deger yoksa, bicimi bozuksa veya algoritma sha256
    degilse None doner ve cagiran taraf dosyayi DOGRULANAMAZ sayar."""
    if not digest or ":" not in digest:
        return None
    algo, _, expected = digest.partition(":")
    if algo.strip().lower() != "sha256":
        return None
    expected = expected.strip().lower()
    if not expected or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return None
    return expected


def verify_download(path: str, digest: Optional[str]) -> bool:
    """Indirilmis dosyayi SHA256 digest'e gore dogrular (indirme sonrasi kontrol).

    Calistirma ONCESI dogrulama icin bu fonksiyon TEK BASINA yeterli DEGILDIR:
    dosyayi acar, okur, kapatir; donusuyle CreateProcess arasinda yerel bir surec
    dosyayi degistirebilir (TOCTOU) ve DPort yukseltilmis calistigi icin
    degistirilmis exe de yuksek yetkiyle calisirdi. Calistirma yolu icin
    `launch_verified()` kullanilir: o, hash'i KILITLI HANDLE uzerinden hesaplar ve
    handle acikken sureci baslatir."""
    try:
        expected = expected_sha256(digest)
        if not expected or not os.path.isfile(path):
            return False
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 256), b""):
                h.update(chunk)
        return h.hexdigest() == expected
    except Exception:
        return False


def launch_verified(path: str, digest: Optional[str]) -> Tuple[bool, str]:
    """Installer'i, DOGRULANAN BAYTLARIN TA KENDISI calisacak sekilde baslatir.

    Akis:
      1. Dosya FILE_SHARE_READ ile acilir. Handle acik oldugu surece baska bir
         surec dosyayi yazamaz, silemez, yeniden adlandiramaz.
      2. SHA-256 bu HANDLE uzerinden hesaplanir (yol yeniden acilmaz).
      3. Hash uyusursa, handle HALA ACIKKEN CreateProcess yapilir. CreateProcess
         imaji okuma+calistirma icin acar; bu, FILE_SHARE_READ ile uyumludur.
      4. Handle kapatilir. Bu noktada imaj zaten dogrulanmis baytlardan
         eslenmistir.

    Boylece dogrulama ile calistirma arasinda dosya degistirme PENCERESI KALMAZ.
    Donus: (basarili_mi, hata_metni). Dogrulama basarisizsa surec BASLATILMAZ."""
    expected = expected_sha256(digest)
    if not expected:
        return False, "gecerli SHA256 digest yok"
    if not os.path.isfile(path):
        return False, "indirilen dosya bulunamadi"

    guard = GuardedFile(path)
    if not guard.open():
        return False, "indirilen dosya guvenli sekilde kilitlenemedi"
    try:
        actual = guard.sha256_hex()
        if actual is None:
            return False, "indirilen dosya okunamadi"
        if actual != expected:
            return False, "SHA256 uyusmadi"
        try:
            subprocess.Popen([path], close_fds=True)
        except Exception as exc:
            return False, str(exc)
        return True, ""
    finally:
        guard.close()


def purge_setup_dir(directory: str, keep: Optional[str] = None) -> int:
    """Indirilmis eski setup dosyalarini temizler.

    GUVENLIK: birikmis installer'lar, ozellikle kullanici-yazilabilir eski
    `%APPDATA%\\DPort\\updates` konumunda, saldirganin onceden hazirlayabilecegi
    ikili yigini olusturur. Yalnizca DPort'un kendi urettigi ad kalibi silinir
    (`DPort-Setup*.exe`, `*.download`); baska hicbir dosyaya dokunulmaz.
    Donus: silinen dosya sayisi."""
    removed = 0
    if not directory or not os.path.isdir(directory):
        return 0
    keep_norm = os.path.normcase(os.path.abspath(keep)) if keep else None
    try:
        names = os.listdir(directory)
    except OSError:
        return 0
    for name in names:
        lower = name.lower()
        is_setup = lower.startswith(f"{APP_NAME.lower()}-setup") and lower.endswith(".exe")
        if not (is_setup or lower.endswith(".download")):
            continue
        full = os.path.join(directory, name)
        if keep_norm and os.path.normcase(os.path.abspath(full)) == keep_norm:
            continue
        try:
            if os.path.isfile(full):
                os.remove(full)
                removed += 1
        except OSError:
            continue
    return removed


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
    return name.strip(" .") or f"{APP_NAME}-Setup.exe"


def download_update(info: dict, dest_dir: str, timeout: int = 30) -> str:
    """Setup dosyasini `dest_dir` altina indirir ve SHA-256 ile dogrular.

    GUVENLIK: `dest_dir` ACL-KORUMALI olmalidir (bkz. secure_store.update_staging_dir).
    Kullanici-yazilabilir bir dizine indirmek, dosyanin calistirilmadan once
    degistirilmesine kapi acar."""
    url = info.get("download_url")
    if not url:
        raise UpdateError("Bu surumde indirilebilir setup dosyasi yok.")
    if not dest_dir:
        raise UpdateError("Guvenli indirme dizini hazirlanamadi.")

    os.makedirs(dest_dir, exist_ok=True)
    filename = _safe_filename(info.get("asset_name") or f"{APP_NAME}-Setup-{info.get('version')}.exe")
    final_path = os.path.join(dest_dir, filename)
    tmp_path = f"{final_path}.download"

    req = urllib.request.Request(
        url,
        headers={"User-Agent": f"{APP_NAME}-Updater"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp, open(tmp_path, "wb") as f:
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
        # Dosya butunlugunu dogrula. GUVENLIK: gecerli SHA256 digest ZORUNLU;
        # yoksa/uyusmazsa dosya SILINIR ve kurulmaz.
        if not verify_download(tmp_path, info.get("digest")):
            raise UpdateError(
                "Guncelleme dogrulanamadi (gecerli SHA256 digest yok veya uyusmadi); "
                "guvenlik icin indirilmedi.")
        os.replace(tmp_path, final_path)
        # Onceki surumlerden kalan setup dosyalari birikmesin (gereksiz ikili
        # yigini = gereksiz saldiri yuzeyi).
        purge_setup_dir(dest_dir, keep=final_path)
        return final_path
    except Exception as exc:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise UpdateError(str(exc)) from exc
