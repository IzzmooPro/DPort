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
  3. Role, gelen ClientHello'dan hedef host adini (SNI) okur, gercek IP'yi DoH
     (1.1.1.1) ile cozer, sunucuya baglanir ve ClientHello'yu parcalayarak iletir.
  4. Sonrasi seffaf TCP tunelidir; TLS uctan uca client ile sunucu arasinda kalir
     (role sertifikayi gormez, MITM yoktur).
"""
import json
import os
import stat
import socket
import threading
import time
import urllib.request
from typing import Dict, List, Optional

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

_DOH_URL = "https://1.1.1.1/dns-query"


# ────────────────────────────── DoH cozumleme ──────────────────────────────
def doh_resolve(host: str, timeout: int = 8) -> List[str]:
    """Gercek IP'leri DoH ile cozer. 1.1.1.1'e IP ile baglaniriz; SNI adi
    gonderilmedigi icin bu istek DPI'a takilmaz."""
    url = f"{_DOH_URL}?name={host}&type=A"
    req = urllib.request.Request(url, headers={"accept": "application/dns-json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        obj = json.load(resp)
    return [a["data"] for a in obj.get("Answer", []) if a.get("type") == 1]


# ─────────────────────────────── SNI ayristirma ───────────────────────────────
def parse_sni(data: bytes) -> Optional[str]:
    """TLS ClientHello icinden server_name (SNI) degerini cikarir."""
    try:
        if len(data) < 45 or data[0] != 0x16:  # 0x16 = handshake
            return None
        idx = 5 + 4 + 2 + 32  # record hdr + handshake hdr + version + random
        sid_len = data[idx]
        idx += 1 + sid_len
        cs_len = int.from_bytes(data[idx:idx + 2], "big")
        idx += 2 + cs_len
        comp_len = data[idx]
        idx += 1 + comp_len
        ext_total = int.from_bytes(data[idx:idx + 2], "big")
        idx += 2
        end = min(idx + ext_total, len(data))
        while idx + 4 <= end:
            etype = int.from_bytes(data[idx:idx + 2], "big")
            elen = int.from_bytes(data[idx + 2:idx + 4], "big")
            body = idx + 4
            if etype == 0x0000:  # server_name
                name_len = int.from_bytes(data[body + 3:body + 5], "big")
                name = data[body + 5:body + 5 + name_len]
                return name.decode("idna", errors="ignore") or name.decode(
                    "latin1", errors="ignore"
                )
            idx = body + elen
        return None
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
    data = b""
    while len(data) < 5:
        chunk = sock.recv(4096)
        if not chunk:
            return data
        data += chunk
    if data[0] != 0x16:  # TLS handshake degil; oldugu gibi don
        return data
    total = 5 + int.from_bytes(data[3:5], "big")
    while len(data) < total and len(data) < cap:
        chunk = sock.recv(4096)
        if not chunk:
            break
        data += chunk
    return data


# ──────────────────────────────── Role (relay) ────────────────────────────────
class DiscordUnblocker:
    def __init__(self, log=None):
        self._log = log
        self._srv: Optional[socket.socket] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._ip_cache: Dict[str, tuple] = {}  # host -> (ips, expiry)

    # --- gunluk ---
    def _l(self, msg: str):
        if self._log:
            try:
                self._log(msg)
            except Exception:
                pass

    # --- IP cozumleme (cache'li) ---
    def _resolve(self, host: str) -> List[str]:
        cached = self._ip_cache.get(host)
        if cached and cached[1] > time.time():
            return cached[0]
        ips = doh_resolve(host)
        if ips:
            self._ip_cache[host] = (ips, time.time() + 300)
        return ips

    # --- parcali ClientHello ile yeniden-denemeli upstream baglantisi ---
    def _open_upstream(self, hello: bytes, ips: List[str], attempts: int = 7):
        """Parcalanmis ClientHello'yu gonderir ve sunucudan ServerHello gelene
        kadar (gerekirse farkli IP'lerle) tekrar dener.

        Bu DPI zamana gore degisken davraniyor: parcalanmis bir baglanti bile
        bazen resetleniyor. Reset, sunucunun el sikismasi sirasinda baglantiyi
        kapatmasi (bos recv / RST) olarak gorunur. Denemeleri araliklara YAYARIZ;
        boylece her deneme taze bir DPI karar penceresine denk gelir ve
        birinde parcalama tutar. Tek deneme ~%75-100 tutuyorsa, yayilmis 7
        deneme ile guvenilirlik pratikte ~%99.9'a cikar.

        Doner: (server_soketi, sunucudan_gelen_ilk_bloklar) veya (None, None)."""
        frag = fragment_client_hello(hello)
        for i in range(attempts):
            se = None
            try:
                ip = ips[i % len(ips)]
                se = socket.create_connection((ip, 443), timeout=8)
                se.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                se.sendall(frag)
                se.settimeout(4)
                first = se.recv(65536)
                if first and first[0] == 0x16:  # 0x16 = TLS ServerHello/handshake
                    se.settimeout(None)
                    return se, first
                # bos veya beklenmedik yanit -> DPI reseti; tekrar dene
                se.close()
            except OSError:
                if se:
                    try:
                        se.close()
                    except OSError:
                        pass
            # denemeler arasi artan bekleme: taze DPI penceresine denk gelmek icin
            time.sleep(0.5 + i * 0.25)
        return None, None

    # --- tek baglanti islemesi ---
    def _handle(self, client: socket.socket):
        server = None
        try:
            client.settimeout(10)
            first = _recv_full_client_hello(client)  # ClientHello'nun tamami
            if not first:
                return
            sni = parse_sni(first)
            host = sni or BLOCKED_HOSTS[0]
            ips = self._resolve(host)
            if not ips:
                self._l(f"unblock: {host} IP cozulemedi")
                return

            server, server_first = self._open_upstream(first, ips)
            if server is None:
                self._l(f"unblock: {host} el sikismasi tum denemelerde resetlendi")
                return

            client.settimeout(None)
            # Sunucudan gelen ilk blogu (ServerHello) istemciye ilet, sonra tunelle
            client.sendall(server_first)
            t = threading.Thread(target=self._pump, args=(client, server), daemon=True)
            t.start()
            self._pump(server, client)
        except Exception:
            pass
        finally:
            for s in (client, server):
                if s:
                    try:
                        s.close()
                    except OSError:
                        pass

    @staticmethod
    def _pump(a: socket.socket, b: socket.socket):
        try:
            while True:
                d = a.recv(65536)
                if not d:
                    break
                b.sendall(d)
        except OSError:
            pass
        finally:
            try:
                b.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    # --- role dongusu ---
    def _serve(self):
        try:
            while self._running:
                try:
                    client, _ = self._srv.accept()
                except OSError:
                    break
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                threading.Thread(target=self._handle, args=(client,), daemon=True).start()
        finally:
            # Dongu hangi sebeple biterse bitsin (stop veya beklenmedik hata),
            # role artik hizmet vermiyor: durumu dogru yansit ki watchdog fark etsin.
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
            self._l(f"unblock: 443 portu dinlenemedi ({e})")
            return False
        self._srv = srv
        self._running = True
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        self._l("unblock: yerel role 127.0.0.1:443 dinliyor")
        return True

    def stop(self):
        self._running = False
        if self._srv:
            try:
                self._srv.close()
            except OSError:
                pass
        self._srv = None

    def is_active(self) -> bool:
        return self._running


# ──────────────────────────────── hosts yonetimi ────────────────────────────────
def _read_hosts() -> Optional[str]:
    try:
        with open(HOSTS_PATH, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    except Exception:
        return None


LAST_HOSTS_ERROR = ""


def last_hosts_error() -> str:
    """Son hosts yazma hatasinin acik metni (teshis icin)."""
    return LAST_HOSTS_ERROR


def _clear_readonly():
    """hosts dosyasi salt-okunur (ReadOnly) isaretliyse yazma bayragini acar.
    Bazi sistemlerde/AV mudahalesinde hosts ReadOnly kaliyor ve yazma engelleniyor."""
    try:
        if os.path.exists(HOSTS_PATH):
            os.chmod(HOSTS_PATH, stat.S_IWRITE | stat.S_IREAD)
    except Exception:
        pass


def _write_hosts(content: str) -> bool:
    global LAST_HOSTS_ERROR
    _clear_readonly()
    try:
        with open(HOSTS_PATH, "w", encoding="utf-8", errors="ignore", newline="") as f:
            f.write(content)
        LAST_HOSTS_ERROR = ""
        return True
    except PermissionError:
        # Bir kez daha salt-okunuru kaldirip tekrar dene.
        _clear_readonly()
        try:
            with open(HOSTS_PATH, "w", encoding="utf-8", errors="ignore", newline="") as f:
                f.write(content)
            LAST_HOSTS_ERROR = ""
            return True
        except Exception as e:
            LAST_HOSTS_ERROR = f"{type(e).__name__}: {e}"
            return False
    except Exception as e:
        LAST_HOSTS_ERROR = f"{type(e).__name__}: {e}"
        return False


def _strip_block(content: str) -> str:
    """Kendi blogumuzu ve eski surumlerden kalan blogu (varsa) temizler."""
    begins = (HOSTS_MARK_BEGIN,) + tuple(b for b, _ in _LEGACY_MARKS)
    ends = (HOSTS_MARK_END,) + tuple(e for _, e in _LEGACY_MARKS)
    if not any(b in content for b in begins):
        return content
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
        if not skip:
            out.append(line)
    return "".join(out)


def add_hosts_redirect() -> bool:
    content = _read_hosts()
    if content is None:
        return False
    content = _strip_block(content)
    if content and not content.endswith("\n"):
        content += "\n"
    block = [HOSTS_MARK_BEGIN]
    block += [f"127.0.0.1 {h}" for h in BLOCKED_HOSTS]
    block.append(HOSTS_MARK_END)
    content += "\n".join(block) + "\n"
    return _write_hosts(content)


def remove_hosts_redirect() -> bool:
    content = _read_hosts()
    if content is None:
        return False
    begins = (HOSTS_MARK_BEGIN,) + tuple(b for b, _ in _LEGACY_MARKS)
    if not any(b in content for b in begins):
        return True
    return _write_hosts(_strip_block(content))


def is_hosts_redirect_active() -> bool:
    content = _read_hosts()
    return bool(content and HOSTS_MARK_BEGIN in content)
