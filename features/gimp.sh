#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: GIMP (Flatpak)
#
# Installs GIMP from Flathub together
# with its Flathub plug-ins:
#
#   - G'MIC-Qt
#   - Resynthesizer
#
# The plug-in branches follow the
# installed GIMP branch automatically.
#
# See docs/GIMP.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, install_flatpak_package,
# SUMMARY...).
########################################

FEATURE_NAME="GIMP (Flatpak)"
FEATURE_PRIORITY=10

feature_install() {
    local changed=false

    local GIMP_BRANCH="3"

    install_flatpak_package org.gimp.GIMP && changed=true

    if [[ "$DRY_RUN" == false ]] && is_flatpak_installed org.gimp.GIMP; then
        GIMP_BRANCH="$(flatpak info org.gimp.GIMP | sed -n 's/^Branch:[[:space:]]*//p')"
    fi

    install_flatpak_package "org.gimp.GIMP.Plugin.GMic//$GIMP_BRANCH" && changed=true
    install_flatpak_package "org.gimp.GIMP.Plugin.Resynthesizer//$GIMP_BRANCH" && changed=true

    if $changed; then
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
    fi
}
