#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

echo "==> Cleaning previous builds"
rm -rf build dist

echo "==> Running PyInstaller"
python -m PyInstaller EurorackInventory.spec --noconfirm

echo "==> Ad-hoc code signing"
codesign --force --deep --sign - "dist/Simple DIY Synth Inventory.app"

# Create DMG if create-dmg is available
if command -v create-dmg &> /dev/null; then
    echo "==> Creating DMG"
    create-dmg \
        --volname "Simple DIY Synth Inventory" \
        --volicon "src/eurorack_inventory/resources/AppIcon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon "Simple DIY Synth Inventory.app" 150 190 \
        --app-drop-link 450 190 \
        --no-internet-enable \
        "dist/Simple DIY Synth Inventory.dmg" \
        "dist/Simple DIY Synth Inventory.app"
    echo "==> Done: dist/Simple DIY Synth Inventory.dmg"
else
    echo "==> Skipping DMG (install create-dmg: brew install create-dmg)"
    echo "==> Done: dist/Simple DIY Synth Inventory.app"
fi
