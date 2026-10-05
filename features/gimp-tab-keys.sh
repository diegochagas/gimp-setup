#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Ctrl+Tab image tabs
#
# Ctrl+Tab / Ctrl+Shift+Tab switch GIMP's
# image tabs like in Photoshop, also on
# the canvas, where GIMP hard-wires
# Ctrl+Tab to its layer picker before
# any shortcut is looked up.
#
# Installs assets/launcher/gimp-tab-keys
# to ~/.local/bin and starts it with the
# desktop session (~/.config/autostart).
# While a GIMP window is focused it turns
# Ctrl+Tab into Ctrl+XF86Launch5, which
# features/photoshop-keymap.sh binds to
# Windows > Next / Previous Image; other
# windows are left alone.
#
# X11 only (needs python3-xlib); skipped
# on Wayland.
#
# See docs/PHOTOSHOP_KEYMAP.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, SUMMARY...).
########################################

FEATURE_NAME="Ctrl+Tab Image Tabs"
FEATURE_PRIORITY=46

GIMP_TAB_KEYS_SRC="$ASSETS_DIR/launcher/gimp-tab-keys"
GIMP_TAB_KEYS_BIN="$HOME/.local/bin/gimp-tab-keys"
GIMP_TAB_KEYS_AUTOSTART="$HOME/.config/autostart/gimp-tab-keys.desktop"

gimp_tab_keys_desktop() {
    cat << EOF2
[Desktop Entry]
Type=Application
Name=GIMP Ctrl+Tab image tabs
Comment=Ctrl+Tab / Ctrl+Shift+Tab switch GIMP's image tabs (gimp-setup)
Exec=$GIMP_TAB_KEYS_BIN
NoDisplay=true
X-GNOME-Autostart-enabled=true
EOF2
}

feature_install() {
    if [[ "${XDG_SESSION_TYPE:-x11}" == wayland ]]; then
        SUMMARY+=("$FEATURE_NAME|⏭️ Wayland session (X11 only)")
        return
    fi

    if ! python3 -c 'import Xlib.ext.xtest' 2> /dev/null; then
        print_info "⏭️ python3-xlib is missing (sudo apt install python3-xlib), then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Needs python3-xlib")
        return
    fi

    local changed=false

    if ! cmp -s "$GIMP_TAB_KEYS_SRC" "$GIMP_TAB_KEYS_BIN"; then
        run mkdir -p "${GIMP_TAB_KEYS_BIN%/*}"
        run install -m 755 "$GIMP_TAB_KEYS_SRC" "$GIMP_TAB_KEYS_BIN"
        print_info "Installed: $GIMP_TAB_KEYS_BIN"
        changed=true
    fi

    if ! gimp_tab_keys_desktop | cmp -s - "$GIMP_TAB_KEYS_AUTOSTART"; then
        run mkdir -p "${GIMP_TAB_KEYS_AUTOSTART%/*}"
        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Write $GIMP_TAB_KEYS_AUTOSTART"
        else
            gimp_tab_keys_desktop > "$GIMP_TAB_KEYS_AUTOSTART"
        fi
        changed=true
    fi

    #
    # Start (or restart, after an update) it now when there is a display,
    # so it works without logging out.
    #
    if [[ -n "${DISPLAY:-}" ]]; then
        if [[ "$changed" == true ]] || ! pgrep -f "^[^ ]*python3 $GIMP_TAB_KEYS_BIN" > /dev/null; then
            run pkill -f "^[^ ]*python3 $GIMP_TAB_KEYS_BIN" || true
            if [[ "$DRY_RUN" == true ]]; then
                print_info "➜ Start $GIMP_TAB_KEYS_BIN"
            else
                setsid "$GIMP_TAB_KEYS_BIN" > /dev/null 2>&1 < /dev/null &
                disown
            fi
            changed=true
        fi
    fi

    if [[ "$changed" == true ]]; then
        SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already configured")
    fi
}
