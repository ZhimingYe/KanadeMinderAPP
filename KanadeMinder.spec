# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for KanadeMinder.app macOS bundle."""

from __future__ import annotations

block_cipher = None

a = Analysis(
    ['src/kanademinder/gui/app.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src/kanademinder/app/web/static', 'kanademinder/app/web/static'),
        ('src/kanademinder/gui/settings/static', 'kanademinder/gui/settings/static'),
    ],
    hiddenimports=[
        'webview',
        'webview.platforms.cocoa',
        'kanademinder',
        'kanademinder.config',
        'kanademinder.db',
        'kanademinder.models',
        'kanademinder.recurrence',
        'kanademinder.llm.client',
        'kanademinder.llm.parser',
        'kanademinder.llm.prompts',
        'kanademinder.app.web.api',
        'kanademinder.app.web.frontend',
        'kanademinder.app.web.router',
        'kanademinder.app.chat.handler',
        'kanademinder.app.chat.actions',
        'kanademinder.app.daemon.scheduler',
        'kanademinder.gui.api',
        'kanademinder.gui.settings.api',
        'kanademinder.gui.settings.window',
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
    [],
    exclude_binaries=True,
    name='KanadeMinder',
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
    icon='assets/icon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='KanadeMinder',
)

app = BUNDLE(
    coll,
    name='KanadeMinder.app',
    icon='assets/icon.icns',
    bundle_identifier='com.kanademinder.app',
    info_plist={
        'CFBundleName': 'KanadeMinder',
        'CFBundleDisplayName': 'KanadeMinder',
        'CFBundleVersion': '0.1.1',
        'CFBundleShortVersionString': '0.1.1',
        'NSHighResolutionCapable': True,
        'LSMinimumSystemVersion': '11.0',
        'NSHumanReadableCopyright': 'by Zhiming Ye',
        'CFBundleDocumentTypes': [],
        'LSApplicationCategoryType': 'public.app-category.productivity',
        'NSAppleEventsUsageDescription': 'KanadeMinder uses Apple Events for notifications.',
    },
)
