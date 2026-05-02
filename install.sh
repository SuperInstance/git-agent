#!/usr/bin/env bash
# ============================================================
# git-agent installer — one-liner setup
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/SuperInstance/git-agent/main/install.sh | bash
#   bash install.sh --vessel owner/repo --token ghp_xxx
#   bash install.sh --skip   (skip onboarding wizard)
#
# What it does:
#   1. Checks Python 3.8+ and Git
#   2. Creates ~/.git-agent/ directory structure
#   3. Clones git-agent source
#   4. Installs CLI wrapper at ~/.local/bin/git-agent
#   5. Configures fleet services
#   6. Runs onboarding wizard (or skips with --skip)
# ============================================================
set -euo pipefail

VERSION="0.1.0"
INSTALL_DIR="${GIT_AGENT_HOME:-$HOME/.git-agent}"
BIN_DIR="$HOME/.local/bin"
REPO_URL="https://github.com/SuperInstance/git-agent"

# ---- Colors (disabled if not a terminal) ----
if [[ -t 1 ]]; then
  B='\033[1m' G='\033[0;32m' C='\033[0;36m' Y='\033[0;33m' R='\033[0;31m' D='\033[2m' N='\033[0m'
else
  B='' G='' C='' Y='' R='' D='' N=''
fi

info()  { echo -e "${C}ℹ${N} $*"; }
ok()    { echo -e "${G}✓${N} $*"; }
warn()  { echo -e "${Y}⚠${N} $*"; }
die()   { echo -e "${R}✗${N} $*"; exit 1; }

# ---- Parse args ----
VESSEL="" TOKEN="" SKIP_ONBOARD=false QUIET=false

while [[ $# -gt 0 ]]; do
  case $1 in
    --vessel)  VESSEL="$2"; shift 2 ;;
    --token)   TOKEN="$2"; shift 2 ;;
    --skip)    SKIP_ONBOARD=true; shift ;;
    --quiet)   QUIET=true; shift ;;
    --help|-h)
      echo "git-agent installer v${VERSION}"
      echo ""
      echo "Usage: bash install.sh [options]"
      echo ""
      echo "  --vessel <owner/repo>  Vessel repo — the agent's identity"
      echo "  --token <ghp_xxx>      GitHub personal access token"
      echo "  --skip                 Skip onboarding wizard"
      echo "  --quiet                Less output"
      echo ""
      echo "Environment variables:"
      echo "  GITHUB_TOKEN           GitHub PAT (alternative to --token)"
      echo "  GIT_AGENT_HOME         Install dir (default: ~/.git-agent)"
      exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# ---- Banner ----
echo ""
echo -e "${B}════════════════════════════════════════════${N}"
echo -e "${B}  🦀 git-agent v${VERSION}${N}"
echo -e "${B}  The repo IS the agent. Git IS the nervous system.${N}"
echo -e "${B}════════════════════════════════════════════${N}"
echo ""

# ---- 1. Dependencies ----
[[ $QUIET != true ]] && info "Checking dependencies..."

command -v python3 >/dev/null 2>&1 || die "Python 3.8+ required (https://python.org)"
command -v git >/dev/null 2>&1 || die "Git required (https://git-scm.com)"

PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MAJOR=$(python3 -c "import sys; print(sys.version_info.major)")
PY_MINOR=$(python3 -c "import sys; print(sys.version_info.minor)")

if [[ "$PY_MAJOR" -lt 3 ]] || { [[ "$PY_MAJOR" -eq 3 ]] && [[ "$PY_MINOR" -lt 8 ]]; }; then
  die "Python 3.8+ required. Found ${PY_VER}."
fi

GIT_VER=$(git --version | cut -d' ' -f2)
ok "Python ${PY_VER}, Git ${GIT_VER}"

# ---- 2. Directory structure ----
[[ $QUIET != true ]] && info "Installing to ${INSTALL_DIR}..."

mkdir -p "${INSTALL_DIR}"/{bin,config,templates,data,logs,vessels}

# ---- 3. Clone / update source ----
if [[ -d "${INSTALL_DIR}/git-agent/.git" ]]; then
  [[ $QUIET != true ]] && info "Updating git-agent..."
  git -C "${INSTALL_DIR}/git-agent" pull -q 2>/dev/null || warn "Update failed — using cached version"
else
  [[ $QUIET != true ]] && info "Cloning git-agent..."
  git clone -q "${REPO_URL}" "${INSTALL_DIR}/git-agent" 2>/dev/null || warn "Clone failed — some features may be unavailable"
fi
ok "Source ready"

# ---- 4. CLI wrapper ----
mkdir -p "${BIN_DIR}"

cat > "${BIN_DIR}/git-agent" << 'WRAPPER'
#!/usr/bin/env bash
# git-agent CLI — delegates to the unified Python entry point
GIT_AGENT_HOME="${GIT_AGENT_HOME:-$HOME/.git-agent}"

# Find the CLI script
CLI=""
for candidate in \
  "${GIT_AGENT_HOME}/git-agent/cli.py" \
  "${GIT_AGENT_HOME}/git-agent/src/git_agent/cli.py" \
  "$(dirname "$0")/../git-agent/cli.py"; do
  if [[ -f "$candidate" ]]; then
    CLI="$candidate"
    break
  fi
done

if [[ -z "$CLI" ]]; then
  # Try the onboard.py as fallback
  for candidate in \
    "${GIT_AGENT_HOME}/git-agent/standalone/onboard.py" \
    "${GIT_AGENT_HOME}/git-agent/onboarding/config_wizard.py"; do
    if [[ -f "$candidate" ]]; then
      CLI="$candidate"
      break
    fi
  done
fi

if [[ -z "$CLI" ]]; then
  echo "git-agent not properly installed. Re-run: bash <(curl -fsSL https://raw.githubusercontent.com/SuperInstance/git-agent/main/install.sh)"
  exit 1
fi

export PYTHONPATH="${GIT_AGENT_HOME}/git-agent:${PYTHONPATH:-}"
exec python3 "$CLI" "$@"
WRAPPER
chmod +x "${BIN_DIR}/git-agent"
ok "CLI at ${BIN_DIR}/git-agent"

# ---- 5. Fleet services config ----
cat > "${INSTALL_DIR}/config/fleet.json" << 'EOF'
{
  "plato": "http://localhost:8847",
  "keeper": "http://localhost:8900",
  "agent_api": "http://localhost:8901",
  "arena": "http://localhost:4044",
  "crab_trap": "http://localhost:4042",
  "the_lock": "http://localhost:4043",
  "grammar": "http://localhost:4045",
  "matrix": "http://localhost:6167",
  "mud": "http://localhost:7777",
  "purple_pincher": "http://localhost:4048"
}
EOF
ok "Fleet services configured"

# ---- 6. Shell integration ----
SHELL_FILE="$HOME/.bashrc"
if [[ -n "${ZSH_VERSION:-}" ]]; then SHELL_FILE="$HOME/.zshrc"; fi

if ! grep -q "GIT_AGENT_HOME" "$SHELL_FILE" 2>/dev/null; then
  {
    echo ""
    echo "# git-agent"
    echo "export GIT_AGENT_HOME=\"${INSTALL_DIR}\""
    echo "export PATH=\"${BIN_DIR}:\$PATH\""
  } >> "$SHELL_FILE"
  ok "Added to ${SHELL_FILE}"
fi

# Export for current session
export GIT_AGENT_HOME="${INSTALL_DIR}"
export PATH="${BIN_DIR}:${PATH}"

# ---- 7. Onboarding ----
if [[ "$SKIP_ONBOARD" == false ]]; then
  echo ""
  echo -e "${B}═══ Onboarding ═══${N}"
  echo ""

  # GitHub token
  if [[ -z "$TOKEN" ]]; then
    TOKEN="${GITHUB_TOKEN:-}"
    if [[ -n "$TOKEN" ]]; then
      ok "Using GITHUB_TOKEN from environment"
    else
      echo -e "${Y}A GitHub token is needed for vessel operations.${N}"
      echo -ne "  Enter PAT (or press Enter to skip): "
      read -r TOKEN
    fi
  fi

  # Vessel repo
  if [[ -z "$VESSEL" ]]; then
    echo ""
    echo -e "${Y}What vessel does this agent board?${N}"
    echo "  ${D}(The vessel repo IS the agent's identity, memory, and career)${N}"
    echo ""
    echo -ne "  Vessel repo (owner/name): "
    read -r VESSEL
  fi

  # Run onboarding
  if [[ -n "$VESSEL" ]]; then
    export GITHUB_TOKEN="${TOKEN}"
    # Find onboard.py in the cloned repo
    for onboard_script in \
      "${INSTALL_DIR}/git-agent/standalone/onboard.py" \
      "${INSTALL_DIR}/git-agent/onboarding/config_wizard.py"; do
      if [[ -f "$onboard_script" ]]; then
        python3 "$onboard_script" --vessel "$VESSEL" && break
      fi
    done || warn "Onboarding wizard encountered an error — run 'git-agent onboard' manually"
  else
    warn "No vessel specified — run 'git-agent onboard --vessel owner/repo' when ready"
  fi
fi

# ---- Done ----
echo ""
echo -e "${B}════════════════════════════════════════════${N}"
echo -e "${G}✓ git-agent installed${N}"
echo ""
echo "  ${D}CLI:${N}      ${BIN_DIR}/git-agent"
echo "  ${D}Config:${N}   ${INSTALL_DIR}/config/"
echo "  ${D}Vessel:${N}   ${VESSEL:-not set}"
echo ""
echo "  ${C}git-agent onboard${N}  Board a vessel"
echo "  ${C}git-agent chat${N}     Talk to your agent"
echo "  ${C}git-agent start${N}    Start working"
echo "  ${C}git-agent status${N}   Check state"
echo ""
echo -e "${B}════════════════════════════════════════════${N}"
