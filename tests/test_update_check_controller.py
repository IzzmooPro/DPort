"""Deterministic scheduler tests: no network, threads, sleeping or GUI."""
import sys
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import ssl
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
from core.update_check import UpdateCheckController  # noqa: E402
from core import updater  # noqa: E402


class TransientError(Exception):
    retryable = True


class Checks(unittest.TestCase):
    def setUp(self):
        self.jobs = {}
        self.counter = 0
        self.workers = []
        self.deliver = Mock()
        self.log = Mock()
        self.check = Mock(return_value={"available": True, "version": "3.14"})
        self.controller = UpdateCheckController(
            self.check, self.schedule, self.jobs.pop, self.deliver, self.log,
            self.workers.append,
        )

    def schedule(self, delay, callback):
        self.counter += 1
        self.jobs[self.counter] = (delay, callback)
        return self.counter

    def tick(self):
        key = next(iter(self.jobs))
        delay, callback = self.jobs.pop(key)
        callback()
        return delay

    def finish(self):
        self.workers.pop(0)()
        self.tick()

    def test_success_delivered_once(self):
        self.controller.request()
        self.finish()
        self.controller.request()
        self.assertEqual(self.check.call_count, 1)
        self.deliver.assert_called_once()
        self.assertFalse(self.jobs)

    def test_manual_joins_running_startup_check(self):
        self.controller.request()
        self.controller.request(manual=True)
        self.assertEqual(len(self.workers), 1)
        self.finish()
        self.assertTrue(self.deliver.call_args.args[2])

    def test_three_transient_failures_stop(self):
        self.check.side_effect = TransientError("timeout")
        self.controller.request()
        self.finish()
        self.assertEqual(self.tick(), 5000)
        self.finish()
        self.assertEqual(self.tick(), 15000)
        self.finish()
        self.assertFalse(self.jobs)
        self.assertEqual(self.check.call_count, 3)
        self.deliver.assert_called_once()
        self.assertFalse(self.deliver.call_args.args[2])
        self.assertEqual(sum("kontrol basarisiz" in c.args[0]
                             for c in self.log.call_args_list), 3)

    def test_retry_recovers(self):
        self.check.side_effect = [TransientError("offline"), {"available": True, "version": "3.14"}]
        self.controller.request()
        self.finish()
        self.tick()
        self.finish()
        self.deliver.assert_called_once()
        self.assertIsNone(self.deliver.call_args.args[1])
        self.assertFalse(self.jobs)

    def test_permanent_failure_is_not_retried(self):
        self.check.side_effect = ValueError("bad metadata")
        self.controller.request()
        self.finish()
        self.assertFalse(self.jobs)
        self.deliver.assert_called_once()

    def test_manual_takes_over_pending_retry(self):
        self.check.side_effect = [TransientError(), {"available": False, "version": "3.13"}]
        self.controller.request()
        self.finish()
        self.controller.request(manual=True)
        self.assertEqual(len(self.jobs), 1)
        self.finish()
        self.assertTrue(self.deliver.call_args.args[2])
        self.assertFalse(self.jobs)

    def test_manual_failure_is_immediate(self):
        self.check.side_effect = TransientError()
        self.controller.request(manual=True)
        self.finish()
        self.assertFalse(self.jobs)
        self.assertTrue(self.deliver.call_args.args[2])

    def test_close_cancels_retry(self):
        self.check.side_effect = TransientError()
        self.controller.request()
        self.finish()
        self.controller.close()
        self.controller.request(manual=True)
        self.assertFalse(self.jobs)
        self.assertFalse(self.workers)

    def test_close_drops_late_worker_result(self):
        self.controller.request()
        self.controller.close()
        self.workers.pop(0)()
        self.deliver.assert_not_called()
        self.assertFalse(self.jobs)

    def test_worker_does_not_deliver_or_schedule(self):
        self.controller.request()
        before = dict(self.jobs)
        self.workers.pop(0)()
        self.assertEqual(self.jobs, before)
        self.deliver.assert_not_called()
        self.tick()
        self.deliver.assert_called_once()

    def test_no_nested_prompt_during_delivery(self):
        self.deliver.side_effect = lambda *args: self.controller.request(manual=True)
        self.controller.request()
        self.finish()
        self.assertFalse(self.workers)
        self.assertFalse(self.jobs)

    def test_explicit_manual_can_reopen_dismissed_offer(self):
        self.controller.request()
        self.finish()
        self.controller.request(manual=True)
        self.finish()
        self.assertEqual(self.deliver.call_count, 2)

    def test_manual_before_startup_suppresses_extra_request(self):
        self.controller.request(manual=True)
        self.finish()
        self.controller.request()
        self.assertFalse(self.workers)

    def test_poll_waits_without_extra_network_request(self):
        self.controller.request()
        self.tick()
        self.assertEqual(len(self.workers), 1)
        self.finish()
        self.assertFalse(self.jobs)


class ErrorClassification(unittest.TestCase):
    def test_http_status_classification(self):
        for code, retryable in [(404, False), (403, False), (401, False),
                                (408, True), (429, True), (500, True), (503, True)]:
            with self.subTest(code=code), patch.object(
                    updater.urllib.request, "urlopen",
                    side_effect=urllib.error.HTTPError("https://example.invalid", code, "error", {}, None)):
                with self.assertRaises(updater.UpdateError) as result:
                    updater._request_json("https://example.invalid")
                self.assertEqual(result.exception.retryable, retryable)

    def test_certificate_error_not_retried(self):
        with patch.object(updater.urllib.request, "urlopen", side_effect=
                          urllib.error.URLError(ssl.SSLCertVerificationError("invalid certificate"))):
            with self.assertRaises(updater.UpdateError) as result:
                updater._request_json("https://example.invalid")
        self.assertFalse(result.exception.retryable)

    def test_timeout_and_network_errors_retryable(self):
        for error in [TimeoutError(), ConnectionResetError(),
                      urllib.error.URLError("offline")]:
            with self.subTest(error=error), patch.object(
                    updater.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(updater.UpdateError) as result:
                    updater._request_json("https://example.invalid")
                self.assertTrue(result.exception.retryable)


if __name__ == "__main__":
    unittest.main()
