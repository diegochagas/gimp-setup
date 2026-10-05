#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: ComfyUI with GIMP
#
# Starts the local AI models with GIMP
# and stops them when GIMP closes, so the
# AI tools need nothing started by hand
# and the GPU memory is free when GIMP
# is not open.
#
# - Installs assets/launcher/gimp-with-
#   comfyui to ~/.local/bin: it starts the
#   `comfyui` user service (features/
#   comfyui.sh), runs GIMP, and stops the
#   service once the last GIMP closes -
#   only if it was the one that started
#   it.
# - Points the GIMP menu entry (the
#   ~/.local copy of org.gimp.GIMP.desktop,
#   which PhotoGIMP also uses) at it.
# - Writes the "comfyui-autostart" setting
#   to ~/.config/PhotoGIMP: the AI tools
#   then wait for a ComfyUI that is still
#   booting instead of failing at once.
#
# Needs the ComfyUI service (COMFYUI_DIR
# set). COMFYUI_START_WITH_GIMP=no in
# config.sh turns it off and restores the
# plain launcher.
#
# Runs after PhotoGIMP (30), which ships
# the ~/.local desktop entry.
#
# See docs/AI_PLUGINS.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, SUMMARY...).
########################################

FEATURE_NAME="ComfyUI with GIMP"
FEATURE_PRIORITY=65

COMFYUI_LAUNCHER_SRC="$ASSETS_DIR/launcher/gimp-with-comfyui"
COMFYUI_LAUNCHER="$HOME/.local/bin/gimp-with-comfyui"
GIMP_DESKTOP_FILE="$HOME/.local/share/applications/org.gimp.GIMP.desktop"
GIMP_FLATPAK_EXEC="/usr/bin/flatpak run --branch=stable --arch=x86_64 --file-forwarding org.gimp.GIMP @@u %U @@"
GIMP_LAUNCHER_EXEC="$COMFYUI_LAUNCHER @@u %U @@"

########################################
# Writes the comfyui-autostart setting to
# the shared PhotoGIMP config folders.
#
# Arguments:
#   $1 - yes / no
########################################
comfyui_with_gimp_setting() {
    local dirs=("$HOME/.config/PhotoGIMP")
    if [[ -d "$HOME/.var/app/org.gimp.GIMP" ]]; then
        dirs+=("$HOME/.var/app/org.gimp.GIMP/config/PhotoGIMP")
    fi

    local dir
    for dir in "${dirs[@]}"; do
        if [[ -f "$dir/comfyui-autostart" && "$(cat "$dir/comfyui-autostart")" == "$1" ]]; then
            continue
        fi
        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Write $dir/comfyui-autostart"
            continue
        fi
        mkdir -p "$dir"
        printf '%s\n' "$1" > "$dir/comfyui-autostart"
        print_info "Saved: $dir/comfyui-autostart"
    done
}

########################################
# Sets the Exec line of the GIMP desktop
# entry, creating the ~/.local copy from
# the Flatpak export when missing.
#
# Arguments:
#   $1 - Exec value
#
# Returns:
#   0 - changed
#   1 - already set
########################################
comfyui_with_gimp_exec() {
    local exec_value="$1"

    if [[ ! -f "$GIMP_DESKTOP_FILE" ]]; then
        local exported
        for exported in /var/lib/flatpak/exports/share/applications/org.gimp.GIMP.desktop \
                        "$HOME/.local/share/flatpak/exports/share/applications/org.gimp.GIMP.desktop"; do
            if [[ -f "$exported" ]]; then
                run mkdir -p "${GIMP_DESKTOP_FILE%/*}"
                run cp -- "$exported" "$GIMP_DESKTOP_FILE"
                break
            fi
        done
        if [[ ! -f "$GIMP_DESKTOP_FILE" && "$DRY_RUN" == false ]]; then
            print_info "⚠️ No GIMP desktop entry found to point at the launcher"
            return 1
        fi
    fi

    if grep -qxF "Exec=$exec_value" "$GIMP_DESKTOP_FILE" 2>/dev/null; then
        return 1
    fi

    # Every Exec line (main entry and actions) that runs GIMP.
    run sed -i -E "s#^Exec=.*(org\.gimp\.GIMP|gimp-with-comfyui).*#Exec=$exec_value#" "$GIMP_DESKTOP_FILE"
    if binary_exists update-desktop-database; then
        run update-desktop-database "${GIMP_DESKTOP_FILE%/*}"
    fi
    print_info "GIMP launcher: Exec=$exec_value"
    return 0
}

feature_install() {
    if [[ "${COMFYUI_START_WITH_GIMP:-yes}" == no ]]; then
        if [[ -f "$GIMP_DESKTOP_FILE" ]] && grep -q "gimp-with-comfyui" "$GIMP_DESKTOP_FILE"; then
            comfyui_with_gimp_exec "$GIMP_FLATPAK_EXEC" || true
            comfyui_with_gimp_setting no
            SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
        else
            SUMMARY+=("$FEATURE_NAME|⏭️ Off (COMFYUI_START_WITH_GIMP=no)")
        fi
        return
    fi

    if ! systemctl --user cat comfyui >/dev/null 2>&1; then
        print_info "⏭️ No ComfyUI service (set COMFYUI_DIR to install it) — GIMP starts alone."
        SUMMARY+=("$FEATURE_NAME|⏭️ ComfyUI not installed")
        return
    fi

    local changed=false

    if ! cmp -s "$COMFYUI_LAUNCHER_SRC" "$COMFYUI_LAUNCHER"; then
        run mkdir -p "${COMFYUI_LAUNCHER%/*}"
        run install -m 755 "$COMFYUI_LAUNCHER_SRC" "$COMFYUI_LAUNCHER"
        print_info "Installed: $COMFYUI_LAUNCHER"
        changed=true
    fi

    if comfyui_with_gimp_exec "$GIMP_LAUNCHER_EXEC"; then
        changed=true
    fi

    comfyui_with_gimp_setting yes

    if [[ "$changed" == true ]]; then
        SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already configured")
    fi
}
