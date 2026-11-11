# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path

block_cipher = None
ROOT = Path(SPEC).parent.resolve()
ICON_ICNS = ROOT / "assets" / "GitSwitch.icns"
ICON_ICO = ROOT / "assets" / "GitSwitch.ico"
ICON_PNG = ROOT / "assets" / "icon.png"

datas = []
if ICON_PNG.exists():
    datas.append((str(ICON_PNG), "assets"))

a = Analysis(
    ["git_account_switcher.py"],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=["tkinter", "_tkinter"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GitSwitch",
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
    icon=str(ICON_ICO) if ICON_ICO.exists() else None,
)

app = BUNDLE(
    exe,
    name="Git Switch.app",
    icon=str(ICON_ICNS) if ICON_ICNS.exists() else None,
    bundle_identifier="com.gitswitch.app",
)
