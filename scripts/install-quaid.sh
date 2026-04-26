#!/usr/bin/env bash
# install-quaid.sh - Download and install the Quaid binary
# Usage: bash install-quaid.sh [version]
# Version: "latest" (default) or specific tag like "v1.0.0"

set -euo pipefail

VERSION="${1:-latest}"
INSTALL_DIR="/usr/local/bin"
REPO="quaid-app/quaid"

echo "Installing Quaid ${VERSION}..."

# Detect OS and arch
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)
case "$ARCH" in
  x86_64) ARCH="amd64" ;;
  aarch64|arm64) ARCH="arm64" ;;
  *) echo "Unsupported arch: $ARCH"; exit 1 ;;
esac

# Resolve "latest" to actual version
if [ "$VERSION" = "latest" ]; then
  VERSION=$(curl -sf "https://api.github.com/repos/${REPO}/releases/latest" | grep '"tag_name"' | cut -d'"' -f4)
  echo "Resolved latest to: $VERSION"
fi

# Download binary
BINARY_NAME="quaid_${OS}_${ARCH}"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${BINARY_NAME}"

echo "Downloading from: $DOWNLOAD_URL"
curl -sL "$DOWNLOAD_URL" -o /tmp/quaid

chmod +x /tmp/quaid
sudo mv /tmp/quaid "$INSTALL_DIR/quaid"

# Verify
quaid --version
echo "Quaid installed successfully."
