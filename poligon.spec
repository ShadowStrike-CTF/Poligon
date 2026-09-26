# poligon.spec — PyInstaller build (onefile, windowed). Build: pyinstaller poligon.spec
# © 2026 ShadowStrike. All rights reserved.
# Aut Viam Inveniam Aut Faciam
block_cipher = None

a = Analysis(
    ['src/poligon/__main__.py'],
    pathex=['src'],
    binaries=[],
    datas=[('src/poligon/web/static/index.html', 'poligon/web/static')],
    hiddenimports=[
        # Pillow format plugins are loaded lazily by Image.save/open — CLAUDE.md mandate
        'PIL.JpegImagePlugin',
        'PIL.PngImagePlugin',
        'PIL._imaging',
    ],
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
    a.zipfiles,
    a.datas,
    [],
    name='poligon',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
