# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec file for Firefly Studio desktop sidecar.

Builds a single-directory bundle containing the Studio server,
bundled frontend, and all Python dependencies.

Usage::

    cd studio-desktop
    pyinstaller pyinstaller/firefly_studio.spec
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import copy_metadata

# Resolve paths relative to the repository root
REPO_ROOT = Path(SPECPATH).resolve().parent.parent
SRC_DIR = REPO_ROOT / "src"
STATIC_DIR = SRC_DIR / "fireflyframework_genai" / "studio" / "static"

# Collect package metadata for packages that call importlib.metadata.version()
pkg_metadata = []
for pkg in ["genai_prices", "pydantic_ai", "pydantic_ai_slim", "fireflyframework-genai"]:
    try:
        pkg_metadata += copy_metadata(pkg)
    except Exception:
        pass  # Package may not be installed

block_cipher = None

a = Analysis(
    [str(REPO_ROOT / "studio-desktop" / "pyinstaller" / "entry_point.py")],
    pathex=[str(SRC_DIR)],
    binaries=[],
    datas=[
        # Bundle the built frontend static files
        (str(STATIC_DIR), os.path.join("fireflyframework_genai", "studio", "static")),
    ]
    + pkg_metadata,
    hiddenimports=[],
    hookspath=[str(REPO_ROOT / "studio-desktop" / "pyinstaller")],
    hooksconfig={},
    runtime_hooks=[str(REPO_ROOT / "studio-desktop" / "pyinstaller" / "rthook_disable_logfire.py")],
    excludes=[
        "tkinter",
        "matplotlib",
        "PIL",
        "scipy",
        "numpy",
        "pandas",
        "logfire",
    ],
    noarchive=False,
    optimize=0,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="firefly-studio",
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
    name="firefly-studio",
)
