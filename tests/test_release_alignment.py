"""
tests/test_release_alignment.py

Yayin oncesi surum hizalamasi. Repo kurali: APP_VERSION, Inno MyAppVersion,
README rozeti ve uretilen `DPort-Setup-X.Y.exe` adi AYNI olmalidir.

NOT: `packaging/` .gitignore'da oldugu icin temiz bir klonda bulunmayabilir;
o dosyalara bagli kontroller dosya yoksa ATLANIR.
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
PREVIOUS_RELEASE = "3.7"

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
        if not os.path.isfile(_ISS):
            self.skipTest("packaging/DPort.iss yok (gitignore'lu yerel dosya)")
        text = _read(_ISS)
        m = re.search(r'#define\s+MyAppVersion\s+"([^"]+)"', text)
        self.assertIsNotNone(m, "MyAppVersion bulunamadi")
        self.assertEqual(m.group(1), APP_VERSION,
                         "Inno MyAppVersion ile APP_VERSION uyusmuyor")

    def test_readme_badge_matches_app_version(self):
        text = _read(_README)
        m = re.search(r"badge/S.*?rüm-v([0-9.]+)-", text)
        self.assertIsNotNone(m, "README surum rozeti bulunamadi")
        self.assertEqual(m.group(1), APP_VERSION,
                         "README rozeti ile APP_VERSION uyusmuyor")

    def test_no_stale_previous_version_left_in_sources(self):
        """Kaynak/paketleme/docs icinde eski surum sabiti kalmamali."""
        targets = [
            os.path.join(_ROOT, "app", "core", "app_info.py"),
            _README,
        ]
        if os.path.isfile(_ISS):
            targets.append(_ISS)
        pattern = re.compile(re.escape(PREVIOUS_RELEASE))
        for path in targets:
            text = _read(path)
            self.assertIsNone(pattern.search(text),
                              f"{os.path.basename(path)} icinde eski surum "
                              f"{PREVIOUS_RELEASE} kalmis")

    def test_current_version_supersedes_previous_release(self):
        """Updater, bu surumu yayindaki son surumden YENI gormeli."""
        self.assertTrue(is_newer_version(APP_VERSION, PREVIOUS_RELEASE),
                        f"{APP_VERSION} > {PREVIOUS_RELEASE} degil")
        self.assertFalse(is_newer_version(PREVIOUS_RELEASE, APP_VERSION))
        self.assertFalse(is_newer_version(APP_VERSION, APP_VERSION))

    def test_git_tag_form_is_also_detected(self):
        """GitHub tag'i 'vX.Y' bicimindedir; updater onu da cozmeli."""
        self.assertTrue(is_newer_version(f"v{APP_VERSION}", PREVIOUS_RELEASE))

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
