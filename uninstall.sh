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
#  fireflyframework-agentic — Interactive Uninstaller
# ══════════════════════════════════════════════════════════════════════════════

readonly VERSION="26.01.01"
readonly PACKAGE="fireflyframework-agentic"
readonly PACKAGE_IMPORT="fireflyframework_agentic"
readonly TOTAL_STEPS=4

# ── Installer state ──────────────────────────────────────────────────────────

INTERACTIVE=true
PYTHON_CMD=""
INSTALLED_VERSION=""
INSTALL_LOCATION=""
HAS_UV=false
SPINNER_PID=""

# ══════════════════════════════════════════════════════════════════════════════
#  Colors — ANSI-C quoting ($'...') produces actual escape bytes
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
#  TTY handling — critical for `curl ... | bash` piped execution
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
    printf "\n  %s⚠%s  Uninstallation cancelled.\n\n" "$YELLOW" "$RESET"
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
    printf "  %s%s%s%s %sUninstaller%s\n" "$BOLD" "$WHITE" "$PACKAGE" "$RESET" "$DIM" "$RESET"
    printf "  %sCopyright 2026 Firefly Software Solutions Inc. Apache License 2.0.%s\n" "$DIM" "$RESET"
    divider
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 1 · Detect Installation
# ══════════════════════════════════════════════════════════════════════════════

step_detect_installation() {
    step_header 1 "Detect Installation"

    # Find Python
    for cmd in python3 python; do
        if command -v "$cmd" &>/dev/null; then
            PYTHON_CMD="$cmd"
            break
        fi
    done

    if [[ -z "$PYTHON_CMD" ]]; then
        error "Python not found. Cannot detect package installation."
        exit 1
    fi
    success "Python: $("$PYTHON_CMD" --version 2>&1 | awk '{print $2}') ($PYTHON_CMD)"

    # Check if package is installed
    if INSTALLED_VERSION="$("$PYTHON_CMD" -c \
        "import ${PACKAGE_IMPORT}; print(${PACKAGE_IMPORT}.__version__)" 2>/dev/null)"; then
        success "Found: ${PACKAGE} v${INSTALLED_VERSION}"
    else
        warn "${PACKAGE} does not appear to be installed."
        exit 0
    fi

    # Detect location
    INSTALL_LOCATION="$("$PYTHON_CMD" -m pip show "$PACKAGE" 2>/dev/null \
        | grep "^Location:" | awk '{print $2}')" || true
    if [[ -n "$INSTALL_LOCATION" ]]; then
        info "Location: ${INSTALL_LOCATION}"
    fi

    # Detect UV
    if command -v uv &>/dev/null; then
        HAS_UV=true
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 2 · Confirm
# ══════════════════════════════════════════════════════════════════════════════

step_confirm() {
    step_header 2 "Confirmation"

    printf "  %sThe following will be removed:%s\n\n" "$YELLOW" "$RESET"
    printf "    %s•%s  %s v%s\n" "$WHITE" "$RESET" "$PACKAGE" "$INSTALLED_VERSION"
    if [[ -n "$INSTALL_LOCATION" ]]; then
        printf "       %sLocation: %s%s\n" "$DIM" "$INSTALL_LOCATION" "$RESET"
    fi
    printf "\n"

    if ! prompt_yn "Proceed with uninstallation?"; then
        info "Uninstallation cancelled."
        exit 0
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 3 · Remove & Cleanup
# ══════════════════════════════════════════════════════════════════════════════

step_remove() {
    step_header 3 "Remove & Cleanup"

    # ── Uninstall package ─────────────────────────────────────────────────
    if [[ "$HAS_UV" == true ]]; then
        spinner_start "Removing ${PACKAGE} via UV..."
        if uv pip uninstall "$PACKAGE" &>/dev/null 2>&1; then
            spinner_stop "ok" "Removed ${PACKAGE} via UV"
        else
            spinner_stop "fail" "UV removal failed — trying pip"
            spinner_start "Removing ${PACKAGE} via pip..."
            if "$PYTHON_CMD" -m pip uninstall -y "$PACKAGE" &>/dev/null 2>&1; then
                spinner_stop "ok" "Removed ${PACKAGE} via pip"
            else
                spinner_stop "fail" "Could not remove ${PACKAGE}"
                error "Please try: ${PYTHON_CMD} -m pip uninstall ${PACKAGE}"
                exit 1
            fi
        fi
    else
        spinner_start "Removing ${PACKAGE} via pip..."
        if "$PYTHON_CMD" -m pip uninstall -y "$PACKAGE" &>/dev/null 2>&1; then
            spinner_stop "ok" "Removed ${PACKAGE} via pip"
        else
            spinner_stop "fail" "Could not remove ${PACKAGE}"
            error "Please try: ${PYTHON_CMD} -m pip uninstall ${PACKAGE}"
            exit 1
        fi
    fi

    # ── Clean source directory ────────────────────────────────────────────
    if [[ -d "${PACKAGE}" ]]; then
        printf "\n"
        if prompt_yn "Remove local source directory '${PACKAGE}/'?" "n"; then
            spinner_start "Removing source directory..."
            rm -rf "${PACKAGE}"
            spinner_stop "ok" "Source directory removed"
        else
            info "Keeping source directory"
        fi
    fi

    # ── Clean pip cache ───────────────────────────────────────────────────
    printf "\n"
    if prompt_yn "Remove cached package files?" "n"; then
        spinner_start "Cleaning pip cache..."
        "$PYTHON_CMD" -m pip cache purge &>/dev/null 2>&1 || true
        spinner_stop "ok" "Cache cleaned"
    else
        info "Skipping cache cleanup"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Step 4 · Verify
# ══════════════════════════════════════════════════════════════════════════════

step_verify() {
    step_header 4 "Verification"

    spinner_start "Verifying removal..."
    if "$PYTHON_CMD" -c "import ${PACKAGE_IMPORT}" &>/dev/null 2>&1; then
        spinner_stop "fail" "Package is still importable — removal may be incomplete"
        warn "Try: ${PYTHON_CMD} -m pip uninstall ${PACKAGE}"
    else
        spinner_stop "ok" "Package successfully removed"
    fi
}

# ══════════════════════════════════════════════════════════════════════════════
#  Summary
# ══════════════════════════════════════════════════════════════════════════════

print_farewell() {
    divider
    print_box "${PACKAGE} has been uninstalled."

    info "Thank you for using ${PACKAGE}!"
    printf "\n"
    printf "  %sReinstall anytime:%s\n" "$DIM" "$RESET"
    printf "  curl -fsSL https://raw.githubusercontent.com/fireflyframework/fireflyframework-agentic/main/install.sh | bash\n"
    printf "\n"
    printf "  %sRepository:%s  https://github.com/fireflyframework/fireflyframework-agentic\n\n" "$DIM" "$RESET"
}

# ══════════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════════

main() {
    setup_colors
    setup_tty

    banner

    step_detect_installation
    step_confirm
    step_remove
    step_verify

    print_farewell
}

main "$@"
