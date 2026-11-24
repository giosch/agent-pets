#!/bin/bash
# Build the Agent Pets menu bar .app bundle with bundled simulator.
# Usage: cd host && ./build.sh [--install]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SIM_DIR="$SCRIPT_DIR/../simulator"
SIM_BINARY="$SIM_DIR/build-static/agent-pets-sim"

# Always rebuild static simulator — cmake handles incremental builds
echo "==> Building static simulator..."
cd "$SIM_DIR"
cmake -B build-static -DSTATIC_SDL2=ON
cmake --build build-static
cd "$SCRIPT_DIR"

# Build .app with py2app
echo "==> Building .app bundle..."
cd "$SCRIPT_DIR"
rm -rf build dist
.venv/bin/python setup.py py2app 2>&1 | tail -3

# Bundle simulator binary
echo "==> Bundling simulator binary..."
cp "$SIM_BINARY" "dist/Agent Pets.app/Contents/Resources/agent-pets-sim"

echo "==> Built: dist/Agent Pets.app"

# Install if requested
if [ "${1:-}" = "--install" ]; then
    echo "==> Installing to /Applications..."
    rm -rf "/Applications/Agent Pets.app"
    cp -R "dist/Agent Pets.app" "/Applications/Agent Pets.app"
    echo "==> Installed to /Applications/Agent Pets.app"
fi
