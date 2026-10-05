#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Layer via Copy / Cut
#
# Installs the layer-via plug-in
# (assets/plug-ins/layer-via):
# Photoshop's Layer via Copy (Ctrl+J)
# and Layer via Cut (Ctrl+Shift+J) as
# Layer > Layer via Copy / Layer via Cut.
# With a selection, a new layer with only
# the selected area, in place (Cut also
# clears it from the layer); without one,
# Layer via Copy duplicates the layer.
# The keys come from the Photoshop keymap
# (features/photoshop-keymap.sh).
#
# Same plug-in as GIMPhoto's. See
# docs/LAYER_VIA.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# SUMMARY...).
########################################

FEATURE_NAME="Layer via Copy / Cut"
FEATURE_PRIORITY=55

LAYER_VIA_FILES=(layer-via.py layer_via.py)

feature_install() {
    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local src_dir="$ASSETS_DIR/plug-ins/layer-via"
    local changed=false
    local dir dest file up_to_date

    for dir in "${profiles[@]}"; do
        dest="$dir/plug-ins/layer-via"
        up_to_date=true
        for file in "${LAYER_VIA_FILES[@]}"; do
            cmp -s "$src_dir/$file" "$dest/$file" || up_to_date=false
        done
        if [[ "$up_to_date" == true ]]; then
            print_info "⏭️ $dest already installed"
            continue
        fi
        run mkdir -p "$dest"
        run install -m 755 "$src_dir/layer-via.py" "$dest/layer-via.py"
        run install -m 644 "$src_dir/layer_via.py" "$dest/layer_via.py"
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
