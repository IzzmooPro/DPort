"""
tests/test_release_alignment.py

Yayin oncesi surum hizalamasi. Repo kurali: APP_VERSION, Inno MyAppVersion,
README rozeti ve uretilen `DPort-Setup-X.Y.exe` adi AYNI olmalidir.

Tarihsel surum notlari ve gercek ekran goruntusunun surum etiketi korunur.
"""
import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_APP = os.path.join(_ROOT, "app")
if _APP not in sys.path:
    sys.path.insert(0, _APP)

from core.app_info import APP_NAME, APP_VERSION      # noqa: E402
from core.updater import _pick_setup_asset, is_newer_version  # noqa: E402

# Bu surumun supersede ettigi, en son YAYINLANMIS surum.
PREVIOUS_RELEASE = "3.17"

_ISS = os.path.join(_ROOT, "packaging", "DPort.iss")
_README = os.path.join(_ROOT, "README.md")


def _read(path: str) -> str:
    with open(path, encoding="utf-8", errors="ignore") as f:
        return f.read()


class TestReleaseAlignment(unittest.TestCase):

    def test_app_version_shape(self):
        self.assertRegex(APP_VERSION, r"^\d+\.\d+$",
                         f"beklenmeyen surum bicimi: {APP_VERSION!r}")

    def test_inno_version_matches_app_version(self):
        self.assertTrue(os.path.isfile(_ISS), "Takip edilen installer kaynagi eksik")
        text = _read(_ISS)
        m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
        self.assertIsNotNone(m, "MyAppVersion bulunamadi")
        self.assertEqual(m.group(1), APP_VERSION,
                         "Inno MyAppVersion ile APP_VERSION uyusmuyor")

    def test_installer_uses_verified_immediate_close_without_restart_manager(self):
        text = _read(_ISS)
        self.assertRegex(text, r"(?m)^CloseApplications=no\s*$")
        self.assertRegex(text, r"(?m)^RestartApplications=no\s*$")
        self.assertNotRegex(text, r"(?m)^CloseApplications=(yes|force)\s*$")

    def test_readme_badge_matches_app_version(self):
        text = _read(_README)
        m = re.search(r"badge/S.*?rüm-v([0-9.]+)-", text)
        self.assertIsNotNone(m, "README surum rozeti bulunamadi")
        self.assertEqual(m.group(1), APP_VERSION,
                         "README rozeti ile APP_VERSION uyusmuyor")

    def test_no_stale_previous_version_left_in_sources(self):
        """Kaynak/paketleme/docs icinde eski UYGULAMA surumu kalmamali.

        Yalnizca uygulama surumu baglamlari aranir: 'v3.10', '"3.10"',
        'Setup-3.10'. Ciplak sayi ARANMAZ; aksi halde README'deki
        'Python 3.10+' gibi ALAKASIZ bir surum notu yanlis alarm verirdi."""
        targets = [
            os.path.join(_ROOT, "app", "core", "app_info.py"),
        ]
        if os.path.isfile(_ISS):
            targets.append(_ISS)
        old = re.escape(PREVIOUS_RELEASE)
        pattern = re.compile(rf'(v{old}\b|"{old}"|Setup-{old}\b)')
        for path in targets:
            text = _read(path)
            hit = pattern.search(text)
            self.assertIsNone(hit,
                              f"{os.path.basename(path)} icinde eski surum "
                              f"{PREVIOUS_RELEASE} kalmis: {hit.group(0) if hit else ''}")

    def test_readme_installer_names_match_current_version(self):
        names = re.findall(r"DPort-Setup-(\d+\.\d+)\.exe", _read(_README))
        self.assertTrue(names)
        self.assertTrue(all(version == APP_VERSION for version in names))

    def test_current_version_supersedes_previous_release(self):
        """Updater, bu surumu yayindaki son surumden YENI gormeli."""
        self.assertTrue(is_newer_version(APP_VERSION, PREVIOUS_RELEASE),
                        f"{APP_VERSION} > {PREVIOUS_RELEASE} degil")
        self.assertFalse(is_newer_version(PREVIOUS_RELEASE, APP_VERSION))
        self.assertFalse(is_newer_version(APP_VERSION, APP_VERSION))

    def test_git_tag_form_is_also_detected(self):
        """GitHub tag'i 'vX.Y' bicimindedir; updater onu da cozmeli."""
        self.assertTrue(is_newer_version(f"v{APP_VERSION}", PREVIOUS_RELEASE))

    def test_multi_digit_minor_version_is_compared_numerically(self):
        """Cok haneli minor surum METINSEL degil SAYISAL karsilastirilmali."""
        self.assertTrue(is_newer_version("3.10", "3.9"))
        self.assertTrue(is_newer_version("v3.10", "3.9"))
        self.assertFalse(is_newer_version("3.9", "3.10"))
        # Cok haneli minor surumler metinsel degil sayisal karsilastirilir.
        self.assertTrue(is_newer_version("3.11", "3.10"))
        self.assertTrue(is_newer_version("v3.11", "3.10"))
        self.assertFalse(is_newer_version("3.10", "3.11"))
        self.assertFalse(is_newer_version("3.11", "3.11"))
        self.assertTrue(is_newer_version("3.12", "3.11"))
        self.assertTrue(is_newer_version("v3.12", "3.11"))
        self.assertFalse(is_newer_version("3.11", "3.12"))

    def test_expected_setup_asset_name_is_selected(self):
        """Uretilen installer adi updater'in sectigi asset ile ayni olmali."""
        expected = f"{APP_NAME}-Setup-{APP_VERSION}.exe"
        assets = [
            {"name": "kaynak-kodu.zip", "browser_download_url": "https://x/z"},
            {"name": expected, "browser_download_url": "https://x/setup"},
        ]
        picked = _pick_setup_asset(assets)
        self.assertIsNotNone(picked, "beklenen setup asset'i secilmedi")
        self.assertEqual(picked["name"], expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
