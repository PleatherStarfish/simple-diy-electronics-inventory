# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for Simple DIY Electronics Inventory macOS app

from PyInstaller.utils.hooks import collect_data_files

tabula_datas = collect_data_files('tabula')

a = Analysis(
    ['src/eurorack_inventory/__main__.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('src/eurorack_inventory/db/migrations', 'eurorack_inventory/db/migrations'),
        ('src/eurorack_inventory/resources/AppIcon.png', 'eurorack_inventory/resources'),
    ] + tabula_datas,
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
    name='SimpleDIYElectronicsInventory',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon='src/eurorack_inventory/resources/AppIcon.icns',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name='SimpleDIYElectronicsInventory',
)

app = BUNDLE(
    coll,
    name='Simple DIY Electronics Inventory.app',
    icon='src/eurorack_inventory/resources/AppIcon.icns',
    bundle_identifier='com.danielmiller.simple-diy-electronics-inventory',
    info_plist={
        'CFBundleShortVersionString': '0.3.2',
        'CFBundleName': 'Simple DIY Electronics Inventory',
        'CFBundleDisplayName': 'Simple DIY Electronics Inventory',
        'NSHighResolutionCapable': True,
    },
)
