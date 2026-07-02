#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: PhotoGIMP
#
# Installs PhotoGIMP 3.0, which applies a
# Photoshop-inspired interface and
# configuration to Flatpak GIMP:
#
#   https://github.com/Diolinux/PhotoGIMP
#
# An existing GIMP 3.0 configuration is
# backed up to a timestamped folder in
# the home directory first.
#
# See docs/PHOTOGIMP.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, file_exists, SUMMARY...).
########################################

FEATURE_NAME="PhotoGIMP"
FEATURE_PRIORITY=30

feature_install() {
    local PHOTOGIMP_VERSION="3.0"
    local PHOTOGIMP_MARKER="$HOME/.config/GIMP/.photogimp-installed"
    local PHOTOGIMP_CONFIG_DIR="$HOME/.config/GIMP/3.0"
    local PHOTOGIMP_TEMP_DIR
    PHOTOGIMP_TEMP_DIR="$(mktemp -d)"

    if file_exists "$PHOTOGIMP_MARKER"; then
        print_info "⏭️ PhotoGIMP already installed"
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return
    fi

    if [[ -d "$PHOTOGIMP_CONFIG_DIR" ]]; then
        local PHOTOGIMP_BACKUP_DIR
        PHOTOGIMP_BACKUP_DIR="$HOME/GIMP-3.0-backup-$(date +%Y%m%d_%H%M%S)"

        run cp -a "$PHOTOGIMP_CONFIG_DIR" "$PHOTOGIMP_BACKUP_DIR"

        print_info "Existing GIMP 3.0 configuration backed up to $PHOTOGIMP_BACKUP_DIR"
    fi

    run curl -fsSL \
        "https://github.com/Diolinux/PhotoGIMP/releases/download/3.0/PhotoGIMP-linux.zip" \
        -o "$PHOTOGIMP_TEMP_DIR/PhotoGIMP-linux.zip"

    run unzip -q \
        "$PHOTOGIMP_TEMP_DIR/PhotoGIMP-linux.zip" \
        -d "$PHOTOGIMP_TEMP_DIR/photogimp"

    run cp -a "$PHOTOGIMP_TEMP_DIR/photogimp/." "$HOME/"

    run mkdir -p "$(dirname "$PHOTOGIMP_MARKER")"

    run bash -c "echo '$PHOTOGIMP_VERSION' > '$PHOTOGIMP_MARKER'"

    run rm -rf "$PHOTOGIMP_TEMP_DIR"

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
