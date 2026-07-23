"""
core/updater.py
Checks GitHub Releases for a newer DPort setup and downloads it on demand.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional

from core.app_info import APP_NAME, GITHUB_LATEST_API_URL, GITHUB_REPO


class UpdateError(RuntimeError):
    pass


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
        raise UpdateError(f"GitHub yaniti: HTTP {exc.code}") from exc
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


def verify_download(path: str, digest: Optional[str]) -> bool:
    """Indirilmis dosyayi SHA256 digest'e gore dogrular.

    GUVENLIK: digest ZORUNLU. GitHub asset'inde gecerli bir 'sha256:<hex>' yoksa,
    algoritma sha256 degilse veya dosya yoksa dosya DOGRULANAMAZ sayilir ve False
    doner (kurulmaz/calistirilmaz). Cagiran, dosyayi CALISTIRMADAN HEMEN ONCE de
    bunu yeniden cagirmali: indirme ile calistirma arasinda yerel bir surec dosyayi
    degistirmis olabilir (TOCTOU) ve DPort yukseltilmis calistigi icin degistirilmis
    exe de yuksek yetkiyle calisirdi."""
    try:
        if not os.path.isfile(path):
            return False
        if not digest or ":" not in digest:
            return False
        algo, _, expected = digest.partition(":")
        if algo.strip().lower() != "sha256" or not expected.strip():
            return False
        expected = expected.strip().lower()
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 256), b""):
                h.update(chunk)
        return h.hexdigest() == expected
    except Exception:
        return False


def _safe_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name or "")
    return name.strip(" .") or f"{APP_NAME}-Setup.exe"


def download_update(info: dict, dest_dir: str, timeout: int = 30) -> str:
    url = info.get("download_url")
    if not url:
        raise UpdateError("Bu surumde indirilebilir setup dosyasi yok.")

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
        return final_path
    except Exception as exc:
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        raise UpdateError(str(exc)) from exc
