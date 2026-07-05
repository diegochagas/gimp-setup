#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: AI Plug-ins
#
# Installs the three AI plug-ins as one
# feature, plus their shared API keys:
#
#   WithoutBG
#     Tools > WithoutBG > Remove Background
#     Cuts out the subject: adds the
#     alpha matte as an unapplied layer
#     mask. Vendored patched copy of
#     withoutbg/withoutbg-gimp targeting
#     the self-hosted server at
#     https://withoutbg.diegochagas.com
#     — see assets/vendor/withoutbg/PATCHES.md.
#     No key needed.
#
#   Generative Fill (GIMP AI Plugin)
#     Filters > AI > Generative Fill
#     Fills the selection from a text
#     prompt (plus Image Generator and
#     Layer Composite). Vendored patched
#     copy of lukaso/gimp-ai — see
#     assets/vendor/gimp-ai-plugin/PATCHES.md.
#     Providers: OpenAI (default),
#     Gemini, SD WebUI.
#
#   AI Remove Selection
#     Filters > AI > Remove Selection (AI)
#     Photoshop-style Remove tool:
#     select (or Quick Mask paint) an
#     object and it is removed. Backends:
#     Gemini, IOPaint (local), SD WebUI.
#
#   Shared API keys
#     GEMINI_API_KEY / OPENAI_API_KEY
#     from config.sh are written to
#     ~/.config/PhotoGIMP/ on the host
#     AND inside the GIMP Flatpak sandbox
#     (~/.var/app/org.gimp.GIMP/config/),
#     so the plug-ins find them in both
#     worlds.
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
# Writes an API key to the shared key
# files on the host and inside the GIMP
# Flatpak sandbox.
#
# Arguments:
#   $1 - Key file name (e.g. gemini-api-key)
#   $2 - Key value
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
    local src="$ASSETS_DIR/plug-ins/ai-remove-selection/ai-remove-selection.py"

    if ! file_exists "$src"; then
        print_info "❌ Plug-in source not found at $src"
        SUMMARY+=("AI Remove Selection|❌ Missing assets")
        return
    fi

    print_step "Installing AI Remove Selection..."

    # Replaces the old photogimp-ai plug-in (its Generative Fill now
    # lives in the GIMP AI Plugin above).
    local rc=0
    ai_install_plugin "ai-remove-selection" "photogimp-ai" "$src" || rc=$?

    if (( rc == 0 )); then
        SUMMARY+=("AI Remove Selection|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("AI Remove Selection|⏭️ Already installed")
    fi
}

########################################
# Shared API keys from config.sh.
########################################
ai_configure_keys() {
    local changed=false
    local configured=false
    local rc

    if [[ -n "${GEMINI_API_KEY:-}" ]]; then
        configured=true
        rc=0
        ai_write_shared_key "gemini-api-key" "$GEMINI_API_KEY" || rc=$?
        (( rc == 0 )) && changed=true
    else
        print_info "GEMINI_API_KEY not set in config.sh — Gemini backends stay unconfigured."
    fi

    if [[ -n "${OPENAI_API_KEY:-}" ]]; then
        configured=true
        rc=0
        ai_write_shared_key "openai-api-key" "$OPENAI_API_KEY" || rc=$?
        (( rc == 0 )) && changed=true
    else
        print_info "OPENAI_API_KEY not set in config.sh — set it for the OpenAI provider."
    fi

    if [[ "$configured" == false ]]; then
        SUMMARY+=("AI API Keys|⏭️ Not configured")
    elif [[ "$changed" == true ]]; then
        SUMMARY+=("AI API Keys|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("AI API Keys|⏭️ Already configured")
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

    ai_configure_keys
}
