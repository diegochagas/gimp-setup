#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: PhotoGIMP
#
# Installs PhotoGIMP 3.0, which applies a
# Photoshop-inspired interface and
# configuration to GIMP:
#
#   https://github.com/Diolinux/PhotoGIMP
#
# The PhotoGIMP release ships its config
# as ~/.config/GIMP/3.0/, but the active
# GIMP may use a newer profile directory
# (3.2, 3.4, ...). The payload is copied
# into EVERY existing GIMP 3.x profile
# (native and Flatpak), each backed up
# to a timestamped folder first and
# marked with a .photogimp-installed
# file so reruns skip it.
#
# The .local part of the release (icon
# and desktop launcher) goes to ~/.local
# as-is.
#
# See docs/PHOTOGIMP.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, file_exists,
# gimp_profile_dirs, gimp_is_running,
# SUMMARY...).
########################################

FEATURE_NAME="PhotoGIMP"
FEATURE_PRIORITY=30

feature_install() {
    local PHOTOGIMP_VERSION="3.0"

    #
    # GIMP rewrites its configuration on exit and would overwrite
    # the PhotoGIMP files.
    #
    if gimp_is_running; then
        print_info "⏭️ GIMP is running. Close it and re-run the setup."
        SUMMARY+=("$FEATURE_NAME|⏭️ GIMP running — skipped")
        return
    fi

    #
    # Profiles that still need PhotoGIMP.
    #
    local profiles=()
    mapfile -t profiles < <(gimp_profile_dirs)

    if (( ${#profiles[@]} == 0 )); then
        # First install on a machine where GIMP never ran: fall back to
        # the release's own layout so GIMP picks it up when created.
        profiles=("$HOME/.config/GIMP/$PHOTOGIMP_VERSION")
    fi

    local pending=()
    local dir
    for dir in "${profiles[@]}"; do
        if ! file_exists "$dir/.photogimp-installed"; then
            pending+=("$dir")
        fi
    done

    if (( ${#pending[@]} == 0 )); then
        print_info "⏭️ PhotoGIMP already installed"
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return
    fi

    #
    # Download and extract the release once.
    #
    local PHOTOGIMP_TEMP_DIR
    PHOTOGIMP_TEMP_DIR="$(mktemp -d)"

    if ! run curl -fsSL \
            "https://github.com/Diolinux/PhotoGIMP/releases/download/3.0/PhotoGIMP-linux.zip" \
            -o "$PHOTOGIMP_TEMP_DIR/PhotoGIMP-linux.zip" < /dev/null; then
        print_info "❌ Failed to download PhotoGIMP"
        SUMMARY+=("$FEATURE_NAME|❌ Download failed")
        rm -rf "$PHOTOGIMP_TEMP_DIR"
        return
    fi

    run unzip -q \
        "$PHOTOGIMP_TEMP_DIR/PhotoGIMP-linux.zip" \
        -d "$PHOTOGIMP_TEMP_DIR/photogimp"

    if [[ "$DRY_RUN" == true ]]; then
        for dir in "${pending[@]}"; do
            print_info "➜ Install PhotoGIMP configuration into $dir"
        done
        rm -rf "$PHOTOGIMP_TEMP_DIR"
        SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
        return
    fi

    #
    # The release wraps its content in a top-level folder
    # (PhotoGIMP-linux/.config/GIMP/3.0), so locate the payload instead
    # of assuming the depth.
    #
    local payload
    payload="$(find "$PHOTOGIMP_TEMP_DIR/photogimp" -maxdepth 4 -type d \
        -path "*/.config/GIMP/$PHOTOGIMP_VERSION" | head -n 1)"

    if [[ -z "$payload" ]]; then
        print_info "❌ Unexpected PhotoGIMP archive layout (no .config/GIMP/$PHOTOGIMP_VERSION)"
        SUMMARY+=("$FEATURE_NAME|❌ Unexpected archive")
        rm -rf "$PHOTOGIMP_TEMP_DIR"
        return
    fi

    #
    # Icon and desktop launcher.
    #
    local local_dir
    local_dir="$(find "$PHOTOGIMP_TEMP_DIR/photogimp" -maxdepth 2 -type d \
        -name ".local" | head -n 1)"

    if [[ -n "$local_dir" ]]; then
        run mkdir -p "$HOME/.local"
        run cp -a "$local_dir/." "$HOME/.local/"

        #
        # The PhotoGIMP launcher hardcodes --command=gimp-3.0, which does
        # not exist in newer GIMP Flatpaks (3.2 ships gimp-3.2). Dropping
        # the override lets Flatpak use the app's default command, which
        # is always correct.
        #
        local desktop_file="$HOME/.local/share/applications/org.gimp.GIMP.desktop"
        if file_exists "$desktop_file"; then
            run sed -i 's/ --command=gimp-[0-9][0-9.]*//' "$desktop_file"
        fi
        if binary_exists update-desktop-database; then
            run update-desktop-database "$HOME/.local/share/applications"
        fi
    fi

    #
    # GIMP configuration, into every profile that needs it.
    #
    local stamp backup suffix
    for dir in "${pending[@]}"; do
        if [[ -d "$dir" ]]; then
            stamp="$(date +%Y%m%d_%H%M%S)"
            backup="$HOME/GIMP-$(basename "$dir")-backup-$stamp"
            suffix=1
            while [[ -e "$backup" ]]; do
                suffix=$((suffix + 1))
                backup="$HOME/GIMP-$(basename "$dir")-backup-$stamp-$suffix"
            done
            run cp -a "$dir" "$backup"
            print_info "Existing $(basename "$dir") configuration backed up to $backup"
        else
            run mkdir -p "$dir"
        fi

        run cp -a "$payload/." "$dir/"

        # The release ships a pluginrc cache from GIMP 3.0, which newer
        # GIMPs reject ("wrong protocol version"). Removing it makes
        # GIMP silently re-scan the plug-ins on the next start.
        run rm -f "$dir/pluginrc"

        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Write $dir/.photogimp-installed"
        else
            printf '%s\n' "$PHOTOGIMP_VERSION" > "$dir/.photogimp-installed"
        fi

        print_info "PhotoGIMP installed into: $dir"
    done

    #
    # Drop the old global marker from previous versions of this feature,
    # which pointed at ~/.config/GIMP/3.0 only.
    #
    if file_exists "$HOME/.config/GIMP/.photogimp-installed"; then
        run rm -f "$HOME/.config/GIMP/.photogimp-installed"
    fi

    run rm -rf "$PHOTOGIMP_TEMP_DIR"

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
