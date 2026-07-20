# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path


repo = Path.cwd()
datas = [
    (str(repo / "reels_editor" / "desktop" / "ui"), "reels_editor/desktop/ui"),
    (str(repo / "styles"), "styles"),
    (str(repo / "prompts"), "prompts"),
]

a = Analysis(
    [str(repo / "desktop" / "pyinstaller" / "desktop_entry.py")],
    pathex=[str(repo)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "webview.platforms.cocoa",
        "uvicorn.loops.auto",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.protocols.websockets.websockets_impl",
        "websockets",
        "websockets.asyncio.server",
        "websockets.legacy.server",
        "uvicorn.lifespan.on",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "gi", "gtk"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Reels Editor",
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
    name="Reels Editor",
)
app = BUNDLE(
    coll,
    name="Reels Editor.app",
    icon=str(repo / "desktop" / "assets" / "ReelsEditor.icns"),
    bundle_identifier="com.jdh4601.reels-editor",
    info_plist={
        "NSHighResolutionCapable": "True",
        "NSHumanReadableCopyright": "Personal local app",
    },
)
