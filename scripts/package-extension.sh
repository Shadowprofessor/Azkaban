#!/bin/bash
# Build the extension and produce a loadable/uploadable zip.
#
#   bash scripts/package-extension.sh        # build + zip
#   SKIP_BUILD=1 bash scripts/package-extension.sh
#
# Uses whatever package manager the checkout has a lockfile for, so this works the same
# on a machine set up with npm and one set up with pnpm.
set -euo pipefail

cd "$(dirname "$0")/.."
EXT_DIR="azkaban-extension"
OUT="$EXT_DIR/.output/chrome-mv3"
DIST="dist"

if [ ! -d "$EXT_DIR" ]; then
    echo "ERROR: $EXT_DIR not found. Run this from the repo root." >&2
    exit 1
fi

if [ -f "$EXT_DIR/pnpm-lock.yaml" ] && command -v pnpm >/dev/null 2>&1; then
    PM=pnpm
elif command -v npm >/dev/null 2>&1; then
    PM=npm
else
    echo "ERROR: neither pnpm nor npm is on PATH." >&2
    exit 1
fi

if [ "${SKIP_BUILD:-0}" != "1" ]; then
    echo "==> building with $PM"
    ( cd "$EXT_DIR" && "$PM" run build )
fi

if [ ! -f "$OUT/manifest.json" ]; then
    echo "ERROR: no build output at $OUT (manifest.json missing)." >&2
    exit 1
fi

VERSION=$(node -p "require('./$EXT_DIR/package.json').version")
ZIP_NAME="azkaban-extension-v${VERSION}.zip"
mkdir -p "$DIST"
rm -f "$DIST/$ZIP_NAME"

# Validate before shipping: a zip with the wrong manifest version is worse than no zip.
node -e "
const m = require('./$OUT/manifest.json');
if (m.manifest_version !== 3) { console.error('ERROR: manifest_version is ' + m.manifest_version + ', expected 3'); process.exit(1); }
if (!m.name || !m.version) { console.error('ERROR: manifest is missing name or version'); process.exit(1); }
console.log('==> manifest ok: ' + m.name + ' v' + m.version + ' (MV' + m.manifest_version + ')');
"

if ! command -v zip >/dev/null 2>&1; then
    echo "ERROR: 'zip' is not installed." >&2
    echo "       Windows: use 'Compress-Archive -Path $OUT\\* -DestinationPath $DIST\\$ZIP_NAME'" >&2
    echo "       Debian/Ubuntu: sudo apt install zip" >&2
    exit 1
fi

# Source maps are build artefacts, not part of the extension.
( cd "$OUT" && zip -q -r "$OLDPWD/$DIST/$ZIP_NAME" . -x "*.map" )

SIZE=$(du -h "$DIST/$ZIP_NAME" | cut -f1)
echo "==> packaged: $DIST/$ZIP_NAME ($SIZE)"
echo
echo "Load it unpacked (for development):"
echo "  chrome://extensions -> Developer mode -> Load unpacked -> select"
echo "  $OUT"
echo
echo "Or upload $DIST/$ZIP_NAME to the Chrome Web Store."
