#!/usr/bin/env bash
# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

set -euo pipefail

# ══════════════════════════════════════════════════════════════════════════════
#  fireflyframework-agentic — Interactive Installer
# ══════════════════════════════════════════════════════════════════════════════

readonly VERSION="26.01.01"
readonly PACKAGE="fireflyframework-agentic"
readonly PACKAGE_IMPORT="fireflyframework_agentic"
readonly REPO_URL="https://github.com/fireflyframework/fireflyframework-agentic.git"
readonly MIN_PYTHON_MAJOR=3
readonly MIN_PYTHON_MINOR=13
readonly TOTAL_STEPS=6

# ── Installer state ──────────────────────────────────────────────────────────

INTERACTIVE=true
PYTHON_CMD=""
PYTHON_VER=""
HAS_UV=false
HAS_GIT=false
EXTRAS=""
USE_VENV=false
VENV_DIR=""
CLONE_DIR=""
OS=""
ARCH=""
SPINNER_PID=""

# ══════════════════════════════════════════════════════════════════════════════
#  Colors — ANSI-C quoting ($'...') produces actual escape bytes so they
#  render correctly everywhere: printf format strings, %s args, and echo.
# ══════════════════════════════════════════════════════════════════════════════

setup_colors() {
    if [[ -t 1 ]]; then
        RED=$'\e[0;31m'
        GREEN=$'\e[0;32m'
        YELLOW=$'\e[1;33m'
        BLUE=$'\e[0;34m'
        MAGENTA=$'\e[0;35m'
        CYAN=$'\e[0;36m'
        WHITE=$'\e[1;37m'
        DIM=$'\e[2m'
        BOLD=$'\e[1m'
        RESET=$'\e[0m'
    else
        RED='' GREEN='' YELLOW='' BLUE='' MAGENTA='' CYAN=''
        WHITE='' DIM='' BOLD='' RESET=''
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  TTY handling — critical for `curl ... | bash` piped execution.
#  When piped, stdin is the curl stream. We reopen stdin from /dev/tty so
#  that `read` prompts go to the real terminal. This is safe because bash
#  has already parsed the entire script before calling main().
# ══════════════════════════════════════════════════════════════════════════════

setup_tty() {
    if [[ ! -t 0 ]]; then
        if [[ -e /dev/tty ]]; then
            exec < /dev/tty
        else
            INTERACTIVE=false
        fi
    fi
}

# ── Cleanup ──────────────────────────────────────────────────────────────────

cleanup() {
    if [[ -n "${SPINNER_PID:-}" ]]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    tput cnorm 2>/dev/null || true
    printf "\n  %s⚠%s  Installation cancelled.\n\n" "$YELLOW" "$RESET"
    exit 130
}
trap cleanup SIGINT SIGTERM

# ══════════════════════════════════════════════════════════════════════════════
#  Output helpers
# ══════════════════════════════════════════════════════════════════════════════

info()    { printf "  %sℹ%s  %s\n" "$BLUE" "$RESET" "$*"; }
success() { printf "  %s✔%s  %s\n" "$GREEN" "$RESET" "$*"; }
warn()    { printf "  %s⚠%s  %s\n" "$YELLOW" "$RESET" "$*"; }
error()   { printf "  %s✖%s  %s\n" "$RED" "$RESET" "$*"; }

step_header() {
    local num="$1" title="$2"
    printf "\n  %s━━━ Step %d/%d · %s ━━━%s\n\n" \
        "${BOLD}${CYAN}" "$num" "$TOTAL_STEPS" "$title" "$RESET"
}

divider() {
    printf "\n  %s════════════════════════════════════════════════════════════%s\n" \
        "$DIM" "$RESET"
}

# ── Dynamic box ──────────────────────────────────────────────────────────────

print_box() {
    local text="$1"
    local len=${#text}
    local inner=$(( len + 4 ))
    local border=""
    for ((i = 0; i < inner; i++)); do border+="═"; done
    printf "\n"
    printf "  %s╔%s╗%s\n" "$GREEN" "$border" "$RESET"
    printf "  %s║%s  %s%s%s%s  %s║%s\n" \
        "$GREEN" "$RESET" "$BOLD" "$WHITE" "$text" "$RESET" "$GREEN" "$RESET"
    printf "  %s╚%s╝%s\n" "$GREEN" "$border" "$RESET"
    printf "\n"
}

# ══════════════════════════════════════════════════════════════════════════════
#  Prompts
# ══════════════════════════════════════════════════════════════════════════════

prompt_yn() {
    local message="$1" default="${2:-y}"
    if [[ "$INTERACTIVE" == false ]]; then
        [[ "$default" == "y" ]] && return 0 || return 1
    fi
    local hint
    if [[ "$default" == "y" ]]; then
        hint="${DIM}[Y/n]${RESET}"
    else
        hint="${DIM}[y/N]${RESET}"
    fi
    printf "  %s?%s  %s %s " "$CYAN" "$RESET" "$message" "$hint"
    local answer
    read -r answer
    answer="${answer:-$default}"
    [[ "$answer" =~ ^[Yy] ]]
}

prompt_input() {
    local message="$1" default="${2:-}"
    if [[ "$INTERACTIVE" == false ]]; then
        echo "$default"
        return
    fi
    if [[ -n "$default" ]]; then
        printf "  %s?%s  %s %s(%s)%s: " "$CYAN" "$RESET" "$message" "$DIM" "$default" "$RESET" >&2
    else
        printf "  %s?%s  %s: " "$CYAN" "$RESET" "$message" >&2
    fi
    local answer
    read -r answer
    echo "${answer:-$default}"
}

# ══════════════════════════════════════════════════════════════════════════════
#  Path expansion — `read -r` captures literal text; we must expand common
#  shell shortcuts ($HOME, ${HOME}, ~) so paths resolve correctly.
# ══════════════════════════════════════════════════════════════════════════════

expand_path() {
    local path="$1"
    # Expand leading ~/ or standalone ~
    if [[ "$path" == "~/"* ]]; then
        path="${HOME}${path#"~"}"
    elif [[ "$path" == "~" ]]; then
        path="$HOME"
    fi
    # Expand $HOME and ${HOME} anywhere in the string
    path="${path//\$HOME/$HOME}"
    path="${path//\$\{HOME\}/$HOME}"
    # Resolve to absolute path
    if [[ "$path" != /* ]]; then
        path="$(pwd)/$path"
    fi
    echo "$path"
}

prompt_choice() {
    local message="$1"
    shift
    local options=("$@")
    if [[ "$INTERACTIVE" == false ]]; then
        echo "1"
        return
    fi
    printf "  %s?%s  %s\n\n" "$CYAN" "$RESET" "$message" >&2
    for i in "${!options[@]}"; do
        printf "     %s%d)%s  %s\n" "$WHITE" "$((i + 1))" "$RESET" "${options[$i]}" >&2
    done
    printf "\n  %s❯%s  Enter choice %s[1]%s: " "$CYAN" "$RESET" "$DIM" "$RESET" >&2
    local choice
    read -r choice
    choice="${choice:-1}"
    if ! [[ "$choice" =~ ^[0-9]+$ ]] || (( choice < 1 || choice > ${#options[@]} )); then
        choice=1
    fi
    echo "$choice"
}

# ══════════════════════════════════════════════════════════════════════════════
#  Spinner
# ══════════════════════════════════════════════════════════════════════════════

spinner_start() {
    local message="$1"
    local frames=("⠋" "⠙" "⠹" "⠸" "⠼" "⠴" "⠦" "⠧" "⠇" "⠏")
    tput civis 2>/dev/null || true
    (
        local i=0
        while true; do
            printf "\r  %s%s%s  %s" "$CYAN" "${frames[$i]}" "$RESET" "$message"
            i=$(( (i + 1) % ${#frames[@]} ))
            sleep 0.08
        done
    ) &
    SPINNER_PID=$!
}

spinner_stop() {
    local status="$1" message="$2"
    if [[ -n "${SPINNER_PID:-}" ]]; then
        kill "$SPINNER_PID" 2>/dev/null || true
        wait "$SPINNER_PID" 2>/dev/null || true
        SPINNER_PID=""
    fi
    tput cnorm 2>/dev/null || true
    printf "\r  %-78s\r" ""
    if [[ "$status" == "ok" ]]; then
        success "$message"
    else
        error "$message"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Banner
# ══════════════════════════════════════════════════════════════════════════════

banner() {
    printf "%s" "$CYAN"
    cat << 'EOF'

  _____.__                _____.__
_/ ____\__|______   _____/ ____\  | ___.__.
\   __\|  \_  __ \_/ __ \   __\|  |<   |  |
 |  |  |  ||  | \/\  ___/|  |  |  |_\___  |
 |__|  |__||__|    \___  >__|  |____/ ____|
                       \/           \/
  _____                                                 __     /\
_/ ____\___________    _____   ______  _  _____________|  | __ \ \
\   __\_  __ \__  \  /     \_/ __ \ \/ \/ /  _ \_  __ \  |/ /  \ \
 |  |   |  | \// __ \|  Y Y  \  ___/\     (  <_> )  | \/    <    \ \
 |__|   |__|  (____  /__|_|  /\___  >\/\_/ \____/|__|  |__|_ \    \ \
                   \/      \/     \/                        \/     \/
  ________                  _____  .__
 /  _____/  ____   ____    /  _  \ |__|
/   \  ____/ __ \ /    \  /  /_\  \|  |
\    \_\  \  ___/|   |  \/    |    \  |
 \______  /\___  >___|  /\____|__  /__|
        \/     \/     \/         \/

EOF
    printf "%s" "$RESET"
    printf "  %s%s%s%s %sv%s%s\n" "$BOLD" "$WHITE" "$PACKAGE" "$RESET" "$DIM" "$VERSION" "$RESET"
    printf "  %sThe production-grade GenAI metaframework built on Pydantic AI%s\n" "$DIM" "$RESET"
    printf "  %sCopyright 2026 Firefly Software Solutions Inc. Apache License 2.0.%s\n" "$DIM" "$RESET"
    divider
}

# ══════════════════════════════════════════════════════════════════════════════
#  System detection
# ══════════════════════════════════════════════════════════════════════════════

detect_os() {
    case "$(uname -s)" in
        Linux*)  echo "linux" ;;
        Darwin*) echo "macos" ;;
        *)       echo "unknown" ;;
    esac
}

detect_arch() {
    case "$(uname -m)" in
        x86_64|amd64)  echo "x86_64" ;;
        arm64|aarch64) echo "arm64" ;;
        *)             echo "$(uname -m)" ;;
    esac
}

# ══════════════════════════════════════════════════════════════════════════════
#  Python discovery — scans PATH for all interpreters >= 3.13
# ══════════════════════════════════════════════════════════════════════════════

find_all_pythons() {
    local seen_versions=""

    # Versioned executables first: python3.13, python3.14, ...
    for ((minor = MIN_PYTHON_MINOR; minor <= 20; minor++)); do
        local cmd="python3.${minor}"
        command -v "$cmd" &>/dev/null || continue

        local full_path ver
        full_path="$(command -v "$cmd")"
        ver="$("$cmd" --version 2>&1 | awk '{print $2}')" || continue

        if [[ "$seen_versions" != *"|${ver}|"* ]]; then
            seen_versions+="|${ver}|"
            printf "%s|%s|%s\n" "$cmd" "$ver" "$full_path"
        fi
    done

    # Generic python3 / python
    for cmd in python3 python; do
        command -v "$cmd" &>/dev/null || continue

        local full_path ver major_v minor_v
        full_path="$(command -v "$cmd")"
        ver="$("$cmd" --version 2>&1 | awk '{print $2}')" || continue
        major_v="$(echo "$ver" | cut -d. -f1)"
        minor_v="$(echo "$ver" | cut -d. -f2)"

        # Skip if below minimum
        if [[ "$major_v" -lt "$MIN_PYTHON_MAJOR" ]]; then continue; fi
        if [[ "$major_v" -eq "$MIN_PYTHON_MAJOR" ]] && \
           [[ "$minor_v" -lt "$MIN_PYTHON_MINOR" ]]; then continue; fi

        if [[ "$seen_versions" != *"|${ver}|"* ]]; then
            seen_versions+="|${ver}|"
            printf "%s|%s|%s\n" "$cmd" "$ver" "$full_path"
        fi
    done
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 1 · Platform Detection
# ══════════════════════════════════════════════════════════════════════════════

step_detect_platform() {
    step_header 1 "Platform Detection"

    OS="$(detect_os)"
    ARCH="$(detect_arch)"

    if [[ "$OS" == "unknown" ]]; then
        error "Unsupported operating system: $(uname -s)"
        error "This installer supports Linux and macOS."
        error "For Windows, use install.ps1 instead."
        exit 1
    fi

    success "Operating system : ${OS}"
    success "Architecture     : ${ARCH}"
    success "Shell            : ${SHELL##*/} (PID $$)"
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 2 · Python Interpreter Selection
# ══════════════════════════════════════════════════════════════════════════════

step_select_python() {
    step_header 2 "Python Interpreter"

    info "Scanning for Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ installations..."
    printf "\n"

    local pythons_raw
    pythons_raw="$(find_all_pythons)"

    if [[ -z "$pythons_raw" ]]; then
        error "No Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ interpreter found."
        printf "\n"
        info "Install Python ${MIN_PYTHON_MAJOR}.${MIN_PYTHON_MINOR}+ from:"
        printf "\n"
        printf "     %shttps://www.python.org/downloads/%s\n" "$CYAN" "$RESET"
        printf "\n"
        info "Or via package manager:"
        printf "\n"
        printf "     macOS:   %sbrew install python@3.13%s\n" "$WHITE" "$RESET"
        printf "     Ubuntu:  %ssudo apt install python3.13%s\n" "$WHITE" "$RESET"
        printf "     Fedora:  %ssudo dnf install python3.13%s\n" "$WHITE" "$RESET"
        printf "\n"
        exit 1
    fi

    # Parse into arrays
    local cmds=() vers=() paths=()
    while IFS='|' read -r cmd ver path; do
        cmds+=("$cmd")
        vers+=("$ver")
        paths+=("$path")
    done <<< "$pythons_raw"

    local count=${#cmds[@]}

    if [[ "$count" -eq 1 ]]; then
        PYTHON_CMD="${cmds[0]}"
        PYTHON_VER="${vers[0]}"
        success "Found: Python ${PYTHON_VER} (${paths[0]})"
    else
        info "Found ${count} compatible Python installations:"
        printf "\n"

        local options=()
        for i in "${!cmds[@]}"; do
            options+=("Python ${vers[$i]}  ${DIM}→ ${paths[$i]}${RESET}")
        done

        local choice
        choice="$(prompt_choice "Which Python do you want to use?" "${options[@]}")"
        local idx=$(( choice - 1 ))

        PYTHON_CMD="${cmds[$idx]}"
        PYTHON_VER="${vers[$idx]}"
        printf "\n"
        success "Selected: Python ${PYTHON_VER} (${paths[$idx]})"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 3 · Package Manager & Tools
# ══════════════════════════════════════════════════════════════════════════════

step_check_tools() {
    step_header 3 "Package Manager & Tools"

    # ── UV ────────────────────────────────────────────────────────────────
    if command -v uv &>/dev/null; then
        local uv_ver
        uv_ver="$(uv --version 2>&1 | awk '{print $2}')"
        success "UV ${uv_ver}"
        HAS_UV=true
    else
        warn "UV not found"
        if prompt_yn "Install UV? (recommended — much faster than pip)"; then
            spinner_start "Installing UV..."
            if curl -LsSf https://astral.sh/uv/install.sh 2>/dev/null | sh &>/dev/null 2>&1; then
                export PATH="$HOME/.local/bin:$PATH"
                local uv_ver
                uv_ver="$(uv --version 2>&1 | awk '{print $2}')"
                spinner_stop "ok" "UV ${uv_ver} installed"
                HAS_UV=true
            else
                spinner_stop "fail" "UV installation failed"
                info "Continuing with pip instead"
            fi
        else
            info "Using pip for installation"
        fi
    fi

    # ── Git ───────────────────────────────────────────────────────────────
    if command -v git &>/dev/null; then
        local git_ver
        git_ver="$(git --version | awk '{print $3}')"
        success "Git ${git_ver}"
        HAS_GIT=true
    else
        warn "Git not found (needed only for source installation)"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 4 · Extras Selection
# ══════════════════════════════════════════════════════════════════════════════

step_select_extras() {
    step_header 4 "Extras Selection"

    info "Optional components add REST API and message queue support."
    printf "\n"

    local options=(
        "Core only      ${DIM}— no optional dependencies${RESET}"
        "REST API       ${DIM}— FastAPI + Uvicorn + SSE streaming${RESET}"
        "Kafka          ${DIM}— aiokafka (Apache Kafka)${RESET}"
        "RabbitMQ       ${DIM}— aio-pika (AMQP)${RESET}"
        "Redis          ${DIM}— redis-py (Pub/Sub)${RESET}"
        "All queues     ${DIM}— Kafka + RabbitMQ + Redis${RESET}"
        "Everything     ${DIM}— REST + all queues + costs${RESET}"
    )

    local choice
    choice="$(prompt_choice "Select a configuration:" "${options[@]}")"

    case "$choice" in
        2) EXTRAS="rest" ;;
        3) EXTRAS="kafka" ;;
        4) EXTRAS="rabbitmq" ;;
        5) EXTRAS="redis" ;;
        6) EXTRAS="queues" ;;
        7) EXTRAS="all" ;;
        *) EXTRAS="" ;;
    esac

    printf "\n"
    if [[ -n "$EXTRAS" ]]; then
        success "Extras: ${EXTRAS}"
    else
        success "Extras: core only (no optional dependencies)"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 5 · Environment Setup
# ══════════════════════════════════════════════════════════════════════════════

step_configure_environment() {
    step_header 5 "Environment Setup"

    # ── Clone directory ───────────────────────────────────────────────────
    info "Choose where to clone the repository."
    printf "\n"
    CLONE_DIR="$(prompt_input "Clone directory" "${HOME}/${PACKAGE}")"
    CLONE_DIR="$(expand_path "$CLONE_DIR")"
    printf "\n"
    success "Clone target: ${CLONE_DIR}"
    printf "\n"

    if prompt_yn "Create a virtual environment inside the clone?"; then
        USE_VENV=true
        VENV_DIR="${CLONE_DIR}/.venv"
        success "Virtual environment: ${VENV_DIR}"
    else
        info "Using current Python environment"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 6 · Review & Install
# ══════════════════════════════════════════════════════════════════════════════

step_review_and_install() {
    step_header 6 "Review & Install"

    printf "  %s%sInstallation Summary:%s\n\n" "$BOLD" "$WHITE" "$RESET"
    printf "    %sPlatform     :%s  %s (%s)\n"  "$DIM" "$RESET" "$OS" "$ARCH"
    printf "    %sPython       :%s  %s (%s)\n"  "$DIM" "$RESET" "$PYTHON_VER" "$PYTHON_CMD"
    printf "    %sPkg manager  :%s  %s\n"       "$DIM" "$RESET" "$( [[ "$HAS_UV" == true ]] && echo "UV" || echo "pip" )"
    printf "    %sExtras       :%s  %s\n"       "$DIM" "$RESET" "${EXTRAS:-core only}"
    if [[ -n "$VENV_DIR" ]]; then
        printf "    %sEnvironment  :%s  %s\n"   "$DIM" "$RESET" "$VENV_DIR"
    else
        printf "    %sEnvironment  :%s  current\n" "$DIM" "$RESET"
    fi
    if [[ -n "$CLONE_DIR" ]]; then
        printf "    %sClone dir    :%s  %s\n"   "$DIM" "$RESET" "$CLONE_DIR"
    fi

    printf "\n"

    if ! prompt_yn "Proceed with installation?"; then
        info "Installation cancelled."
        exit 0
    fi

    printf "\n"

    # ── Install ───────────────────────────────────────────────────────────
    do_install_source

    # ── Verify ────────────────────────────────────────────────────────────
    do_verify
}

# ══════════════════════════════════════════════════════════════════════════════
#  Installation routines
# ══════════════════════════════════════════════════════════════════════════════

do_install_source() {
    # ── Clone ─────────────────────────────────────────────────────────────
    if [[ -d "$CLONE_DIR" ]]; then
        warn "Directory '${CLONE_DIR}' already exists."
        if prompt_yn "Remove and re-clone?" "n"; then
            rm -rf "$CLONE_DIR"
        else
            info "Using existing directory"
        fi
    fi

    if [[ ! -d "$CLONE_DIR" ]]; then
        spinner_start "Cloning ${REPO_URL}..."
        if git clone "$REPO_URL" "$CLONE_DIR" &>/dev/null 2>&1; then
            spinner_stop "ok" "Repository cloned to ${CLONE_DIR}"
        else
            spinner_stop "fail" "Clone failed"
            error "Could not clone ${REPO_URL}"
            exit 1
        fi
    fi

    # ── Create virtual environment (after clone so directory exists) ───────
    if [[ "$USE_VENV" == true ]] && [[ -n "$VENV_DIR" ]]; then
        spinner_start "Creating virtual environment at ${VENV_DIR}..."
        if [[ "$HAS_UV" == true ]]; then
            if uv venv "$VENV_DIR" --python "$PYTHON_CMD" &>/dev/null 2>&1; then
                spinner_stop "ok" "Virtual environment created: ${VENV_DIR}"
            else
                spinner_stop "fail" "uv venv failed — trying python -m venv"
                spinner_start "Creating virtual environment via python..."
                "$PYTHON_CMD" -m venv "$VENV_DIR" &>/dev/null 2>&1
                spinner_stop "ok" "Virtual environment created: ${VENV_DIR}"
            fi
        else
            "$PYTHON_CMD" -m venv "$VENV_DIR" &>/dev/null 2>&1
            spinner_stop "ok" "Virtual environment created: ${VENV_DIR}"
        fi
        # Activate
        # shellcheck disable=SC1091
        source "${VENV_DIR}/bin/activate" 2>/dev/null || true
    fi

    # ── Install dependencies ──────────────────────────────────────────────
    if [[ "$HAS_UV" == true ]]; then
        local uv_args="sync"
        if [[ -z "$EXTRAS" ]]; then
            uv_args="sync"
        elif [[ "$EXTRAS" == "all" ]]; then
            uv_args="sync --all-extras"
        else
            # Map comma-separated extras to --extra flags
            IFS=',' read -ra extra_arr <<< "$EXTRAS"
            for extra in "${extra_arr[@]}"; do
                uv_args+=" --extra ${extra}"
            done
        fi
        spinner_start "Installing dependencies (uv ${uv_args})..."
        if (cd "$CLONE_DIR" && uv $uv_args) &>/dev/null 2>&1; then
            spinner_stop "ok" "Dependencies installed via UV"
        else
            spinner_stop "fail" "uv sync failed"
            exit 1
        fi
    else
        local pip_spec="."
        [[ -n "$EXTRAS" ]] && pip_spec=".[${EXTRAS}]"
        spinner_start "Installing dependencies (pip install -e)..."
        if (cd "$CLONE_DIR" && "$PYTHON_CMD" -m pip install -e "$pip_spec") &>/dev/null 2>&1; then
            spinner_stop "ok" "Dependencies installed via pip"
        else
            spinner_stop "fail" "pip install failed"
            exit 1
        fi
    fi
}

do_verify() {
    printf "\n"
    spinner_start "Verifying installation..."

    local verify_cmd="$PYTHON_CMD"
    # Prefer the venv python if available
    if [[ -n "$VENV_DIR" ]] && [[ -x "${VENV_DIR}/bin/python" ]]; then
        verify_cmd="${VENV_DIR}/bin/python"
    fi
    # Check inside the clone
    if [[ -n "$CLONE_DIR" ]]; then
        if [[ -x "${CLONE_DIR}/.venv/bin/python" ]]; then
            verify_cmd="${CLONE_DIR}/.venv/bin/python"
        fi
    fi

    local installed_ver
    if installed_ver="$("$verify_cmd" -c \
        "import ${PACKAGE_IMPORT}; print(${PACKAGE_IMPORT}.__version__)" 2>/dev/null)"; then
        spinner_stop "ok" "${PACKAGE} v${installed_ver} verified successfully"
    else
        spinner_stop "fail" "Package import failed"
        warn "The package was installed but could not be imported in the current shell."
        if [[ -n "$VENV_DIR" ]]; then
            info "Activate your environment first:"
            printf "\n     %ssource %s/bin/activate%s\n\n" "$WHITE" "$VENV_DIR" "$RESET"
        fi
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Summary
# ══════════════════════════════════════════════════════════════════════════════

print_summary() {
    divider
    print_box "${PACKAGE} v${VERSION} installed successfully!"

    printf "  %s%sGet Started:%s\n\n" "$BOLD" "$WHITE" "$RESET"

    local step_num=1

    if [[ -n "$VENV_DIR" ]]; then
        printf "  %s# %d. Activate your environment%s\n" "$DIM" "$step_num" "$RESET"
        printf "  source %s/bin/activate\n\n" "$VENV_DIR"
        step_num=$((step_num + 1))
    fi

    printf "  %s# %d. Configure your model provider%s\n" "$DIM" "$step_num" "$RESET"
    printf "  export OPENAI_API_KEY=sk-...\n"
    printf "  export FIREFLY_AGENTIC_DEFAULT_MODEL=openai:gpt-4o\n\n"
    step_num=$((step_num + 1))

    printf "  %s# %d. Create your first agent%s\n" "$DIM" "$step_num" "$RESET"
    printf "  from fireflyframework_agentic.agents import firefly_agent\n\n"
    printf "  @firefly_agent(name=\"assistant\", model=\"openai:gpt-4o\")\n"
    printf "  def instructions(ctx):\n"
    printf "      return \"You are a helpful assistant.\"\n\n"

    printf "  %s%sResources:%s\n\n" "$BOLD" "$WHITE" "$RESET"
    printf "  %sDocs      :%s  https://github.com/fireflyframework/fireflyframework-agentic/tree/main/docs\n" "$DIM" "$RESET"
    printf "  %sTutorial  :%s  https://github.com/fireflyframework/fireflyframework-agentic/blob/main/docs/tutorial.md\n" "$DIM" "$RESET"
    printf "  %sRepository:%s  https://github.com/fireflyframework/fireflyframework-agentic\n\n" "$DIM" "$RESET"
}

# ══════════════════════════════════════════════════════════════════════════════
#  Main — all function definitions are parsed before this line executes,
#  making exec < /dev/tty in setup_tty() safe for piped execution.
# ══════════════════════════════════════════════════════════════════════════════

main() {
    setup_colors
    setup_tty

    banner

    step_detect_platform
    step_select_python
    step_check_tools
    step_select_extras
    step_configure_environment
    step_review_and_install

    print_summary

    # Ensure terminal is clean before exit
    tput cnorm 2>/dev/null || true
    exit 0
}

main "$@"
exit 0
