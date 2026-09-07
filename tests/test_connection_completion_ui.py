"""Completion UI must not wait for optional system-information queries."""
import os
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'app'))
from gui import app as g


class CompletionTests(unittest.TestCase):
    def make_app(self, active=False):
        app = g.DPortApp.__new__(g.DPortApp)
        app._alive = True
        app._busy = True
        app._connecting = True
        app._status_generation = 5
        app._dns_backup_mem = {}
        app._active_since = None
        app._unblocker = Mock()
        app._unblocker.is_active.return_value = active
        app.dash = {key: Mock() for key in ('dns', 'servers', 'uptime')}
        for key in ('hero_dot', 'hero_state', 'hero', 'btn_open'):
            setattr(app, key, Mock())
        app._refresh_status_async = Mock()
        return app

    def test_completion_button_changes_before_background_query(self):
        for active in (False, True):
            app = self.make_app(active)
            def refresh():
                self.assertFalse(app._busy)
                self.assertEqual(app._connection_action_mode, 'restore' if active else 'activate')
                app.btn_open.configure.assert_called_once()
            app._refresh_status_async.side_effect = refresh
            with patch.object(g, 'get_dns', side_effect=AssertionError('slow query')), \
                 patch.object(g, 'get_active_adapters', side_effect=AssertionError('slow query')), \
                 patch.object(g, 'running_discord_version', side_effect=AssertionError('slow query')):
                app._finish_connection_operation()
            self.assertEqual(app._status_generation, 6)
            self.assertFalse(app._connecting)
            self.assertEqual(app.dash['dns'].configure.call_args.kwargs['text'], g.L['val_unknown'])
            app._refresh_status_async.assert_called_once()

    def test_old_queued_result_cannot_overwrite_completion(self):
        app = self.make_app()
        app._apply_status = Mock()
        app._finish_connection_operation()
        app._apply_status_if_current(5, True, 'old', '1.1.1.1')
        app._apply_status.assert_not_called()

    def test_partial_restore_and_remaining_backup_keep_restore_action(self):
        for retry in (False, True):
            app = self.make_app()
            app._dns_backup_mem = {} if retry else {'adapter': {}}
            app._finish_connection_operation(can_retry=retry)
            self.assertEqual(app._connection_action_mode, 'restore')
            self.assertEqual(app._restore_retry_required, retry)

    def test_closed_window_is_untouched(self):
        app = self.make_app()
        app._alive = False
        app._finish_connection_operation()
        app.btn_open.configure.assert_not_called()
        app._refresh_status_async.assert_not_called()

    def test_restore_completion_waits_for_safety_but_not_extra_dns_read(self):
        for ok in (False, True):
            app = self.make_app()
            order = []
            app._st = Mock()
            app._disable_discord_unblock = Mock(side_effect=lambda: order.append('hosts') or ok)
            app._restore_dns = Mock(side_effect=lambda: order.append('dns') or True)
            app._flushdns = Mock(side_effect=lambda: order.append('flush'))
            app._current_dns_text = Mock(side_effect=AssertionError('redundant DNS query'))
            callbacks = []
            app.after = lambda delay, callback: callbacks.append(callback)
            app._restore_normal_w()
            self.assertTrue(app._busy, 'worker must not unlock UI before callback')
            self.assertEqual(order, ['hosts', 'dns', 'flush'])
            self.assertEqual(len(callbacks), 1)
            callbacks[0]()
            self.assertFalse(app._busy)
            self.assertEqual(app._connection_action_mode, 'activate' if ok else 'restore')
            self.assertEqual(app._restore_retry_required, not ok)

    def test_restore_exception_keeps_retry_available(self):
        app = self.make_app()
        app._st = Mock()
        app._disable_discord_unblock = Mock(side_effect=OSError('blocked'))
        callbacks = []
        app.after = lambda delay, callback: callbacks.append(callback)
        with self.assertRaises(OSError):
            app._restore_normal_w()
        callbacks[0]()
        self.assertEqual(app._connection_action_mode, 'restore')


if __name__ == '__main__':
    unittest.main()
