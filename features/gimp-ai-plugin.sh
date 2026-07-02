#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: GIMP AI Plugin
#
# Installs the GIMP AI Plugin by lukaso
# (OpenAI-powered Inpainting, Image
# Generator and Layer Composite):
#
#   https://github.com/lukaso/gimp-ai
#
# The GIMP version subfolder is detected
# automatically, preferring the latest
# stable even-numbered release.
#
# See docs/GIMP_AI_PLUGIN.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, file_exists, SUMMARY...).
########################################

FEATURE_NAME="GIMP AI Plugin"
FEATURE_PRIORITY=60

feature_install() {
    local GIMP_AI_DETECTED_VERSION=""

    #
    # Detect the newest stable GIMP configuration (3.0, 3.2, 3.4, ...)
    #
    GIMP_AI_DETECTED_VERSION="$(
        flatpak run --command=bash org.gimp.GIMP -c \
            "ls ~/.config/GIMP/ 2>/dev/null" 2>/dev/null |
        tr ' ' '\n' |
        sort -V -r |
        while IFS= read -r ver; do
            minor=$(echo "$ver" | cut -d. -f2)

            if [[ -n "$minor" ]] && (( minor % 2 == 0 )); then
                echo "$ver"
                break
            fi
        done
    )"

    #
    # Already installed?
    #
    if [[ -n "$GIMP_AI_DETECTED_VERSION" ]] &&
       file_exists "$HOME/.config/GIMP/$GIMP_AI_DETECTED_VERSION/plug-ins/gimp-ai-plugin/gimp-ai-plugin.py"
    then
        print_info "⏭️ GIMP AI Plugin already installed"
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return
    fi

    #
    # Fallback to the newest available config if no stable version was found.
    #
    if [[ -z "$GIMP_AI_DETECTED_VERSION" ]]; then
        GIMP_AI_DETECTED_VERSION="$(
            flatpak run --command=bash org.gimp.GIMP -c \
                "ls ~/.config/GIMP/ 2>/dev/null" 2>/dev/null |
            tr ' ' '\n' |
            sort -V |
            tail -1
        )"
    fi

    #
    # GIMP has never been started.
    #
    if [[ -z "$GIMP_AI_DETECTED_VERSION" ]]; then
        print_info "GIMP config directory not found — open GIMP once after setup, then re-run to install the GIMP AI Plugin."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local GIMP_AI_PLUGIN_DIR="$HOME/.config/GIMP/$GIMP_AI_DETECTED_VERSION/plug-ins/gimp-ai-plugin"
    local GIMP_AI_TEMP_DIR
    GIMP_AI_TEMP_DIR="$(mktemp -d)"

    local GIMP_AI_TAG
    GIMP_AI_TAG="$(
        curl -fsSL https://api.github.com/repos/lukaso/gimp-ai/releases/latest |
        jq -r '.tag_name'
    )"

    local GIMP_AI_ZIP_URL
    GIMP_AI_ZIP_URL="https://github.com/lukaso/gimp-ai/releases/download/${GIMP_AI_TAG}/gimp-ai-plugin-${GIMP_AI_TAG}.zip"

    run curl -fsSL "$GIMP_AI_ZIP_URL" \
        -o "$GIMP_AI_TEMP_DIR/gimp-ai-plugin.zip"

    run unzip -q \
        "$GIMP_AI_TEMP_DIR/gimp-ai-plugin.zip" \
        -d "$GIMP_AI_TEMP_DIR/extracted"

    run mkdir -p "$GIMP_AI_PLUGIN_DIR"

    run find "$GIMP_AI_TEMP_DIR/extracted" \
        -name "gimp-ai-plugin.py" \
        -exec cp {} "$GIMP_AI_PLUGIN_DIR/" \;

    run find "$GIMP_AI_TEMP_DIR/extracted" \
        -name "coordinate_utils.py" \
        -exec cp {} "$GIMP_AI_PLUGIN_DIR/" \;

    run chmod +x "$GIMP_AI_PLUGIN_DIR/gimp-ai-plugin.py"
    run chmod +x "$GIMP_AI_PLUGIN_DIR/coordinate_utils.py"

    run find "$HOME/.var/app/org.gimp.GIMP/" -name pluginrc -delete
    run find "$HOME/.config/GIMP/" -name pluginrc -delete

    run rm -rf "$GIMP_AI_TEMP_DIR"

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
