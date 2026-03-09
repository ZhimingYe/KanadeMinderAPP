#!/usr/bin/env bash
# make_dmg.sh — Build a distributable DMG for KanadeMinder using macOS built-in tools
# Usage: bash scripts/make_dmg.sh <AppName> <Version> <AppPath> <DmgPath>
# Example: bash scripts/make_dmg.sh KanadeMinder 0.1.0 dist/KanadeMinder.app dist/KanadeMinder-0.1.0.dmg

set -euo pipefail

APP_NAME="${1:?Missing APP_NAME}"
VERSION="${2:?Missing VERSION}"
APP_PATH="${3:?Missing APP_PATH}"
DMG_PATH="${4:?Missing DMG_PATH}"

VOLUME_NAME="${APP_NAME} ${VERSION}"
TMP_DMG="${DMG_PATH%.dmg}-tmp.dmg"
MOUNT_POINT="/Volumes/${VOLUME_NAME}"

# Disk size: add 50 MB headroom over app bundle size
APP_SIZE_KB=$(du -sk "${APP_PATH}" | cut -f1)
DMG_SIZE_MB=$(( (APP_SIZE_KB / 1024) + 80 ))

echo "→ Creating writable DMG (${DMG_SIZE_MB} MB) ..."
hdiutil create \
    -volname "${VOLUME_NAME}" \
    -srcfolder "${APP_PATH}" \
    -ov \
    -fs HFS+ \
    -size "${DMG_SIZE_MB}m" \
    -format UDRW \
    "${TMP_DMG}"

echo "→ Mounting DMG ..."
hdiutil attach "${TMP_DMG}" -mountpoint "${MOUNT_POINT}" -nobrowse -quiet

# Add /Applications symlink so users can drag-and-drop
echo "→ Adding /Applications symlink ..."
ln -sf /Applications "${MOUNT_POINT}/Applications"

# Position icons and set window appearance via AppleScript
echo "→ Setting window appearance ..."
osascript <<APPLESCRIPT
tell application "Finder"
    tell disk "${VOLUME_NAME}"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {400, 100, 900, 430}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 128
        set position of item "${APP_NAME}.app" of container window to {130, 160}
        set position of item "Applications" of container window to {370, 160}
        close
        open
        update without registering applications
        delay 2
        close
    end tell
end tell
APPLESCRIPT

# Tell Finder to release the volume before we detach
osascript -e "tell application \"Finder\" to if disk \"${VOLUME_NAME}\" exists then eject disk \"${VOLUME_NAME}\"" 2>/dev/null || true

# Sync and unmount
sync
echo "→ Unmounting DMG ..."
# Retry up to 5 times; fall back to -force if Finder is still holding the volume
for i in 1 2 3 4 5; do
    hdiutil detach "${MOUNT_POINT}" -quiet 2>/dev/null && break
    if [ "$i" -eq 5 ]; then
        echo "  (retries exhausted — forcing detach)"
        hdiutil detach "${MOUNT_POINT}" -force -quiet || true
    else
        echo "  (retry $i — waiting for Finder to release volume...)"
        sleep 2
    fi
done

# Verify volume is gone before converting
if [ -d "${MOUNT_POINT}" ]; then
    echo "ERROR: volume still mounted at ${MOUNT_POINT} — cannot convert" >&2
    exit 1
fi

# Convert to compressed read-only DMG
echo "→ Converting to compressed read-only DMG ..."
rm -f "${DMG_PATH}"
hdiutil convert "${TMP_DMG}" \
    -format UDZO \
    -imagekey zlib-level=9 \
    -o "${DMG_PATH}"

rm -f "${TMP_DMG}"
echo "✓ DMG ready: ${DMG_PATH}"
