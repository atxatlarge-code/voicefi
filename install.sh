#!/usr/bin/env bash
# ==============================================================================
#  VoiceFi™ (vifi) — Universal Ambient Voice Layer for macOS & AI Agents
#  Install Script for https://vifi.sh / https://voicefi.org
# ==============================================================================
set -e

# ANSI Colors
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

echo ""
echo -e "${CYAN}${BOLD}"
echo "        _  __ _ "
echo " __   _(_)/ _(_)"
echo " \ \ / / | |_| |"
echo "  \ V /| |  _| |"
echo -e "   \_/ |_|_| |_|   ${PURPLE}VoiceFi™${CYAN} (vifi.sh)${NC}"
echo ""
echo -e "Website: ${CYAN}https://voicefi.org${NC} · Docs: ${CYAN}https://vifi.sh${NC}"
echo "------------------------------------------------------------------"

# 1. OS Check
OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
    echo -e "${RED}❌ VoiceFi is currently optimized for macOS (Darwin). Found: $OS${NC}"
    exit 1
fi

ARCH="$(uname -m)"
echo -e "${GREEN}✓${NC} Detected macOS ($ARCH)"

# 2. Python 3.10+ Check
if ! command -v python3 >/dev/null 2>&1; then
    echo -e "${RED}❌ Python 3 is required but not found. Please install Python 3.10+ via Homebrew: brew install python${NC}"
    exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"

if [ "$PY_MAJOR" -lt 3 ] || [ "$PY_MINOR" -lt 10 ]; then
    echo -e "${RED}❌ Python 3.10+ is required. Found Python $PY_VER${NC}"
    exit 1
fi
echo -e "${GREEN}✓${NC} Python $PY_VER detected"

# 3. Create Install Directories
INSTALL_DIR="$HOME/.voicefi"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

echo -e "${CYAN}⚡ Setting up VoiceFi virtual environment in $INSTALL_DIR...${NC}"

if command -v uv >/dev/null 2>&1; then
    uv venv "$INSTALL_DIR/venv" --allow-existing >/dev/null 2>&1 || uv venv "$INSTALL_DIR/venv" >/dev/null 2>&1
    PIP_CMD="uv pip install --python $INSTALL_DIR/venv/bin/python"
else
    if [ ! -f "$INSTALL_DIR/venv/bin/python" ] || [ ! -f "$INSTALL_DIR/venv/bin/pip" ]; then
        rm -rf "$INSTALL_DIR/venv"
        python3 -m venv "$INSTALL_DIR/venv"
        "$INSTALL_DIR/venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
    PIP_CMD="$INSTALL_DIR/venv/bin/pip install"
fi

# If executing from within a cloned repo, install in editable mode
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    echo -e "${CYAN}⚡ Installing local repository ($SCRIPT_DIR)...${NC}"
    $PIP_CMD --quiet -e "$SCRIPT_DIR"
else
    echo -e "${CYAN}⚡ Installing latest VoiceFi release from voicefi.org...${NC}"
    $PIP_CMD --quiet git+https://github.com/atxatlarge-code/voicefi.git || $PIP_CMD --quiet voicefi
fi

# 4. Create wrapper binary for 'vifi', 'vg', and 'voicefi'
rm -f "$BIN_DIR/vifi" "$BIN_DIR/vg" "$BIN_DIR/voicefi"
cat << 'RUNNER' > "$BIN_DIR/vifi"
#!/usr/bin/env bash
exec "$HOME/.voicefi/venv/bin/voicefi" "$@"
RUNNER
chmod +x "$BIN_DIR/vifi"

ln -sf "$BIN_DIR/vifi" "$BIN_DIR/voicefi"
ln -sf "$BIN_DIR/vifi" "$BIN_DIR/vg"

# 5. Connect AI Agent lifecycle hooks & user settings
#    - Registers user-space 'Stop' hooks in:
#      • ~/.gemini/config/hooks.json (Antigravity)
#      • ~/.claude/settings.json (Claude Code - when installed)
#      so VoiceFi speaks turn completions in custom agent personas and listens hands-free.
#    - Writes user preferences (voice selection, sensitivity) to ~/.voicefi/config.yaml.
#    - For Cursor & Windsurf: VoiceFi uses system-wide audio dictation (Ctrl+T).
#    - Modifies zero system/root binaries and adds no telemetry services.
echo -e "${CYAN}⚡ Configuring Agent lifecycle hooks (Antigravity & Claude Code)...${NC}"
"$INSTALL_DIR/venv/bin/voicefi" setup >/dev/null 2>&1 || true

# 6. Check for Obsidian and prompt user interactively
if [ -d "$HOME/Library/Application Support/obsidian" ] || [ -d "$HOME/Documents/Obsidian Vault" ]; then
    INSTALL_OBSIDIAN="y"
    if [ -t 0 ] && [ -r /dev/tty ]; then
        echo ""
        echo -e "${PURPLE}📓 Detected Obsidian on your Mac.${NC}"
        read -r -p "👉 Install VoiceFi Obsidian voice bridge plugin? [Y/n]: " user_obsidian_choice 2>/dev/null < /dev/tty || user_obsidian_choice="y"
        if [[ "$user_obsidian_choice" =~ ^[Nn] ]]; then
            INSTALL_OBSIDIAN="n"
        fi
    fi

    if [ "$INSTALL_OBSIDIAN" = "y" ]; then
        echo -e "${CYAN}⚡ Installing VoiceFi plugin to Obsidian vaults...${NC}"
        "$INSTALL_DIR/venv/bin/voicefi" obsidian install --all >/dev/null 2>&1 || true
    else
        echo -e "💡 Skipped Obsidian install. You can install it anytime with: ${CYAN}vifi obsidian install${NC}"
    fi
fi

# 7. Check PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    echo ""
    echo -e "${PURPLE}⚠️  Notice: $BIN_DIR is not in your current PATH.${NC}"
    echo -e "Add it to your shell configuration (~/.zshrc or ~/.bashrc):"
    echo -e "  ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
fi

echo ""
echo -e "${GREEN}${BOLD}🎉 VoiceFi Installation Complete!${NC}"
echo "------------------------------------------------------------------"
echo -e "🗣️  ${BOLD}Claude Code & Antigravity:${NC} Hands-free conversational voice turns active"
echo -e "💻  ${BOLD}Cursor & macOS:${NC}            Universal ${CYAN}${BOLD}<Ctrl>+T${NC} dictation into any text box"
echo -e "📓 ${BOLD}Obsidian:${NC}                Auto-configured across local vaults"
echo -e "🔊 ${BOLD}Test Voice:${NC}              Run ${CYAN}${BOLD}vifi voice test${NC} (or ${CYAN}${BOLD}vg voice test${NC})"
echo -e "👂 ${BOLD}Hearing Test:${NC}            Run ${CYAN}${BOLD}vifi hearing-test${NC}"
echo -e "🔄 ${BOLD}Feedback Loop:${NC}           Run ${CYAN}${BOLD}vifi feedback-loop${NC}"
echo -e "🎛️  ${BOLD}Control Panel:${NC}           Run ${CYAN}${BOLD}vifi panel${NC} (http://localhost:8765)"
echo -e "📖 ${BOLD}Commands:${NC}                Run ${CYAN}${BOLD}vifi --help${NC}"
echo "------------------------------------------------------------------"
echo ""

# 7. Play interactive welcome greeting with auto-detected user name
DETECTED_USER="$("$INSTALL_DIR/venv/bin/python" -c 'from voicefi.config import load_config; print(load_config().user_name)' 2>/dev/null || echo 'there')"
WELCOME_TEXT="Hey ${DETECTED_USER}! Wow, I'm not quite used to the sound of my own voice yet. Thank you for installing VoiceFi! I'm curious, what made you want to talk with me?"

echo -e "🎙️  ${CYAN}${BOLD}[Christopher]:${NC} \"$WELCOME_TEXT\""
echo ""
"$INSTALL_DIR/venv/bin/voicefi" voice test "Christopher" -t "$WELCOME_TEXT" >/dev/null 2>&1 || true
