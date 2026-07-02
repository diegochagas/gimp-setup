#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: LinuxBeaver GEGL Plug-ins
#
# Installs the LinuxBeaver GEGL plug-in
# collection for Flatpak GIMP 3:
#
#   https://github.com/LinuxBeaver/LinuxBeaver
#
# Only .so binaries are installed, and a
# manifest tracks them so reruns can
# replace stale binaries without touching
# other GEGL plug-ins.
#
# See docs/LINUXBEAVER.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, file_exists, SUMMARY...).
########################################

FEATURE_NAME="LinuxBeaver"
FEATURE_PRIORITY=50

feature_install() {
    local LINUXBEAVER_PLUGIN_DIR="$HOME/.var/app/org.gimp.GIMP/data/gegl-0.4/plug-ins"
    local LINUXBEAVER_MANIFEST="$HOME/.local/share/LinuxBeaver-GEGL-plugins.manifest"
    local LINUXBEAVER_TEMP_DIR
    LINUXBEAVER_TEMP_DIR="$(mktemp -d)"

    if file_exists "$LINUXBEAVER_MANIFEST"; then
        print_info "⏭️ LinuxBeaver already installed"
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return
    fi

    run mkdir -p "$LINUXBEAVER_PLUGIN_DIR" "$(dirname "$LINUXBEAVER_MANIFEST")"

    run curl -fsSL \
        "https://github.com/LinuxBeaver/LinuxBeaver/releases/download/Gimp_GEGL_Plugin_download_page/LinuxBinaries_all_plugins.zip" \
        -o "$LINUXBEAVER_TEMP_DIR/LinuxBinaries_all_plugins.zip"

    run unzip -q \
        "$LINUXBEAVER_TEMP_DIR/LinuxBinaries_all_plugins.zip" \
        -d "$LINUXBEAVER_TEMP_DIR/extracted"

    if [[ "$DRY_RUN" == false ]]; then
        local LINUXBEAVER_PLUGIN_COUNT
        LINUXBEAVER_PLUGIN_COUNT="$(find "$LINUXBEAVER_TEMP_DIR/extracted" \
            -maxdepth 3 \
            -type f \
            -name '*.so' \
            -print | wc -l)"

        if [[ "$LINUXBEAVER_PLUGIN_COUNT" -eq 0 ]]; then
            print_info "No LinuxBeaver GEGL plugin binaries were found in the downloaded archive."
            exit 1
        fi

        if [[ -f "$LINUXBEAVER_MANIFEST" ]]; then
            while IFS= read -r LINUXBEAVER_PLUGIN_NAME; do
                case "$LINUXBEAVER_PLUGIN_NAME" in
                    */*) ;;
                    *.so) rm -f "$LINUXBEAVER_PLUGIN_DIR/$LINUXBEAVER_PLUGIN_NAME" ;;
                esac
            done < "$LINUXBEAVER_MANIFEST"
        fi

        : > "$LINUXBEAVER_MANIFEST"

        while IFS= read -r -d '' LINUXBEAVER_PLUGIN_FILE; do
            LINUXBEAVER_PLUGIN_NAME="$(basename "$LINUXBEAVER_PLUGIN_FILE")"
            install -m 755 "$LINUXBEAVER_PLUGIN_FILE" "$LINUXBEAVER_PLUGIN_DIR/$LINUXBEAVER_PLUGIN_NAME"
            printf '%s\n' "$LINUXBEAVER_PLUGIN_NAME" >> "$LINUXBEAVER_MANIFEST"
        done < <(find "$LINUXBEAVER_TEMP_DIR/extracted" \
            -maxdepth 3 \
            -type f \
            -name '*.so' \
            -print0)
    fi

    run rm -rf "$LINUXBEAVER_TEMP_DIR"

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
