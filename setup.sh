#!/usr/bin/env bash

set -Eeuo pipefail
trap 'handle_error $? ${LINENO} "$BASH_COMMAND"' ERR

########################################
# GIMP Setup
#
# Installs the complete GIMP ecosystem
# (Flatpak GIMP, plug-ins, resources and
# extra features) with a single command.
#
# Every part of the ecosystem is a
# feature file in features/. This script
# only provides the shared helpers and
# runs all features in priority order.
#
# Main entry point.
########################################

# Get the directory where this script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_DIR

# Load configuration.
#
# Every configuration value also falls back to an environment variable of
# the same name, so this script can be driven by a parent setup script
# (for example, linux-mint-setup) without a local config.sh.
CONFIG_FILE="$SCRIPT_DIR/config.sh"

if [[ -f "$CONFIG_FILE" ]]; then
    # shellcheck source=/dev/null
    source "$CONFIG_FILE"
fi

readonly VERSION="0.1.0"
START_TIME=$(date +%s)
readonly START_TIME

readonly LOG_DIR="$SCRIPT_DIR/logs"
LOG_FILE="$LOG_DIR/$(date +%Y-%m-%d_%H-%M-%S).log"
readonly LOG_FILE

readonly FEATURES_DIR="$SCRIPT_DIR/features"
# Used by sourced feature files.
# shellcheck disable=SC2034
readonly ASSETS_DIR="$SCRIPT_DIR/assets"

# Priority used by feature files that do not declare FEATURE_PRIORITY.
readonly DEFAULT_FEATURE_PRIORITY=50

########################################
# Runtime options
########################################

DRY_RUN=false

# Used by sourced feature files.
# shellcheck disable=SC2034
INSTALLATION_MESSAGE=""
# shellcheck disable=SC2034
CONFIGURATION_MESSAGE=""

SUMMARY=()

########################################
# Functions
########################################

print_info() {
    echo "$@"

    if [[ -n "${LOG_FILE:-}" ]]; then
        echo "$@" >> "$LOG_FILE"
    fi
}

format_time() {
    local seconds="$1"

    printf "%02d:%02d:%02d\n" \
        $((seconds/3600)) \
        $(((seconds%3600)/60)) \
        $((seconds%60))
}

print_header() {
    echo
    echo "=========================================="
    echo "           GIMP Setup v$VERSION"
    echo "=========================================="
    echo "Mode: $([[ "$DRY_RUN" == true ]] && echo "Simulation" || echo "Installation")"
    echo
}

########################################
# Prints a section header.
#
# Arguments:
#   $1 - Section title
########################################
print_section() {
    print_info
    print_info "========================================"
    print_info "$1"
    print_info "========================================"
    print_info
}

print_help() {
    cat << EOF
GIMP Setup v$VERSION

Installs the complete GIMP ecosystem: Flatpak GIMP, plug-ins,
brushes, presets, shortcuts and AI tools. Every component is a
feature file in features/, executed in priority order.

Usage:
    ./setup.sh [options]

Options:
    --dry-run           Simulate the setup.
    --help              Show help.
    --version           Show version.

Examples:
    ./setup.sh

    ./setup.sh --dry-run
EOF
}

print_version() {
    echo "$VERSION"
}

########################################
# Prints execution summary.
########################################
print_summary() {
    local elapsed="$1"

    print_section "Summary"

    for item in "${SUMMARY[@]}"; do
        IFS="|" read -r name status <<< "$item"
        print_field "$name" "$status"
    done

    print_info

    print_field "Elapsed:" "$(format_time "$elapsed")"
}

parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --dry-run)
                DRY_RUN=true
                shift
                ;;

            --help)
                print_help
                exit 0
                ;;

            --version)
                print_version
                exit 0
                ;;

            *)
                print_info "❌ Unknown argument: $1"
                echo
                echo "Run './setup.sh --help' for usage information."
                exit 1
                ;;
        esac
    done
}

initialize_logging() {
    mkdir -p "$LOG_DIR"

    touch "$LOG_FILE"
}

write_log_header() {
    {
        echo "========================================"
        echo "GIMP Setup v$VERSION"
        echo "========================================"
        echo
        echo "Date:        $(date)"
        echo "Host:        $(hostname)"
        echo "Mode:        $([[ "$DRY_RUN" == true ]] && echo "Simulation" || echo "Installation")"
        echo
        echo "========================================"
        echo
    } >> "$LOG_FILE"
}

write_log_footer() {
    local elapsed="$1"

    {
        echo
        echo "========================================"
        echo "Finished"
        echo "========================================"
        echo
        echo "Status:      SUCCESS"
        echo "Elapsed:     $(format_time "$elapsed")"
    } >> "$LOG_FILE"
}

print_field() {
    printf "%-22s %s\n" "$1" "$2"

    if [[ -n "${LOG_FILE:-}" ]]; then
        printf "%-22s %s\n" "$1" "$2" >> "$LOG_FILE"
    fi
}

print_step() {
    print_info
    print_info "▶ $1"
    print_info
}

########################################
# Handles unexpected errors.
#
# Arguments:
#   $1 - Exit code
#   $2 - Line number
#   $3 - Command
########################################
handle_error() {
    local exit_code="$1"
    local line="$2"
    local command="$3"

    echo
    print_info "❌ Setup failed!"
    echo

    print_field "Exit code:" "$exit_code"
    print_field "Line:" "$line"
    print_field "Command:" "$command"

    if [[ -n "${LOG_FILE:-}" ]]; then
        echo
        print_info "See log:"
        print_info "  $LOG_FILE"
    fi

    exit "$exit_code"
}

########################################
# Executes a command.
#
# In dry-run mode, only prints it.
########################################
run() {
    printf -v cmd '%q ' "$@"
    print_info "➜ ${cmd% }"

    if [[ "$DRY_RUN" == false ]]; then
        "$@"
    fi
}

########################################
# Checks whether a binary exists.
#
# Arguments:
#   $1 - Binary name
########################################
binary_exists() {
    command -v "$1" >/dev/null 2>&1
}

########################################
# Checks whether a file exists.
########################################
file_exists() {
    [[ -f "$1" ]]
}

directory_exists() {
    [[ -d "$1" ]]
}

########################################
# Checks whether a command succeeds.
#
# Arguments:
#   $@ - Command to execute
########################################
command_succeeds() {
    "$@" >/dev/null 2>&1
}

########################################
# Checks whether two values match.
#
# Arguments:
#   $1 - Current value
#   $2 - Expected value
########################################
values_match() {
    [[ "$1" == "$2" ]]
}

########################################
# Checks whether GIMP is running.
#
# The process name carries the version
# (gimp-3.0, gimp-3.2, ...), so match it
# as a pattern instead of listing names.
# The Flatpak launcher is checked too:
# during startup the gimp binary has not
# been exec'ed yet, and a GIMP that
# starts while the setup runs would
# overwrite freshly written config on
# exit.
########################################
gimp_is_running() {
    pgrep -x 'gimp([-.][0-9.]+)?' >/dev/null 2>&1 ||
    pgrep -f 'flatpak run.*org\.gimp\.GIMP' >/dev/null 2>&1
}

########################################
# Lists every GIMP 3.x profile directory
# (native and Flatpak locations).
#
# Outputs one directory per line.
########################################
gimp_profile_dirs() {
    shopt -s nullglob
    local candidates=(
        "$HOME"/.config/GIMP/3.*
        "$HOME"/.var/app/org.gimp.GIMP/config/GIMP/3.*
    )
    shopt -u nullglob

    local dir
    for dir in "${candidates[@]}"; do
        [[ -d "$dir" ]] && echo "$dir"
    done
}

########################################
# Checks whether a Flatpak package
# is already installed.
#
# Arguments:
#   $1 - Flatpak ID
########################################
is_flatpak_installed() {
    flatpak info "$1" >/dev/null 2>&1
}

########################################
# Installs a Flatpak package if needed.
#
# Arguments:
#   $1 - Flatpak ID (optionally ID//branch)
#
# Returns:
#   0 - installed now
#   1 - already installed
#   2 - installation failed
########################################
install_flatpak_package() {
    local target="$1"
    local app_id="${target%%//*}"

    if is_flatpak_installed "$app_id"; then
        print_info "⏭️  $app_id already installed"
        return 1
    fi

    print_step "Installing $app_id..."

    # --noninteractive keeps flatpak from ever prompting (an ambiguous
    # ref prompts even with -y), and </dev/null keeps it from reading
    # the answer off inherited stdin — which used to swallow the
    # feature list and abort the whole setup after the first feature.
    if ! run flatpak install --noninteractive flathub "$target" < /dev/null; then
        print_info "❌ Failed to install $app_id ($target)"
        return 2
    fi

    if [[ "$DRY_RUN" == false ]]; then
        print_info "✅ $app_id installed"
    else
        print_info "🔄 Would install $app_id"
    fi

    return 0
}

########################################
# Initialization
########################################

########################################
# Checks if required commands exist.
########################################
check_dependencies() {
    print_info "Checking dependencies..."

    local dependencies=(
        curl
        unzip
        jq
        git
        flatpak
        python3
    )

    local missing=()

    for dependency in "${dependencies[@]}"; do
        if ! command -v "$dependency" >/dev/null 2>&1; then
            missing+=("$dependency")
        fi
    done

    if (( ${#missing[@]} > 0 )); then
        print_info "❌ Missing required dependencies:"
        for dependency in "${missing[@]}"; do
            print_info "  • $dependency"
        done

        echo
        print_info "Please install the missing dependencies and run the script again."
        exit 1
    fi

    print_info "✅ Dependencies OK"
    print_info
}

########################################
# Checks if there is an active
# internet connection.
########################################
check_internet_connection() {
    print_info "Checking internet connection..."

    if curl -Is https://github.com >/dev/null 2>&1; then
        print_info "✅ Connected"
    else
        print_info "❌ No internet connection."
        print_info
        print_info "Please connect to the internet and run the script again."
        exit 1
    fi

    print_info
}

########################################
# Checks that the Flathub remote is
# configured for Flatpak.
########################################
check_flathub() {
    print_info "Checking Flathub remote..."

    if flatpak remotes | grep -q flathub; then
        print_info "✅ Flathub configured"
    else
        run flatpak remote-add --if-not-exists flathub \
            https://dl.flathub.org/repo/flathub.flatpakrepo
        print_info "✅ Flathub added"
    fi

    print_info
}

initialize() {
    print_section "Initialization"

    check_dependencies

    check_internet_connection

    check_flathub
}

########################################
# Features
#
# Every features/*.sh file is a
# self-contained part of the GIMP
# ecosystem: the GIMP install itself,
# plug-ins, resources, shortcuts, menu
# options...
#
# A feature file must define:
#   FEATURE_NAME      - Display name
#   feature_install   - Function that
#                       performs the work
#
# It may also define:
#   FEATURE_PRIORITY  - Execution order
#                       (lower runs first;
#                       default 50)
#
# New features are added by dropping a
# new file into features/ — this script
# does not need to change.
########################################

########################################
# Reads the FEATURE_PRIORITY declared in
# a feature file, without sourcing it.
#
# Arguments:
#   $1 - Feature file path
########################################
feature_priority() {
    local priority

    priority="$(sed -n 's/^FEATURE_PRIORITY=\([0-9][0-9]*\).*/\1/p' "$1" | head -n 1)"

    echo "${priority:-$DEFAULT_FEATURE_PRIORITY}"
}

run_features() {
    print_section "Features"

    shopt -s nullglob
    local feature_files=("$FEATURES_DIR"/*.sh)
    shopt -u nullglob

    if (( ${#feature_files[@]} == 0 )); then
        print_info "No features found in $FEATURES_DIR"
        return
    fi

    #
    # Sort by priority (then by name for stable ties).
    #
    local ordered=()
    local feature_file

    for feature_file in "${feature_files[@]}"; do
        ordered+=("$(printf '%03d' "$(feature_priority "$feature_file")")|$feature_file")
    done

    #
    # Iterate over a pre-built array instead of piping the list into the
    # loop through stdin: a feature command that reads stdin (curl,
    # flatpak, python...) must never be able to swallow the feature list.
    #
    local sorted=()
    mapfile -t sorted < <(printf '%s\n' "${ordered[@]}" | sort)

    local entry
    for entry in "${sorted[@]}"; do
        feature_file="${entry#*|}"

        FEATURE_NAME="$(basename "$feature_file")"
        unset -f feature_install 2>/dev/null || true

        # shellcheck source=/dev/null
        source "$feature_file"

        if ! declare -F feature_install >/dev/null; then
            print_info "⏭️ $(basename "$feature_file") does not define feature_install — skipped"
            SUMMARY+=("$FEATURE_NAME|⏭️ Invalid feature")
            continue
        fi

        print_step "Feature: $FEATURE_NAME"

        feature_install
    done

    print_section "Setup complete!"
}

########################################
# Main
########################################

main() {
    parse_arguments "$@"

    # Used by sourced feature files.
    # shellcheck disable=SC2034
    if [[ "$DRY_RUN" == true ]]; then
        INSTALLATION_MESSAGE="🔄 Would install"
        CONFIGURATION_MESSAGE="🔄 Would configure"
    else
        INSTALLATION_MESSAGE="✅ Installed"
        CONFIGURATION_MESSAGE="✅ Configured"
    fi

    initialize_logging

    write_log_header

    print_header

    initialize

    run_features

    local end_time
    end_time=$(date +%s)

    local elapsed=$((end_time - START_TIME))

    print_summary "$elapsed"

    write_log_footer "$elapsed"
}

main "$@"
