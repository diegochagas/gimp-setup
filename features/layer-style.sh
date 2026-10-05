#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Layer Style
#
# Installs the layer-style plug-in
# (assets/plug-ins/layer-style):
# Photoshop's Layer Style dialog (fx) as
# Layer > Layer Style > Blending
# Options... / Drop Shadow... / Stroke...
# / ... and Copy / Paste / Clear Layer
# Style. Effects are non-destructive
# filters built from GEGL operations GIMP
# and the LinuxBeaver plug-ins
# (features/linuxbeaver.sh) provide.
#
# See docs/LAYER_STYLE.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# SUMMARY...).
########################################

FEATURE_NAME="Layer Style"
FEATURE_PRIORITY=55

LAYER_STYLE_FILES=(layer-style.py layer_style_engine.py)

feature_install() {
    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local src_dir="$ASSETS_DIR/plug-ins/layer-style"
    local changed=false
    local dir dest file up_to_date

    for dir in "${profiles[@]}"; do
        dest="$dir/plug-ins/layer-style"
        up_to_date=true
        for file in "${LAYER_STYLE_FILES[@]}"; do
            cmp -s "$src_dir/$file" "$dest/$file" || up_to_date=false
        done
        if [[ "$up_to_date" == true ]]; then
            print_info "⏭️ $dest already installed"
            continue
        fi
        run mkdir -p "$dest"
        run install -m 755 "$src_dir/layer-style.py" "$dest/layer-style.py"
        run install -m 644 "$src_dir/layer_style_engine.py" "$dest/layer_style_engine.py"
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
