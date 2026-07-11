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
import errno
import json
import os
import stat
import socket
import threading
import time
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
            # Kotuye kullanim engeli: SNI VERILMIS ama whitelist disi bir hedefse
            # reddet (keyfi hedefe tunel actirmayi engeller). SNI okunamazsa keyfi
            # hedef zaten belirlenemez; guvenli varsayilana (updates.discord.com,
            # whitelist'te) duseriz — bu bazi Discord baglantilarinin calismasi icin
            # gereklidir ve keyfi tunele izin vermez.
            if sni and sni.lower() not in ALLOWED_HOSTS:
                self._l(f"unblock: izin verilmeyen hedef reddedildi ({sni})")
                return
            host = sni if sni else BLOCKED_HOSTS[0]
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

# hosts dosyasina yazma/okuma islemlerini (add/remove/aktiflik) TEK sirada tutar;
# ayni anda iki thread'in (or. _open_discord_w ile watchdog) dosyayi ezmesini onler.
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


def _write_hosts_once(content: str) -> Tuple[bool, str, Optional[int], bool]:
    """hosts'a TEK yazma denemesi. Donus: (basari, hata_metni, winerror, gecici_mi).

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
        return True, "", None, False
    except (PermissionError, OSError) as e:
        winerr = getattr(e, "winerror", None)
        err_no = getattr(e, "errno", None)
        text = f"{type(e).__name__}: errno={err_no} winerror={winerr}: {e}"
        return False, text, winerr, _is_transient_write_error(winerr, err_no)


def _write_with_retry(compute: Callable[[], Optional[str]], backoffs) -> bool:
    """compute() her cagrildiginda hosts'u YENIDEN okuyup yazilacak tam icerigi
    (str) ya da None (okunamadi) dondurur. Gecici gorunumlu yazma hatalarinda
    sinirli sayida, artan backoff ile yeniden dener; SONSUZ beklemez. Her denemede
    diski yeniden okudugu icin, denemeler arasinda baska bir surecin yaptigi
    hosts degisiklikleri EZILMEZ."""
    global LAST_HOSTS_ERROR, LAST_HOSTS_WINERROR
    total = len(backoffs) + 1
    for i in range(total):
        content = compute()
        if content is None:
            LAST_HOSTS_ERROR = "hosts okunamadi"
            LAST_HOSTS_WINERROR = None
            return False
        ok, err, winerr, transient = _write_hosts_once(content)
        if ok:
            LAST_HOSTS_ERROR = ""
            LAST_HOSTS_WINERROR = None
            return True
        LAST_HOSTS_ERROR = err
        LAST_HOSTS_WINERROR = winerr
        if not transient or i == total - 1:
            return False
        time.sleep(backoffs[i])
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
            return True   # temizlenecek blok yok
        return _write_with_retry(_compute_remove_content, _REMOVE_BACKOFFS)


def is_hosts_redirect_active() -> bool:
    with _HOSTS_LOCK:
        content = _read_hosts()
    return bool(content and HOSTS_MARK_BEGIN in content)
