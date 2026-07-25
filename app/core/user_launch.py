"""
core/user_launch.py

Yukseltilmis (Administrator) DPort surecinden, MASAUSTU OTURUMUNUN NORMAL
KULLANICI tokeni ile surec baslatir.

NEDEN (F1):
  DPort `uac_admin=True` ile yuksek butunlukte calisir. subprocess.Popen ->
  CreateProcess cagrisi, cocuk surece UST SURECIN TOKENINI miras birakir. Bu
  yuzden `%LOCALAPPDATA%\\Discord\\Update.exe` gibi STANDART KULLANICININ
  YAZABILDIGI bir exe, DPort'tan baslatildiginda Administrator olarak calisirdi
  (UAC istemi de gorunmez). Kullanici baglaminda kod calistirabilen biri o
  dosyayi degistirerek yerel yetki yukseltmesi elde edebilirdi.

YONTEM VE NEDEN GERCEKTEN YETKI DUSURUR:
  ShellExecute("open", ...) TEK BASINA yetki DUSURMEZ — cagiran surecin tokeni
  ile CreateProcess yapar; yalnizca manifesti "requireAdministrator" olan hedefi
  YUKSELTIR. Bu yuzden ShellExecute'e guvenmiyoruz.

  Bunun yerine token acikca degistiriliyor:
    1. Kendi oturumumuzda (ProcessIdToSessionId) calisan explorer.exe bulunur.
       Kabuk (shell) surecidir; masaustunu isleten NORMAL kullanici baglaminda
       calisir.
    2. Sahtecilige karsi surecin gercek imaj yolu (QueryFullProcessImageNameW)
       `%SystemRoot%\\explorer.exe` ile karsilastirilir.
    3. Token acilir ve TokenElevation ile YUKSELTILMEMIS oldugu DOGRULANIR.
       Yukseltilmis bir kabuk (nadir) bulunursa islem REDDEDILIR — aksi halde
       yetki dusurdugumuzu sanip yukseltilmis token dagitirdik.
    4. DuplicateTokenEx ile birincil (primary) token uretilir ve
       CreateProcessWithTokenW ile surec BU TOKENLA olusturulur. Cocuk surecin
       tokeni artik acikca kabugun yukseltilmemis tokenidir; DPort'un yuksek
       butunluklu tokeni MIRAS ALINMAZ.
    5. Ortam blogu CreateEnvironmentBlock ile TOKENIN kendisinden uretilir;
       boylece yukseltilmis surecin ortam degiskenleri cocuga tasinmaz.

  CreateProcessWithTokenW, cagiranda SE_IMPERSONATE_NAME ayricaligi ister;
  yukseltilmis Administrator bu ayricaliga sahiptir.

GERI DUSME KURALI:
  Yukseltilmis calisirken token yolu basarisiz olursa YUKSEK YETKILI Popen'a
  GERI DUSULMEZ; hata dondurulur. Boylece "bir sekilde acilsin" ugruna
  guvenlik degismezi bozulmaz.

  DPort yukseltilmemis calisiyorsa (or. kaynaktan, admin olmadan) dusurulecek
  bir ayricalik yoktur; bu durumda normal Popen kullanilir ve davranis aynen
  korunur.
"""
from __future__ import annotations

import ctypes
import os
import subprocess
from ctypes import wintypes
from typing import List, Optional, Tuple

_IS_WINDOWS = os.name == "nt"

if _IS_WINDOWS:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    _userenv = ctypes.WinDLL("userenv", use_last_error=True)
else:  # pragma: no cover - DPort yalnizca Windows'ta calisir
    _kernel32 = _advapi32 = _userenv = None


# ───────────────────────────── Win32 sabitleri ─────────────────────────────
TH32CS_SNAPPROCESS = 0x00000002
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_DUPLICATE = 0x0002
TOKEN_QUERY = 0x0008
MAXIMUM_ALLOWED = 0x02000000

TokenElevation = 20
SecurityImpersonation = 2
TokenPrimary = 1

CREATE_UNICODE_ENVIRONMENT = 0x00000400
CREATE_NO_WINDOW = 0x08000000


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * 260),
    ]


class _STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


def _close(handle) -> None:
    try:
        if handle:
            _kernel32.CloseHandle(wintypes.HANDLE(handle))
    except Exception:
        pass


# ───────────────────────────── Yetki tespiti ─────────────────────────────
def is_elevated() -> bool:
    """Bu surec YUKSELTILMIS (elevated) bir tokenla mi calisiyor?

    IsUserAnAdmin yerine TokenElevation kullanilir: "yonetici grubunda uye"
    olmakla "su an yukseltilmis calismak" farkli seylerdir ve bizi ilgilendiren
    ikincisidir."""
    if not _IS_WINDOWS:
        return False
    token = wintypes.HANDLE()
    try:
        if not _advapi32.OpenProcessToken(
            _kernel32.GetCurrentProcess(), TOKEN_QUERY, ctypes.byref(token)
        ):
            return False
        try:
            elevated = wintypes.DWORD(0)
            size = wintypes.DWORD(0)
            if not _advapi32.GetTokenInformation(
                token, TokenElevation, ctypes.byref(elevated),
                ctypes.sizeof(elevated), ctypes.byref(size),
            ):
                return False
            return bool(elevated.value)
        finally:
            _close(token.value)
    except Exception:
        return False


def _token_is_elevated(token) -> Optional[bool]:
    """Verilen token yukseltilmis mi? Okunamazsa None (cagiran REDDEDER)."""
    elevated = wintypes.DWORD(0)
    size = wintypes.DWORD(0)
    if not _advapi32.GetTokenInformation(
        wintypes.HANDLE(token), TokenElevation, ctypes.byref(elevated),
        ctypes.sizeof(elevated), ctypes.byref(size),
    ):
        return None
    return bool(elevated.value)


# ───────────────────────────── Kabuk (shell) tokeni ─────────────────────────
def _expected_explorer_path() -> str:
    root = os.environ.get("SystemRoot") or r"C:\Windows"
    return os.path.normcase(os.path.join(root, "explorer.exe"))


def _process_image_path(pid: int) -> Optional[str]:
    handle = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not handle:
        return None
    try:
        size = wintypes.DWORD(32768)
        buf = ctypes.create_unicode_buffer(size.value)
        if not _kernel32.QueryFullProcessImageNameW(
            wintypes.HANDLE(handle), 0, buf, ctypes.byref(size)
        ):
            return None
        return buf.value
    finally:
        _close(handle)


def _current_session_id() -> Optional[int]:
    sid = wintypes.DWORD(0)
    if not _kernel32.ProcessIdToSessionId(
        _kernel32.GetCurrentProcessId(), ctypes.byref(sid)
    ):
        return None
    return sid.value


def _iter_explorer_pids() -> List[int]:
    """Bu oturumda calisan, imaj yolu %SystemRoot%\\explorer.exe olan surecler."""
    pids: List[int] = []
    session = _current_session_id()
    if session is None:
        return pids

    snap = _kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return pids
    try:
        entry = _PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
        ok = _kernel32.Process32FirstW(wintypes.HANDLE(snap), ctypes.byref(entry))
        expected = _expected_explorer_path()
        while ok:
            if entry.szExeFile.lower() == "explorer.exe":
                pid = entry.th32ProcessID
                psid = wintypes.DWORD(0)
                if _kernel32.ProcessIdToSessionId(pid, ctypes.byref(psid)) and psid.value == session:
                    # Sahtecilige karsi: adi "explorer.exe" olan herhangi bir
                    # surec degil, GERCEK kabuk ikilisi kabul edilir.
                    image = _process_image_path(pid)
                    if image and os.path.normcase(image) == expected:
                        pids.append(pid)
            ok = _kernel32.Process32NextW(wintypes.HANDLE(snap), ctypes.byref(entry))
    finally:
        _close(snap)
    return pids


def _open_desktop_user_token():
    """Kabuk surecinin YUKSELTILMEMIS tokeninden birincil (primary) token uretir.

    Yukseltilmis bir kabuk bulunursa (veya token durumu okunamazsa) o aday
    ATLANIR: amac yetki dusurmek; yukseltilmis token kopyalamak degismezi
    bozardi. Uygun aday yoksa None doner."""
    for pid in _iter_explorer_pids():
        proc = _kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not proc:
            continue
        token = wintypes.HANDLE()
        try:
            if not _advapi32.OpenProcessToken(
                wintypes.HANDLE(proc), TOKEN_DUPLICATE | TOKEN_QUERY, ctypes.byref(token)
            ):
                continue
            if _token_is_elevated(token.value) is not False:
                continue  # yukseltilmis ya da belirsiz -> kullanma
            primary = wintypes.HANDLE()
            if not _advapi32.DuplicateTokenEx(
                token, MAXIMUM_ALLOWED, None, SecurityImpersonation,
                TokenPrimary, ctypes.byref(primary),
            ):
                continue
            # Kopyalanan token da yukseltilmemis olmali (savunma katmani).
            if _token_is_elevated(primary.value) is not False:
                _close(primary.value)
                continue
            return primary.value
        finally:
            _close(token.value)
            _close(proc)
    return None


# ───────────────────────────── Surec baslatma ─────────────────────────────
def _create_process_with_token(token, argv: List[str], cwd: Optional[str]) -> Tuple[bool, str]:
    env_block = ctypes.c_void_p()
    have_env = bool(_userenv.CreateEnvironmentBlock(
        ctypes.byref(env_block), wintypes.HANDLE(token), False
    ))

    startup = _STARTUPINFOW()
    startup.cb = ctypes.sizeof(_STARTUPINFOW)
    info = _PROCESS_INFORMATION()

    flags = CREATE_NO_WINDOW
    if have_env:
        flags |= CREATE_UNICODE_ENVIRONMENT

    # lpApplicationName acikca verilir: exe yolu komut satirindan AYRISTIRILMAZ,
    # boylece bosluklu yollarda hedef belirsizligi olusmaz.
    cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
    try:
        ok = _advapi32.CreateProcessWithTokenW(
            wintypes.HANDLE(token), 0, argv[0], cmdline, flags,
            env_block if have_env else None, cwd,
            ctypes.byref(startup), ctypes.byref(info),
        )
        if not ok:
            return False, f"CreateProcessWithTokenW basarisiz (WinError {ctypes.get_last_error()})"
        _close(info.hProcess)
        _close(info.hThread)
        return True, ""
    finally:
        if have_env:
            try:
                _userenv.DestroyEnvironmentBlock(env_block)
            except Exception:
                pass


def launch_as_user(argv: List[str], cwd: Optional[str] = None) -> Tuple[bool, str]:
    """`argv`'yi masaustu oturumunun NORMAL kullanici tokeni ile baslatir.

    Donus: (basarili_mi, hata_metni).

    GUVENLIK DEGISMEZI: DPort yukseltilmis calisiyorsa cocuk surec HICBIR
    kosulda DPort'un yuksek butunluklu tokenini miras almaz. Token yolu
    basarisiz olursa yuksek yetkili Popen'a GERI DUSULMEZ."""
    if not argv:
        return False, "bos komut"

    if not _IS_WINDOWS:  # pragma: no cover - yalnizca Windows destekleniyor
        return False, "desteklenmeyen platform"

    if not is_elevated():
        # Dusurulecek ayricalik yok: cocuk zaten normal kullanici butunlugunde
        # olusur. Mevcut davranis (ve hata metinleri) aynen korunur.
        try:
            subprocess.Popen(
                argv, cwd=cwd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=CREATE_NO_WINDOW,
            )
            return True, ""
        except Exception as exc:
            return False, str(exc)

    token = _open_desktop_user_token()
    if not token:
        return False, (
            "Masaustu oturumunun kullanici tokeni alinamadi; yonetici yetkisiyle "
            "baslatmamak icin islem iptal edildi."
        )
    try:
        return _create_process_with_token(token, argv, cwd)
    finally:
        _close(token)


def _configure_prototypes() -> None:
    """argtypes/restype tanimlari — 64 bit'te isaretci kirpilmasini onler."""
    if not _IS_WINDOWS:  # pragma: no cover
        return
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_PROCESSENTRY32W)]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    _kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.ProcessIdToSessionId.argtypes = [wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]

    _advapi32.OpenProcessToken.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)
    ]
    _advapi32.GetTokenInformation.argtypes = [
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
    ]
    _advapi32.DuplicateTokenEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, ctypes.c_int,
        ctypes.c_int, ctypes.POINTER(wintypes.HANDLE),
    ]
    _advapi32.CreateProcessWithTokenW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPWSTR,
        wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(_STARTUPINFOW), ctypes.POINTER(_PROCESS_INFORMATION),
    ]

    _userenv.CreateEnvironmentBlock.argtypes = [
        ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.BOOL
    ]
    _userenv.DestroyEnvironmentBlock.argtypes = [ctypes.c_void_p]


_configure_prototypes()
