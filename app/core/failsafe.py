"""
core/failsafe.py

hosts-yonlendirmesi guvenlik agi.

Discord'un engelli host'lari (discord.com, gateway... vb.) program calisirken
127.0.0.1'e yonlendiriliyor. Program NORMAL kapanmadan olurse (cokme, Gorev
Yoneticisi'nden kapatma, ani elektrik, mavi ekran) bu satirlar hosts'ta kalir ve
Discord + tarayicidan discord.com TAMAMEN acilmaz.

Bu modul, her oturum acilista (logon) YUKSEK YETKIYLE sessizce calisan bir
zamanlanmis gorev kurar. Gorev, DOGRULANMIS kurulu DPort.exe'yi `--cleanup-hosts`
ile cagirir; o da hosts'taki isaretli blogu siler. Boylece program bir daha hic
acilmasa bile Discord en gec bir sonraki oturumda tekrar normale doner.

YASAM DONGUSU: gorev KALICI DEGILDIR. Yalnizca isaretli hosts yonlendirmesinin
aktif olabilecegi aralikta bulunur:
  kur       -> hosts YAZILMADAN hemen once (baglanti yolu)
  uzlastir  -> hosts temizligi denenen her yerde (acilis, kapanis, watchdog,
               rollback, `--cleanup-hosts`) -> reconcile_failsafe_task()
Temiz bir sistemde ONLOGON/HIGHEST bir gorev asili KALMAZ.

────────────────────────────────────────────────────────────────────────────
GUVENLIK (F2): "/RL HIGHEST" gorevinin hedefi ASLA degistirilebilir olmamali
────────────────────────────────────────────────────────────────────────────
Gorev, her oturum acilista EN YUKSEK yetkiyle calisir. Hedefi standart
kullanicinin degistirebildigi bir exe olursa, kullanici baglamindaki bir surec
o dosyayi kendi yuku ile degistirip KALICI, UAC'siz yetki yukseltmesi elde eder.

Eski kontrol yalnizca `sys.executable`'in `%ProgramFiles%` ile BASLAYIP
baslamadigina bakiyordu. Bu yetersizdi:
  - `ProgramFiles`, `ProgramFiles(x86)`, `ProgramW6432` ortam degiskenleri
    standart kullanici tarafindan (HKCU\\Environment) DEGISTIRILEBILIR; sahte
    bir kok gostererek yazilabilir bir klasor "korumali" sayilabiliyordu.
  - Yol dizgi olarak karsilastiriliyordu; junction/symlink, 8.3 kisa ad veya
    farkli yazim ile ayni kontrol atlatilabiliyordu.
  - Klasorun GERCEK izinlerine hic bakilmiyordu; Program Files altinda bile
    olsa gevsek ACL'li bir klasor kabul ediliyordu.

Yeni kontrol (hepsi saglanmazsa gorev KURULMAZ):
  1. Surec paketlenmis (frozen) olmali.
  2. Program Files kokleri ORTAM DEGISKENINDEN DEGIL, SHGetKnownFolderPath ile
     alinir (kullanici degistiremez).
  3. `sys.executable` ve koklerin ikisi de GetFinalPathNameByHandleW ile
     CANONICAL hale getirilir: symlink/junction cozulur, 8.3 kisa ad acilir,
     yazim normallenir. Ag (UNC) yollari reddedilir.
  4. Exe'den surucu kokune kadar TUM zincirde reparse point (junction/symlink)
     olmamali.
  5. Exe'nin ve exe klasorunun GERCEK DACL'i okunur. Yazma/silme/sahiplik/ACL
     haklari yalnizca SYSTEM, Administrators, TrustedInstaller ve CREATOR OWNER
     tarafindan tutulabilir. Users, Authenticated Users, Everyone veya herhangi
     bir normal kullanici hesabi bu haklardan birine sahipse REDDEDILIR.
  6. Exe'nin ve klasorunun SAHIBI de ayricalikli olmali (sahip, DACL'i her zaman
     degistirebilir).
  7. Herhangi bir Windows API hatasinda veya tanimadigimiz bir ACE turunde
     FAIL CLOSED davranilir (guvenli sayilmaz).

Kosul saglanmazsa yalnizca kurulum atlanmaz; onceki surumlerden kalmis olabilecek
GUVENSIZ/ESKI gorev de KALDIRILIR. Gorev hedefine her zaman DOGRULANMIS canonical
exe yolu yazilir (`sys.executable` ham hali degil).

KAYNAK MODU: `sys.executable` python.exe, betik ise kullanici-yazilabilir bir
.py dosyasidir; ikisi de HIGHEST yetkili bir goreve ASLA hedef olamaz. Bunun
yerine BAGIMSIZ olarak kesfedilmis ve ayni olcutlerden gecen kurulu
`<ProgramFiles>\\DPort\\DPort.exe` kurtarma hedefi olarak kullanilabilir
(bkz. `_installed_recovery_target`).

Gorev kurulamadiginda hosts yonlendirmesi HIC YAZILMAZ: temizleyicisi olmayan
bir yonlendirme birakmaktansa baglanti yolu acilmaz. Bu yuzden ust katman,
sistemi degistirmeden once `verified_failsafe_target()` ile salt-okunur bir
on-kontrol yapar (bkz. gui/app.py::_preflight_failsafe_target); son ve baglayici
kontrol yine `install_logon_failsafe()` icindedir (TOCTOU).
"""
import ctypes
import os
import subprocess
import sys
from ctypes import wintypes
from typing import List, Optional

TASK_NAME = "DPortHostsFailsafe"
_LEGACY_TASKS = ("DiscordConnectHostsFailsafe",)

_FLAGS = subprocess.CREATE_NO_WINDOW

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
else:  # pragma: no cover - DPort yalnizca Windows'ta calisir
    _kernel32 = _advapi32 = _shell32 = _ole32 = None


# ───────────────────────────── Win32 sabitleri ─────────────────────────────
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000   # dizin handle'i acabilmek icin
FILE_NAME_NORMALIZED = 0x0
VOLUME_NAME_DOS = 0x0
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
SE_FILE_OBJECT = 1

ACCESS_ALLOWED_ACE_TYPE = 0x00
ACCESS_DENIED_ACE_TYPE = 0x01
INHERIT_ONLY_ACE = 0x08

# Bir dosyayi/klasoru DEGISTIRMEYE veya izinlerini ele gecirmeye yarayan haklar.
FILE_WRITE_DATA = 0x00000002        # = FILE_ADD_FILE
FILE_APPEND_DATA = 0x00000004       # = FILE_ADD_SUBDIRECTORY
FILE_WRITE_EA = 0x00000010
FILE_DELETE_CHILD = 0x00000040
FILE_WRITE_ATTRIBUTES = 0x00000100
DELETE = 0x00010000
WRITE_DAC = 0x00040000
WRITE_OWNER = 0x00080000
GENERIC_ALL = 0x10000000
GENERIC_WRITE = 0x40000000

_DANGEROUS_RIGHTS = (
    FILE_WRITE_DATA | FILE_APPEND_DATA | FILE_WRITE_EA | FILE_DELETE_CHILD
    | FILE_WRITE_ATTRIBUTES | DELETE | WRITE_DAC | WRITE_OWNER
    | GENERIC_ALL | GENERIC_WRITE
)

# Kurulum konumunda YAZMA hakki tutmasina izin verilen tek principal'lar.
# Allowlist bilincli: tanimadigimiz hicbir principal yazma hakki tutamaz.
_TRUSTED_WRITER_SIDS = frozenset({
    "S-1-5-18",        # NT AUTHORITY\SYSTEM
    "S-1-5-32-544",    # BUILTIN\Administrators
    "S-1-3-0",         # CREATOR OWNER (sahip ayrica dogrulanir)
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",  # TrustedInstaller
})

# Nesnenin sahibi olabilecek ayricalikli principal'lar (sahip DACL'i degistirebilir).
_TRUSTED_OWNER_SIDS = frozenset({
    "S-1-5-18",
    "S-1-5-32-544",
    "S-1-5-80-956008885-3418522649-1831038044-1853292631-2271478464",
})


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(d1, d2, d3, tail):
    return _GUID(d1, d2, d3, (ctypes.c_ubyte * 8)(*tail))


# FOLDERID_ProgramFiles / ProgramFilesX86 / ProgramFilesX64
_FOLDERID_PROGRAM_FILES = _guid(
    0x905E63B6, 0xC1BF, 0x494E, (0xB2, 0x9C, 0x65, 0xB7, 0x32, 0xD3, 0xD2, 0x1A))
_FOLDERID_PROGRAM_FILES_X86 = _guid(
    0x7C5A40EF, 0xA0FB, 0x4BFC, (0x87, 0x4A, 0xC0, 0xF2, 0xE0, 0xB9, 0xFA, 0x8E))
_FOLDERID_PROGRAM_FILES_X64 = _guid(
    0x6D809377, 0x6AF0, 0x444B, (0x89, 0x57, 0xA3, 0x77, 0x3F, 0x02, 0x20, 0x0E))


class _ACL(ctypes.Structure):
    _fields_ = [
        ("AclRevision", ctypes.c_ubyte),
        ("Sbz1", ctypes.c_ubyte),
        ("AclSize", wintypes.WORD),
        ("AceCount", wintypes.WORD),
        ("Sbz2", wintypes.WORD),
    ]


class _ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("AceType", ctypes.c_ubyte),
        ("AceFlags", ctypes.c_ubyte),
        ("AceSize", wintypes.WORD),
    ]


class _ACCESS_ALLOWED_ACE(ctypes.Structure):
    _fields_ = [
        ("Header", _ACE_HEADER),
        ("Mask", wintypes.DWORD),
        ("SidStart", wintypes.DWORD),
    ]


_SID_OFFSET = _ACCESS_ALLOWED_ACE.SidStart.offset


# ───────────────────────────── Yol normalizasyonu ─────────────────────────────
def _known_folder(folder_id: _GUID) -> Optional[str]:
    """Bilinen klasor yolunu ORTAM DEGISKENINDEN DEGIL, kabuk API'sinden alir."""
    if not _IS_WINDOWS:  # pragma: no cover
        return None
    ptr = ctypes.c_wchar_p()
    try:
        if _shell32.SHGetKnownFolderPath(
            ctypes.byref(folder_id), 0, None, ctypes.byref(ptr)
        ) != 0:
            return None
        return ptr.value
    except Exception:
        return None
    finally:
        try:
            if ptr:
                _ole32.CoTaskMemFree(ptr)
        except Exception:
            pass


def canonical_path(path: str) -> Optional[str]:
    """Yolu GERCEK, tam nitelikli haline cevirir.

    GetFinalPathNameByHandleW kullanir: symlink/junction cozulur, 8.3 kisa ad
    acilir, buyuk/kucuk harf ve yazim normallenir. Boylece dizgi karsilastirmasi
    yaniltilamaz. Ag (UNC) yollari korumali kurulum sayilmaz -> None.
    Hata halinde None (fail closed)."""
    if not _IS_WINDOWS or not path:  # pragma: no cover
        return None
    handle = _kernel32.CreateFileW(
        path, 0,  # yalnizca metadata; okuma izni gerekmez
        FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
        None, OPEN_EXISTING, FILE_FLAG_BACKUP_SEMANTICS, None,
    )
    if not handle or handle == INVALID_HANDLE_VALUE:
        return None
    try:
        buf = ctypes.create_unicode_buffer(32768)
        length = _kernel32.GetFinalPathNameByHandleW(
            wintypes.HANDLE(handle), buf, 32767,
            FILE_NAME_NORMALIZED | VOLUME_NAME_DOS,
        )
        if length == 0 or length >= 32767:
            return None
        resolved = buf.value
        if resolved.startswith("\\\\?\\UNC\\"):
            return None                      # ag paylasimi korumali sayilmaz
        if resolved.startswith("\\\\?\\"):
            resolved = resolved[4:]
        if not resolved:
            return None
        return os.path.normcase(resolved)
    except Exception:
        return None
    finally:
        try:
            _kernel32.CloseHandle(wintypes.HANDLE(handle))
        except Exception:
            pass


def _path_chain(path: str) -> List[str]:
    """Yolun kendisi + surucu kokune kadar tum ust dizinleri."""
    chain = [path]
    current = os.path.dirname(path)
    while current and current not in chain:
        chain.append(current)
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return chain


def _is_reparse_point(path: str) -> Optional[bool]:
    """True/False; okunamazsa None (cagiran FAIL CLOSED davranir)."""
    if not _IS_WINDOWS:  # pragma: no cover
        return None
    attrs = _kernel32.GetFileAttributesW(path)
    if attrs == INVALID_FILE_ATTRIBUTES:
        return None
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def _chain_has_reparse_point(path: str) -> Optional[bool]:
    """Zincirdeki herhangi bir bileşen reparse point mi? Belirsizse None."""
    for part in _path_chain(path):
        state = _is_reparse_point(part)
        if state is None:
            return None
        if state:
            return True
    return False


# ───────────────────────────── DACL / sahiplik ─────────────────────────────
def _sid_to_string(sid_ptr) -> Optional[str]:
    text = ctypes.c_wchar_p()
    try:
        if not _advapi32.ConvertSidToStringSidW(sid_ptr, ctypes.byref(text)):
            return None
        try:
            return text.value
        finally:
            try:
                _kernel32.LocalFree(text)
            except Exception:
                pass
    except Exception:
        return None


def _is_untrusted_writer(sid: str) -> bool:
    """Bu principal kurulum klasorunde yazma hakki TUTMAMALI mi?

    Allowlist disindaki her sey guvensizdir. Users (S-1-5-32-545),
    Authenticated Users (S-1-5-11), Everyone (S-1-1-0) ve normal kullanici
    hesaplari (S-1-5-21-...-RID>=1000) bu tanimin icindedir."""
    return sid not in _TRUSTED_WRITER_SIDS


def dacl_writers_are_trusted(path: str) -> Optional[bool]:
    """Yalnizca guvenilir principal'lar yazma/silme/ACL hakki tutuyor mu?

    True  : guvenli.
    False : Users / Authenticated Users / Everyone / normal bir hesap yazabiliyor,
            silebiliyor ya da sahiplik/ACL degistirebiliyor.
    None  : okunamadi veya tanimadigimiz bir ACE turu var -> FAIL CLOSED.

    NOT: DENY ACE'leri bilincli olarak YOK SAYILIR. Bir deny ACE, allow'u
    daraltabilirdi; onu hesaba katmamak bizi yalnizca DAHA katı yapar
    (guvenli tarafa hata yapariz)."""
    if not _IS_WINDOWS:  # pragma: no cover
        return None
    psd = ctypes.c_void_p()
    dacl = ctypes.c_void_p()
    try:
        if _advapi32.GetNamedSecurityInfoW(
            path, SE_FILE_OBJECT, DACL_SECURITY_INFORMATION,
            None, None, ctypes.byref(dacl), None, ctypes.byref(psd),
        ) != 0:
            return None
        if not dacl:
            # NULL DACL = herkese tam yetki. Kesinlikle guvenli degil.
            return False

        acl = ctypes.cast(dacl, ctypes.POINTER(_ACL)).contents
        for index in range(acl.AceCount):
            pace = ctypes.c_void_p()
            if not _advapi32.GetAce(dacl, index, ctypes.byref(pace)):
                return None
            header = ctypes.cast(pace, ctypes.POINTER(_ACE_HEADER)).contents
            if header.AceFlags & INHERIT_ONLY_ACE:
                continue                     # bu nesneye uygulanmaz
            if header.AceType == ACCESS_DENIED_ACE_TYPE:
                continue                     # bkz. docstring
            if header.AceType != ACCESS_ALLOWED_ACE_TYPE:
                return None                  # tanimadigimiz tur -> fail closed
            ace = ctypes.cast(pace, ctypes.POINTER(_ACCESS_ALLOWED_ACE)).contents
            if not (ace.Mask & _DANGEROUS_RIGHTS):
                continue
            sid = _sid_to_string(ctypes.c_void_p(pace.value + _SID_OFFSET))
            if sid is None:
                return None
            if _is_untrusted_writer(sid):
                return False
        return True
    except Exception:
        return None
    finally:
        try:
            if psd:
                _kernel32.LocalFree(psd)
        except Exception:
            pass


def owner_is_trusted(path: str) -> Optional[bool]:
    """Nesnenin sahibi ayricalikli mi? Sahip DACL'i her zaman degistirebilir,
    bu yuzden gevsek bir sahip gevsek bir ACL kadar tehlikelidir.
    Okunamazsa None (fail closed)."""
    if not _IS_WINDOWS:  # pragma: no cover
        return None
    psd = ctypes.c_void_p()
    sid = ctypes.c_void_p()
    try:
        if _advapi32.GetNamedSecurityInfoW(
            path, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION,
            ctypes.byref(sid), None, None, None, ctypes.byref(psd),
        ) != 0:
            return None
        text = _sid_to_string(sid)
        if text is None:
            return None
        return text in _TRUSTED_OWNER_SIDS
    except Exception:
        return None
    finally:
        try:
            if psd:
                _kernel32.LocalFree(psd)
        except Exception:
            pass


def _location_is_acl_protected(path: str) -> bool:
    """Verilen nesne ve icinde bulundugu klasor, standart kullanicinin
    degistiremeyecegi sekilde korunuyor mu? Belirsizlikte False."""
    for target in (path, os.path.dirname(path)):
        if not target:
            return False
        if dacl_writers_are_trusted(target) is not True:
            return False
        if owner_is_trusted(target) is not True:
            return False
    return True


# ───────────────────────── Korumali konum kontrolu ─────────────────────────
def _program_files_roots() -> List[str]:
    """Gercek Program Files kokleri (canonical). Ortam degiskeni KULLANILMAZ."""
    roots = []
    for folder_id in (_FOLDERID_PROGRAM_FILES,
                      _FOLDERID_PROGRAM_FILES_X86,
                      _FOLDERID_PROGRAM_FILES_X64):
        raw = _known_folder(folder_id)
        if not raw:
            continue
        resolved = canonical_path(raw)
        if resolved and resolved not in roots:
            roots.append(resolved)
    return roots


def path_is_verified_install(path: str) -> Optional[str]:
    """VERILEN yol, HIGHEST yetkili goreve baglanabilecek kadar korunuyor mu?

    Tum kontroller gecerse canonical yolu, aksi halde None dondurur. Hem calisan
    exe'yi hem de KAYITLI bir gorev hedefini ayni olcutle degerlendirmek icin
    kullanilir."""
    if not _IS_WINDOWS or not path:  # pragma: no cover
        return None

    exe = canonical_path(path)
    if not exe or not os.path.isfile(exe):
        return None

    # Junction/symlink ile korumali gorunen bir yol uydurulamasin.
    if _chain_has_reparse_point(exe) is not False:
        return None

    roots = _program_files_roots()
    if not roots:
        return None
    if not any(exe.startswith(root + os.sep) for root in roots):
        return None

    # Program Files altinda olmak TEK BASINA yetmez: gercek izinler de kapali olmali.
    if not _location_is_acl_protected(exe):
        return None

    return exe


_INSTALL_DIR_NAME = "DPort"
_INSTALL_EXE_NAME = "DPort.exe"


def _installed_recovery_target() -> Optional[str]:
    """Kaynaktan calisirken kullanilabilecek KURULU DPort.exe.

    Kaynak modunda `sys.executable` python.exe'dir ve betik kullanici-yazilabilir
    bir .py dosyasidir; ikisi de HIGHEST yetkili bir goreve BAGLANAMAZ. Ama
    makinede Program Files altinda DOGRULANMIS bir DPort kurulumu varsa, hosts
    yonlendirmesinin kurtaricisi O olabilir.

    Aday, ortam degiskeni/PATH/kullanici dizini gibi ZEHIRLENEBILIR kaynaklardan
    DEGIL, `_program_files_roots()` (SHGetKnownFolderPath) uzerinden kesfedilir
    ve `path_is_verified_install()` kontrollerinin (canonical yol, reparse point
    yok, DACL + sahiplik kapali) TAMAMINDAN gecmek zorundadir.

    Ikinci kaynak: hali hazirda KAYITLI gorevin hedefi. O da ayni olcutle
    dogrulanir; dogrulanamiyorsa yeniden KULLANILMAZ (ayrica
    `_ensure_no_unsafe_task()` tarafindan kaldirilir).

    PROTOKOL: hedefin `--cleanup-hosts` bayragini destekledigi varsayim degil:
    bu bayrak DPort'un ILK surumunden beri `main.py` girisindedir ve aday
    yalnizca `<ProgramFiles>\\DPort\\DPort.exe` kalibina uyan, dogrulanmis bir
    DPort kurulumu olabilir."""
    for root in _program_files_roots():
        candidate = os.path.join(root, _INSTALL_DIR_NAME, _INSTALL_EXE_NAME)
        verified = path_is_verified_install(candidate)
        if verified:
            return verified

    registered = _registered_task_target()
    if registered:
        verified = path_is_verified_install(registered)
        if verified and (os.path.basename(verified)
                         == os.path.normcase(_INSTALL_EXE_NAME)):
            return verified
    return None


def verified_failsafe_target() -> Optional[str]:
    """HIGHEST yetkili gorevin hedefi olarak kabul edilebilecek yol.

    Gorev hedefine YALNIZCA bu deger yazilir.

    - Paketlenmis (frozen) surec: YALNIZCA calisan exe degerlendirilir. Portable
      veya kurcalanmis bir kopya, kurulu surumun gorevini devralamaz.
    - Kaynak modu: calisan betik ASLA hedef olamaz; yalnizca bagimsiz olarak
      kesfedilmis ve dogrulanmis kurulu DPort.exe kullanilabilir."""
    if getattr(sys, "frozen", False):
        return path_is_verified_install(sys.executable)
    return _installed_recovery_target()


def _exe_in_protected_location() -> bool:
    """Geriye donuk ad: HIGHEST yetkili goreve baglanabilecek DOGRULANMIS bir
    hedef var mi? (Paketlenmis surecte calisan exe; kaynak modunda bagimsiz
    kesfedilmis kurulu DPort.exe.)"""
    return verified_failsafe_target() is not None


# ───────────────────────────── Gorev yasam dongusu ─────────────────────────────
def _cleanup_command(exe: str) -> str:
    """hosts temizleyiciyi calistiran komut satiri. `exe` DOGRULANMIS canonical
    yoldur; ham `sys.executable` asla kullanilmaz."""
    return f'"{exe}" --cleanup-hosts'


# Son basarisiz gorev islemi (teshis/log icin). Sessizce yutulan bir silme
# hatasi, yazilabilir bir hedefi gosteren HIGHEST gorevin AYAKTA KALMASI
# demektir; bu yuzden gorunur olmali.
LAST_ERROR = ""


def last_failsafe_error() -> str:
    """Son gorev islemindeki hata metni (yoksa bos). Ust katman loglar."""
    return LAST_ERROR


def _set_error(message: str) -> None:
    global LAST_ERROR
    LAST_ERROR = message


def _run_schtasks(args: List[str]):
    """schtasks calistirir. Hata halinde None (cagiran FAIL CLOSED davranir)."""
    try:
        return subprocess.run(
            ["schtasks"] + args, capture_output=True, text=True,
            encoding="utf-8", errors="ignore", timeout=15, creationflags=_FLAGS,
        )
    except Exception as exc:
        _set_error(f"schtasks calistirilamadi: {exc}")
        return None


def _task_exists(name: str) -> Optional[bool]:
    """Gorev kayitli mi? Sorgu calistirilamazsa None (belirsiz)."""
    r = _run_schtasks(["/Query", "/TN", name])
    if r is None:
        return None
    return r.returncode == 0


def _task_command(name: str) -> Optional[str]:
    """Gorevin <Command> alani. Okunamazsa None."""
    r = _run_schtasks(["/Query", "/TN", name, "/XML"])
    if r is None or r.returncode != 0 or not r.stdout:
        return None
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("<Command>") and line.endswith("</Command>"):
            return line[len("<Command>"):-len("</Command>")].strip()
    return None


def _delete_task(name: str) -> bool:
    """Gorevi siler ve GERCEKTEN silindigini DOGRULAR.

    Donus True yalnizca "bu isimde kayitli gorev artik YOK" anlamina gelir:
      - Gorev zaten yoksa   -> True (silinecek bir sey yok; schtasks bu durumda
        sifir-disi kod dondurur, bu bir HATA DEGILDIR).
      - Gorev vardi ve gitti -> True.
      - /Delete sifir-disi kod dondurduyse VEYA gorev hala kayitliysa -> False.
      - Varlik belirlenemiyorsa -> False (fail closed).
    Basarisizlikta LAST_ERROR doldurulur; cagiran bunu SESSIZCE YUTMAMALIDIR."""
    exists = _task_exists(name)
    if exists is None:
        _set_error(f"'{name}' gorevinin varligi belirlenemedi")
        return False
    if not exists:
        return True

    r = _run_schtasks(["/Delete", "/TN", name, "/F"])
    if r is None:
        return False

    still = _task_exists(name)
    if still is None:
        _set_error(f"'{name}' silindikten sonra dogrulanamadi")
        return False
    if still:
        _set_error(
            f"GUVENLIK: '{name}' gorevi SILINEMEDI (hala kayitli); "
            f"schtasks rc={r.returncode} {(r.stderr or r.stdout or '').strip()}")
        return False
    if r.returncode != 0:
        # Gorev gitmis ama komut hata bildirmis: guvenilir sayma.
        _set_error(f"'{name}' silindi ama schtasks rc={r.returncode} "
                   f"{(r.stderr or r.stdout or '').strip()}")
        return False
    return True


def _registered_task_target(name: str = TASK_NAME) -> Optional[str]:
    """Kayitli gorevin <Command> alanindaki ham exe yolu (tirnaksiz).
    Gorev yoksa veya alan okunamazsa None."""
    registered = _task_command(name)
    if not registered:
        return None
    return registered.strip().strip('"').strip() or None


def _ensure_no_unsafe_task() -> bool:
    """Kayitli gorev DOGRULANABILIR bir hedefi gostermiyorsa KALDIRIR.

    Donus True = "ayakta GUVENSIZ gorev yok" garanti edilebiliyor:
      - gorev yok                              -> True
      - hedefi kendi basina dogrulanabiliyor   -> True (mesru gorev; korunur)
      - hedefi okunamiyor VEYA dogrulanamiyor  -> kaldirilir; kaldirma
        dogrulanabilirse True, aksi halde False."""
    exists = _task_exists(TASK_NAME)
    if exists is None:
        _set_error(f"'{TASK_NAME}' gorevinin varligi belirlenemedi")
        return False
    if not exists:
        return True
    registered = _registered_task_target()
    if registered and path_is_verified_install(registered):
        return True
    return remove_logon_failsafe()


def _guard_after_failure(message: str) -> None:
    """Bir basarisizlik sonrasi guvenlik agini kapatir: gorev kurulamamis olsa
    bile GUVENSIZ bir gorev ayakta kalmamalidir. Ozgun hata mesaji korunur."""
    if not _ensure_no_unsafe_task():
        message = f"{message} | GUVENLIK: guvensiz gorev kaldirilamadi: {LAST_ERROR}"
    _set_error(message)


def install_logon_failsafe() -> bool:
    """Logon'da yuksek yetkiyle hosts temizleyen zamanlanmis gorevi kurar.

    GUVENLIK: Yalnizca `verified_failsafe_target()` bir yol dondururse kurar
    (paketlenmis exe + gercek Program Files + reparse point yok + ACL ve sahiplik
    kapali). Kosul saglanmazsa gorev KURULMAZ ve varsa ESKI/GUVENSIZ gorev
    KALDIRILIR — boylece onceki bir surumden kalmis, yazilabilir bir konumu
    gosteren tehlikeli gorev de temizlenir. Kaldirma BASARISIZ olursa bu sessizce
    yutulmaz: LAST_ERROR doldurulur ve False donulur.

    Kurulumdan sonra gorev GERI OKUNUR: kayitli <Command>, dogrulanmis canonical
    exe degilse gorev SILINIR ve False donulur."""
    _set_error("")
    target = verified_failsafe_target()
    if not target:
        # Gorev icin baglanabilecegimiz DOGRULANMIS bir hedef yok. KAYITLI hedef
        # KENDI BASINA dogrulanabiliyorsa (or. Program Files'a kurulu surumun
        # olusturdugu mesru gorev) ona DOKUNMAYIZ: amac guvensiz gorevi
        # kaldirmak, saglam bir guvenlik agini yok etmek degil.
        if getattr(sys, "frozen", False):
            reason = ("calisan exe dogrulanmis bir kurulum degil "
                      "(portable/gevsek ACL/reparse point)")
        else:
            reason = ("kaynak modunda dogrulanmis kurulu recovery hedefi yok "
                      "(Program Files altinda dogrulanmis DPort.exe bulunamadi)")
        if not _ensure_no_unsafe_task():
            reason = (f"{reason} | GUVENLIK: eski gorev kaldirilamadi: "
                      f"{LAST_ERROR}")
        _set_error(reason)
        return False

    for old in _LEGACY_TASKS:
        if not _delete_task(old):
            # Eski ad duruyorsa yeni gorevi kurmayiz; ama kendi gorevimiz de
            # guvensiz bir hedefle ayakta KALMAMALI.
            _guard_after_failure(LAST_ERROR)
            return False

    command = _cleanup_command(target)
    r = _run_schtasks(["/Create", "/TN", TASK_NAME, "/TR", command,
                       "/SC", "ONLOGON", "/RL", "HIGHEST", "/F"])
    if r is None:
        _guard_after_failure(LAST_ERROR or "schtasks /Create calistirilamadi")
        return False
    if r.returncode != 0:
        # Olusturma basarisiz: onceki surumden kalmis GUVENSIZ tanim hala
        # kayitli olabilir -> kesinlikle ayakta birakma.
        _guard_after_failure(f"gorev olusturulamadi: schtasks rc={r.returncode} "
                             f"{(r.stderr or r.stdout or '').strip()}")
        return False

    # Geri okuma: kayitli hedef gercekten dogruladigimiz exe mi?
    registered = _task_command(TASK_NAME)
    if registered is None:
        _guard_after_failure(
            "gorev olusturuldu ama hedefi geri okunamadi (dogrulanmadi)")
        return False
    if os.path.normcase(registered.strip('"')) != os.path.normcase(target):
        _set_error(f"GUVENLIK: gorev hedefi beklenenden farkli kaydedildi: "
                   f"{registered!r}")
        _delete_task(TASK_NAME)
        return False
    return True


def remove_logon_failsafe() -> bool:
    """Gorevimizi ve eski surumlerden kalmis adlari siler.

    Donus: TUM adlar icin silme DOGRULANDIYSA True. Herhangi biri kaldiysa
    False (ve LAST_ERROR dolu) — cagiran bunu gorunur kilmalidir."""
    ok = _delete_task(TASK_NAME)
    for old in _LEGACY_TASKS:
        if not _delete_task(old):
            ok = False
    return ok


def reconcile_failsafe_task(hosts_cleared: bool) -> bool:
    """Gorev yasam dongusunun TEK karar noktasi.

    Acilis, normal kapanis, watchdog, baglanti rollback'i ve `--cleanup-hosts`
    bakim yolu AYNI siniflandirmayi kullanir:

      hosts_cleared=True  -> isaretli yonlendirme DOGRULANMIS bicimde yok;
                             gorev artik gereksizdir, TUM adlar kaldirilir.
      hosts_cleared=False -> yonlendirme hala duruyor OLABILIR:
          * gorev yok                                  -> yapacak sey yok
          * hedefi BAGIMSIZ olarak dogrulanabiliyor    -> KORUNUR (bir sonraki
            logon'da yeniden denesin)
          * hedefi okunamiyor / dogrulanamiyor         -> KALDIRILIR; hosts
            sonucu bunu degistirmez, cunku yazilabilir bir hedefi gosteren
            HIGHEST gorev kalici yetki yukseltmesi demektir
      Eski (legacy) adlar hosts sonucundan BAGIMSIZ olarak her zaman kaldirilir:
      onlarin hedefi bizim protokolumuzle dogrulanmaz.

    Donus: "ayakta guvensiz veya gereksiz gorev kalmadi" GARANTI edilebiliyor mu.
    False ise LAST_ERROR doludur ve cagiran bunu SESSIZCE YUTMAMALIDIR."""
    _set_error("")
    ok = True
    for old in _LEGACY_TASKS:
        if not _delete_task(old):
            ok = False
    if hosts_cleared:
        if not _delete_task(TASK_NAME):
            ok = False
        return ok
    if not _ensure_no_unsafe_task():
        ok = False
    return ok


def failsafe_installed() -> bool:
    try:
        r = subprocess.run(
            ["schtasks", "/Query", "/TN", TASK_NAME],
            capture_output=True, text=True, encoding="utf-8", errors="ignore",
            timeout=15, creationflags=_FLAGS,
        )
        return r.returncode == 0
    except Exception:
        return False


def _configure_prototypes() -> None:
    """argtypes/restype — 64 bit'te isaretci kirpilmasini onler."""
    if not _IS_WINDOWS:  # pragma: no cover
        return
    _shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    _shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _kernel32.GetFinalPathNameByHandleW.restype = wintypes.DWORD
    _kernel32.GetFinalPathNameByHandleW.argtypes = [
        wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD,
    ]
    _kernel32.GetFileAttributesW.restype = wintypes.DWORD
    _kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]

    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _advapi32.GetAce.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p)
    ]
    _advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)
    ]


_configure_prototypes()
