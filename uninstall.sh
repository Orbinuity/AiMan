#!/bin/sh
set -e

TARGET="$HOME/.local/bin/aiman"
APP_DIR="$HOME/.local/share/AiMan"

if [ -f "$TARGET" ] || [ -d "$APP_DIR" ]; then
    rm -f "$TARGET"
    rm -rf "$APP_DIR"
    printf "\033[0;32m[✓]\033[0m AiMan has been uninstalled.\n"
else
    printf "\033[1;33m[!]\033[0m AiMan was not found in $HOME/.local/bin\n"
fi