#!/bin/bash
#
# Install arXiv skills to a project directory
#
# Usage:
#   ./install-skills.sh [options]
#
# Options:
#   --help              Show this help message
#   --all               Install all skills (default)
#   --arxivterminal     Install only arxivterminal skill
#   --arxiv-doc-builder Install only arxiv-doc-builder skill
#
# Environment Variables:
#   SKILLS_INSTALL_PATH  Custom installation path (default: $PWD/.claude/skills)

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Default installation path
DEFAULT_INSTALL_PATH="$PWD/.claude/skills"
INSTALL_PATH="${SKILLS_INSTALL_PATH:-$DEFAULT_INSTALL_PATH}"

# Script directory (where this script is located)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_SOURCE_DIR="$SCRIPT_DIR/skills"

# Skills to install
INSTALL_ALL=true
INSTALL_ARXIVTERMINAL=false
INSTALL_DOC_BUILDER=false

# Functions
print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

show_help() {
    cat << EOF
Install arXiv skills to a project directory

Usage:
  ./install-skills.sh [options]

Options:
  --help              Show this help message
  --all               Install all skills (default)
  --arxivterminal     Install only arxivterminal skill
  --arxiv-doc-builder Install only arxiv-doc-builder skill

Environment Variables:
  SKILLS_INSTALL_PATH  Custom installation path (default: \$PWD/.claude/skills)

Examples:
  # Install all skills to default location
  ./install-skills.sh

  # Install all skills to custom location
  SKILLS_INSTALL_PATH=/path/to/project/.claude/skills ./install-skills.sh

  # Install only arxivterminal
  ./install-skills.sh --arxivterminal

  # Install to custom path with specific skill
  SKILLS_INSTALL_PATH=/path/to/project ./install-skills.sh --arxiv-doc-builder

EOF
}

install_skill() {
    local skill_name=$1
    local source_path="$SKILLS_SOURCE_DIR/$skill_name"
    local dest_path="$INSTALL_PATH/$skill_name"

    if [ ! -d "$source_path" ]; then
        print_error "Skill not found: $skill_name"
        return 1
    fi

    # Create destination directory
    mkdir -p "$INSTALL_PATH"

    # Remove existing installation if present
    if [ -d "$dest_path" ]; then
        print_warn "Removing existing installation: $dest_path"
        rm -rf "$dest_path"
    fi

    # Copy skill
    print_info "Installing $skill_name..."
    cp -r "$source_path" "$dest_path"

    print_info "✓ Installed $skill_name to $dest_path"
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --help)
            show_help
            exit 0
            ;;
        --all)
            INSTALL_ALL=true
            shift
            ;;
        --arxivterminal)
            INSTALL_ALL=false
            INSTALL_ARXIVTERMINAL=true
            shift
            ;;
        --arxiv-doc-builder)
            INSTALL_ALL=false
            INSTALL_DOC_BUILDER=true
            shift
            ;;
        *)
            print_error "Unknown option: $1"
            echo ""
            show_help
            exit 1
            ;;
    esac
done

# Main installation
echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║       arXiv Skills Installation                    ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
print_info "Installation path: $INSTALL_PATH"
echo ""

# Check if source directory exists
if [ ! -d "$SKILLS_SOURCE_DIR" ]; then
    print_error "Skills source directory not found: $SKILLS_SOURCE_DIR"
    exit 1
fi

# Install selected skills
if [ "$INSTALL_ALL" = true ]; then
    print_info "Installing all skills..."
    echo ""
    install_skill "arxivterminal"
    install_skill "arxiv-doc-builder"
else
    if [ "$INSTALL_ARXIVTERMINAL" = true ]; then
        install_skill "arxivterminal"
    fi
    if [ "$INSTALL_DOC_BUILDER" = true ]; then
        install_skill "arxiv-doc-builder"
    fi
fi

echo ""
echo "╔════════════════════════════════════════════════════╗"
echo "║       Installation Complete!                       ║"
echo "╚════════════════════════════════════════════════════╝"
echo ""
print_info "Skills installed to: $INSTALL_PATH"
echo ""
print_info "Next steps:"
echo "  1. Make sure Claude Code knows about this skills directory"
echo "  2. For arxivterminal: install arxivterminal package (if not already)"
echo "  3. For arxiv-doc-builder: install pandoc (brew install pandoc)"
echo ""
