import os
import sys
import tempfile
import time
import unittest
from unittest import mock


APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app"))
if APP_DIR not in sys.path:
    sys.path.insert(0, APP_DIR)

from core import discord_manager  # noqa: E402
from core.lang import L, set_lang  # noqa: E402
from gui import app as gui_app  # noqa: E402


class TestRunningDiscordVersion(unittest.TestCase):
    def test_reads_version_from_running_executable_path(self):
        info = {
            "paths": [
                r"C:\Users\Test\AppData\Local\Discord\app-1.0.9249\Discord.exe",
                r"C:\Users\Test\AppData\Local\Discord\app-1.0.9250\Discord.exe",
            ]
        }
        with mock.patch.object(
            discord_manager, "get_discord_process_info", return_value=info
        ):
            self.assertEqual(discord_manager.running_discord_version(), "1.0.9250")

    def test_ignores_process_path_without_app_version_directory(self):
        info = {"paths": [r"C:\Temp\Discord.exe", None]}
        with mock.patch.object(
            discord_manager, "get_discord_process_info", return_value=info
        ):
            self.assertIsNone(discord_manager.running_discord_version())

    def test_restart_is_required_only_for_older_running_version(self):
        self.assertTrue(
            discord_manager.discord_restart_required("1.0.9250", "1.0.9249")
        )
        self.assertFalse(
            discord_manager.discord_restart_required("1.0.9250", "1.0.9250")
        )
        self.assertFalse(
            discord_manager.discord_restart_required("1.0.9249", "1.0.9250")
        )
        self.assertFalse(discord_manager.discord_restart_required("1.0.9250", None))


class TestDiscordUpdaterLogState(unittest.TestCase):
    def _status_for(self, lines):
        fd, path = tempfile.mkstemp(suffix=".log")
        os.close(fd)
        try:
            with open(path, "w", encoding="utf-8") as stream:
                stream.write("\n".join(lines) + "\n")
            with mock.patch.object(
                discord_manager, "_discord_updater_log_path", return_value=path
            ):
                return discord_manager.get_discord_update_status()
        finally:
            os.remove(path)

    def test_complete_is_not_overwritten_by_late_module_messages(self):
        status, _, stage = self._status_for(
            [
                "[2026-07-29 00:05:02 +03:00] Starting update to latest",
                "[2026-07-29 00:05:03 +03:00] Executing download tasks",
                "[2026-07-29 00:05:40 +03:00] Update to latest complete",
                (
                    "[2026-07-29 00:05:41 +03:00] "
                    "Install of module discord_overlay2 finished successfully"
                ),
            ]
        )
        self.assertEqual(status, "ok")
        self.assertEqual(stage, "")

    def test_new_attempt_after_complete_can_report_progress(self):
        status, _, stage = self._status_for(
            [
                "[2026-07-29 00:05:40 +03:00] Update to latest complete",
                "[2026-07-29 00:06:47 +03:00] Starting update to latest",
                "[2026-07-29 00:06:48 +03:00] Executing download tasks",
            ]
        )
        self.assertEqual(status, "progress")
        self.assertEqual(stage, "downloading")

    def test_complete_is_not_overwritten_by_late_error_line(self):
        status, _, stage = self._status_for(
            [
                "[2026-07-29 00:05:02 +03:00] Starting update to latest",
                "[2026-07-29 00:05:40 +03:00] Update to latest complete",
                "[2026-07-29 00:05:41 +03:00] ERROR [updater_client] late noise",
            ]
        )
        self.assertEqual(status, "ok")
        self.assertEqual(stage, "")


class TestDiscordVersionTile(unittest.TestCase):
    def setUp(self):
        set_lang("tr")
        self.app = gui_app.DPortApp.__new__(gui_app.DPortApp)
        self.app._discord_update_phase = ""
        self.app._discord_update_notice_until = 0.0

    def test_restart_message_persists_without_icon(self):
        text, color = self.app._discord_version_tile(
            "1.0.9250", "1.0.9249", "1.0.9250"
        )
        self.assertEqual(text, "1.0.9250\nYeniden başlat")
        self.assertNotIn("✓", text)
        self.assertEqual(color, gui_app.YELL)
        self.assertEqual(self.app._discord_update_phase, "restart")

    def test_matching_running_version_becomes_updated_message(self):
        self.app._discord_update_phase = "restart"
        with mock.patch.object(time, "time", return_value=100.0):
            text, color = self.app._discord_version_tile(
                "1.0.9250", "1.0.9250", "1.0.9250"
            )
        self.assertEqual(text, "1.0.9250\nGüncellendi")
        self.assertEqual(color, gui_app.GREEN)
        self.assertEqual(self.app._discord_update_notice_until, 105.0)

    def test_restart_message_stays_when_discord_is_temporarily_closed(self):
        self.app._discord_update_phase = "restart"
        text, color = self.app._discord_version_tile(
            "1.0.9250", None, "1.0.9250"
        )
        self.assertEqual(text, "1.0.9250\nYeniden başlat")
        self.assertEqual(color, gui_app.YELL)
        self.assertEqual(self.app._discord_update_phase, "restart")

    def test_updated_message_expires_to_plain_version(self):
        self.app._discord_update_phase = "updated"
        self.app._discord_update_notice_until = 104.0
        with mock.patch.object(time, "time", return_value=105.0):
            text, color = self.app._discord_version_tile(
                "1.0.9250", "1.0.9250", "1.0.9250"
            )
        self.assertEqual(text, "1.0.9250")
        self.assertEqual(color, gui_app.TEXT)
        self.assertEqual(self.app._discord_update_phase, "")

    def test_checking_message_is_plain_text(self):
        self.app._discord_update_phase = "checking"
        text, color = self.app._discord_version_tile(
            "1.0.9249", "1.0.9249", "1.0.9249"
        )
        self.assertEqual(text, f"1.0.9249\n{L['discord_ver_checking']}")
        self.assertNotIn("✓", text)
        self.assertEqual(color, gui_app.YELL)


class TestStaleStatusRefresh(unittest.TestCase):
    def test_queued_old_generation_cannot_apply_after_restore(self):
        app = gui_app.DPortApp.__new__(gui_app.DPortApp)
        app._alive = True
        app._status_generation = 2
        app._apply_status = mock.Mock()

        app._apply_status_if_current(1, True, "1", "1.1.1.1")

        app._apply_status.assert_not_called()

    def test_old_generation_cannot_apply_stale_connected_state(self):
        app = gui_app.DPortApp.__new__(gui_app.DPortApp)
        app._alive = True
        app._status_generation = 2
        app._status_refreshing = True
        app._status_refresh_pending = False
        app._unblocker = mock.Mock()
        app._unblocker.is_active.return_value = True
        app.after = mock.Mock()

        with mock.patch.object(gui_app, "installed_discord_version", return_value="1"), \
             mock.patch.object(gui_app, "running_discord_version", return_value="1"), \
             mock.patch.object(gui_app, "get_active_adapters", return_value=[]):
            app._do_refresh_status(generation=1)

        app.after.assert_not_called()
        self.assertFalse(app._status_refreshing)

    def test_pending_refresh_is_scheduled_after_old_one_finishes(self):
        app = gui_app.DPortApp.__new__(gui_app.DPortApp)
        app._alive = True
        app._status_generation = 2
        app._status_refreshing = True
        app._status_refresh_pending = True
        app._unblocker = mock.Mock()
        app._unblocker.is_active.return_value = True
        app.after = mock.Mock()

        with mock.patch.object(gui_app, "installed_discord_version", return_value="1"), \
             mock.patch.object(gui_app, "running_discord_version", return_value="1"), \
             mock.patch.object(gui_app, "get_active_adapters", return_value=[]):
            app._do_refresh_status(generation=1)

        app.after.assert_called_once()
        self.assertEqual(app.after.call_args.args[0], 0)
        self.assertFalse(app._status_refresh_pending)


if __name__ == "__main__":
    unittest.main()
