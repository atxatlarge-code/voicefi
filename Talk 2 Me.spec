# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['/Users/jaketrigg/Projects/Talk 2 Me/src/talk2me/cli.py'],
    pathex=[],
    binaries=[],
    datas=[('/Users/jaketrigg/Projects/Talk 2 Me/assets/icon.icns', 'assets')],
    hiddenimports=['rumps', 'pynput', 'faster_whisper', 'sounddevice', 'soundfile', 'pydantic', 'yaml'],
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
    name='Talk 2 Me',
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
    icon=['/Users/jaketrigg/Projects/Talk 2 Me/assets/icon.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='Talk 2 Me',
)
app = BUNDLE(
    coll,
    name='Talk 2 Me.app',
    icon='/Users/jaketrigg/Projects/Talk 2 Me/assets/icon.icns',
    bundle_identifier='com.lienlogicdata.talk2me',
)
