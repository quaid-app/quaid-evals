#!/usr/bin/env bash
# install-quaid.sh - Download or build the Quaid binary
# Usage: bash scripts/install-quaid.sh [version]
# Version: "latest" (default) or specific tag like "v1.0.0"
#
# Strategy:
#   1. Try to download a pre-built binary from GitHub releases
#   2. If no binary release exists, build from source (Rust/cargo)

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

# Resolve "latest" to actual version tag
if [ "$VERSION" = "latest" ]; then
  VERSION=$(curl -sf "https://api.github.com/repos/${REPO}/releases/latest" \
    -H "Accept: application/vnd.github.v3+json" \
    | grep '"tag_name"' | cut -d'"' -f4 || echo "")
  if [ -z "$VERSION" ]; then
    echo "No releases found on ${REPO} - falling back to build from source"
    VERSION="source"
  else
    echo "Resolved latest to: $VERSION"
  fi
fi

# Try downloading a pre-built binary
BINARY_NAME="quaid_${OS}_${ARCH}"
DOWNLOAD_URL="https://github.com/${REPO}/releases/download/${VERSION}/${BINARY_NAME}"

if [ "$VERSION" != "source" ]; then
  echo "Attempting binary download from: $DOWNLOAD_URL"
  HTTP_CODE=$(curl -sL -w "%{http_code}" "$DOWNLOAD_URL" -o /tmp/quaid_candidate)

  if [ "$HTTP_CODE" = "200" ]; then
    # Verify it looks like an actual binary (not an HTML/text error page)
    FILETYPE=$(file /tmp/quaid_candidate | head -1)
    if echo "$FILETYPE" | grep -qiE "ELF|Mach-O|executable"; then
      chmod +x /tmp/quaid_candidate
      sudo mv /tmp/quaid_candidate "$INSTALL_DIR/quaid"
      echo "Binary installed from release."
      quaid --version
      exit 0
    else
      echo "Downloaded file is not a valid binary (HTTP $HTTP_CODE, type: $FILETYPE)"
      echo "Falling back to build from source..."
    fi
  else
    echo "Binary download failed (HTTP $HTTP_CODE) - no pre-built binary for ${VERSION}"
    echo "Falling back to build from source..."
  fi
fi

# Build from source
echo ""
echo "=== Building Quaid from source ==="
echo "This requires Rust (cargo). Installing if needed..."

# Install Rust if not present
if ! command -v cargo &>/dev/null; then
  curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --no-modify-path
  source "$HOME/.cargo/env"
fi

CLONE_DIR="/tmp/quaid-src"
if [ -d "$CLONE_DIR" ]; then
  echo "Updating existing clone..."
  cd "$CLONE_DIR" && git fetch --tags
else
  echo "Cloning ${REPO}..."
  git clone "https://github.com/${REPO}.git" "$CLONE_DIR"
  cd "$CLONE_DIR"
fi

# Checkout the requested version if it's a real tag
if [ "$VERSION" != "source" ] && git tag | grep -q "^${VERSION}$"; then
  git checkout "$VERSION"
else
  git checkout main 2>/dev/null || git checkout master 2>/dev/null || true
  echo "Using HEAD of default branch"
fi

# macOS arm64 patch for stat.st_mode (known issue in fs_safety.rs)
if [ "$OS" = "darwin" ] && [ "$(uname -m)" = "arm64" ]; then
  if grep -q "st_mode as i32" src/core/fs_safety.rs 2>/dev/null; then
    sed -i.bak 's/st_mode as i32/st_mode as u32/g' src/core/fs_safety.rs
    echo "Applied macOS arm64 patch to fs_safety.rs"
  fi
fi

echo "Building (release mode)..."
cargo build --release 2>&1 | tail -5

sudo cp target/release/quaid "$INSTALL_DIR/quaid"
echo ""
echo "Quaid built and installed from source."
quaid --version
