# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['app.py'],
    pathex=[],
    binaries=[
        ('runtime\\b10229\\*.dll', 'runtime'),
        ('runtime\\b10229\\llama-server.exe', 'runtime'),
    ],
    datas=[
        ('assets\\quickgloss-logo.png', 'assets'),
        ('assets\\quickgloss.ico', 'assets'),
    ],
    hiddenimports=['pystray._win32'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['win32crypt'], noarchive=False, optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='划词通', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=True, upx_exclude=[], runtime_tmpdir=None,
    console=False, disable_windowed_traceback=False,
    argv_emulation=False, target_arch=None, codesign_identity=None,
    entitlements_file=None, icon=['assets\\quickgloss.ico'],
)
