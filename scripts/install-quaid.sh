#!/usr/bin/env bash
# install-quaid.sh - Download or build the Quaid binary
# Usage: bash scripts/install-quaid.sh [version]
# Version: "latest" (default) or specific tag like "v0.9.9"
#
# Binary naming convention (v0.9.9+):
#   quaid-{os}-{arch}-online   (embedded embeddings, recommended for CI)
#   quaid-{os}-{arch}-airgapped
#
# OS:   darwin, linux
# Arch: arm64, aarch64, x86_64
#
# Fallback: build from source via cargo if no binary release found.

set -euo pipefail

VERSION="${1:-latest}"
INSTALL_DIR="/usr/local/bin"
REPO="quaid-app/quaid"

echo "Installing Quaid ${VERSION}..."

# Detect OS and arch
OS=$(uname -s | tr '[:upper:]' '[:lower:]')
ARCH=$(uname -m)

# Map to quaid release naming
case "$OS-$ARCH" in
  linux-x86_64)   BINARY_NAME="quaid-linux-x86_64-online" ;;
  linux-aarch64)  BINARY_NAME="quaid-linux-aarch64-online" ;;
  linux-arm64)    BINARY_NAME="quaid-linux-aarch64-online" ;;
  darwin-arm64)   BINARY_NAME="quaid-darwin-arm64-online" ;;
  darwin-x86_64)  BINARY_NAME="quaid-darwin-x86_64-online" ;;
  *)
    echo "Unknown platform: $OS-$ARCH"
    BINARY_NAME=""
    ;;
esac

# Resolve "latest" to actual version tag
if [ "$VERSION" = "latest" ]; then
  VERSION=$(curl -sf \
    -H "Accept: application/vnd.github.v3+json" \
    "https://api.github.com/repos/${REPO}/releases/latest" \
    | grep '"tag_name"' | cut -d'"' -f4 || echo "")

  if [ -z "$VERSION" ]; then
    echo "No releases found - building from source."
    VERSION="source"
  else
    echo "Resolved latest to: $VERSION"
  fi
fi

# Try downloading pre-built binary
if [ "$VERSION" != "source" ] && [ -n "$BINARY_NAME" ]; then
  DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${BINARY_NAME}"
  echo "Downloading: $DOWNLOAD_URL"

  HTTP_CODE=$(curl -sL -w "%{http_code}" "$DOWNLOAD_URL" -o /tmp/quaid_candidate 2>/dev/null)

  if [ "$HTTP_CODE" = "200" ]; then
    FILETYPE=$(file /tmp/quaid_candidate 2>/dev/null | head -1)
    if echo "$FILETYPE" | grep -qiE "ELF|Mach-O|executable"; then
      chmod +x /tmp/quaid_candidate
      sudo mv /tmp/quaid_candidate "$INSTALL_DIR/quaid"
      echo "Binary installed: $BINARY_NAME ($VERSION)"
      quaid --version
      exit 0
    else
      echo "Downloaded file is not a valid binary (type: $FILETYPE) - falling back to source build."
    fi
  else
    echo "Binary download failed (HTTP $HTTP_CODE) - falling back to source build."
  fi
fi

# Build from source
echo ""
echo "=== Building Quaid from source ==="

if ! command -v cargo &>/dev/null; then
  echo "Installing Rust..."
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
  source "$HOME/.cargo/env"
fi

CLONE_DIR="/tmp/quaid-src"
if [ -d "$CLONE_DIR/.git" ]; then
  cd "$CLONE_DIR" && git fetch --tags --quiet
else
  git clone --depth=50 "https://github.com/${REPO}.git" "$CLONE_DIR"
  cd "$CLONE_DIR"
fi

if [ "$VERSION" != "source" ] && git tag | grep -q "^${VERSION}$"; then
  git checkout "$VERSION" --quiet
  echo "Checked out tag: $VERSION"
else
  git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
  echo "Building from HEAD"
fi

# macOS arm64 patch (st_mode type issue in older releases)
if [ "$OS" = "darwin" ] && [ "$ARCH" = "arm64" ]; then
  if grep -q "st_mode as i32" src/core/fs_safety.rs 2>/dev/null; then
    sed -i.bak 's/st_mode as i32/st_mode as u32/g' src/core/fs_safety.rs
    echo "Applied macOS arm64 patch."
  fi
fi

echo "Building (release mode)..."
cargo build --release 2>&1 | tail -3

sudo cp target/release/quaid "$INSTALL_DIR/quaid"
echo "Quaid built and installed from source."
quaid --version
