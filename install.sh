#!/bin/sh
set -e

REPO="Orbinuity/AiMan"
APP_NAME="AiMan"
BINARY_NAME="aiman"
INSTALL_DIR="$HOME/.local/bin"
INSTALLER_VERSION="2.3-linux"

BOLD=$(printf '\033[1m')
GREEN=$(printf '\033[0;32m')
CYAN=$(printf '\033[0;36m')
YELLOW=$(printf '\033[1;33m')
RED=$(printf '\033[0;31m')
NC=$(printf '\033[0m')

info()    { printf "%s[*]%s %s\n" "$CYAN" "$NC" "$1"; }
success() { printf "%s[✓]%s %s\n" "$GREEN" "$NC" "$1"; }
warn()    { printf "%s[!]%s %s\n" "$YELLOW" "$NC" "$1"; }
error()   { printf "%s[✗]%s %s\n" "$RED" "$NC" "$1"; exit 1; }

printf "\n%s=== %s installer v%s ===%s\n\n" "$BOLD" "$APP_NAME" "$INSTALLER_VERSION" "$NC"

info "Fetching latest release info from GitHub..."
LATEST_RELEASE_JSON=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest") || error "Failed to connect to GitHub."
LATEST_TAG=$(echo "$LATEST_RELEASE_JSON" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$LATEST_TAG" ]; then
    error "Could not retrieve latest version tag from GitHub API."
fi

if [ -n "$TERMUX_VERSION" ] || [ -d "/data/data/com.termux" ]; then
    info "Android (Termux) environment detected!"
    
    TERMUX_BIN="${PREFIX:-/data/data/com.termux/files/usr}/bin"
    
    info "Installing repo for python secific versions"
    pkg install tur-repo

    info "Installing system packages (Python, Pip, Curl)..."
    pkg update -y && pkg install python3.13 python3.13-pip curl -y

    info "Installing Python dependencies..."
    python3 -m pip install ollama==0.6.1 --extra-index-url https://eutalix.github.io/android-pydantic-core/ --only-binary pydantic-core

    rm -f "$TERMUX_BIN/$BINARY_NAME"

    APP_DIR="$HOME/.local/share/$APP_NAME"
    mkdir -p "$APP_DIR"

    info "Downloading AiMan ${LATEST_TAG} source code..."
    APP_DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${LATEST_TAG}/app.py"
    curl -fsSL "$APP_DOWNLOAD_URL" -o "$APP_DIR/app.py"

    info "Creating launcher..."
    cat << 'EOF' > "$TERMUX_BIN/$BINARY_NAME"
#!/bin/sh
exec python3 "$HOME/.local/share/AiMan/app.py" "$@"
EOF
    chmod +x "$TERMUX_BIN/$BINARY_NAME"

    success "Successfully installed $APP_NAME (${LATEST_TAG}) for Termux!"
    printf "\n%s%sDone! Run '%s' to launch.%s\n\n" "$GREEN" "$BOLD" "$BINARY_NAME" "$NC"
    exit 0
fi

TARGET_BINARY="$INSTALL_DIR/$BINARY_NAME"

if [ -f "$TARGET_BINARY" ]; then
    LOCAL_VERSION=$("$TARGET_BINARY" --version 2>/dev/null | head -n 1 || true)
    
    if [ -n "$LOCAL_VERSION" ] && echo "$LOCAL_VERSION" | grep -q "$LATEST_TAG"; then
        success "$APP_NAME is already installed and up to date (${BOLD}${LATEST_TAG}${NC})!"
        printf "\n"
        exit 0
    else
        warn "Found existing installation. Upgrading to ${BOLD}${LATEST_TAG}${NC}..."
    fi
fi

OS="$(uname -s)"
case "${OS}" in
    Linux*)     OS_ASSET="linux";;
    Darwin*)    OS_ASSET="macos";;
    *)          error "Unsupported Operating System: ${OS}";;
esac

DOWNLOAD_URL=$(echo "$LATEST_RELEASE_JSON" \
  | grep "browser_download_url" \
  | grep "${OS_ASSET}" \
  | cut -d '"' -f 4 \
  | head -n 1)

if [ -z "$DOWNLOAD_URL" ]; then
    error "No binary release found matching platform: ${OS_ASSET}"
fi

mkdir -p "$INSTALL_DIR"
TMP_DIR=$(mktemp -d)
trap 'rm -rf "$TMP_DIR"' EXIT

info "Downloading ${APP_NAME} ${LATEST_TAG}..."
curl -fsSL -o "$TMP_DIR/$BINARY_NAME" "$DOWNLOAD_URL"
chmod +x "$TMP_DIR/$BINARY_NAME"

mv "$TMP_DIR/$BINARY_NAME" "$TARGET_BINARY"
success "Successfully installed ${APP_NAME} (${LATEST_TAG}) to ${INSTALL_DIR}"

case ":$PATH:" in
  *":$INSTALL_DIR:"*) ;;
  *) 
    warn "${INSTALL_DIR} is not in your PATH."
    info "Add it to your shell config (~/.bashrc or ~/.zshrc):"
    printf "    %sexport PATH=\"\$HOME/.local/bin:\$PATH\"%s\n" "$BOLD" "$NC"
    ;;
esac

printf "\n%s%sDone! Run '%s' to launch.%s\n\n" "$GREEN" "$BOLD" "$BINARY_NAME" "$NC"