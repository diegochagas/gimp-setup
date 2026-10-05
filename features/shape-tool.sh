#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Shape Tool
#
# Installs the shape-tool plug-in
# (assets/plug-ins/shape-tool):
# Photoshop's shape tools (U) - Rectangle,
# Ellipse, Triangle, Polygon, Line and
# Custom Shape - as GIMP 3.2 vector
# layers, from Tools > Shape Tool... or
# U (bound by features/photoshop-keymap.sh).
#
# GIMP older than 3.2 has no vector
# layers: the plug-in then registers
# nothing.
#
# See docs/SHAPE_TOOL.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# SUMMARY...).
########################################

FEATURE_NAME="Shape Tool"
FEATURE_PRIORITY=55

feature_install() {
    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local src_dir="$ASSETS_DIR/plug-ins/shape-tool"
    local changed=false
    local dir dest

    for dir in "${profiles[@]}"; do
        dest="$dir/plug-ins/shape-tool"
        if cmp -s "$src_dir/shape-tool.py" "$dest/shape-tool.py" &&
           cmp -s "$src_dir/shape_geometry.py" "$dest/shape_geometry.py"; then
            print_info "⏭️ $dest already installed"
            continue
        fi
        run mkdir -p "$dest"
        run install -m 755 "$src_dir/shape-tool.py" "$dest/shape-tool.py"
        run install -m 644 "$src_dir/shape_geometry.py" "$dest/shape_geometry.py"
        # GIMP caches the plug-in list; make it re-scan on the next start.
        run rm -f "$dir/pluginrc"
        print_info "Installed: $dest"
        changed=true
    done

    if [[ "$changed" == true ]]; then
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
    fi
}
