#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Photoshop Theme
#
# Makes GIMP look closer to Photoshop
# (default "medium gray" interface):
#
#   - a "Photoshop" GIMP theme
#     (assets/themes/Photoshop/gimp.css):
#     #535353 panels, darker tab strips,
#     flat borderless icon buttons (the
#     Layers/Channels/Paths footer bar
#     included), slim sliders, blue
#     accent for selection and focus;
#   - the pasteboard around the image in
#     Photoshop's #282828;
#   - dock tabs that only showed an icon
#     show their name instead, like
#     Photoshop's panel tabs.
#
# The theme reuses GIMP's own Default
# theme for every widget rule: its
# @import points at the Default theme
# folder of the installed GIMP (Flatpak
# /app/share/..., or the native install),
# filled in here.
#
# Runs after PhotoGIMP (30) and the
# keymap (40), which replace gimprc /
# sessionrc wholesale. gimprc and
# sessionrc are backed up before each
# change. Back to GIMP's look: Edit >
# Preferences > Interface > Theme.
#
# See docs/PHOTOSHOP_THEME.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# gimp_is_running, SUMMARY...).
########################################

FEATURE_NAME="Photoshop Theme"
FEATURE_PRIORITY=45

PHOTOSHOP_THEME_NAME="Photoshop"
PHOTOSHOP_THEME_VARIANTS=(gimp gimp-dark gimp-gray gimp-light)

########################################
# Prints the Default theme folder of the
# GIMP that uses the given profile.
#
# Arguments:
#   $1 - profile directory
########################################
photoshop_theme_default_dir() {
    local profile="$1"
    local candidate

    # The Flatpak (any profile location: it also reads ~/.config/GIMP)
    # sees its own files under /app.
    if is_flatpak_installed org.gimp.GIMP; then
        echo "/app/share/gimp/3.0/themes/Default"
        return
    fi

    for candidate in /usr/share/gimp/3.0/themes/Default \
                     /usr/local/share/gimp/3.0/themes/Default; do
        if [[ -f "$candidate/common-dark.css" ]]; then
            echo "$candidate"
            return
        fi
    done
    print_info "⚠️ GIMP's Default theme not found for $profile; assuming the Flatpak path" >&2
    echo "/app/share/gimp/3.0/themes/Default"
}

feature_install() {
    #
    # GIMP rewrites gimprc and sessionrc on exit and would undo this.
    #
    if gimp_is_running; then
        print_info "⏭️ GIMP is running. Close it and re-run the setup."
        SUMMARY+=("$FEATURE_NAME|⏭️ GIMP running — skipped")
        return
    fi

    local profiles
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        print_info "No GIMP 3.x profile found — open GIMP once after setup, then re-run."
        SUMMARY+=("$FEATURE_NAME|⏭️ Waiting for GIMP")
        return
    fi

    local source_css="$ASSETS_DIR/themes/$PHOTOSHOP_THEME_NAME/gimp.css"
    local layout_script="$ASSETS_DIR/themes/apply_photoshop_layout.py"
    local changed=false
    local dir theme_dir default_dir rendered variant stamp

    rendered="$(mktemp)"

    for dir in "${profiles[@]}"; do
        theme_dir="$dir/themes/$PHOTOSHOP_THEME_NAME"
        default_dir="$(photoshop_theme_default_dir "$dir")"
        sed "s#@DEFAULT_THEME_DIR@#$default_dir#" "$source_css" > "$rendered"

        #
        # Theme files: one per color scheme variant, so the theme stays
        # the same whichever scheme Preferences has selected.
        #
        local theme_ok=true
        for variant in "${PHOTOSHOP_THEME_VARIANTS[@]}"; do
            cmp -s "$rendered" "$theme_dir/$variant.css" || theme_ok=false
        done

        if [[ "$theme_ok" == false ]]; then
            run mkdir -p "$theme_dir"
            for variant in "${PHOTOSHOP_THEME_VARIANTS[@]}"; do
                run install -m 644 "$rendered" "$theme_dir/$variant.css"
            done
            print_info "Installed theme: $theme_dir"
            changed=true
        fi

        #
        # gimprc (theme + pasteboard) and sessionrc (dock tab names).
        #
        if python3 "$layout_script" "$dir" --check >/dev/null; then
            [[ "$theme_ok" == true ]] && print_info "⏭️ $dir already configured"
            continue
        fi

        stamp="$(date +%Y%m%d-%H%M%S)"
        local rc
        for rc in gimprc sessionrc; do
            if [[ -f "$dir/$rc" ]]; then
                run cp -p -- "$dir/$rc" "$dir/$rc.bak-$stamp"
            fi
        done

        local line lines
        if [[ "$DRY_RUN" == true ]]; then
            # --check exits 1 when something would change
            lines="$(python3 "$layout_script" "$dir" --check || true)"
            while read -r line; do print_info "➜ $line"; done <<< "$lines"
        else
            lines="$(python3 "$layout_script" "$dir")"
            while read -r line; do print_info "$line"; done <<< "$lines"
        fi
        changed=true
    done

    rm -f "$rendered"

    if [[ "$changed" == true ]]; then
        SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already configured")
    fi
}
