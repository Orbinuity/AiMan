#!/bin/sh
set -e

REPO="Orbinuity/AiMan"
APP_NAME="AiMan"
BINARY_NAME="aiman"
APP_VERSION="1.0-linux"
INSTALL_DIR="$HOME/.local/bin"

BOLD='\033[1m'
GREEN='\033[0;32m'
CYAN='\033[0;36m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { printf "${CYAN}[*]${NC} %s\n" "$1"; }
success() { printf "${GREEN}[✓]${NC} %s\n" "$1"; }
warn()    { printf "${YELLOW}[!]${NC} %s\n" "$1"; }
error()   { printf "${RED}[✗]${NC} %s\n" "$1"; exit 1; }

printf "\n${BOLD}=== %s Installer v%s ===${NC}\n\n" "$APP_NAME" "$APP_VERSION"

if [ -n "$TERMUX_VERSION" ] || [ -d "/data/data/com.termux" ]; then
    info "Android (Termux) environment detected!"
    
    info "Installing Python and Curl..."
    pkg update -y && pkg install python curl -y

    mkdir -p "$INSTALL_DIR"
    APP_DIR="$HOME/.local/share/$APP_NAME"
    mkdir -p "$APP_DIR"

    info "Downloading latest AiMan app source..."
    curl -fsSL "https://raw.githubusercontent.com/${REPO}/main/app.py" -o "$APP_DIR/app.py"

    cat << 'EOF' > "$INSTALL_DIR/$BINARY_NAME"
#!/bin/sh
exec python3 "$HOME/.local/share/AiMan/app.py" "$@"
EOF
    chmod +x "$INSTALL_DIR/$BINARY_NAME"

    case ":$PATH:" in
      *":$INSTALL_DIR:"*) ;;
      *) 
        warn "${INSTALL_DIR} is not in your PATH."
        info "Add it to your shell config (~/.bashrc):"
        printf "    ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n"
        ;;
    esac

    success "Successfully installed $APP_NAME for Termux!"
    printf "\n${GREEN}${BOLD}Done! Run '${BINARY_NAME}' to launch.${NC}\n\n"
    exit 0
fi

info "Fetching latest release info from GitHub..."
LATEST_RELEASE_JSON=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest") || error "Failed to connect to GitHub."
LATEST_TAG=$(echo "$LATEST_RELEASE_JSON" | grep '"tag_name":' | sed -E 's/.*"([^"]+)".*/\1/')

if [ -z "$LATEST_TAG" ]; then
    error "Could not retrieve latest version tag from GitHub API."
fi

TARGET_BINARY="$INSTALL_DIR/$BINARY_NAME"

if [ -f "$TARGET_BINARY" ]; then
    LOCAL_VERSION=$("$TARGET_BINARY" --version 2>/devnull | head -n 1 || true)
    
    if [ -n "$LOCAL_VERSION" ] && echo "$LOCAL_VERSION" | grep -q "$LATEST_TAG"; then
        success "$APP_NAME is already installed and up to date (${BOLD}${LATEST_TAG}${NC}${GREEN})!${NC}"
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
    printf "    ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}\n"
    ;;
esac

printf "\n${GREEN}${BOLD}Done! Run '${BINARY_NAME}' to launch.${NC}\n\n"