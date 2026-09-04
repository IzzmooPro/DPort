"""Single-flight update checks. All UI callbacks run through the UI scheduler."""
import queue
import threading


class UpdateCheckController:
    RETRY_DELAYS = (5000, 15000)

    def __init__(self, check, schedule, cancel, deliver, log, launch=None):
        self.check, self.schedule, self.cancel = check, schedule, cancel
        self.deliver, self.log = deliver, log
        self.launch = launch or self._launch
        self.results = queue.Queue()
        self.closed = False
        self.busy = False
        self.manual = False
        self.started = False
        self.attempt = 0
        self.timer = None
        self.prompted = set()

    @staticmethod
    def _launch(work):
        threading.Thread(target=work, daemon=True).start()

    def request(self, manual=False):
        if self.closed or (not manual and self.started):
            return
        if self.busy:
            self.manual = self.manual or manual
            return
        self.started = True
        if self.timer is not None:
            self.cancel(self.timer)
            self.timer = None
        self.manual = manual
        self.attempt = 0
        self._start()

    def _start(self):
        self.timer = None
        if self.closed:
            return
        self.busy = True
        self.attempt += 1
        self.log(f"UPDATE | kontrol basladi | deneme={self.attempt}")
        try:
            self.launch(self._worker)
        except Exception as exc:
            self.results.put((None, exc))
        self.timer = self.schedule(100, self._poll)

    def _worker(self):
        # No Tk access, log/UI callbacks, sleeps or scheduling in worker thread.
        try:
            self.results.put((self.check(), None))
        except Exception as exc:
            self.results.put((None, exc))

    def _poll(self):
        self.timer = None
        if self.closed:
            return
        try:
            info, error = self.results.get_nowait()
        except queue.Empty:
            self.timer = self.schedule(100, self._poll)
            return
        if error:
            self.log(f"UPDATE | kontrol basarisiz | deneme={self.attempt} | {error}")
            if (not self.manual and getattr(error, "retryable", False)
                    and self.attempt <= len(self.RETRY_DELAYS)):
                self.busy = False
                delay = self.RETRY_DELAYS[self.attempt - 1]
                self.log(f"UPDATE | tekrar planlandi | {delay // 1000} saniye")
                self.timer = self.schedule(delay, self._start)
                return
        else:
            self.log(f"UPDATE | kontrol tamamlandi | surum={info.get('version')} "
                     f"| yeni={bool(info.get('available'))}")
        try:
            if info and info.get("available"):
                version = info.get("version")
                if version in self.prompted and not self.manual:
                    return
                self.prompted.add(version)
            # Keep busy through modal delivery to prevent nested requests.
            self.deliver(info, error, self.manual)
        finally:
            self.busy = False

    def close(self):
        self.closed = True
        if self.timer is not None:
            self.cancel(self.timer)
            self.timer = None
