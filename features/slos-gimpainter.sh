#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: SLOS-GIMPainter
#
# Installs the SLOS-GIMPainter brush,
# dynamics and tool-preset package:
#
#   https://github.com/SenlinOS/SLOS-GIMPainter
#
# The package folders are registered in
# GIMP's gimprc. Runs after PhotoGIMP so
# the resource paths stay registered.
#
# See docs/SLOS_GIMPAINTER.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, directory_exists, SUMMARY...).
########################################

FEATURE_NAME="SLOS-GIMPainter"
FEATURE_PRIORITY=40

feature_install() {
    if directory_exists "$HOME/.local/share/SLOS-GIMPainter"; then
        print_info "⏭️ SLOS-GIMPainter already installed"
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return
    fi

    local SLOS_INSTALL_DIR="$HOME/.local/share/SLOS-GIMPainter"
    local SLOS_TEMP_DIR
    SLOS_TEMP_DIR="$(mktemp -d)"
    local SLOS_GIMPRC
    SLOS_GIMPRC="$HOME/.config/GIMP/3.0/gimprc"

    run curl -fsSL https://github.com/SenlinOS/SLOS-GIMPainter/archive/refs/heads/master.zip \
    -o "$SLOS_TEMP_DIR/SLOS-GIMPainter.zip"
    run unzip -q "$SLOS_TEMP_DIR/SLOS-GIMPainter.zip" -d "$SLOS_TEMP_DIR"
    run rm -rf "$SLOS_INSTALL_DIR"
    run mv "$SLOS_TEMP_DIR/SLOS-GIMPainter-master" "$SLOS_INSTALL_DIR"
    run rm -rf "$SLOS_TEMP_DIR"

    run mkdir -p "$(dirname "$SLOS_GIMPRC")"
    run touch "$SLOS_GIMPRC"

    if ! grep -Fq "$SLOS_INSTALL_DIR" "$SLOS_GIMPRC"; then
        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Update $SLOS_GIMPRC"
        else
            {
                echo "(brush-path-writable \"$SLOS_INSTALL_DIR/brushes\")"
                echo "(pattern-path-writable \"$SLOS_INSTALL_DIR/patterns\")"
                echo "(gradient-path-writable \"$SLOS_INSTALL_DIR/gradients\")"
            } >> "$SLOS_GIMPRC"
        fi
    fi

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
