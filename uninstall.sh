#!/bin/sh
set -e

TARGET="$HOME/.local/bin/aiman"

if [ -f "$TARGET" ]; then
    rm -f "$TARGET"
    printf "\033[0;32m[✓]\033[0m AiMan has been uninstalled.\n";
else
    printf "\033[1;33m[!]\033[0m AiMan was not found in $HOME/.local/bin\n"
fi