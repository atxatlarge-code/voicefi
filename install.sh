#!/usr/bin/env bash
# ==============================================================================
#  VoiceFi™ (vifi) — Universal Voice Layer for AI Agents, MCP, and macOS
#  Install Script for https://vifi.sh / https://voicefi.org
# ==============================================================================
set -e

# ANSI Colors (POSIX compliant printf)
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
GREEN='\033[0;32m'
RED='\033[0;31m'
BOLD='\033[1m'
NC='\033[0m'

say_msg() {
    printf "%b\n" "$*"
}

say_msg ""
say_msg "${CYAN}${BOLD}"
say_msg "        _  __ _ "
say_msg " __   _(_)/ _(_)"
say_msg " \\ \\ / / | |_| |"
say_msg "  \\ V /| |  _| |"
say_msg "   \\_/ |_|_| |_|   ${PURPLE}VoiceFi™${CYAN} (vifi.sh)${NC}"
say_msg ""
say_msg "Website: ${CYAN}https://voicefi.org${NC} · Docs: ${CYAN}https://vifi.sh${NC}"
say_msg "------------------------------------------------------------------"

# 1. OS Check
OS="$(uname -s)"
if [ "$OS" != "Darwin" ]; then
    say_msg "${RED}❌ VoiceFi is currently optimized for macOS (Darwin). Found: $OS${NC}"
    exit 1
fi

ARCH="$(uname -m)"
say_msg "${GREEN}✓${NC} Detected macOS ($ARCH)"

# 2. Directory Setup
INSTALL_DIR="$HOME/.voicefi"
BIN_DIR="$HOME/.local/bin"
mkdir -p "$INSTALL_DIR"
mkdir -p "$BIN_DIR"

# 3. Python 3.10+ / uv Check & Bootstrapping
HAS_GOOD_PYTHON=0
if command -v python3 >/dev/null 2>&1; then
    PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo '0.0')"
    PY_MAJOR="$(echo "$PY_VER" | cut -d. -f1)"
    PY_MINOR="$(echo "$PY_VER" | cut -d. -f2)"
    if [ "$PY_MAJOR" -ge 3 ] 2>/dev/null && [ "$PY_MINOR" -ge 10 ] 2>/dev/null; then
        HAS_GOOD_PYTHON=1
        say_msg "${GREEN}✓${NC} Python $PY_VER detected"
    fi
fi

# Locate or install Astral uv (provides standalone pre-built Python 3.12 with zero developer tools)
UV_BIN=""
if command -v uv >/dev/null 2>&1; then
    UV_BIN="$(command -v uv)"
elif [ -f "$HOME/.local/bin/uv" ]; then
    UV_BIN="$HOME/.local/bin/uv"
elif [ -f "$HOME/.cargo/bin/uv" ]; then
    UV_BIN="$HOME/.cargo/bin/uv"
fi

if [ -z "$UV_BIN" ]; then
    if [ "$HAS_GOOD_PYTHON" -eq 0 ]; then
        say_msg "${CYAN}⚡ System Python is < 3.10. Setting up fast, self-contained Python 3.12 via uv...${NC}"
    fi
    # Install uv standalone binary
    curl -LsSf https://astral.sh/uv/install.sh | sh >/dev/null 2>&1 || true
    if [ -f "$HOME/.local/bin/uv" ]; then
        UV_BIN="$HOME/.local/bin/uv"
    elif [ -f "$HOME/.cargo/bin/uv" ]; then
        UV_BIN="$HOME/.cargo/bin/uv"
    fi
fi

# Ensure local bin is on path for this installer session
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

say_msg "${CYAN}⚡ Setting up VoiceFi virtual environment in $INSTALL_DIR...${NC}"

if [ -n "$UV_BIN" ]; then
    # uv automatically manages standalone Python 3.12 if system Python is outdated or missing
    "$UV_BIN" venv "$INSTALL_DIR/venv" --python 3.12 --seed --allow-existing >/dev/null 2>&1 || \
    "$UV_BIN" venv "$INSTALL_DIR/venv" --python 3.12 --seed >/dev/null 2>&1 || \
    "$UV_BIN" venv "$INSTALL_DIR/venv" --seed --allow-existing >/dev/null 2>&1
    PIP_EXEC="$UV_BIN pip install --python $INSTALL_DIR/venv/bin/python"
else
    if [ "$HAS_GOOD_PYTHON" -eq 0 ]; then
        say_msg "${RED}❌ Python 3.10+ is required and uv could not be bootstrapped automatically.${NC}"
        say_msg "Please install Python 3.10+ via Homebrew: brew install python"
        exit 1
    fi
    if [ ! -f "$INSTALL_DIR/venv/bin/python" ] || [ ! -f "$INSTALL_DIR/venv/bin/pip" ]; then
        rm -rf "$INSTALL_DIR/venv"
        python3 -m venv "$INSTALL_DIR/venv"
        "$INSTALL_DIR/venv/bin/python" -m ensurepip --upgrade >/dev/null 2>&1 || true
    fi
    PIP_EXEC="$INSTALL_DIR/venv/bin/pip install"
fi

# If executing from within a cloned repo, install in editable mode
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || echo "")"
if [ -n "$SCRIPT_DIR" ] && [ -f "$SCRIPT_DIR/pyproject.toml" ]; then
    say_msg "${CYAN}⚡ Installing local repository ($SCRIPT_DIR)...${NC}"
    $PIP_EXEC --quiet -e "$SCRIPT_DIR"
else
    say_msg "${CYAN}⚡ Installing latest VoiceFi release from voicefi.org...${NC}"
    $PIP_EXEC --quiet git+https://github.com/atxatlarge-code/voicefi.git || $PIP_EXEC --quiet voicefi
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
say_msg "${CYAN}⚡ Configuring Agent lifecycle hooks (Antigravity & Claude Code)...${NC}"
"$INSTALL_DIR/venv/bin/voicefi" setup >/dev/null 2>&1 || true

# 6. Enable Persistent Menu Bar Companion & Dynamic Island HUD (autostart daemon)
say_msg "${CYAN}⚡ Enabling VoiceFi Menu Bar Companion & Persistent Dynamic Island HUD (autostart)...${NC}"
"$INSTALL_DIR/venv/bin/voicefi" autostart >/dev/null 2>&1 || true

# 7. Check for Obsidian and prompt user interactively
if [ -d "$HOME/Library/Application Support/obsidian" ] || [ -d "$HOME/Documents/Obsidian Vault" ]; then
    INSTALL_OBSIDIAN="y"
    if [ -t 0 ] && [ -r /dev/tty ]; then
        say_msg ""
        say_msg "${PURPLE}📓 Detected Obsidian on your Mac.${NC}"
        read -r -p "👉 Install VoiceFi Obsidian voice bridge plugin? [Y/n]: " user_obsidian_choice 2>/dev/null < /dev/tty || user_obsidian_choice="y"
        if [[ "$user_obsidian_choice" =~ ^[Nn] ]]; then
            INSTALL_OBSIDIAN="n"
        fi
    fi

    if [ "$INSTALL_OBSIDIAN" = "y" ]; then
        say_msg "${CYAN}⚡ Installing VoiceFi plugin to Obsidian vaults...${NC}"
        "$INSTALL_DIR/venv/bin/voicefi" obsidian install --all >/dev/null 2>&1 || true
    else
        say_msg "💡 Skipped Obsidian install. You can install it anytime with: ${CYAN}vifi obsidian install${NC}"
    fi
fi

# 8. Check PATH
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
    say_msg ""
    say_msg "${PURPLE}⚠️  Notice: $BIN_DIR is not in your current PATH.${NC}"
    say_msg "Add it to your shell configuration (~/.zshrc or ~/.bashrc):"
    say_msg "  ${BOLD}export PATH=\"\$HOME/.local/bin:\$PATH\"${NC}"
fi

say_msg ""
say_msg "${GREEN}${BOLD}🎉 VoiceFi Installation Complete!${NC}"
say_msg "------------------------------------------------------------------"
say_msg "🗣️  ${BOLD}Claude Code & Antigravity:${NC} Hands-free conversational voice turns active"
say_msg "💻  ${BOLD}Cursor & macOS:${NC}            Universal ${CYAN}${BOLD}<Ctrl>+T${NC} dictation into any text box"
say_msg "📓 ${BOLD}Obsidian:${NC}                Auto-configured across local vaults"
say_msg "🔊 ${BOLD}Test Voice:${NC}              Run ${CYAN}${BOLD}vifi voice test${NC} (or ${CYAN}${BOLD}vg voice test${NC})"
say_msg "👂 ${BOLD}Hearing Test:${NC}            Run ${CYAN}${BOLD}vifi hearing-test${NC}"
say_msg "🔄 ${BOLD}Feedback Loop:${NC}           Run ${CYAN}${BOLD}vifi feedback-loop${NC}"
say_msg "🎛️  ${BOLD}Control Panel:${NC}           Run ${CYAN}${BOLD}vifi panel${NC} (http://localhost:8765)"
say_msg "📖 ${BOLD}Commands:${NC}                Run ${CYAN}${BOLD}vifi --help${NC}"
say_msg "------------------------------------------------------------------"
say_msg ""

# 9. Play interactive welcome greeting with auto-detected user name
echo -e "${CYAN}⚡ Launching VoiceFi Onboarding...${NC}"
"$INSTALL_DIR/venv/bin/voicefi" onboarding || true
