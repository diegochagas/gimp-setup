#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: AI Plug-ins
#
# Installs the three AI plug-ins as one
# feature, plus their shared API keys:
#
#   AI Remove Background
#     Filters > AI > AI Remove Background
#     Cuts out the subject / deletes the
#     background. Local (rembg/U2Net),
#     no key needed.
#     https://github.com/galixstroyer/ai-remove-background-g3
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
# AI Remove Background: local rembg
# (U2Net) plug-in for Flatpak GIMP.
# Installs rembg + onnxruntime inside
# the Flatpak Python and patches the
# plug-in to use them.
########################################
ai_install_remove_background() {
    local plugin_name="ai-remove-background-g3"

    #
    # Already installed in every profile? If only some profiles have it
    # (e.g. a new profile appeared after a GIMP upgrade), reuse the
    # existing patched copy instead of redoing the full install.
    #
    local existing=""
    local missing=false
    local dir
    for dir in "${AI_PROFILES[@]}"; do
        if file_exists "$dir/plug-ins/$plugin_name/$plugin_name.py"; then
            existing="$dir/plug-ins/$plugin_name/$plugin_name.py"
        else
            missing=true
        fi
    done

    if [[ "$missing" == false ]]; then
        print_info "⏭️ AI Remove Background already installed"
        SUMMARY+=("AI Remove Background|⏭️ Already installed")
        return
    fi

    if [[ -n "$existing" ]]; then
        print_step "Installing AI Remove Background (from existing copy)..."
        local rc=0
        ai_install_plugin "$plugin_name" "" "$existing" || rc=$?
        SUMMARY+=("AI Remove Background|$INSTALLATION_MESSAGE")
        return
    fi

    if ! is_flatpak_installed org.gimp.GIMP; then
        print_info "⏭️ AI Remove Background needs Flatpak GIMP — skipped"
        SUMMARY+=("AI Remove Background|⏭️ Needs Flatpak GIMP")
        return
    fi

    print_step "Installing AI Remove Background..."

    local temp_dir plugin_file
    temp_dir="$(mktemp -d)"
    plugin_file="$temp_dir/$plugin_name/$plugin_name.py"

    if ! run git clone --depth 1 \
            https://github.com/galixstroyer/ai-remove-background-g3.git \
            "$temp_dir/$plugin_name" < /dev/null; then
        print_info "❌ Failed to clone AI Remove Background"
        SUMMARY+=("AI Remove Background|❌ Failed (see log)")
        rm -rf "$temp_dir"
        return
    fi

    #
    # rembg + onnxruntime inside the Flatpak Python environment.
    #
    if ! run flatpak run --command=bash org.gimp.GIMP -c "
    python3 -m ensurepip --user 2>/dev/null || true
    python3 -m pip install --user 'rembg[cpu,cli]' onnxruntime
    " < /dev/null; then
        print_info "❌ Failed to install rembg in the Flatpak Python"
        SUMMARY+=("AI Remove Background|❌ Failed (see log)")
        rm -rf "$temp_dir"
        return
    fi

    local site_packages
    site_packages="$(flatpak run --command=bash org.gimp.GIMP -c \
        "python3 -c 'import site; print(site.getusersitepackages())'" < /dev/null)"

    export AI_PLUGIN_FILE="$plugin_file" AI_SITE_PACKAGES="$site_packages"

    #
    # Patch the plug-in to call the Flatpak Python + rembg directly.
    #
    if [[ "$DRY_RUN" == true ]]; then
        print_info "➜ Patch AI Remove Background plugin"
    else
        python3 <<'PYEOF'
import os
import re

plugin_file = os.environ["AI_PLUGIN_FILE"]
site_packages = os.environ["AI_SITE_PACKAGES"]

with open(plugin_file, encoding="utf-8") as file:
    content = file.read()

content = content.replace(
    'DEFAULT_PYTHON = os.path.expanduser("~/.rembg/bin/python")',
    'DEFAULT_PYTHON = "/usr/bin/python3"',
)

new_func = f'''def _run_rembg(python_exe: str, model: str, alpha_matting: bool,
               ae_value: int, in_path: str, out_path: str):
    script = (
        "import sys\\n"
        "sys.path.insert(0, {site_packages!r})\\n"
        "from rembg import remove, new_session\\n"
        "from PIL import Image\\n"
        "kwargs = {{'alpha_matting': " + str(alpha_matting) + ", 'alpha_matting_erode_size': " + str(int(ae_value)) + "}}\\n"
        "session = new_session('" + model + "')\\n"
        "inp = Image.open('" + in_path + "')\\n"
        "out = remove(inp, session=session, **kwargs)\\n"
        "out.save('" + out_path + "')\\n"
    )
    proc = subprocess.Popen(["/usr/bin/python3", "-c", script],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=False)
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(msg or "rembg exited with an error")
'''

content, replacements = re.subn(
    r"def _run_rembg\(.*?\n(?=def |\Z)",
    lambda _: new_func + "\n",
    content,
    flags=re.DOTALL,
)
if replacements != 1:
    raise RuntimeError(f"Expected to patch one _run_rembg function, patched {replacements}")

with open(plugin_file, "w", encoding="utf-8") as file:
    file.write(content)
PYEOF
    fi

    run flatpak override --user org.gimp.GIMP --filesystem=home < /dev/null

    local rc=0
    ai_install_plugin "$plugin_name" "" "$plugin_file" || rc=$?

    rm -rf "$temp_dir"

    SUMMARY+=("AI Remove Background|$INSTALLATION_MESSAGE")
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
            SUMMARY+=("Generative Fill (GIMP AI)|❌ Missing assets")
            return
        fi
    done

    print_step "Installing Generative Fill (GIMP AI Plugin)..."

    local rc=0
    ai_install_plugin "gimp-ai-plugin" "" "${sources[@]}" || rc=$?

    if (( rc == 0 )); then
        ai_refresh_pluginrc
        SUMMARY+=("Generative Fill (GIMP AI)|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("Generative Fill (GIMP AI)|⏭️ Already installed")
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

    ai_install_remove_background

    ai_install_generative_fill

    ai_install_remove_selection

    ai_configure_keys
}
