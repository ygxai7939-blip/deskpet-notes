# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
from runpy import run_path
from PyInstaller.utils.win32.versioninfo import (
    FixedFileInfo, StringFileInfo, StringStruct, StringTable, VarFileInfo, VarStruct, VSVersionInfo,
)

release_dir = Path(SPECPATH)
app_dir = release_dir.parent / 'deskpet-live'
runtime_dir = release_dir.parent / 'deskpet-zh'
version = run_path(str(app_dir / 'app_version.py'))['APP_VERSION']
version_parts = (*map(int, version.split('.')), 0)
version_info = VSVersionInfo(
    ffi=FixedFileInfo(filevers=version_parts, prodvers=version_parts),
    kids=[
        StringFileInfo([StringTable('080404b0', [
            StringStruct('FileDescription', '桌宠便签'),
            StringStruct('FileVersion', version),
            StringStruct('OriginalFilename', 'DeskPetNotes.exe'),
            StringStruct('ProductName', '桌宠便签'),
            StringStruct('ProductVersion', version),
        ])]),
        VarFileInfo([VarStruct('Translation', [0x0804, 1200])]),
    ],
)

a = Analysis(
    [str(app_dir / 'open_preview.pyw')],
    pathex=[str(runtime_dir)],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='DeskPetNotes',
    version=version_info,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='DeskPetNotes',
)
