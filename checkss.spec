# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path


project_dir = Path(SPECPATH).resolve()
stockfish_dir = project_dir / "tools" / "stockfish" / "stockfish"
stockfish_avxvnni_dir = project_dir / "tools" / "stockfish-avxvnni" / "stockfish"

a = Analysis(
    [str(project_dir / "src" / "launcher.py")],
    pathex=[str(project_dir / "src")],
    binaries=[
        (
            str(stockfish_dir / "stockfish-windows-x86-64-avx2.exe"),
            "stockfish",
        ),
        (
            str(stockfish_avxvnni_dir / "stockfish-windows-x86-64-avxvnni.exe"),
            "stockfish",
        ),
    ],
    datas=[
        (str(project_dir / "src" / "templates"), "templates"),
        (str(project_dir / "static"), "static"),
        (str(stockfish_dir / "Copying.txt"), "licenses/stockfish"),
        (str(stockfish_dir / "AUTHORS"), "licenses/stockfish"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="checkss",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    icon=str(project_dir / "static" / "assets" / "checkss.ico"),
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
    name="checkss",
)
