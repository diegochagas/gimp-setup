#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: AI Tools
#
# Installs the PhotoGIMP AI tools plug-in
# (AI Remove + Generative Fill) into every
# GIMP 3.x profile found on this machine
# (native and Flatpak).
#
# After installing, restart GIMP. The tools
# appear under:
#   Filters > AI > Remove Selection (AI)...
#   Filters > AI > Generative Fill...   (also in the Edit menu)
#
# Backends (pick one in the tool dialog):
#   - Gemini / Nano Banana (online): free API key from
#     https://aistudio.google.com/apikey — set GEMINI_API_KEY in
#     config.sh and this feature saves it to
#     ~/.config/PhotoGIMP/gemini-api-key automatically.
#   - IOPaint (local, LaMa, Remove only):
#       pipx install iopaint && iopaint start --model=lama --port=8080
#   - Stable Diffusion WebUI (local): run AUTOMATIC1111 with --api
#
# See docs/AI_TOOLS.md for the full backend guide.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs, SUMMARY...).
########################################

FEATURE_NAME="AI Tools"
FEATURE_PRIORITY=80

feature_install() {
    local src="$ASSETS_DIR/plug-ins/photogimp-ai/photogimp-ai.py"

    if ! file_exists "$src"; then
        print_info "❌ Plug-in source not found at $src"
        exit 1
    fi

    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    #
    # Plug-in installation
    #
    local changed=false
    local dir dest

    for dir in "${profiles[@]}"; do
        dest="$dir/plug-ins/photogimp-ai/photogimp-ai.py"

        if file_exists "$dest" && cmp -s "$src" "$dest"; then
            print_info "⏭️ $dest already installed"
            continue
        fi

        changed=true

        run mkdir -p "$(dirname "$dest")"
        run install -m 755 "$src" "$dest"

        print_info "Installed: $dest"
    done

    if $changed; then
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
    fi

    #
    # Gemini API key (optional, from config.sh)
    #
    if [[ -z "${GEMINI_API_KEY:-}" ]]; then
        print_info "GEMINI_API_KEY not configured — set it in config.sh to use the Gemini backend."
        SUMMARY+=("Gemini API Key|⏭️ Not configured")
        return
    fi

    local key_file="$HOME/.config/PhotoGIMP/gemini-api-key"

    if file_exists "$key_file" && values_match "$(cat "$key_file")" "$GEMINI_API_KEY"; then
        print_info "⏭️ Gemini API key already configured"
        SUMMARY+=("Gemini API Key|⏭️ Already configured")
        return
    fi

    run mkdir -p "$(dirname "$key_file")"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "➜ Write $key_file"
    else
        printf '%s\n' "$GEMINI_API_KEY" > "$key_file"
    fi

    run chmod 600 "$key_file"

    SUMMARY+=("Gemini API Key|$CONFIGURATION_MESSAGE")
}
