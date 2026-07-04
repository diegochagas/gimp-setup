#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Photoshop Keymap
#
# Installs the Photoshop keymap for
# GIMP 3 (shortcutsrc + controllerrc):
#
#   https://github.com/loloolooo/photoshop-keymap-for-gimp
#
# The files are fetched pinned to a
# commit for reproducible installs and
# copied into every GIMP 3.x profile
# (native and Flatpak), with timestamped
# backups of any file they replace.
#
# Runs after PhotoGIMP (priority 30) on
# purpose: this keymap wins over the
# shortcuts PhotoGIMP ships.
#
# See docs/PHOTOSHOP_KEYMAP.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs,
# gimp_is_running, SUMMARY...).
########################################

FEATURE_NAME="Photoshop Keymap"
FEATURE_PRIORITY=40

# Pinned commit of loloolooo/photoshop-keymap-for-gimp.
PHOTOSHOP_KEYMAP_COMMIT="4599d8c7abda91ac557f982770b6db5212d05577"
PHOTOSHOP_KEYMAP_BASE_URL="https://raw.githubusercontent.com/loloolooo/photoshop-keymap-for-gimp/$PHOTOSHOP_KEYMAP_COMMIT"
PHOTOSHOP_KEYMAP_FILES=(shortcutsrc controllerrc)

feature_install() {
    #
    # GIMP rewrites shortcutsrc on exit and would overwrite this change.
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

    #
    # Download the keymap files once, pinned to the commit.
    #
    local temp_dir
    temp_dir="$(mktemp -d)"

    local file
    for file in "${PHOTOSHOP_KEYMAP_FILES[@]}"; do
        if ! run curl -fsSL "$PHOTOSHOP_KEYMAP_BASE_URL/$file" \
                -o "$temp_dir/$file" < /dev/null; then
            print_info "❌ Failed to download $file"
            SUMMARY+=("$FEATURE_NAME|❌ Download failed")
            rm -rf "$temp_dir"
            return
        fi
    done

    #
    # Install into every profile, backing up what gets replaced.
    #
    local changed=false
    local dir dest stamp

    for dir in "${profiles[@]}"; do
        local up_to_date=true
        for file in "${PHOTOSHOP_KEYMAP_FILES[@]}"; do
            if [[ "$DRY_RUN" == false ]] &&
               ! cmp -s "$temp_dir/$file" "$dir/$file" 2>/dev/null; then
                up_to_date=false
                break
            fi
        done

        if [[ "$DRY_RUN" == false && "$up_to_date" == true ]]; then
            print_info "⏭️ $dir already configured"
            continue
        fi

        changed=true
        print_info "Installing Photoshop keymap into: $dir"
        stamp="$(date +%Y%m%d-%H%M%S)"

        for file in "${PHOTOSHOP_KEYMAP_FILES[@]}"; do
            dest="$dir/$file"

            if [[ "$DRY_RUN" == true ]]; then
                print_info "➜ Install $dest"
                continue
            fi

            if [[ -f "$dest" ]]; then
                cp -p -- "$dest" "$dest.bak-$stamp"
            fi

            install -m 644 "$temp_dir/$file" "$dest"
        done
    done

    rm -rf "$temp_dir"

    if $changed; then
        SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already configured")
    fi
}
