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
#   --skill <name>      Install specific skill(s) (can be used multiple times)
#   --symlink           Create symlinks instead of copying (enables automatic updates)
#   --symlink-force     Create symlinks with force flag (overwrite existing files without prompt)
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
CODEX_INSTALL_PATH="$HOME/.codex/skills"
INSTALL_PATH="$DEFAULT_INSTALL_PATH"
USE_CODEX_PATH=false
USE_SYMLINK=false
USE_SYMLINK_FORCE=false

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
  --skill <name>      Install specific skill(s) (can be used multiple times)
  --symlink           Create symlinks instead of copying (enables automatic updates)
  --symlink-force     Create symlinks with force flag (overwrite existing files without prompt)
  --codex             Install to Codex global skills path (~/.codex/skills)

Environment Variables:
  SKILLS_INSTALL_PATH  Custom installation path (default: \$PWD/.claude/skills)

Examples:
  # Install all skills to default location (copy mode)
  ./install-skills.sh

  # Install with symlinks (recommended for development)
  ./install-skills.sh --symlink --all

  # Install with symlinks, forcefully overwriting existing files
  ./install-skills.sh --symlink-force --all

  # List available skills
  ./install-skills.sh --list

  # Install all skills to custom location
  SKILLS_INSTALL_PATH=/path/to/project/.claude/skills ./install-skills.sh

  # Install specific skills with symlinks
  ./install-skills.sh --symlink --skill my-skill --skill another-skill

  # Install to custom path with specific skill
  SKILLS_INSTALL_PATH=/path/to/project ./install-skills.sh --skill my-skill

  # Install for Codex (global) with symlinks
  ./install-skills.sh --symlink --codex --all

Note:
  When using --symlink, the skills will reference this repository directly.
  Any updates to the repository (e.g., git pull) will be immediately reflected
  in all installations. This is useful for development and keeping skills up-to-date.

  Use --symlink-force when you want to overwrite existing files without being prompted.

EOF
}

list_available_skills() {
    echo ""
    print_info "Available skills in $SKILLS_SOURCE_DIR:"
    echo ""

    if [ ! -d "$SKILLS_SOURCE_DIR" ]; then
        print_error "Skills directory not found: $SKILLS_SOURCE_DIR"
        return 1
    fi

    local found=false
    for skill_dir in "$SKILLS_SOURCE_DIR"/*/ ; do
        if [ -d "$skill_dir" ]; then
            local skill_name=$(basename "$skill_dir")
            if [ -f "$skill_dir/SKILL.md" ]; then
                # Extract description from YAML frontmatter if available
                local description=$(awk '/^---$/,/^---$/{if(/^description:/) {sub(/^description: */, ""); print; exit}}' "$skill_dir/SKILL.md")
                if [ -n "$description" ]; then
                    echo "  • $skill_name"
                    echo "    $description"
                else
                    echo "  • $skill_name"
                fi
                found=true
            fi
        fi
    done

    if [ "$found" = false ]; then
        print_warn "No skills found (no SKILL.md files)"
    fi
    echo ""
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

    # Remove existing installation if present (handles both directories and symlinks)
    if [ -e "$dest_path" ] || [ -L "$dest_path" ]; then
        print_warn "Removing existing installation: $dest_path"
        rm -rf "$dest_path"
    fi

    if [ "$USE_SYMLINK" = true ] || [ "$USE_SYMLINK_FORCE" = true ]; then
        # Create symlink with absolute path
        print_info "Creating symlink for $skill_name..."

        if [ "$USE_SYMLINK_FORCE" = true ]; then
            # Use force flag
            ln -fs "$source_path" "$dest_path"
            print_info "✓ Symlinked $skill_name (forced): $dest_path -> $source_path"
        else
            # Try without force flag first
            if ln -s "$source_path" "$dest_path" 2>/dev/null; then
                print_info "✓ Symlinked $skill_name: $dest_path -> $source_path"
            else
                # If it fails, ask user for confirmation to use force
                print_warn "Failed to create symlink for $skill_name"
                echo -e "${YELLOW}[?]${NC} A file or directory already exists at: $dest_path"
                echo -e "${YELLOW}[?]${NC} Do you want to force overwrite it? (y/N): "
                read -r response
                if [[ "$response" =~ ^[Yy]$ ]]; then
                    ln -fs "$source_path" "$dest_path"
                    print_info "✓ Symlinked $skill_name (forced): $dest_path -> $source_path"
                else
                    print_error "Skipped $skill_name - user declined to overwrite"
                    return 1
                fi
            fi
        fi
    else
        # Copy skill
        print_info "Installing $skill_name..."
        cp -r "$source_path" "$dest_path"
        print_info "✓ Installed $skill_name to $dest_path"
    fi
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
        --symlink)
            USE_SYMLINK=true
            shift
            ;;
        --symlink-force)
            USE_SYMLINK_FORCE=true
            USE_SYMLINK=true
            shift
            ;;
        --codex)
            USE_CODEX_PATH=true
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

if [ "$USE_SYMLINK_FORCE" = true ]; then
    print_info "Installation mode: Symlink (force)"
    echo ""
    echo "  Skills are symlinked from: $SCRIPT_DIR/skills"
    echo "  → Existing files were forcefully overwritten"
    echo "  → Any updates to the repository will be automatically reflected"
    echo "  → Run 'git pull' in $SCRIPT_DIR to update skills"
    echo ""
elif [ "$USE_SYMLINK" = true ]; then
    print_info "Installation mode: Symlink"
    echo ""
    echo "  Skills are symlinked from: $SCRIPT_DIR/skills"
    echo "  → Any updates to the repository will be automatically reflected"
    echo "  → Run 'git pull' in $SCRIPT_DIR to update skills"
    echo ""
else
    print_info "Installation mode: Copy"
    echo ""
    echo "  Skills have been copied to: $INSTALL_PATH"
    echo "  → To enable automatic updates, reinstall with --symlink flag"
    echo ""
fi

print_info "Next steps:"
echo ""
echo "  Choose ONE of the following methods to use these skills:"
echo ""
echo "  Option 1: Direct use (Recommended for single project)"
echo "    → Skills in .claude/skills/ are automatically detected"
echo "    → No additional configuration needed"
echo ""
echo "  Option 2: Plugin installation (Recommended for multiple projects)"
echo "    → In Claude Code, run: /plugin install $SCRIPT_DIR"
echo "    → Makes skills available across projects"
echo ""
echo "  Option 3: Team-wide marketplace (Advanced)"
echo "    → Add to .claude/settings.json in your project:"
echo "    → See README.md for detailed instructions"
echo ""
print_info "Next: Check each skill's SKILL.md for specific dependencies and setup"
echo ""
