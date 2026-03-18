#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_DIR"

APP_NAME="Simple DIY Electronics Inventory"
APP_PATH="dist/${APP_NAME}.app"
DMG_PATH="dist/${APP_NAME}.dmg"

if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON_BIN="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${PROJECT_DIR}/.venv/bin/python" ]]; then
    PYTHON_BIN="${PROJECT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    PYTHON_BIN="$(command -v python)"
fi

SIGNING_IDENTITY="${APPLE_SIGNING_IDENTITY:-}"
APPLE_ID="${APPLE_ID:-}"
APPLE_TEAM_ID="${APPLE_TEAM_ID:-}"
APPLE_APP_PASSWORD="${APPLE_APP_PASSWORD:-}"

echo "==> Cleaning previous builds"
# Eject any mounted DMG from a previous build to avoid rm failures
hdiutil detach "/Volumes/${APP_NAME}" 2>/dev/null || true
rm -rf build dist

echo "==> Running PyInstaller"
"${PYTHON_BIN}" -m PyInstaller EurorackInventory.spec --noconfirm

if [[ -n "${SIGNING_IDENTITY}" ]]; then
    echo "==> Code signing with Developer ID identity"
    codesign \
        --force \
        --deep \
        --options runtime \
        --timestamp \
        --sign "${SIGNING_IDENTITY}" \
        "${APP_PATH}"
    codesign --verify --deep --strict --verbose=2 "${APP_PATH}"
else
    echo "==> Ad-hoc code signing"
    echo "    Local builds will run on this machine, but downloaded releases will be blocked by Gatekeeper."
    codesign --force --deep --sign - "${APP_PATH}"
fi

if command -v create-dmg >/dev/null 2>&1; then
    echo "==> Creating DMG"
    create-dmg \
        --volname "${APP_NAME}" \
        --volicon "src/eurorack_inventory/resources/AppIcon.icns" \
        --window-pos 200 120 \
        --window-size 600 400 \
        --icon "${APP_NAME}.app" 150 190 \
        --app-drop-link 450 190 \
        --no-internet-enable \
        "${DMG_PATH}" \
        "dist"

    if [[ -n "${SIGNING_IDENTITY}" ]] && [[ -n "${APPLE_ID}" ]] && [[ -n "${APPLE_TEAM_ID}" ]] && [[ -n "${APPLE_APP_PASSWORD}" ]]; then
        echo "==> Submitting DMG for notarization"
        xcrun notarytool submit \
            "${DMG_PATH}" \
            --apple-id "${APPLE_ID}" \
            --team-id "${APPLE_TEAM_ID}" \
            --password "${APPLE_APP_PASSWORD}" \
            --wait

        echo "==> Stapling notarization ticket"
        xcrun stapler staple "${APP_PATH}"
        xcrun stapler staple "${DMG_PATH}"
        xcrun stapler validate "${DMG_PATH}"
    else
        echo "==> Skipping notarization"
        echo "    Set APPLE_SIGNING_IDENTITY, APPLE_ID, APPLE_TEAM_ID, and APPLE_APP_PASSWORD for distributable releases."
    fi

    echo "==> Done: ${DMG_PATH}"
else
    echo "==> Skipping DMG (install create-dmg: brew install create-dmg)"
    echo "==> Done: ${APP_PATH}"
fi
