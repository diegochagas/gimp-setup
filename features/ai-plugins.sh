#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: AI Plug-ins
#
# Installs the five AI plug-ins as one
# feature, plus their shared settings:
#
#   WithoutBG
#     Tools > WithoutBG > Remove Background
#     Cuts out the subject: adds the
#     alpha matte as an unapplied layer
#     mask. Vendored patched copy of
#     withoutbg/withoutbg-gimp targeting
#     the server in WITHOUTBG_SERVER_URL
#     — see assets/vendor/withoutbg/PATCHES.md.
#     No key needed.
#
#   Generative Fill (GIMP AI Plugin)
#     Filters > AI > Generative Fill
#     Fills the selection from a text
#     prompt (plus Image Generator).
#     Vendored patched copy of
#     lukaso/gimp-ai — see
#     assets/vendor/gimp-ai-plugin/PATCHES.md.
#     Fully local: FLUX.2 klein or
#     Qwen-Image-Edit through ComfyUI.
#
#   AI Remove Selection
#     Filters > AI > Remove Selection (AI)
#     Photoshop-style Remove tool:
#     select (or Quick Mask paint) an
#     object and it is removed. Fully
#     local: FLUX.2 klein or
#     Qwen-Image-Edit through ComfyUI.
#
#   AI Restore Photo
#     Filters > AI > Restore Photo (AI)
#     Repairs a scanned photo print:
#     blotches, stains, scratches (or
#     chemical burns) are repainted by
#     a local model, kept only where
#     the print was damaged, as a new
#     layer with an editable mask.
#
#   AI Object Selection
#     Select > Object Selection (AI) and
#     Select > Subject (AI): Photoshop's
#     Object Selection with SAM 2.1
#     through ComfyUI.
#
#   ComfyUI client
#     assets/plug-ins/comfyui/comfyui_client.py
#     is installed next to the three
#     ComfyUI plug-ins above; the ComfyUI server itself is
#     installed by linux-mint-setup (steps/comfyui), and
#     gimp-setup's own ComfyUI node by features/comfyui-nodes.sh.
#
#   Shared settings
#     WITHOUTBG_SERVER_URL / COMFYUI_URL
#     from config.sh
#     are written to ~/.config/PhotoGIMP/
#     on the host AND inside the GIMP
#     Flatpak sandbox
#     (~/.var/app/org.gimp.GIMP/config/),
#     so the plug-ins find them in both
#     worlds.
#
#   Online providers removed
#     Earlier versions also offered
#     OpenAI, Google Gemini and Stable
#     Diffusion WebUI; the API keys they
#     saved are removed again (see
#     ai_remove_online_settings).
#
# See docs/AI_PLUGINS.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# file_exists, SUMMARY...).
########################################

FEATURE_NAME="AI Plug-ins"
FEATURE_PRIORITY=60

# Profiles are resolved once in feature_install.
AI_PROFILES=()

# ComfyUI client module, installed next to every plug-in that imports it.
AI_COMFYUI_CLIENT="$ASSETS_DIR/plug-ins/comfyui/comfyui_client.py"

########################################
# Copies plug-in files into every GIMP
# 3.x profile, skipping up-to-date ones
# and removing an obsolete plug-in dir
# the new one replaces (if given).
#
# Arguments:
#   $1 - Plug-in directory name
#   $2 - Obsolete directory name ("" for none)
#   $@ - Source files
#
# Returns:
#   0 - something was (re)installed
#   1 - everything already up to date
########################################
ai_install_plugin() {
    local plugin_name="$1"
    local obsolete_name="$2"
    shift 2
    local sources=("$@")

    local changed=false
    local dir dest src

    for dir in "${AI_PROFILES[@]}"; do
        dest="$dir/plug-ins/$plugin_name"

        if [[ -n "$obsolete_name" && -d "$dir/plug-ins/$obsolete_name" ]]; then
            run rm -rf "$dir/plug-ins/$obsolete_name"
            print_info "Removed obsolete: $dir/plug-ins/$obsolete_name"
            changed=true
        fi

        local up_to_date=true
        for src in "${sources[@]}"; do
            if ! cmp -s "$src" "$dest/$(basename "$src")" 2>/dev/null; then
                up_to_date=false
                break
            fi
        done

        if [[ "$up_to_date" == true ]]; then
            print_info "⏭️ $dest already installed"
            continue
        fi

        changed=true
        run mkdir -p "$dest"
        for src in "${sources[@]}"; do
            run install -m 755 "$src" "$dest/$(basename "$src")"
        done
        print_info "Installed: $dest"
    done

    if [[ "$changed" == true ]]; then
        return 0
    fi
    return 1
}

########################################
# Forces GIMP to re-scan plug-ins on the
# next start by removing the pluginrc
# caches.
########################################
ai_refresh_pluginrc() {
    local dir
    for dir in "${AI_PROFILES[@]}"; do
        if [[ -f "$dir/pluginrc" ]]; then
            run rm -f "$dir/pluginrc"
        fi
    done
}

########################################
# Writes a shared setting (server URL)
# to the shared config files
# on the host and inside the GIMP Flatpak
# sandbox.
#
# Arguments:
#   $1 - File name (e.g. comfyui-url)
#   $2 - Value
#
# Returns:
#   0 - a file was written
#   1 - all files already up to date
########################################
ai_write_shared_key() {
    local name="$1"
    local value="$2"

    local key_dirs=("$HOME/.config/PhotoGIMP")
    if [[ -d "$HOME/.var/app/org.gimp.GIMP" ]]; then
        key_dirs+=("$HOME/.var/app/org.gimp.GIMP/config/PhotoGIMP")
    fi

    local changed=false
    local dir key_file

    for dir in "${key_dirs[@]}"; do
        key_file="$dir/$name"

        if file_exists "$key_file" && values_match "$(cat "$key_file")" "$value"; then
            continue
        fi

        changed=true

        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Write $key_file"
            continue
        fi

        mkdir -p "$dir"
        printf '%s\n' "$value" > "$key_file"
        chmod 600 "$key_file"
        print_info "Saved: $key_file"
    done

    if [[ "$changed" == true ]]; then
        return 0
    fi
    return 1
}

########################################
# WithoutBG: background removal via the
# self-hosted WithoutBG server. Vendored
# patched copy of withoutbg/withoutbg-gimp
# (see assets/vendor/withoutbg/PATCHES.md).
# Replaces the old rembg-based AI Remove
# Background plug-in.
########################################
ai_install_withoutbg() {
    local src="$ASSETS_DIR/vendor/withoutbg/withoutbg.py"

    if ! file_exists "$src"; then
        print_info "❌ Vendored plug-in file not found: $src"
        SUMMARY+=("WithoutBG|❌ Missing assets")
        return
    fi

    print_step "Installing WithoutBG (background removal)..."

    # Replaces the old rembg-based plug-in.
    local rc=0
    ai_install_plugin "withoutbg" "ai-remove-background-g3" "$src" || rc=$?

    if (( rc == 0 )); then
        ai_refresh_pluginrc
        SUMMARY+=("WithoutBG|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("WithoutBG|⏭️ Already installed")
    fi
}

########################################
# Generative Fill: the vendored patched
# GIMP AI Plugin (lukaso/gimp-ai +
# multi-provider support).
########################################
ai_install_generative_fill() {
    local vendor_dir="$ASSETS_DIR/vendor/gimp-ai-plugin"
    local sources=(
        "$vendor_dir/gimp-ai-plugin.py"
        "$vendor_dir/coordinate_utils.py"
        "$vendor_dir/ai_providers.py"
        "$AI_COMFYUI_CLIENT"
    )

    local src
    for src in "${sources[@]}"; do
        if ! file_exists "$src"; then
            print_info "❌ Vendored plug-in file not found: $src"
            SUMMARY+=("Generative Fill|❌ Missing assets")
            return
        fi
    done

    print_step "Installing Generative Fill (GIMP AI Plugin)..."

    local rc=0
    ai_install_plugin "gimp-ai-plugin" "" "${sources[@]}" || rc=$?

    if (( rc == 0 )); then
        ai_refresh_pluginrc
        SUMMARY+=("Generative Fill|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("Generative Fill|⏭️ Already installed")
    fi
}

########################################
# AI Remove Selection: the PhotoGIMP
# Photoshop-style Remove tool.
########################################
ai_install_remove_selection() {
    local sources=(
        "$ASSETS_DIR/plug-ins/ai-remove-selection/ai-remove-selection.py"
        "$AI_COMFYUI_CLIENT"
    )

    local src
    for src in "${sources[@]}"; do
        if ! file_exists "$src"; then
            print_info "❌ Plug-in source not found at $src"
            SUMMARY+=("AI Remove Selection|❌ Missing assets")
            return
        fi
    done

    print_step "Installing AI Remove Selection..."

    # Replaces the old photogimp-ai plug-in (its Generative Fill now
    # lives in the GIMP AI Plugin above).
    local rc=0
    ai_install_plugin "ai-remove-selection" "photogimp-ai" "${sources[@]}" || rc=$?

    if (( rc == 0 )); then
        ai_refresh_pluginrc
        SUMMARY+=("AI Remove Selection|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("AI Remove Selection|⏭️ Already installed")
    fi
}

########################################
# AI Object Selection: Photoshop's Object
# Selection tool and Select Subject, with
# SAM 2.1 through ComfyUI.
########################################
ai_install_object_select() {
    local sources=(
        "$ASSETS_DIR/plug-ins/ai-object-select/ai-object-select.py"
        "$AI_COMFYUI_CLIENT"
    )

    local src
    for src in "${sources[@]}"; do
        if ! file_exists "$src"; then
            print_info "❌ Plug-in source not found at $src"
            SUMMARY+=("AI Object Selection|❌ Missing assets")
            return
        fi
    done

    print_step "Installing AI Object Selection..."

    local rc=0
    ai_install_plugin "ai-object-select" "" "${sources[@]}" || rc=$?

    if (( rc == 0 )); then
        ai_refresh_pluginrc
        SUMMARY+=("AI Object Selection|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("AI Object Selection|⏭️ Already installed")
    fi
}

########################################
# AI Restore Photo: repairs scanned photo
# prints (the photo-restore method); the
# damage mask is computed by
# restore_mask.py with the numpy, scipy
# and Pillow GIMP's Python ships.
########################################
ai_install_restore_photo() {
    local plugin_dir="$ASSETS_DIR/plug-ins/ai-restore-photo"
    local sources=(
        "$plugin_dir/ai-restore-photo.py"
        "$plugin_dir/restore_mask.py"
        "$AI_COMFYUI_CLIENT"
    )

    local src
    for src in "${sources[@]}"; do
        if ! file_exists "$src"; then
            print_info "❌ Plug-in source not found at $src"
            SUMMARY+=("AI Restore Photo|❌ Missing assets")
            return
        fi
    done

    print_step "Installing AI Restore Photo..."

    local rc=0
    ai_install_plugin "ai-restore-photo" "" "${sources[@]}" || rc=$?

    if (( rc == 0 )); then
        ai_refresh_pluginrc
        SUMMARY+=("AI Restore Photo|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("AI Restore Photo|⏭️ Already installed")
    fi
}

########################################
# Removes what earlier versions saved for
# the online providers that are gone
# (OpenAI, Google Gemini, Stable Diffusion
# WebUI): their shared API key files, and
# the key and settings kept in the GIMP AI
# Plugin's own config.json.
#
# Only these leftovers are touched; every
# other setting in config.json stays.
########################################
ai_remove_online_settings() {
    local removed=false
    local dir file name

    local key_dirs=("$HOME/.config/PhotoGIMP")
    if [[ -d "$HOME/.var/app/org.gimp.GIMP" ]]; then
        key_dirs+=("$HOME/.var/app/org.gimp.GIMP/config/PhotoGIMP")
    fi

    for dir in "${key_dirs[@]}"; do
        for name in gemini-api-key openai-api-key; do
            file="$dir/$name"
            if file_exists "$file"; then
                run rm -f "$file"
                removed=true
            fi
        done
    done

    for dir in "${AI_PROFILES[@]}"; do
        file="$dir/gimp-ai-plugin/config.json"
        file_exists "$file" || continue

        # Exits 0 when it rewrote the file, 1 when nothing was left to drop.
        if python3 - "$file" "$DRY_RUN" << 'PY'
import json
import sys

path, dry_run = sys.argv[1], sys.argv[2] == "true"
with open(path, encoding="utf-8") as f:
    config = json.load(f)

changed = False
for section in ("openai", "gemini", "sdwebui"):
    if section in config:
        del config[section]
        changed = True
if config.get("provider") not in (None, "comfyui-klein", "comfyui-qwen"):
    del config["provider"]
    changed = True

if changed and not dry_run:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)
sys.exit(0 if changed else 1)
PY
        then
            print_info "Cleaned online provider settings: $file"
            removed=true
        fi
    done

    if [[ "$removed" == true ]]; then
        SUMMARY+=("Online AI Settings|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("Online AI Settings|⏭️ None left")
    fi
}

########################################
# Shared settings from config.sh.
########################################
ai_configure_settings() {
    local changed=false
    local configured=false
    local comfyui_url="${COMFYUI_URL:-}"
    local rc

    if [[ -n "${WITHOUTBG_SERVER_URL:-}" ]]; then
        configured=true
        rc=0
        ai_write_shared_key "withoutbg-server-url" "$WITHOUTBG_SERVER_URL" || rc=$?
        (( rc == 0 )) && changed=true
    else
        print_info "WITHOUTBG_SERVER_URL not set in config.sh — WithoutBG falls back to a local server."
    fi

    # The local ComfyUI (linux-mint-setup's `comfyui` service) listens on
    # the port of that service; without it, or COMFYUI_URL, the plug-ins
    # use ComfyUI's default address.
    if [[ -z "$comfyui_url" ]]; then
        comfyui_url="$(comfyui_service_url)"
    fi

    if [[ -n "$comfyui_url" ]]; then
        configured=true
        rc=0
        ai_write_shared_key "comfyui-url" "$comfyui_url" || rc=$?
        (( rc == 0 )) && changed=true
    fi

    if [[ "$configured" == false ]]; then
        SUMMARY+=("AI Settings|⏭️ Not configured")
    elif [[ "$changed" == true ]]; then
        SUMMARY+=("AI Settings|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("AI Settings|⏭️ Already configured")
    fi
}

feature_install() {
    mapfile -t AI_PROFILES < <(gimp_profile_dirs)

    if (( ${#AI_PROFILES[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    ai_install_withoutbg

    ai_install_generative_fill

    ai_install_remove_selection

    ai_install_restore_photo

    ai_install_object_select

    ai_remove_online_settings

    ai_configure_settings
}
