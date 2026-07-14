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
# The downloaded shortcutsrc is
# sanitized first: the pinned upstream
# has a malformed line (doubled quote)
# that makes GIMP abort parsing there
# and ignore the rest of the file.
#
# Two extra bindings are layered on top
# of the upstream keymap (see
# PHOTOSHOP_KEYMAP_EXTRAS below), for
# GIMP-only actions only — nothing the
# keymap or PhotoGIMP binds is changed.
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

########################################
# Extra bindings applied on top of the
# upstream keymap, 'action|binding|comment'
# per entry. An empty binding unbinds the
# action (used to free its shortcut).
#
# When adding an entry with a binding,
# make sure no other action in the
# upstream file still holds that
# accelerator — unbind it here too,
# or GIMP drops the new assignment
# (first explicit holder wins).
########################################
PHOTOSHOP_KEYMAP_EXTRAS=(
    # GIMP-only actions; both accelerators verified free in the upstream
    # keymap and in GIMP 3.2 defaults, so nothing gets displaced.
    'file-overwrite|<Primary><Alt>e|File > Overwrite'
    # Modifiers in GIMP's canonical order (Primary, Shift, Alt) so the
    # line survives GIMP's own rewrites byte-identically:
    'file-export-as|<Primary><Shift><Alt>w|File > Export As (Photoshop Export As shortcut)'
)

########################################
# Drops unparseable lines from a
# shortcutsrc: any non-comment line with
# an odd number of double quotes (e.g.
# the upstream typo `"<Alt>j""`) makes
# GIMP hit a fatal parse error and
# ignore the whole rest of the file.
#
# Arguments:
#   $1 - shortcutsrc path
########################################
sanitize_shortcutsrc() {
    local rc="$1"
    local tmp
    tmp="$(mktemp)"

    awk -F'"' '/^[[:space:]]*#/ || /^[[:space:]]*$/ || NF % 2 == 1' \
        "$rc" > "$tmp"

    cat "$tmp" > "$rc"
    rm -f "$tmp"
}

########################################
# Applies PHOTOSHOP_KEYMAP_EXTRAS to a
# shortcutsrc file, in place: existing
# lines for the managed actions are
# dropped, then the extras are appended.
#
# Arguments:
#   $1 - shortcutsrc path
########################################
apply_keymap_extras() {
    local rc="$1"
    local entry action binding comment

    local pattern=""
    for entry in "${PHOTOSHOP_KEYMAP_EXTRAS[@]}"; do
        IFS='|' read -r action binding comment <<< "$entry"
        pattern="${pattern:+$pattern|}^#? *\(action \"$action\""
    done

    local tmp
    tmp="$(mktemp)"
    grep -Ev "$pattern" "$rc" | grep -v '^# end of shortcutsrc' > "$tmp" || true

    {
        printf '\n# gimp-setup extras on top of the Photoshop keymap\n'
        for entry in "${PHOTOSHOP_KEYMAP_EXTRAS[@]}"; do
            IFS='|' read -r action binding comment <<< "$entry"
            if [[ -n "$binding" ]]; then
                printf '(action "%s" "%s")  # %s\n' "$action" "$binding" "$comment"
            else
                printf '(action "%s")  # %s\n' "$action" "$comment"
            fi
        done
        printf '# end of shortcutsrc\n'
    } >> "$tmp"

    cat "$tmp" > "$rc"
    rm -f "$tmp"
}

########################################
# Checks whether a profile's shortcutsrc
# already carries every extra binding.
#
# GIMP rewrites shortcutsrc on every
# exit (reformatted, same bindings), so
# comparing whole files would reinstall
# forever; the extras are the reliable
# marker that this feature ran.
########################################
keymap_extras_applied() {
    local rc="$1"

    [[ -f "$rc" ]] || return 1

    local entry action binding comment expected
    for entry in "${PHOTOSHOP_KEYMAP_EXTRAS[@]}"; do
        IFS='|' read -r action binding comment <<< "$entry"
        if [[ -n "$binding" ]]; then
            expected="(action \"$action\" \"$binding\")"
        else
            expected="(action \"$action\")"
        fi
        grep -Fq "$expected" "$rc" || return 1
    done
}

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
    # Profiles that still need the keymap.
    #
    local pending=()
    local dir
    for dir in "${profiles[@]}"; do
        if keymap_extras_applied "$dir/shortcutsrc" &&
           [[ -f "$dir/controllerrc" ]]; then
            print_info "⏭️ $dir already configured"
        else
            pending+=("$dir")
        fi
    done

    if (( ${#pending[@]} == 0 )); then
        SUMMARY+=("$FEATURE_NAME|⏭️ Already configured")
        return
    fi

    #
    # Download the keymap files once, pinned to the commit, and layer
    # the extra bindings on top before distributing.
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

    if [[ "$DRY_RUN" == false ]]; then
        sanitize_shortcutsrc "$temp_dir/shortcutsrc"
        apply_keymap_extras "$temp_dir/shortcutsrc"
    fi

    #
    # Install into the pending profiles, backing up what gets replaced.
    #
    local dest stamp
    for dir in "${pending[@]}"; do
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

    SUMMARY+=("$FEATURE_NAME|$CONFIGURATION_MESSAGE")
}
