#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: Menu Shortcuts
#
# Adds Photoshop-style shortcuts to every
# GIMP 3.x profile (native and Flatpak):
#
#   Ctrl+Alt+I  ->  Image > Scale Image...   (image-scale)
#   Ctrl+Alt+C  ->  Image > Canvas Size...   (image-resize)
#
# GIMP shows assigned shortcuts next to the
# menu entries automatically, so after a
# restart both items display their shortcut
# like "New... Ctrl+N".
#
# More shortcuts can be added without
# touching this file: define them in
# config.sh through the GIMP_SHORTCUTS
# array, one entry per shortcut, in the
# form "action|binding|comment".
#
# Only the managed bindings are touched;
# the rest of the configuration is left
# as-is. A timestamped backup of
# shortcutsrc is created next to it.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, gimp_profile_dirs, SUMMARY...).
########################################

FEATURE_NAME="Menu Shortcuts"
FEATURE_PRIORITY=70

feature_install() {
    #
    # Default shortcuts + extras from config.sh
    #
    local shortcuts=(
        'image-scale|<Primary><Alt>i|Photoshop: Image Size'
        'image-resize|<Primary><Alt>c|Photoshop: Canvas Size'
    )

    if [[ -n "${GIMP_SHORTCUTS[*]:-}" ]]; then
        shortcuts+=("${GIMP_SHORTCUTS[@]}")
    fi

    #
    # GIMP rewrites shortcutsrc on exit and would
    # overwrite this change.
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

    local changed=false
    local dir rc entry action binding comment expected

    for dir in "${profiles[@]}"; do
        rc="$dir/shortcutsrc"

        #
        # Already configured?
        #
        local missing=false
        for entry in "${shortcuts[@]}"; do
            IFS='|' read -r action binding comment <<< "$entry"
            expected="(action \"$action\" \"$binding\")"

            if ! file_exists "$rc" || ! grep -Fq "$expected" "$rc"; then
                missing=true
                break
            fi
        done

        if [[ "$missing" == false ]]; then
            print_info "⏭️ $dir already configured"
            continue
        fi

        changed=true
        print_info "Patching profile: $dir"

        if [[ "$DRY_RUN" == true ]]; then
            print_info "➜ Update $rc"
            continue
        fi

        if [[ -f "$rc" ]]; then
            cp -p -- "$rc" "$rc.bak-$(date +%Y%m%d-%H%M%S)"
        else
            printf '# GIMP shortcutsrc\n\n(file-version 1)\n\n' > "$rc"
        fi

        #
        # Drop any existing lines for the managed actions (active or
        # commented) so the bindings below are the only ones, and keep
        # the closing comment out of the middle of the file.
        #
        local tmp
        tmp="$(mktemp)"
        local pattern=""
        for entry in "${shortcuts[@]}"; do
            IFS='|' read -r action binding comment <<< "$entry"
            pattern="${pattern:+$pattern|}^#? *\(action \"$action\""
        done
        grep -Ev "$pattern" "$rc" | grep -v '^# end of shortcutsrc' > "$tmp" || true
        cat "$tmp" > "$rc"
        rm -f "$tmp"

        {
            for entry in "${shortcuts[@]}"; do
                IFS='|' read -r action binding comment <<< "$entry"
                if [[ -n "$comment" ]]; then
                    printf '(action "%s" "%s")  # %s\n' "$action" "$binding" "$comment"
                else
                    printf '(action "%s" "%s")\n' "$action" "$binding"
                fi
            done
            printf '# end of shortcutsrc\n'
        } >> "$rc"

        for entry in "${shortcuts[@]}"; do
            IFS='|' read -r action binding comment <<< "$entry"
            print_info "  -> $binding = $action"
        done
    done

    if $changed; then
        SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
    else
        SUMMARY+=("$FEATURE_NAME|⏭️ Already configured")
    fi
}
