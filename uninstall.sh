#!/bin/sh
set -e

BINARY_NAME="aiman"
APP_NAME="AiMan"

# Detect possible installation targets
LOCAL_BIN="$HOME/.local/bin/$BINARY_NAME"
TERMUX_BIN="${PREFIX:-/data/data/com.termux/files/usr}/bin/$BINARY_NAME"
APP_DIR="$HOME/.local/share/$APP_NAME"

REMOVED=0

# Clean up binaries
if [ -f "$LOCAL_BIN" ]; then
    rm -f "$LOCAL_BIN"
    REMOVED=1
fi

if [ -f "$TERMUX_BIN" ]; then
    rm -f "$TERMUX_BIN"
    REMOVED=1
fi

# Clean up Termux source files
if [ -d "$APP_DIR" ]; then
    rm -rf "$APP_DIR"
    REMOVED=1
fi

# Report result
if [ "$REMOVED" -eq 1 ]; then
    printf "\033[0;32m[✓]\033[0m %s has been successfully uninstalled.\n" "$APP_NAME"
else
    printf "\033[1;33m[!]\033[0m %s installation was not found.\n" "$APP_NAME"
fi