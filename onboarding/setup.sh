#!/bin/bash
# ==========================================================================
# One-command bootstrap for git-agent
# ==========================================================================
# Usage:
#   curl -sL https://raw.githubusercontent.com/SuperInstance/git-agent/main/onboarding/setup.sh | bash
#
# Or locally:
#   bash onboarding/setup.sh
#
# This script will:
#   1. Check Python 3.11+ is installed
#   2. Create a virtual environment
#   3. Install dependencies
#   4. Run the interactive config wizard
#   5. Validate GitHub PAT
#   6. Validate LLM API key (or proxy URL)
#   7. Clone vessel repo (if configured)
#   8. Run self-tests
#   9. Print success message with next steps
# ==========================================================================

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# ---- Helper functions ----

info()  { echo -e "${BLUE}[INFO]${NC}  $*"; }
ok()    { echo -e "${GREEN}[OK]${NC}    $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC}  $*"; }
fail()  { echo -e "${RED}[FAIL]${NC}  $*"; }

# ---- Detect script location ----

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# If running from curl, we need to clone first
if [ ! -f "$PROJECT_DIR/pyproject.toml" ]; then
    info "pyproject.toml not found — cloning git-agent repository..."
    PROJECT_DIR="/tmp/git-agent"
    git clone https://github.com/SuperInstance/git-agent.git "$PROJECT_DIR" 2>/dev/null || {
        fail "Failed to clone git-agent. Check your internet connection."
        exit 1
    }
    cd "$PROJECT_DIR"
fi

cd "$PROJECT_DIR"

echo ""
echo -e "${CYAN}============================================================${NC}"
echo -e "${CYAN}  git-agent Bootstrap — One-Command Setup${NC}"
echo -e "${CYAN}============================================================${NC}"
echo ""

# ---- Step 1: Check Python version ----

info "Checking Python version..."

if command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    fail "Python 3 is not installed. Please install Python 3.11 or later."
    info "  Ubuntu/Debian: sudo apt install python3.11 python3.11-venv"
    info "  macOS:         brew install python@3.11"
    info "  Windows:       winget install Python.Python.3.11"
    exit 1
fi

PY_VERSION=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [ "$PY_MAJOR" -lt 3 ] || { [ "$PY_MAJOR" -eq 3 ] && [ "$PY_MINOR" -lt 11 ]; }; then
    fail "Python 3.11+ is required. Found Python $PY_VERSION."
    info "  Please upgrade Python to 3.11 or later."
    exit 1
fi

ok "Python $PY_VERSION detected."

# ---- Step 2: Create virtual environment ----

VENV_DIR="$PROJECT_DIR/.venv"

if [ ! -d "$VENV_DIR" ]; then
    info "Creating virtual environment at $VENV_DIR..."
    $PYTHON -m venv "$VENV_DIR" || {
        fail "Failed to create virtual environment."
        info "  You may need to install python3-venv:"
        info "  Ubuntu/Debian: sudo apt install python3.11-venv"
        exit 1
    }
    ok "Virtual environment created."
else
    ok "Virtual environment already exists."
fi

# Activate venv
source "$VENV_DIR/bin/activate"

# ---- Step 3: Install dependencies ----

info "Installing dependencies (pip install -e '.[all]')..."

if pip install -e ".[all]" 2>&1 | tail -5; then
    ok "Dependencies installed successfully."
else
    warn "Trying without extras (pip install -e '.')..."
    pip install -e "." || {
        fail "Failed to install dependencies."
        exit 1
    }
    ok "Basic dependencies installed (some extras may be missing)."
fi

# ---- Step 4: Run interactive config wizard ----

echo ""
info "Launching interactive configuration wizard..."
echo ""

if [ -f "$PROJECT_DIR/onboarding/config_wizard.py" ]; then
    $PYTHON "$PROJECT_DIR/onboarding/config_wizard.py" || {
        warn "Config wizard exited with an error. You can re-run it later:"
        warn "  python onboarding/config_wizard.py"
    }
else
    warn "Config wizard not found. Skipping."
    warn "  You can configure manually by creating ~/.git-agent/config.yaml"
fi

# ---- Step 5: Validate configuration ----

CONFIG_PATH="$HOME/.git-agent/config.yaml"

if [ -f "$CONFIG_PATH" ]; then
    echo ""
    info "Validating configuration..."

    # Validate GitHub PAT
    GITHUB_TOKEN=$(python3 -c "
import yaml, sys
with open('$CONFIG_PATH') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('github_token', ''))
" 2>/dev/null || echo "")

    if [ -n "$GITHUB_TOKEN" ] && [ "$GITHUB_TOKEN" != "YOUR_TOKEN_HERE" ]; then
        info "Validating GitHub PAT..."
        HTTP_STATUS=$(curl -s -o /dev/null -w "%{http_code}" \
            -H "Authorization: token $GITHUB_TOKEN" \
            https://api.github.com/user 2>/dev/null || echo "000")

        if [ "$HTTP_STATUS" = "200" ]; then
            GH_USER=$(curl -s -H "Authorization: token $GITHUB_TOKEN" \
                https://api.github.com/user 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('login','unknown'))" 2>/dev/null || echo "unknown")
            ok "GitHub PAT valid (authenticated as @$GH_USER)."
        else
            warn "GitHub PAT returned HTTP $HTTP_STATUS. Check your token."
        fi
    else
        warn "No GitHub PAT configured. Set 'github_token' in $CONFIG_PATH."
    fi

    # Validate LLM connection
    LLM_PROVIDER=$(python3 -c "
import yaml, sys
with open('$CONFIG_PATH') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('llm_provider', ''))
" 2>/dev/null || echo "")

    if [ -n "$LLM_PROVIDER" ]; then
        info "LLM provider: $LLM_PROVIDER configured."
    fi
else
    warn "No configuration file found at $CONFIG_PATH."
    warn "  Run the config wizard: python onboarding/config_wizard.py"
fi

# ---- Step 6: Clone vessel repo ----

VESSEL_REPO=$(python3 -c "
import yaml, sys
with open('$CONFIG_PATH') as f:
    cfg = yaml.safe_load(f)
print(cfg.get('vessel_repo', ''))
" 2>/dev/null || echo "")

if [ -n "$VESSEL_REPO" ]; then
    VESSEL_PATH="$PROJECT_DIR/vessel"
    if [ ! -d "$VESSEL_PATH/.git" ]; then
        info "Cloning vessel repo ($VESSEL_REPO)..."
        if git clone "https://github.com/$VESSEL_REPO.git" "$VESSEL_PATH" 2>/dev/null; then
            ok "Vessel repo cloned to $VESSEL_PATH."
        else
            warn "Could not clone vessel repo. It may not exist yet — you can create it later."
        fi
    else
        ok "Vessel repo already exists at $VESSEL_PATH."
    fi
fi

# ---- Step 7: Run self-tests ----

echo ""
info "Running self-tests..."

if pytest tests/ -v --tb=short 2>&1 | tail -20; then
    ok "All self-tests passed."
else
    warn "Some tests failed. Check the output above for details."
fi

# ---- Success ----

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  git-agent Setup Complete!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo -e "  ${CYAN}Project directory:${NC}  $PROJECT_DIR"
echo -e "  ${CYAN}Virtual environment:${NC}  $VENV_DIR"
echo -e "  ${CYAN}Configuration:${NC}  $CONFIG_PATH"
echo ""
echo -e "  ${YELLOW}Next steps:${NC}"
echo ""
echo "    1. Activate the environment:"
echo "       source $VENV_DIR/bin/activate"
echo ""
echo "    2. Review your config:"
echo "       cat $CONFIG_PATH"
echo ""
echo "    3. Run the agent:"
echo "       python -m git_agent"
echo ""
echo -e "  ${YELLOW}Useful commands:${NC}"
echo ""
echo "    python onboarding/config_wizard.py  # Reconfigure"
echo "    pytest tests/ -v                     # Run tests"
echo "    pip install -e '.[dev]'             # Dev dependencies"
echo ""
echo -e "  ${CYAN}Welcome to the FLUX Fleet. The repo IS the agent.${NC}"
echo ""
