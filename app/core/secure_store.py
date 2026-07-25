"""
core/secure_store.py

Yonetici yetkisiyle GERI UYGULANACAK durumu (DNS kurtarma verisi) ve yonetici
yetkisiyle CALISTIRILACAK dosyalari (guncelleme installer'i) standart
kullanicinin DEGISTIREMEYECEGI bir konumda tutar.

NEDEN (F4 ve F3):
  Eskiden DNS yedegi `%APPDATA%\\DPort\\config.json` icinde, guncelleme
  installer'i ise `%APPDATA%\\DPort\\updates` altinda tutuluyordu. Iki konum da
  etkilesimli kullaniciya TAM YAZMA hakki verir. Yukseltilmis DPort bu veriyi
  netsh'e (DNS) veya CreateProcess'e (installer) besledigi icin, standart
  kullanici baglamindaki bir surec yonetici yetkisiyle yapilan islemin GIRDISINI
  belirleyebiliyordu.

BU MODULUN SAGLADIGI:
  1. `%ProgramData%\\DPort` altinda, KORUMALI (protected / kalitimi kapali) bir
     DACL ile dizin: SYSTEM ve Administrators tam yetki, Users yalnizca
     OKUMA+CALISTIRMA. Yani standart kullanici buraya YAZAMAZ.
     Konum, ortam degiskeni yerine SHGetKnownFolderPath ile alinir (ortam
     degiskeni kullanici tarafindan degistirilebilir).
  2. Reparse point (junction/symlink) reddi: kullanici `%ProgramData%` altinda
     dizin olusturabildigi icin, bizden once olusturulmus bir yeniden ayrisma
     noktasi yukseltilmis yazmayi baska bir hedefe yonlendirebilirdi.
  3. Sahiplik (owner) dogrulamasi: guvendigimiz dosyanin sahibi
     Administrators/SYSTEM olmalidir. Standart kullanici bir nesnenin sahibini
     Administrators yapamaz (token'inda bu SID yalnizca "deny-only" bulunur),
     dolayisiyla sahiplik "yukseltilmis bir surec yazdi" isaretidir.
  4. `GuardedFile`: dosyayi FILE_SHARE_READ ile acar. Handle acik kaldigi
     surece baska bir surec dosyayi YAZAMAZ, SILEMEZ ve YENIDEN ADLANDIRAMAZ;
     boylece "hash'i dogrulanan bayt" ile "calistirilan bayt" ayni olur (TOCTOU).

FAIL CLOSED:
  Korumali konum hazirlanamazsa (izin yok, reparse point, ACL yazilamadi) bu
  modul None/False doner. Cagiran taraf, guvenli olmayan bir konuma DUSMEK
  yerine ilgili ayricalikli islemi yapmaz.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import threading
from ctypes import wintypes
from typing import Optional

APP_DIR_NAME = "DPort"
DNS_STATE_FILE = "dns_state.json"
UPDATE_STAGING_DIR = "updates"

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    _ole32 = ctypes.WinDLL("ole32", use_last_error=True)
else:  # pragma: no cover - DPort yalnizca Windows'ta calisir
    _kernel32 = _advapi32 = _shell32 = _ole32 = None


# ───────────────────────────── Win32 sabitleri ─────────────────────────────
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SE_FILE_OBJECT = 1
SDDL_REVISION_1 = 1

FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF

GENERIC_READ = 0x80000000
FILE_READ_DATA = 0x00000001
FILE_EXECUTE = 0x00000020
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x00000080
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

# Korumali guvenlik tanimlayicisi (SDDL):
#   O:BA                -> sahip: BUILTIN\Administrators
#   D:P                 -> DACL kalitimi KAPALI (ust dizinden ACE sizmaz)
#   (A;OICI;FA;;;SY)    -> SYSTEM tam yetki (alt nesnelere kalitimli)
#   (A;OICI;FA;;;BA)    -> Administrators tam yetki
#   (A;OICI;0x1200a9;;;BU) -> Users yalnizca Read & Execute (YAZMA YOK)
_PROTECTED_SDDL = "O:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;0x1200a9;;;BU)"

# Yukseltilmis bir surec tarafindan yazilmis sayilan sahip SID'leri.
_TRUSTED_OWNER_SIDS = frozenset({"S-1-5-18", "S-1-5-32-544"})

_LOCK = threading.RLock()
_root_cache: Optional[object] = None  # None = denenmedi, False = kullanilamaz, str = yol


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


# FOLDERID_ProgramData = {62AB5D82-FDC1-4DC3-A9DD-070D1D495D97}
_FOLDERID_ProgramData = _GUID(
    0x62AB5D82, 0xFDC1, 0x4DC3,
    (ctypes.c_ubyte * 8)(0xA9, 0xDD, 0x07, 0x0D, 0x1D, 0x49, 0x5D, 0x97),
)


def _program_data_dir() -> Optional[str]:
    """`%ProgramData%` yolunu ORTAM DEGISKENINDEN DEGIL, bilinen klasor
    API'sinden alir (ortam degiskeni kullanici tarafindan degistirilebilir)."""
    if not _IS_WINDOWS:  # pragma: no cover
        return None
    ptr = ctypes.c_wchar_p()
    try:
        if _shell32.SHGetKnownFolderPath(
            ctypes.byref(_FOLDERID_ProgramData), 0, None, ctypes.byref(ptr)
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


# ───────────────────────────── ACL yardimcilari ─────────────────────────────
def is_reparse_point(path: str) -> bool:
    """Yol bir junction/symlink mi? (Yukseltilmis yazmayi baska hedefe
    yonlendirme girisimine karsi.)"""
    if not _IS_WINDOWS:  # pragma: no cover
        return os.path.islink(path)
    attrs = _kernel32.GetFileAttributesW(path)
    if attrs == INVALID_FILE_ATTRIBUTES:
        return False
    return bool(attrs & FILE_ATTRIBUTE_REPARSE_POINT)


def apply_protected_acl(path: str) -> bool:
    """Yola korumali DACL + Administrators sahipligi uygular.

    Basarisizsa False — cagiran taraf konumu KULLANMAZ (fail closed)."""
    if not _IS_WINDOWS:  # pragma: no cover
        return False
    psd = ctypes.c_void_p()
    if not _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        _PROTECTED_SDDL, SDDL_REVISION_1, ctypes.byref(psd), None
    ):
        return False
    try:
        dacl = ctypes.c_void_p()
        present = wintypes.BOOL(False)
        defaulted = wintypes.BOOL(False)
        if not _advapi32.GetSecurityDescriptorDacl(
            psd, ctypes.byref(present), ctypes.byref(dacl), ctypes.byref(defaulted)
        ) or not present.value:
            return False

        owner = ctypes.c_void_p()
        owner_defaulted = wintypes.BOOL(False)
        if not _advapi32.GetSecurityDescriptorOwner(
            psd, ctypes.byref(owner), ctypes.byref(owner_defaulted)
        ):
            return False

        return _advapi32.SetNamedSecurityInfoW(
            path, SE_FILE_OBJECT,
            OWNER_SECURITY_INFORMATION
            | DACL_SECURITY_INFORMATION
            | PROTECTED_DACL_SECURITY_INFORMATION,
            owner, None, dacl, None,
        ) == 0
    except Exception:
        return False
    finally:
        try:
            _kernel32.LocalFree(psd)
        except Exception:
            pass


def owner_sid(path: str) -> Optional[str]:
    """Nesnenin sahip SID'ini metin olarak dondurur (or. 'S-1-5-32-544')."""
    if not _IS_WINDOWS:  # pragma: no cover
        return None
    sid = ctypes.c_void_p()
    psd = ctypes.c_void_p()
    try:
        if _advapi32.GetNamedSecurityInfoW(
            path, SE_FILE_OBJECT, OWNER_SECURITY_INFORMATION,
            ctypes.byref(sid), None, None, None, ctypes.byref(psd),
        ) != 0:
            return None
        text = ctypes.c_wchar_p()
        if not _advapi32.ConvertSidToStringSidW(sid, ctypes.byref(text)):
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
    finally:
        try:
            if psd:
                _kernel32.LocalFree(psd)
        except Exception:
            pass


def written_by_privileged_process(path: str) -> bool:
    """Dosya/dizin yukseltilmis bir surec tarafindan mi olusturuldu?

    Standart kullanici, nesne sahibini Administrators/SYSTEM yapamaz; bu yuzden
    sahiplik guvenilir bir 'ayricalikli yazar' isaretidir."""
    return owner_sid(path) in _TRUSTED_OWNER_SIDS


# ───────────────────────────── Korumali kok dizin ───────────────────────────
def _prepare_dir(path: str) -> bool:
    if is_reparse_point(path):
        return False
    if not os.path.isdir(path):
        try:
            os.makedirs(path, exist_ok=True)
        except OSError:
            return False
        # Olusturma ile kontrol arasinda yer degistirme girisimi olmadigini
        # tekrar dogrula.
        if is_reparse_point(path):
            return False
    return apply_protected_acl(path)


def secure_root(refresh: bool = False) -> Optional[str]:
    """`%ProgramData%\\DPort` — hazir ve korumali ise yolu, degilse None."""
    global _root_cache
    with _LOCK:
        if not refresh and _root_cache is not None:
            return _root_cache or None
        base = _program_data_dir()
        root = os.path.join(base, APP_DIR_NAME) if base else None
        _root_cache = root if (root and _prepare_dir(root)) else False
        return _root_cache or None


def secure_subdir(name: str) -> Optional[str]:
    """Korumali kok altinda, yine korumali bir alt dizin dondurur."""
    root = secure_root()
    if not root:
        return None
    path = os.path.join(root, name)
    return path if _prepare_dir(path) else None


def update_staging_dir() -> Optional[str]:
    """Guncelleme installer'inin indirilecegi ACL-korumali staging dizini."""
    return secure_subdir(UPDATE_STAGING_DIR)


# ───────────────────────────── DNS kurtarma durumu ──────────────────────────
def _dns_state_path() -> Optional[str]:
    root = secure_root()
    return os.path.join(root, DNS_STATE_FILE) if root else None


def load_dns_backup() -> dict:
    """Ayricalikli DNS kurtarma durumunu okur.

    Dosya yoksa, bozuksa VEYA yukseltilmis olmayan bir surec tarafindan
    olusturulmussa BOS dondurur (ve guvenilmez dosyayi siler). Boylece
    kurcalanmis bir state yonetici yetkili netsh'e ULASAMAZ."""
    path = _dns_state_path()
    if not path or not os.path.isfile(path):
        return {}
    try:
        if is_reparse_point(path) or not written_by_privileged_process(path):
            _discard_untrusted(path)
            return {}
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        backup = data.get("dns_backup") if isinstance(data, dict) else None
        return backup if isinstance(backup, dict) else {}
    except Exception:
        return {}


def _discard_untrusted(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def save_dns_backup(backup: Optional[dict]) -> bool:
    """Ayricalikli DNS kurtarma durumunu yazar. Bos/None ise durumu siler.

    Donus: kalici olarak yazilabildi mi. False ise cagiran taraf yalnizca
    bellek ici yedekle devam eder (kullanici-yazilabilir bir dosyaya ASLA
    dusmez)."""
    path = _dns_state_path()
    if not path:
        return False
    try:
        if not backup:
            if os.path.isfile(path):
                os.remove(path)
            return True
        tmp = f"{path}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "dns_backup": backup}, f, indent=2, ensure_ascii=False)
        os.replace(tmp, path)
        # Sahipligi acikca Administrators yap: okuma tarafindaki 'ayricalikli
        # yazar' dogrulamasi buna dayanir.
        apply_protected_acl(path)
        return True
    except Exception:
        return False


# ───────────────────────────── TOCTOU korumali dosya ────────────────────────
class GuardedFile:
    """Dosyayi FILE_SHARE_READ ile acik tutar.

    Paylasim modu yalnizca OKUMA oldugu icin, handle acikken baska bir surec
    dosyayi yazmak, silmek veya yeniden adlandirmak uzere ACAMAZ (yeniden
    adlandirma/silme DELETE erisimi ister; FILE_SHARE_DELETE verilmemistir).

    CreateProcess, imaji FILE_READ_DATA|FILE_EXECUTE ile ve FILE_SHARE_READ ile
    uyumlu sekilde acar; bu yuzden handle acikken dosya CALISTIRILABILIR. Boylece
    'hash'i dogrulanan bayt' ile 'calistirilan bayt' ayni olur."""

    def __init__(self, path: str):
        self.path = path
        self._handle = None

    def __enter__(self) -> "GuardedFile":
        self.open()
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def open(self) -> bool:
        if not _IS_WINDOWS:  # pragma: no cover
            return False
        if is_reparse_point(self.path):
            return False
        handle = _kernel32.CreateFileW(
            self.path, GENERIC_READ, FILE_SHARE_READ, None,
            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, None,
        )
        if not handle or handle == INVALID_HANDLE_VALUE:
            self._handle = None
            return False
        self._handle = handle
        return True

    @property
    def ok(self) -> bool:
        return self._handle is not None

    def sha256_hex(self) -> Optional[str]:
        """Hash'i, kilitli HANDLE uzerinden okuyarak hesaplar (yolu yeniden
        acmaz; boylece arada dosya degistirilemez)."""
        if not self.ok:
            return None
        digest = hashlib.sha256()
        buf = ctypes.create_string_buffer(256 * 1024)
        read = wintypes.DWORD(0)
        try:
            # Dosya basina konumlan (tekrar cagrilabilsin).
            if _kernel32.SetFilePointerEx(
                wintypes.HANDLE(self._handle), ctypes.c_longlong(0), None, 0
            ) == 0:
                return None
            while True:
                if not _kernel32.ReadFile(
                    wintypes.HANDLE(self._handle), buf, len(buf), ctypes.byref(read), None
                ):
                    return None
                if read.value == 0:
                    break
                digest.update(buf.raw[: read.value])
            return digest.hexdigest()
        except Exception:
            return None

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle:
            try:
                _kernel32.CloseHandle(wintypes.HANDLE(handle))
            except Exception:
                pass


def _configure_prototypes() -> None:
    if not _IS_WINDOWS:  # pragma: no cover
        return
    _shell32.SHGetKnownFolderPath.restype = ctypes.c_long
    _shell32.SHGetKnownFolderPath.argtypes = [
        ctypes.POINTER(_GUID), wintypes.DWORD, wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_wchar_p),
    ]
    _ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]

    _kernel32.GetFileAttributesW.argtypes = [wintypes.LPCWSTR]
    _kernel32.GetFileAttributesW.restype = wintypes.DWORD
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _kernel32.CreateFileW.restype = wintypes.HANDLE
    _kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    _kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    _kernel32.SetFilePointerEx.argtypes = [
        wintypes.HANDLE, ctypes.c_longlong, ctypes.c_void_p, wintypes.DWORD
    ]
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

    _advapi32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.GetSecurityDescriptorDacl.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(wintypes.BOOL),
        ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL),
    ]
    _advapi32.GetSecurityDescriptorOwner.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.BOOL)
    ]
    _advapi32.SetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.SetNamedSecurityInfoW.argtypes = [
        wintypes.LPWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
    ]
    _advapi32.GetNamedSecurityInfoW.restype = wintypes.DWORD
    _advapi32.GetNamedSecurityInfoW.argtypes = [
        wintypes.LPCWSTR, ctypes.c_int, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p), ctypes.c_void_p,
        ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    _advapi32.ConvertSidToStringSidW.argtypes = [
        ctypes.c_void_p, ctypes.POINTER(ctypes.c_wchar_p)
    ]


_configure_prototypes()
