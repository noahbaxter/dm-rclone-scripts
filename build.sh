#!/bin/bash
#
# Build standalone executable for Synchotic
#
# Usage:
#   ./build.sh           Build for current platform
#   ./build.sh --clean   Remove build artifacts
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
echo_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Detect platform
detect_platform() {
    case "$(uname -s)" in
        Darwin*)
            PLATFORM="macos"
            ARCH="$(uname -m)"
            if [ "$ARCH" = "arm64" ]; then
                echo_info "Detected: macOS (Apple Silicon)"
            else
                echo_info "Detected: macOS (Intel)"
            fi
            ;;
        MINGW*|CYGWIN*|MSYS*)
            PLATFORM="windows"
            echo_info "Detected: Windows"
            ;;
        *)
            echo_error "Unsupported platform: $(uname -s)"
            echo_error "Use GitHub Actions for cross-platform builds."
            exit 1
            ;;
    esac
}

# Check dependencies
check_deps() {
    echo_info "Checking dependencies..."

    if ! command -v python3 &> /dev/null; then
        echo_error "Python 3 is required but not found"
        exit 1
    fi

    PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    echo_info "Python version: $PYTHON_VERSION"
}

# Setup virtual environment
setup_venv() {
    echo_info "Setting up virtual environment..."

    if [ ! -d "venv" ]; then
        python3 -m venv venv
    fi

    # Activate venv
    if [ "$PLATFORM" = "windows" ]; then
        source venv/Scripts/activate
    else
        source venv/bin/activate
    fi

    # Install dependencies
    echo_info "Installing dependencies..."
    pip install --upgrade pip > /dev/null
    pip install -r requirements.txt > /dev/null
    pip install pyinstaller > /dev/null
}

# Build for current platform
build() {
    if [ "$PLATFORM" = "macos" ]; then
        echo_info "Building macOS executable..."
        OUTPUT_NAME="synchotic-macos"
    else
        echo_info "Building Windows executable..."
        OUTPUT_NAME="synchotic"
    fi

    # Clean previous builds
    rm -rf build dist/*.spec

    pyinstaller \
        --onefile \
        --name "$OUTPUT_NAME" \
        --clean \
        --noconfirm \
        sync.py 2>/dev/null

    if [ "$PLATFORM" = "windows" ]; then
        OUTPUT_FILE="dist/${OUTPUT_NAME}.exe"
    else
        OUTPUT_FILE="dist/${OUTPUT_NAME}"
    fi

    if [ -f "$OUTPUT_FILE" ]; then
        SIZE=$(du -h "$OUTPUT_FILE" | cut -f1)
        echo_info "Built: $OUTPUT_FILE ($SIZE)"
    else
        echo_error "Build failed"
        exit 1
    fi
}

# Clean build artifacts
clean() {
    echo_info "Cleaning build artifacts..."
    rm -rf build dist *.spec __pycache__ src/__pycache__
    echo_info "Clean complete"
}

# Show usage
usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Options:"
    echo "  (none)     Build for current platform"
    echo "  --clean    Remove build artifacts"
    echo "  --help     Show this help"
    echo ""
    echo "Output is created in the 'dist' directory."
    echo ""
    echo "For cross-platform builds, use GitHub Actions:"
    echo "  git tag v2.x.x && git push origin v2.x.x"
}

# Main
main() {
    case "${1:-}" in
        --clean)
            clean
            ;;
        --help|-h)
            usage
            ;;
        "")
            detect_platform
            check_deps
            setup_venv
            build
            ;;
        *)
            echo_error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
}

main "$@"
