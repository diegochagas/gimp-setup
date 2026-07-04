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
# Flathub publishes the plug-ins under
# GIMP's major version as the branch
# ("3"), not under GIMP's own branch
# name ("stable"), so the branch is
# derived from GIMP's version number.
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

########################################
# Prints the Flathub branch used by the
# GIMP plug-in packages: the installed
# GIMP's major version, falling back
# to "3".
#
# LC_ALL=C keeps `flatpak info` output
# in English — field names are localized
# otherwise (e.g. "Ramo:" in pt_BR),
# which used to break the parsing and
# produce an empty branch.
########################################
gimp_plugin_branch() {
    local version=""

    if is_flatpak_installed org.gimp.GIMP; then
        version="$(LC_ALL=C flatpak info org.gimp.GIMP 2>/dev/null |
            sed -n 's/^[[:space:]]*Version:[[:space:]]*//p' | head -n 1)"
    fi

    if [[ "$version" =~ ^([0-9]+)\. ]]; then
        echo "${BASH_REMATCH[1]}"
    else
        echo "3"
    fi
}

feature_install() {
    local changed=false
    local failed=false
    local rc

    rc=0
    install_flatpak_package org.gimp.GIMP || rc=$?
    (( rc == 0 )) && changed=true
    (( rc == 2 )) && failed=true

    local plugin_branch
    plugin_branch="$(gimp_plugin_branch)"

    rc=0
    install_flatpak_package "org.gimp.GIMP.Plugin.GMic//$plugin_branch" || rc=$?
    (( rc == 0 )) && changed=true
    (( rc == 2 )) && failed=true

    rc=0
    install_flatpak_package "org.gimp.GIMP.Plugin.Resynthesizer//$plugin_branch" || rc=$?
    (( rc == 0 )) && changed=true
    (( rc == 2 )) && failed=true

    if $failed; then
        SUMMARY+=("$FEATURE_NAME|❌ Failed (see log)")
    elif $changed; then
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
    fi
}
