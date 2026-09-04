# -*- mode: python ; coding: utf-8 -*-
import os
import re
import sys

from PyInstaller.utils.hooks import collect_all
from PyInstaller.utils.win32.versioninfo import (
    VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable,
    StringStruct, VarFileInfo, VarStruct,
)

spec_dir = os.path.abspath(SPECPATH)
root_dir = os.path.dirname(spec_dir)
app_dir = os.path.join(root_dir, 'app')
assets_dir = os.path.join(app_dir, 'assets')

# ── Windows version resource — TEK surum kaynagi: app/core/app_info.py APP_VERSION.
# Buradan turetildigi icin elle 2. bir yerde surum tutulmaz (drift olmaz). Windows
# 4 parcali sayisal surum ister: "3.1" -> (3, 1, 0, 0).
_app_info = os.path.join(app_dir, 'core', 'app_info.py')
with open(_app_info, encoding='utf-8') as _f:
    _m = re.search(r'^APP_VERSION\s*=\s*["\']([^"\']+)["\']', _f.read(), re.MULTILINE)
_app_version = _m.group(1) if _m else '0.0'
_nums = [int(n) for n in re.findall(r'\d+', _app_version)][:4]
_nums += [0] * (4 - len(_nums))
_vers_tuple = tuple(_nums)
_vers_str = '.'.join(str(n) for n in _vers_tuple)   # "3.1.0.0"

version_info = VSVersionInfo(
    ffi=FixedFileInfo(
        filevers=_vers_tuple,
        prodvers=_vers_tuple,
        mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0, 0),
    ),
    kids=[
        StringFileInfo([StringTable('040904B0', [
            StringStruct('CompanyName', 'IzzmooPro'),
            StringStruct('FileDescription', 'DPort'),
            StringStruct('FileVersion', _vers_str),
            StringStruct('InternalName', 'DPort'),
            StringStruct('LegalCopyright', '(c) IzzmooPro'),
            StringStruct('OriginalFilename', 'DPort.exe'),
            StringStruct('ProductName', 'DPort'),
            StringStruct('ProductVersion', _vers_str),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0409, 1200])]),
    ],
)

datas = [(assets_dir, 'assets')]
# Venv Scripts/ does not contain the base runtime DLLs.
python_root = sys.base_prefix
binaries = [
    (os.path.join(python_root, name), '.')
    for name in ('python3.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
    if os.path.exists(os.path.join(python_root, name))
]
hiddenimports = ['customtkinter', 'PIL', 'pystray']
tmp_ret = collect_all('customtkinter')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    [os.path.join(app_dir, 'main.py')],
    pathex=[app_dir, root_dir],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['numpy', 'pandas'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    name='DPort',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    uac_admin=True,
    icon=[os.path.join(assets_dir, 'icon.ico')],
    version=version_info,
    exclude_binaries=True,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='DPort',
)
