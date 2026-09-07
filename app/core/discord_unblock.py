"""
core/discord_unblock.py

Turkiye'deki Discord update engelini DIS bir programa (WARP/VPN) ihtiyac duymadan,
DPort'un kendi icinde asar.

Engel nasil calisiyor:
  updates.discord.com DNS'te dogru cozuluyor, TCP baglantisi kuruluyor; fakat
  ISS, TLS ClientHello icindeki "updates.discord.com" SNI adini gorunce baglantiyi
  resetliyor (DPI). Bu yuzden VPN olmadan da, ilk paketi (ClientHello) SNI adinin
  ortasindan birkac parcaya bolerek gonderirsek DPI adi yakalayamaz ve engel asilir.

Nasil calisir:
  1. 127.0.0.1:443 uzerinde kucuk bir yerel role (relay) dinler.
  2. hosts dosyasina "updates.discord.com -> 127.0.0.1" satiri eklenir; boylece
     Discord'un kendi updater'i da bu roleye baglanir.
  3. Role, gelen ClientHello'dan hedef host adini (SNI) okur, gercek IP'yi
     sertifika dogrulamali DoH ile cozer, sunucuya baglanir ve ClientHello'yu
     parcalayarak iletir.
  4. Sonrasi seffaf TCP tunelidir; TLS uctan uca client ile sunucu arasinda kalir
     (role sertifikayi gormez, MITM yoktur).
"""
import errno
import ipaddress
import json
import queue
import select
import itertools
import os
import ssl
import stat
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Dict, List, Optional, Tuple

# hosts uzerinden 127.0.0.1'e yonlendirilecek, DPI ile engellenen Discord host'lari.
# Olcum: bu host'lar dogrudan 0/5 (engelli), relay uzerinden 5/5 (0.1 sn).
#  - updates.discord.com : guncelleme manifesti (guncelleme sorunu)
#  - discord.com         : ana API (acilista giris/sunucu/mesaj cekme)
#  - gateway.discord.gg  : kalici websocket baglantisi (Discord'un "online" olmasi)
#  - cdn.discordapp.com  : statik varliklar, avatar, ekler
#  - media.discordapp.net: gorsel/medya proxy
# NOT: *.discord.media (ses/latency) engelli DEGIL (olcumde 5/5 dogrudan gecti);
# gereksiz yuk ve gecikme olmasin diye onu KASITLI olarak yonlendirmiyoruz.
BLOCKED_HOSTS = (
    "updates.discord.com",
    "discord.com",
    "gateway.discord.gg",
    "cdn.discordapp.com",
    "media.discordapp.net",
)

# Role SADECE bu host'lara tunel acar. hosts dosyasi zaten yalnizca bu adlari
# 127.0.0.1'e yonlendirdigi icin mesru trafik bu kume ile sinirli; bu whitelist
# baska bir yerel islemin roleyi keyfi hedeflere parcalayici proxy gibi
# kullanmasini engeller. (Discord'un calismasini etkilemez.)
ALLOWED_HOSTS = frozenset(BLOCKED_HOSTS)

# Parcali ClientHello ile denenecek AZAMI IP sayisi (bkz. _open_upstream).
# Parcali TLS yanitlanmadiginda her IP recv zaman asimi (4 sn) kadar bekletir;
# bu sinir, dogrudan TLS'e gecisin IP sayisiyla birlikte buyumesini onler.
_FRAG_SWEEP_IPS = 2

# At most four races (eight workers) process-wide, including late TCP connects.
# Waiting callers do not spawn more threads; their original deadline still applies.
_TLS_RACE_SLOTS = threading.BoundedSemaphore(4)

HOSTS_PATH = os.path.join(
    os.environ.get("SystemRoot", r"C:\Windows"),
    "System32", "drivers", "etc", "hosts",
)
HOSTS_MARK_BEGIN = "# >>> DPort Discord unblock >>>"
HOSTS_MARK_END = "# <<< DPort Discord unblock <<<"
# Eski surumden kalmis olabilecek isaretler (temizlik icin)
_LEGACY_MARKS = (
    ("# >>> DNSGuardian Discord unblock >>>", "# <<< DNSGuardian Discord unblock <<<"),
)

_DOH_ENDPOINTS = (
    ("Cloudflare IP", "https://1.1.1.1/dns-query"),
    ("Cloudflare", "https://cloudflare-dns.com/dns-query"),
    ("Google", "https://dns.google/resolve"),
)


class DohResolutionError(RuntimeError):
    """Tum guvenli DoH saglayicilari basarisiz oldugunda yukseltilir."""


def _doh_error_text(exc: Exception) -> str:
    """Kullanici verisi icermeyen, sinirli uzunlukta DoH hata teshisi."""
    reason = exc
    if isinstance(exc, urllib.error.URLError) and isinstance(exc.reason, Exception):
        reason = exc.reason
    if isinstance(reason, ssl.SSLCertVerificationError):
        verify_code = getattr(reason, "verify_code", None)
        verify_message = getattr(reason, "verify_message", None) or str(reason)
        return (
            "sertifika dogrulanamadi"
            f" (verify_code={verify_code}, verify_message={verify_message})"
        )[:300]
    return f"{type(reason).__name__}: {reason}"[:300]


def _socket_error_text(exc: BaseException) -> str:
    """Kisisel veri icermeyen, karsilastirilabilir ag hata sinifi.

    Istisnanin serbest metnini loglamiyoruz: isletim sistemi metni beklenmedik
    yerel ayrintilar icerebilir. Teshis icin hata turu ve sayisal kodlar yeterli.
    """
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return "timeout"
    if isinstance(exc, ConnectionResetError):
        return "reset"
    if isinstance(exc, ConnectionRefusedError):
        return "reddedildi"
    errno_value = getattr(exc, "errno", None)
    winerror_value = getattr(exc, "winerror", None)
    return (
        f"{type(exc).__name__}"
        f"(errno={errno_value},winerror={winerror_value})"
    )[:120]


def _public_ipv4_answers(obj) -> List[str]:
    """Basarili DoH JSON'indan yalniz genel kullanima acik IPv4 adreslerini al."""
    if not isinstance(obj, dict) or obj.get("Status") != 0:
        raise ValueError("DoH sunucusu basarisiz durum dondurdu")
    answers = obj.get("Answer")
    if not isinstance(answers, list):
        raise ValueError("DoH yanitinda Answer listesi yok")

    result = []
    seen = set()
    for answer in answers:
        if not isinstance(answer, dict) or answer.get("type") != 1:
            continue
        try:
            ip = ipaddress.ip_address(str(answer.get("data", "")))
        except ValueError:
            continue
        if not isinstance(ip, ipaddress.IPv4Address) or not ip.is_global:
            continue
        text = str(ip)
        if text not in seen:
            result.append(text)
            seen.add(text)
    if not result:
        raise ValueError("DoH yanitinda kullanilabilir genel IPv4 adresi yok")
    return result


# ────────────────────────────── DoH cozumleme ──────────────────────────────
_DOH_SLOTS = threading.BoundedSemaphore(4)


def doh_resolve(host, timeout=8, log=None, *, total_timeout=24, cancel=None):
    """Bound caller latency even while Windows resolver/TLS calls are blocked.

    A timed-out OS call cannot be killed safely. At most four daemon workers
    may remain inside it; cancelled workers cannot log, cache, or start a
    fallback request. No system DNS fallback or TLS verification bypass.
    """
    event = threading.Event()
    deadline = time.monotonic() + total_timeout
    result = queue.Queue(maxsize=1)
    while True:
        if cancel is not None and cancel.is_set():
            raise DohResolutionError("DoH iptal edildi")
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DohResolutionError("DoH kapasite bekleme suresi doldu")
        if _DOH_SLOTS.acquire(timeout=min(0.05, remaining)):
            break
    def report(message):
        if log and not event.is_set():
            log(message)
    def work():
        try:
            result.put((_doh_resolve_blocking(host, timeout, report, event, deadline), None))
        except Exception as exc:
            result.put((None, exc))
        finally:
            _DOH_SLOTS.release()
    try:
        threading.Thread(target=work, daemon=True).start()
    except Exception:
        _DOH_SLOTS.release()
        raise
    while not event.is_set():
        if cancel is not None and cancel.is_set():
            event.set()
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            event.set()
            if log:
                log("DoH | sonuc=toplam_sure_siniri")
            raise DohResolutionError("Guvenli DNS toplam sure sinirina ulasti")
        try:
            ips, error = result.get(timeout=min(0.05, remaining))
        except queue.Empty:
            continue
        if event.is_set():
            break
        if error:
            raise error
        return ips
    raise DohResolutionError("Guvenli DNS islemi iptal edildi")


def _doh_resolve_blocking(
    host: str,
    timeout: int = 8,
    log: Optional[Callable[[str], None]] = None,
    cancel=None,
    deadline=None,
) -> List[str]:
    """Gercek IP'leri, sertifika dogrulamasi acik HTTPS DoH ile cozer.

    Ilk yol DPI nedeniyle veya yerel sertifika zinciri sorunu yuzunden
    calismazsa iki resmi HTTPS DoH adresi sirayla denenir. TLS dogrulamasi
    hicbir kosulda kapatilmaz; tum yollar basarisizsa fail-closed davranilir.
    """
    host = host.strip().rstrip(".").lower()
    try:
        ascii_host = host.encode("idna").decode("ascii")
    except (UnicodeError, AttributeError) as exc:
        raise DohResolutionError("Gecersiz DNS adi") from exc
    if not ascii_host or len(ascii_host) > 253:
        raise DohResolutionError("Gecersiz DNS adi")

    failures = []
    query = urllib.parse.urlencode({"name": ascii_host, "type": "A"})
    for label, endpoint in _DOH_ENDPOINTS:
        if cancel.is_set() or time.monotonic() >= deadline:
            raise DohResolutionError("Guvenli DNS islemi iptal edildi")
        started = time.monotonic()
        url = f"{endpoint}?{query}"
        req = urllib.request.Request(
            url,
            headers={"accept": "application/dns-json"},
        )
        try:
            # context verilmemesi kasitlidir: urllib sistem/Python varsayilan
            # guven deposunu, hostname kontrolunu ve CERT_REQUIRED'i kullanir.
            with urllib.request.urlopen(req, timeout=min(timeout, max(0.001, deadline - time.monotonic()))) as resp:
                status = getattr(resp, "status", 200)
                if status != 200:
                    raise ValueError(f"HTTP {status}")
                ips = _public_ipv4_answers(json.load(resp))
            if log:
                try:
                    elapsed_ms = round((time.monotonic() - started) * 1000)
                    fallback = " | yedek=true" if failures else ""
                    log(
                        f"DoH | host={ascii_host} | saglayici={label} | "
                        f"sonuc=basarili | ip_sayisi={len(ips)} | "
                        f"sure_ms={elapsed_ms}{fallback}"
                    )
                except Exception:
                    pass
            return ips
        except Exception as exc:
            detail = _doh_error_text(exc)
            failures.append(f"{label}: {detail}")
            if log:
                try:
                    elapsed_ms = round((time.monotonic() - started) * 1000)
                    log(
                        f"DoH | host={ascii_host} | saglayici={label} | "
                        f"sonuc=basarisiz | sure_ms={elapsed_ms} | {detail}"
                    )
                except Exception:
                    pass

    raise DohResolutionError(
        f"Guvenli DoH saglayicilarinin tamami basarisiz ({len(failures)}/{len(_DOH_ENDPOINTS)})"
    )


# ─────────────────────────────── SNI ayristirma ───────────────────────────────
def parse_sni(data: bytes) -> Optional[str]:
    """TLS ClientHello icinden server_name (SNI) degerini cikarir."""
    try:
        payload = bytearray()
        offset = 0
        while offset < len(data):
            if len(data) - offset < 5 or data[offset] != 0x16:
                return None
            length = int.from_bytes(data[offset + 3:offset + 5], "big")
            if not length or offset + 5 + length > len(data):
                return None
            payload.extend(data[offset + 5:offset + 5 + length])
            offset += 5 + length
            if len(payload) >= 4 and len(payload) >= 4 + int.from_bytes(payload[1:4], "big"):
                break
        if len(payload) < 4 or payload[0] != 1:
            return None
        size = 4 + int.from_bytes(payload[1:4], "big")
        if len(payload) != size:
            return None
        data = bytes(payload)
        idx = 4 + 2 + 32
        sid_len = data[idx]
        idx += 1 + sid_len
        cs_len = int.from_bytes(data[idx:idx + 2], "big")
        idx += 2 + cs_len
        comp_len = data[idx]
        idx += 1 + comp_len
        ext_total = int.from_bytes(data[idx:idx + 2], "big")
        idx += 2
        end = idx + ext_total
        if end != len(data):
            return None
        found = None
        while idx + 4 <= end:
            etype = int.from_bytes(data[idx:idx + 2], "big")
            elen = int.from_bytes(data[idx + 2:idx + 4], "big")
            body = idx + 4
            if body + elen > end:
                return None
            if etype == 0x0000:  # server_name
                if found is not None or elen < 5 or data[body + 2] != 0:
                    return None
                name_len = int.from_bytes(data[body + 3:body + 5], "big")
                if (name_len == 0 or name_len + 5 != elen or
                        int.from_bytes(data[body:body + 2], "big") != elen - 2):
                    return None
                name = data[body + 5:body + 5 + name_len]
                found = name.decode("ascii").lower()
                if any(c not in "abcdefghijklmnopqrstuvwxyz0123456789.-" for c in found):
                    return None
            idx = body + elen
        return found if idx == end else None
    except Exception:
        return None


def fragment_client_hello(data: bytes, record_size: int = 40) -> bytes:
    """ClientHello'yu TLS KAYIT katmaninda parcalar.

    Tek bir ClientHello handshake mesajini, her biri kendi 5 baytlik TLS kayit
    basligina sahip kucuk kayitlara boleriz. TLS standardi bir handshake
    mesajinin birden cok kayda yayilmasina izin verir; sunucu bunu sorunsuz
    birlestirir. Ama DPI genelde yalnizca ILK kaydi inceler ve SNI ilk 40 baytta
    olmadigi icin adi goremez, engeli uygulayamaz.

    Olcumlerde bu yontem 40/40 basari verdi; basit TCP parcalama ise ~%55'te
    kaldi (DPI TCP segmentlerini yeniden birlestiriyor, TLS kayitlarini degil).
    """
    if len(data) < 6 or data[0] != 0x16:
        return data  # TLS handshake degil, oldugu gibi birak
    rec_len = int.from_bytes(data[3:5], "big")
    handshake = data[5:5 + rec_len]
    trailer = data[5 + rec_len:]  # nadiren ayni pakette ek veri olabilir
    version = data[1:3]
    out = bytearray()
    for i in range(0, len(handshake), record_size):
        chunk = handshake[i:i + record_size]
        out += b"\x16" + version + len(chunk).to_bytes(2, "big") + chunk
    out += trailer
    return bytes(out)


def _recv_full_client_hello(sock: socket.socket, cap: int = 65536) -> bytes:
    """ClientHello'nun TAMAMINI okur.

    ClientHello birden fazla TCP parcasina bolunerek gelebilir; tek recv ile
    okunursa SNI ikinci parcada kalabilir ve parcalama SNI'i bolemez (engel
    gecer). TLS kayit basligindaki uzunluga (bayt 3-4) gore tam kayit gelene
    kadar okuruz."""
    data, payload = bytearray(), bytearray()
    deadline = time.monotonic() + 10
    def exact(size):
        result = bytearray()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            sock.settimeout(remaining)
            chunk = sock.recv(size - len(result))
            if not chunk:
                raise ValueError("eksik ClientHello")
            result.extend(chunk)
        return bytes(result)
    while len(data) < cap:
        header = exact(5)
        size = int.from_bytes(header[3:5], "big")
        if header[0] != 0x16 or not size or len(data) + 5 + size > cap:
            raise ValueError("gecersiz TLS kaydi")
        body = exact(size)
        data.extend(header + body)
        payload.extend(body)
        if len(payload) >= 4:
            total = 4 + int.from_bytes(payload[1:4], "big")
            if payload[0] != 1 or total > cap:
                raise ValueError("gecersiz ClientHello")
            if len(payload) >= total:
                return bytes(data)
    raise ValueError("ClientHello boyut siniri")


# ──────────────────────────────── Role (relay) ────────────────────────────────
class DiscordUnblocker:
    def __init__(self, log=None):
        self._log = log
        self._srv: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ip_cache: Dict[str, tuple] = {}  # host -> (ips, expiry)
        self._socket_lock = threading.RLock()
        self._sockets = set()
        self._stop_event = threading.Event()
        self._dns_lock = threading.Lock()
        self._dns_pending = {}
        self._connection_ids = itertools.count(1)

    def _track(self, sock, event):
        with self._socket_lock:
            if event.is_set():
                sock.close()
                return False
            self._sockets.add(sock)
            return True

    def _close_socket(self, sock):
        with self._socket_lock:
            self._sockets.discard(sock)
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except (OSError, AttributeError):
            pass
        try:
            sock.close()
        except OSError:
            pass

    # --- gunluk ---
    def _l(self, msg: str):
        if self._log:
            try:
                self._log(msg)
            except Exception:
                pass

    # --- IP cozumleme (cache'li) ---
    def _resolve(self, host: str, cancel=None) -> List[str]:
        cancel = cancel if cancel is not None else self._stop_event
        key = (host, cancel)
        with self._dns_lock:
            if cancel.is_set():
                raise DohResolutionError("DoH iptal edildi")
            cached = self._ip_cache.get(host)
            if cached and cached[1] > time.time():
                return list(cached[0])
            pending = self._dns_pending.get(key)
            leader = pending is None
            if leader:
                pending = {'done': threading.Event(), 'ips': None, 'error': None}
                self._dns_pending[key] = pending
        if not leader:
            self._l(f"DNS | host={host} | sonuc=ortak_sorgu_bekleniyor")
            deadline = time.monotonic() + 24
            while not pending['done'].wait(0.05):
                if cancel.is_set() or time.monotonic() >= deadline:
                    raise DohResolutionError("Ortak DNS beklemesi iptal veya timeout")
            if cancel.is_set():
                raise DohResolutionError("DoH iptal edildi")
            if pending['error'] is not None:
                raise DohResolutionError("Ortak DNS sorgusu basarisiz") from pending['error']
            return list(pending['ips'])
        try:
            ips = doh_resolve(host, log=self._l, cancel=cancel)
            with self._dns_lock:
                if cancel.is_set():
                    raise DohResolutionError("DoH iptal edildi")
                if ips:
                    self._ip_cache[host] = (list(ips), time.time() + 300)
                pending['ips'] = list(ips)
            return ips
        except BaseException as exc:
            pending['error'] = exc
            self._l(f"DNS | host={host} | sonuc=cozumleme_basarisiz | hata={type(exc).__name__}")
            raise
        finally:
            with self._dns_lock:
                self._dns_pending.pop(key, None)
                pending['done'].set()

    def preflight(self, host: str = "discord.com") -> List[str]:
        """Relay acilmadan once guvenli cozumlemeyi dene ve sonucu cache'le."""
        if self._stop_event.is_set():
            self._stop_event = threading.Event()
        return self._resolve(host, cancel=self._stop_event)

    def _open_upstream(self, hello, ips, attempts=None, host="bilinmiyor",
                       stop_event=None, total_timeout=24, connection_id=0):
        """Race two strategy lanes; only the winning socket reaches the client.

        Only ClientHello is duplicated, never application traffic. A first TLS
        record retains the existing selection criterion, not session validation.
        Cancellation closes registered losers; a late connect is rejected before
        sending. The global permit remains held until both workers have exited.
        """
        stop_event = stop_event if stop_event is not None else self._stop_event
        started = time.monotonic()
        deadline = started + total_timeout
        attempts = max(7, 2 * len(ips)) if attempts is None else attempts
        if not ips or attempts <= 0:
            return None, None
        cancelled = threading.Event()
        changed = threading.Event()
        lock = threading.Lock()
        sockets = set()
        winner = [None, None]
        remaining = [2]
        frag = fragment_client_hello(hello)
        # Keep the previous total attempt budget and alternate-IP coverage.
        candidates = [(ip, frag, True) for ip in ips[:_FRAG_SWEEP_IPS]]
        candidates += [(ip, hello, False) for ip in ips[:_FRAG_SWEEP_IPS]]
        for ip in ips[_FRAG_SWEEP_IPS:]:
            candidates.extend(((ip, frag, True), (ip, hello, False)))
        probe_count = len(candidates)
        while len(candidates) < attempts:
            candidates.append((ips[(len(candidates) - probe_count) % len(ips)], frag, True))
        lanes = [[candidate for candidate in candidates[:attempts] if candidate[2] == mode]
                 for mode in (True, False)]

        while not stop_event.is_set() and time.monotonic() < deadline:
            if _TLS_RACE_SLOTS.acquire(timeout=min(.02, max(0, deadline - time.monotonic()))):
                break
        else:
            self._l(f"TLS | id={connection_id} | host={host} | sonuc=iptal_veya_kapasite_siniri")
            return None, None

        def register(sock):
            with lock:
                if cancelled.is_set() or stop_event.is_set():
                    return False
                sockets.add(sock)
                return True

        def worker(lane, initial_probes):
            try:
                if lane and not stop_event.is_set() and not cancelled.is_set():
                    sock, first = self._open_upstream_serial(
                        hello, ips, attempts=len(lane), host=host,
                        stop_event=cancelled, total_timeout=max(0, deadline - time.monotonic()),
                        connection_id=connection_id, _candidates=lane, _register=register,
                        _probe_count=initial_probes)
                    if sock is not None:
                        with lock:
                            if not cancelled.is_set() and not stop_event.is_set() and time.monotonic() < deadline:
                                winner[:] = [sock, first]
                                cancelled.set()
                            else:
                                self._close_socket(sock)
            except Exception as exc:
                self._l(f"TLS | id={connection_id} | host={host} | sonuc=deneme_kolu_hatasi | hata={type(exc).__name__}")
            finally:
                with lock:
                    remaining[0] -= 1
                    if remaining[0] == 0:
                        _TLS_RACE_SLOTS.release()
                changed.set()

        self._l(f"TLS | id={connection_id} | host={host} | asama=paralel_basladi | azami_kol=2")
        try:
            for index, lane in enumerate(lanes):
                try:
                    initial_probes = sum(c[2] == (index == 0) for c in candidates[:min(probe_count, attempts)])
                    threading.Thread(target=worker, args=(lane, initial_probes), daemon=True,
                                     name=f"DPort-TLS-{connection_id}-{index}").start()
                except Exception:
                    with lock:
                        remaining[0] -= len(lanes) - index
                        if remaining[0] == 0:
                            _TLS_RACE_SLOTS.release()
                    raise
            while not stop_event.is_set() and time.monotonic() < deadline:
                with lock:
                    if winner[0] is not None or remaining[0] == 0:
                        break
                changed.wait(.02)
                changed.clear()
        except BaseException:
            with lock:
                winner[:] = [None, None]
            raise
        finally:
            with lock:
                cancelled.set()
                if stop_event.is_set() or time.monotonic() >= deadline:
                    winner[:] = [None, None]
                for sock in sockets:
                    if sock is not winner[0]:
                        self._close_socket(sock)
        result = 'ilk_tls_yaniti' if winner[0] is not None else 'basarisiz_veya_iptal'
        self._l(f"TLS | id={connection_id} | host={host} | asama=paralel_tamamlandi | sonuc={result} | sure_ms={round((time.monotonic()-started)*1000)} | tam_oturum_dogrulanmadi=True")
        return tuple(winner)

    # Each bounded race lane tries its own candidates sequentially.
    def _open_upstream_serial(
        self,
        hello: bytes,
        ips: List[str],
        attempts: Optional[int] = None,
        host: str = "bilinmiyor",
        stop_event=None,
        total_timeout: float = 24,
        connection_id: int = 0,
        _candidates=None,
        _register=None,
        _probe_count=None,
    ):
        """Execute one race lane, retaining bounded timeouts and retry backoff.

        With no explicit candidates this also supports the former serial plan
        for isolated before/after regression measurements. Production calls
        supply disjoint strategy lanes via _open_upstream.
        Returns the first handshake record, not proof of a complete session.
        """
        attempts = max(7, 2 * len(ips)) if attempts is None else attempts
        stop_event = stop_event or self._stop_event
        deadline = time.monotonic() + total_timeout
        if not ips or attempts <= 0:
            self._l(
                f"TLS | id={connection_id} | host={host} | sonuc=basarisiz | neden=hedef_yok "
                f"| ip_sayisi={len(ips)} | deneme_butcesi={attempts}"
            )
            return None, None

        frag = fragment_client_hello(hello)
        # Preserve the early direct fallback for the first two IPs. Remaining
        # IPs each get both strategies, subject to the shared wall-clock budget.
        candidates = []
        candidates.extend((ip, frag, True) for ip in ips[:_FRAG_SWEEP_IPS])
        candidates.extend((ip, hello, False) for ip in ips[:_FRAG_SWEEP_IPS])
        for ip in ips[_FRAG_SWEEP_IPS:]:
            candidates.extend(((ip, frag, True), (ip, hello, False)))
        probe_count = len(candidates)
        while len(candidates) < attempts:
            ip = ips[(len(candidates) - probe_count) % len(ips)]
            candidates.append((ip, frag, True))
        if _candidates is not None:
            candidates = _candidates
            probe_count = len(candidates) if _probe_count is None else _probe_count

        for i, (ip, client_hello, fragmented) in enumerate(candidates[:attempts]):
            if stop_event.is_set() or time.monotonic() >= deadline:
                self._l(f"TLS | id={connection_id} | host={host} | sonuc=iptal_veya_sure_siniri")
                return None, None
            se = None
            started = time.monotonic()
            strategy = "parcali" if fragmented else "dogrudan"
            try:
                se = socket.create_connection((ip, 443), timeout=max(0.001, min(8, deadline - time.monotonic())))
                self._l(f"TCP | id={connection_id} | host={host} | deneme={i + 1}/{attempts} | sonuc=baglandi | sure_ms={round((time.monotonic()-started)*1000)}")
                if not self._track(se, stop_event):
                    return None, None
                if _register is not None and not _register(se):
                    self._close_socket(se)
                    return None, None
                se.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                se.settimeout(max(0.001, min(4, deadline - time.monotonic())))
                se.sendall(client_hello)
                se.settimeout(max(0.001, min(4, deadline - time.monotonic())))
                first = se.recv(65536)
                if stop_event.is_set() or time.monotonic() >= deadline:
                    self._close_socket(se)
                    return None, None
                if first and first[0] == 0x16:  # 0x16 = TLS ServerHello/handshake
                    se.settimeout(None)
                    elapsed_ms = round((time.monotonic() - started) * 1000)
                    self._l(
                        f"TLS | id={connection_id} | host={host} | deneme={i + 1}/{attempts} | "
                        f"yol={strategy} | hedef={ip}:443 | "
                        f"sonuc=ilk_tls_yaniti | sure_ms={elapsed_ms}"
                    )
                    return se, first
                # bos veya beklenmedik yanit -> DPI reseti; tekrar dene
                self._close_socket(se)
                elapsed_ms = round((time.monotonic() - started) * 1000)
                response = "bos_yanit" if not first else "tls_disi_yanit"
                self._l(
                    f"TLS | id={connection_id} | host={host} | deneme={i + 1}/{attempts} | "
                    f"yol={strategy} | hedef={ip}:443 | sonuc={response} "
                    f"| sure_ms={elapsed_ms}"
                )
            except OSError as exc:
                if se:
                    try:
                        self._close_socket(se)
                    except OSError:
                        pass
                if stop_event.is_set():
                    return None, None
                elapsed_ms = round((time.monotonic() - started) * 1000)
                self._l(
                    f"TLS | id={connection_id} | host={host} | deneme={i + 1}/{attempts} | "
                    f"yol={strategy} | hedef={ip}:443 | "
                    f"sonuc={_socket_error_text(exc)} | sure_ms={elapsed_ms}"
                )
            # Ilk parcali/dogrudan IP taramasini hizli tut. Yalniz kalan parcali
            # tekrar denemelerini taze DPI karar pencerelerine yay.
            if i + 1 < min(len(candidates), attempts) and i + 1 >= probe_count:
                retry_index = i + 1 - probe_count
                stop_event.wait(min(0.5 + retry_index * 0.25, max(0, deadline - time.monotonic())))
        self._l(
            f"TLS | id={connection_id} | host={host} | sonuc=basarisiz | "
            f"tum_denemeler_bitti={min(len(candidates), attempts)}"
        )
        return None, None

    # --- tek baglanti islemesi ---
    def _handle(self, client: socket.socket, stop_event=None):
        server = None
        connection_id = next(self._connection_ids)
        phase = 'client_hello'
        started = time.monotonic()
        reason = 'bilinmiyor'
        closed = threading.Event()
        stop_event = stop_event or self._stop_event
        if not self._track(client, stop_event):
            return
        try:
            client.settimeout(10)
            first = _recv_full_client_hello(client)  # ClientHello'nun tamami
            if not first:
                reason = 'istemci_verisi_yok'
                self._l("TLS | host=bilinmiyor | sonuc=istemci_verisi_yok")
                return
            sni = parse_sni(first)
            # Missing, malformed and non-allowlisted SNI must never choose a
            # substitute destination. Do not persist untrusted host strings.
            if not sni or sni not in ALLOWED_HOSTS:
                reason = 'gecersiz_veya_izinsiz_sni'
                self._l("TLS | host=bilinmiyor | sonuc=gecersiz_veya_izinsiz_sni")
                return
            host = sni
            self._l(f"TLS | id={connection_id} | host={host} | asama=sni_okundu")
            phase = 'dns'
            dns_started = time.monotonic()
            self._l(f"DNS | id={connection_id} | host={host} | asama=basladi")
            ips = self._resolve(host, cancel=stop_event)
            self._l(f"DNS | id={connection_id} | host={host} | asama=tamamlandi | ip_sayisi={len(ips)} | sure_ms={round((time.monotonic()-dns_started)*1000)}")
            if stop_event.is_set():
                return
            if not ips:
                reason = 'dns_hedef_yok'
                self._l(f"DNS | host={host} | sonuc=ip_cozulemedi")
                return

            phase = 'upstream'
            server, server_first = self._open_upstream(first, ips, host=host, stop_event=stop_event, connection_id=connection_id)
            if server is None:
                reason = 'upstream_kurulamadi'
                self._l(f"TLS | host={host} | sonuc=tunel_kurulamadi")
                return

            client.settimeout(None)
            phase = 'ilk_yanit_istemciye'
            # Sunucudan gelen ilk blogu (ServerHello) istemciye ilet, sonra tunelle
            client.sendall(server_first)
            self._l(f"TLS | id={connection_id} | host={host} | asama=ilk_yanit_iletildi | bayt={len(server_first)} | sure_ms={round((time.monotonic()-started)*1000)} | tam_oturum_dogrulanmadi=True")
            t = threading.Thread(target=self._pump,
                                 args=(client, server, stop_event, closed, host, 'istemci_sunucu', connection_id, True), daemon=True)
            t.start()
            phase = 'tunel'
            reason = self._pump(server, client, stop_event, closed, host, 'sunucu_istemci', connection_id, True)
        except Exception as exc:
            reason = 'zaman_asimi' if isinstance(exc, TimeoutError) else 'islem_hatasi'
            if not stop_event.is_set():
                self._l(
                    f"TLS | id={connection_id} | asama={phase} | host={locals().get('host', 'bilinmiyor')} | "
                    f"sonuc=beklenmeyen_hata | hata={_socket_error_text(exc)}"
                )
        finally:
            closed.set()
            if stop_event.is_set():
                reason = 'dport_durdurdu'
            self._l(f"TUNNEL | id={connection_id} | host={locals().get('host', 'bilinmiyor')} | sonuc=kapandi | asama={phase} | neden={reason} | sure_ms={round((time.monotonic()-started)*1000)}")
            for s in (client, server):
                if s:
                    self._close_socket(s)

    def _pump(self, a: socket.socket, b: socket.socket, stop_event=None,
              closed=None, host="bilinmiyor", direction="bilinmiyor", connection_id=0,
              observe_wait=False):
        stop_event = stop_event if stop_event is not None else self._stop_event
        operation = 'recv'
        count = 0
        started = time.monotonic()
        last_progress = started
        warned = False
        reason = 'bilinmiyor'
        try:
            while True:
                operation = 'recv'
                if observe_wait:
                    if stop_event.is_set() or (closed is not None and closed.is_set()):
                        reason = 'dport_durdurdu' if stop_event.is_set() else 'diger_yon_kapandi'
                        break
                    ready, _, _ = select.select([a], [], [], 1)
                    if not ready:
                        idle = time.monotonic() - last_progress
                        if idle >= 30 and not warned:
                            warned = True
                            self._l(f"TUNNEL | id={connection_id} | host={host} | yon={direction} | sonuc=veri_bekleniyor | bos_sure_ms={round(idle*1000)} | aktarilan_bayt={count} | ariza_kaniti=False")
                        continue
                d = a.recv(65536)
                if not d:
                    reason = 'karsi_uc_eof'
                    break
                operation = 'send'
                b.sendall(d)
                count += len(d)
                last_progress = time.monotonic()
        except (OSError, ValueError) as exc:
            # select can see an already-closed fd during concurrent stop.
            reason = 'zaman_asimi' if isinstance(exc, TimeoutError) else 'soket_hatasi'
            if not stop_event.is_set() and not (closed is not None and closed.is_set()):
                self._l(f"TUNNEL | id={connection_id} | host={host} | yon={direction} | islem={operation} | sonuc=aktarim_hatasi | hata={_socket_error_text(exc)}")
        finally:
            if stop_event.is_set():
                reason = 'dport_durdurdu'
            elif closed is not None and closed.is_set():
                reason = 'diger_yon_kapandi'
            self._l(f"TUNNEL | id={connection_id} | host={host} | yon={direction} | aktarilan_bayt={count} | sure_ms={round((time.monotonic()-started)*1000)} | sonuc=aktarim_bitti | neden={reason}")
            try:
                b.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        return reason

    # --- role dongusu ---
    def _serve(self, srv, event):
        try:
            while not event.is_set():
                try:
                    client, _ = srv.accept()
                except OSError:
                    break
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                threading.Thread(target=self._handle, args=(client, event), daemon=True).start()
        finally:
            # Dongu hangi sebeple biterse bitsin (stop veya beklenmedik hata),
            # role artik hizmet vermiyor: durumu dogru yansit ki watchdog fark etsin.
            if self._stop_event is event:
                self._running = False

    def start(self) -> bool:
        if self._running:
            return True
        try:
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind(("127.0.0.1", 443))
            srv.listen(16)
        except OSError as e:
            self._l(
                f"RELAY | adres=127.0.0.1:443 | sonuc=baslatilamadi | "
                f"hata={_socket_error_text(e)}"
            )
            return False
        self._srv = srv
        self._stop_event = threading.Event()
        self._running = True
        self._thread = threading.Thread(target=self._serve, args=(srv, self._stop_event), daemon=True)
        self._thread.start()
        self._l("RELAY | adres=127.0.0.1:443 | sonuc=dinliyor")
        return True

    def stop(self):
        was_running = self._running or self._srv is not None
        self._running = False
        self._stop_event.set()
        with self._dns_lock:
            self._ip_cache.clear()
        with self._socket_lock:
            sockets = list(self._sockets)
        for sock in sockets:
            self._close_socket(sock)
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
        self._srv = None
        if was_running:
            self._l("RELAY | adres=127.0.0.1:443 | sonuc=durduruldu")

    def is_active(self) -> bool:
        return self._running


# ──────────────────────────────── hosts yonetimi ────────────────────────────────
def _read_hosts() -> Optional[str]:
    # newline="" ONEMLI: evrensel satir-sonu cevirisini kapatir, boylece
    # kullanicinin CRLF satir sonlari LF'ye cevrilmeden BYTE-birebir korunur.
    # errors="surrogateescape": UTF-8 olmayan (yerel kod sayfasi/gecersiz) 3. taraf
    # byte'lari surrogate kod noktalarina esler; ayni error-handler ile geri
    # yazildiginda ORIJINAL byte'lara donusur. Boylece "byte-birebir DPort disi
    # koruma" gecersiz byte iceren hosts'ta da gercekten dogru olur (eski
    # errors='ignore' bu byte'lari sessizce dusuruyordu).
    try:
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="surrogateescape", newline="") as f:
            return f.read()
    except Exception:
        return None


LAST_HOSTS_ERROR = ""
LAST_HOSTS_WINERROR: Optional[int] = None

# Son BASARILI hosts yazma operasyonunun retry teshisi (yalniz kayit amacli;
# davranisi/akisi etkilemez). CAGIRAN THREAD'e OZEL tutulur (threading.local):
# app, add_hosts_redirect'i cagirdigi AYNI thread'de kendi sonucunu okur; arada
# baska bir thread'in yazmasi bu bilgiyi KARISTIRAMAZ (global paylasimli degil).
#  attempts: kacinci denemede basarildi (1 = ilk deneme, retry yok; 0 = henuz basari yok)
#  retry_errno / retry_winerror: basari ONCESI son gecici hatanin kodlari (retry yoksa None)
_HOSTS_TLS = threading.local()


def _reset_retry_info() -> None:
    """Cagiran thread'in retry teshis bilgisini sifirlar (yeni operasyon veya no-op)."""
    _HOSTS_TLS.attempts = 0
    _HOSTS_TLS.retry_errno = None
    _HOSTS_TLS.retry_winerror = None

# hosts dosyasina yazma/okuma islemlerini (add/remove/aktiflik) TEK sirada tutar;
# ayni anda iki thread'in (or. baglanti-etkinlestirme ile watchdog) dosyayi ezmesini onler.
_HOSTS_LOCK = threading.RLock()

# Windows winerror kodlari (hata sinifi teshisi icin):
_WINERR_ACCESS_DENIED = 5       # ERROR_ACCESS_DENIED — gercek yetki VEYA AV/controlled-folder
_WINERR_SHARING_VIOLATION = 32  # ERROR_SHARING_VIOLATION — dosyayi baska surec tutuyor
_WINERR_LOCK_VIOLATION = 33     # ERROR_LOCK_VIOLATION — kilitli bolge

# Bu winerror'lar GECICI kabul edilir (kisa sure sonra yeniden denenir). 5 (access
# denied) DPort zaten yonetici oldugu icin genelde AV/oyun anti-cheat kaynakli
# GECICI kilittir; kalici yetki reddi (elevation yok) ayrimini UST katman (app.py)
# mesajlarken winerror=5 + admin-degil kontroluyle yapar.
_TRANSIENT_WINERRORS = (_WINERR_ACCESS_DENIED, _WINERR_SHARING_VIOLATION, _WINERR_LOCK_VIOLATION)

# Artan backoff (saniye). add: ~11 sn toplam (8 deneme) — log kanitindaki ~14 sn'lik
# gecici kilidi buyuk olcude yakalar. remove: kisa (~1 sn) — acilis/watchdog yolunu
# dondurmaz; kalan temizligi watchdog + logon failsafe zaten toplar.
_ADD_BACKOFFS = (0.3, 0.6, 1.0, 1.5, 2.0, 2.5, 3.0)
_REMOVE_BACKOFFS = (0.3, 0.6)


def last_hosts_error() -> str:
    """Son hosts yazma hatasinin acik metni (teshis icin)."""
    return LAST_HOSTS_ERROR


def last_hosts_winerror() -> Optional[int]:
    """Son hosts yazma hatasinin Windows winerror kodu (yoksa None). Ust katman
    'gercek yetki reddi mi, gecici kilit mi' ayrimini bununla yapar."""
    return LAST_HOSTS_WINERROR


def last_hosts_retry_info() -> Tuple[int, Optional[int], Optional[int]]:
    """CAGIRAN THREAD'in son hosts yazma operasyonunun retry teshisi.
    Donus: (attempts, errno, winerror).
      attempts == 1 -> ilk denemede basari (retry YOK); errno/winerror None.
      attempts  > 1 -> retry oldu; errno/winerror basari ONCESI son gecici hatayi yansitir.
      attempts == 0 -> bu thread'de henuz basarili yazma olmadi (or. final failure / no-op).
    Thread'e ozeldir (threading.local): baska thread'in es zamanli islemi bu degeri
    etkilemez. Yalnizca kayit/teshis icindir; akisi veya donus davranisini etkilemez."""
    return (
        getattr(_HOSTS_TLS, "attempts", 0),
        getattr(_HOSTS_TLS, "retry_errno", None),
        getattr(_HOSTS_TLS, "retry_winerror", None),
    )


def _clear_readonly():
    """hosts dosyasi salt-okunur (ReadOnly) isaretliyse yazma bayragini acar.
    Bazi sistemlerde/AV mudahalesinde hosts ReadOnly kaliyor ve yazma engelleniyor."""
    try:
        if os.path.exists(HOSTS_PATH):
            os.chmod(HOSTS_PATH, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def _is_transient_write_error(winerr: Optional[int], err_no: Optional[int]) -> bool:
    """Yazma hatasinin GECICI (yeniden denenebilir) olup olmadigini kestirir.
    Sharing/lock violation ve (yonetici oldugumuz icin) access-denied gecici sayilir;
    winerror yoksa saf errno EACCES/EAGAIN de gecici kabul edilir. ENOSPC (disk dolu)
    gibi kalici hatalar yeniden DENENMEZ."""
    if winerr in _TRANSIENT_WINERRORS:
        return True
    if winerr is None and err_no in (errno.EACCES, errno.EAGAIN):
        return True
    return False


def _write_hosts_once(content: str) -> Tuple[bool, str, Optional[int], bool, Optional[int]]:
    """hosts'a TEK yazma denemesi. Donus: (basari, hata_metni, winerror, gecici_mi, errno).

    Yerinde 'r+' yazimi kullanilir:
      - Dosya var olan handle uzerinden yazildigi icin ACL/owner DEGISMEZ
        (os.replace gibi guvenlik tanimlayicisini temp dosyayla ezmez).
      - 'w' modunun aksine acilista dosyayi 0'a INDIRMEZ; once yeni icerik yazilir,
        sonra truncate ile fazlalik atilir. Boylece yazma yarida kesilse bile dosya
        BOS kalmaz (kullanicinin buyuk 3. taraf listesi korunur)."""
    _clear_readonly()
    try:
        # Dosya normalde vardir; yoksa (cok nadir) 'w' ile olustur — kaybedilecek
        # icerik olmadigi icin bu durumda truncation riski de yoktur.
        mode = "r+" if os.path.exists(HOSTS_PATH) else "w"
        # errors="surrogateescape": _read_hosts ile SIMETRIK — surrogate'e eslenen
        # gecersiz 3. taraf byte'lar burada tam orijinal byte olarak geri yazilir.
        with open(HOSTS_PATH, mode, encoding="utf-8", errors="surrogateescape", newline="") as f:
            f.seek(0)
            f.write(content)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass
            f.truncate()   # yeni icerik eskisinden kisaysa artan kuyrugu at
        return True, "", None, False, None
    except (PermissionError, OSError) as e:
        winerr = getattr(e, "winerror", None)
        err_no = getattr(e, "errno", None)
        text = f"{type(e).__name__}: errno={err_no} winerror={winerr}: {e}"
        return False, text, winerr, _is_transient_write_error(winerr, err_no), err_no


def _write_with_retry(compute: Callable[[], Optional[str]], backoffs) -> bool:
    """compute() her cagrildiginda hosts'u YENIDEN okuyup yazilacak tam icerigi
    (str) ya da None (okunamadi) dondurur. Gecici gorunumlu yazma hatalarinda
    sinirli sayida, artan backoff ile yeniden dener; SONSUZ beklemez. Her denemede
    diski yeniden okudugu icin, denemeler arasinda baska bir surecin yaptigi
    hosts degisiklikleri EZILMEZ."""
    global LAST_HOSTS_ERROR, LAST_HOSTS_WINERROR
    # Yeni operasyon: bu THREAD'in retry teshis bilgisini sifirla (tasima yok).
    _reset_retry_info()
    total = len(backoffs) + 1
    for i in range(total):
        content = compute()
        if content is None:
            LAST_HOSTS_ERROR = "hosts okunamadi"
            LAST_HOSTS_WINERROR = None
            return False
        ok, err, winerr, transient, err_no = _write_hosts_once(content)
        if ok:
            LAST_HOSTS_ERROR = ""
            LAST_HOSTS_WINERROR = None
            _HOSTS_TLS.attempts = i + 1   # kacinci denemede basarildi (1 = ilk, retry yok)
            return True
        LAST_HOSTS_ERROR = err
        LAST_HOSTS_WINERROR = winerr
        # Basari ONCESI son gecici hatanin kodlarini sakla (retry olursa gorunur).
        _HOSTS_TLS.retry_errno = err_no
        _HOSTS_TLS.retry_winerror = winerr
        if not transient or i == total - 1:
            return False
        time.sleep(backoffs[i])
    return False


def _strip_block(content: str) -> str:
    """Kendi blogumuzu ve eski surumlerden kalan blogu (varsa) temizler.

    GUVENLIK/VERI KAYBI: Bitis isareti eksikse (yarim yazma, elle mudahale, bozuk
    dosya) eskiden baslangic isaretinden dosya SONUNA kadar her satir silinirdi;
    bu, kullanicinin bloktan sonraki ozel hosts kayitlarini yok edebilirdi. Artik
    skip modunda YALNIZCA kendi bildigimiz '127.0.0.1 <blocked host>' satirlarini
    sileriz; bize ait olmayan bir satir gelince blogu bitmis sayar ve o satiri
    KORURUZ. Bitis isareti mevcutsa davranis oncekiyle aynidir."""
    begins = (HOSTS_MARK_BEGIN,) + tuple(b for b, _ in _LEGACY_MARKS)
    ends = (HOSTS_MARK_END,) + tuple(e for _, e in _LEGACY_MARKS)
    if not any(b in content for b in begins):
        return content
    blocked = set(BLOCKED_HOSTS)

    def _is_our_redirect(s: str) -> bool:
        parts = s.split()
        return len(parts) == 2 and parts[0] == "127.0.0.1" and parts[1] in blocked

    out = []
    skip = False
    for line in content.splitlines(keepends=True):
        s = line.strip()
        if s in begins:
            skip = True
            continue
        if s in ends:
            skip = False
            continue
        if skip:
            if _is_our_redirect(s):
                continue                 # bizim blok satirimiz -> sil
            skip = False                 # yabanci satir -> blok bitti say, KORU
            out.append(line)
        else:
            out.append(line)
    return "".join(out)


def _compute_add_content() -> Optional[str]:
    """hosts'u YENIDEN okuyup DPort blogu eklenmis TAM icerigi hesaplar (yalniz
    kendi/eski blogumuzu temizler; 3. taraf tum satirlar ve satir sonlari korunur).
    None: hosts okunamadi."""
    content = _read_hosts()
    if content is None:
        return None
    content = _strip_block(content)
    if content and not content.endswith("\n"):
        content += "\n"
    block = [HOSTS_MARK_BEGIN]
    block += [f"127.0.0.1 {h}" for h in BLOCKED_HOSTS]
    block.append(HOSTS_MARK_END)
    return content + "\n".join(block) + "\n"


def _compute_remove_content() -> Optional[str]:
    """hosts'u YENIDEN okuyup yalnizca DPort/eski blogu cikarilmis icerigi
    hesaplar. None: okunamadi."""
    content = _read_hosts()
    if content is None:
        return None
    return _strip_block(content)


def add_hosts_redirect() -> bool:
    with _HOSTS_LOCK:
        return _write_with_retry(_compute_add_content, _ADD_BACKOFFS)


def remove_hosts_redirect() -> bool:
    with _HOSTS_LOCK:
        content = _read_hosts()
        if content is None:
            return False
        begins = (HOSTS_MARK_BEGIN,) + tuple(b for b, _ in _LEGACY_MARKS)
        if not any(b in content for b in begins):
            # Temizlenecek blok yok: yazma yapilmaz ama bu thread'in ONCEKI
            # operasyondan kalan retry teshis bilgisi de bayat kalmasin — sifirla.
            _reset_retry_info()
            return True
        return _write_with_retry(_compute_remove_content, _REMOVE_BACKOFFS)


def is_hosts_redirect_active() -> bool:
    with _HOSTS_LOCK:
        content = _read_hosts()
    return bool(content and HOSTS_MARK_BEGIN in content)
