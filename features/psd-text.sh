#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: PSD with editable text
#
# Installs the psd-text plug-in
# (assets/plug-ins/psd-text): GIMP opens
# Photoshop files with their Type layers
# as editable GIMP text layers (Layer
# Styles as Text Styling filters), and
# exports GIMP text layers to PSD as
# Type layers Photoshop can still edit.
# It replaces GIMP's own PSD open/export
# for .psd files (lower priority value),
# using GIMP's own PSD support for the
# pixels and ag-psd for the text.
#
# Needs Node.js + npm on the host: ag-psd
# is installed next to the plug-in with
# `npm ci`, and the node binary path is
# saved to ~/.config/PhotoGIMP/node-path
# (the GIMP Flatpak runs it from there).
# Without Node the feature is skipped and
# GIMP keeps its own PSD support.
#
# PSD_TEXT_LANGUAGE (config.sh) is the
# Photoshop text language written for
# text layers with no language set in
# GIMP.
#
# See docs/PSD_TEXT.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, binary_exists,
# gimp_profile_dirs, SUMMARY...).
########################################

FEATURE_NAME="PSD Editable Text"
FEATURE_PRIORITY=55

PSD_TEXT_PLUGIN="psd-text"
PSD_TEXT_FILES=(psd-text.py psd_text_gimp.py psd_text_fonts.py
                psd_text_info.mjs write_psd_text.mjs package.json package-lock.json)
# The Layer Style renderer, shared: PSD effects open as Layer Styles.
PSD_TEXT_ENGINE="$ASSETS_DIR/plug-ins/layer-style/layer_style_engine.py"

########################################
# Prints the Adobe text engine code for
# PSD_TEXT_LANGUAGE (a code, or one of
# the language tags below).
########################################
psd_text_language_code() {
    local value="${PSD_TEXT_LANGUAGE:-}"
    value="${value,,}"
    value="${value//_/-}"
    case "$value" in
        ""|en|en-us) echo 0 ;;
        pt|pt-pt)    echo 10 ;;
        pt-br)       echo 11 ;;
        *[!0-9]*)
            print_info "⚠️ PSD_TEXT_LANGUAGE \"$PSD_TEXT_LANGUAGE\" unknown (use en-us, pt, pt-br or an Adobe code) — using en-us" >&2
            echo 0 ;;
        *) echo "$value" ;;
    esac
}

########################################
# Writes a setting file to the shared
# PhotoGIMP config folders (host and
# Flatpak sandbox).
#
# Arguments:
#   $1 - File name
#   $2 - Value
########################################
psd_text_write_setting() {
    local dirs=("$HOME/.config/PhotoGIMP")
    if [[ -d "$HOME/.var/app/org.gimp.GIMP" ]]; then
        dirs+=("$HOME/.var/app/org.gimp.GIMP/config/PhotoGIMP")
    fi

    local dir
    for dir in "${dirs[@]}"; do
        if [[ -f "$dir/$1" && "$(cat "$dir/$1")" == "$2" ]]; then
            continue
        fi
        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Write $dir/$1"
            continue
        fi
        mkdir -p "$dir"
        printf '%s\n' "$2" > "$dir/$1"
        print_info "Saved: $dir/$1"
    done
}

feature_install() {
    local node_bin
    node_bin="$(command -v node || true)"

    if [[ -z "$node_bin" ]] || ! binary_exists npm; then
        print_info "⏭️ Node.js/npm not found — GIMP keeps its own PSD support (text opens as pixels)."
        SUMMARY+=("$FEATURE_NAME|⏭️ Needs Node.js")
        return
    fi

    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local src_dir="$ASSETS_DIR/plug-ins/$PSD_TEXT_PLUGIN"
    local changed=false
    local dir dest file up_to_date

    for dir in "${profiles[@]}"; do
        dest="$dir/plug-ins/$PSD_TEXT_PLUGIN"

        up_to_date=true
        for file in "${PSD_TEXT_FILES[@]}"; do
            cmp -s "$src_dir/$file" "$dest/$file" 2>/dev/null || up_to_date=false
        done
        cmp -s "$PSD_TEXT_ENGINE" "$dest/layer_style_engine.py" 2>/dev/null || up_to_date=false
        [[ -d "$dest/node_modules/ag-psd" ]] || up_to_date=false

        if [[ "$up_to_date" == true ]]; then
            print_info "⏭️ $dest already installed"
            continue
        fi

        changed=true
        run mkdir -p "$dest"
        for file in "${PSD_TEXT_FILES[@]}"; do
            if [[ "$file" == psd-text.py ]]; then
                run install -m 755 "$src_dir/$file" "$dest/$file"
            else
                run install -m 644 "$src_dir/$file" "$dest/$file"
            fi
        done

        run install -m 644 "$PSD_TEXT_ENGINE" "$dest/layer_style_engine.py"

        print_info "Installing ag-psd into $dest..."
        if ! run npm ci --prefix "$dest" --omit=dev --no-audit --no-fund --loglevel=error < /dev/null; then
            print_info "❌ npm ci failed in $dest"
            SUMMARY+=("$FEATURE_NAME|❌ npm install failed")
            return
        fi

        # GIMP caches the plug-in list; make it re-scan on the next start.
        run rm -f "$dir/pluginrc"
        print_info "Installed: $dest"
    done

    psd_text_write_setting "node-path" "$node_bin"
    psd_text_write_setting "psd-text-language" "$(psd_text_language_code)"

    if [[ "$changed" == true ]]; then
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
    fi
}
