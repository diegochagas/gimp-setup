#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Smart Objects
#
# Installs the smart-objects plug-in
# (assets/plug-ins/smart-objects):
# Layer > Smart Object > Convert to Smart
# Object / Edit Contents / Replace
# Contents, Photoshop's Smart Object
# workflow on top of GIMP 3.2's link
# layers (non-destructive transforms, an
# edited contents file updates every
# layer that shows it).
#
# GIMP older than 3.2 has no link layers:
# the plug-in then registers nothing.
#
# See docs/SMART_OBJECTS.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# SUMMARY...).
########################################

FEATURE_NAME="Smart Objects"
FEATURE_PRIORITY=55

feature_install() {
    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local src="$ASSETS_DIR/plug-ins/smart-objects/smart-objects.py"
    local changed=false
    local dir dest

    for dir in "${profiles[@]}"; do
        dest="$dir/plug-ins/smart-objects/smart-objects.py"
        if cmp -s "$src" "$dest"; then
            print_info "⏭️ ${dest%/*} already installed"
            continue
        fi
        run mkdir -p "${dest%/*}"
        run install -m 755 "$src" "$dest"
        # GIMP caches the plug-in list; make it re-scan on the next start.
        run rm -f "$dir/pluginrc"
        print_info "Installed: ${dest%/*}"
        changed=true
    done

    if [[ "$changed" == true ]]; then
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
    fi
}
