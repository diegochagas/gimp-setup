#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: ComfyUI nodes for GIMP
#
# Adds gimp-setup's own ComfyUI node
# (GimpSetupBBox, in assets/comfyui/
# custom_nodes), used by the Object
# Selection plug-in, to the local ComfyUI.
#
# ComfyUI itself, its models and its
# `comfyui` user service are installed by
# local-ai-setup; this
# feature finds that ComfyUI through the
# service and is skipped without it.
#
# See docs/AI_PLUGINS.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, comfyui_service_dir,
# SUMMARY...).
########################################

FEATURE_NAME="ComfyUI Nodes for GIMP"
FEATURE_PRIORITY=62

COMFYUI_OWN_NODES_DIR="$ASSETS_DIR/comfyui/custom_nodes/gimp_setup_nodes"

feature_install() {
    local comfyui_dir
    local own_dir

    comfyui_dir="$(comfyui_service_dir)"

    if [[ -z "$comfyui_dir" || ! -f "$comfyui_dir/main.py" ]]; then
        print_info "⏭️ No local ComfyUI (install it with local-ai-setup: github.com/diegochagas/local-ai-setup)."
        SUMMARY+=("$FEATURE_NAME|⏭️ ComfyUI not installed")
        return 0
    fi

    own_dir="$comfyui_dir/custom_nodes/gimp_setup_nodes"

    if diff -rq "$COMFYUI_OWN_NODES_DIR" "$own_dir" -x __pycache__ >/dev/null 2>&1; then
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return 0
    fi

    run mkdir -p "$own_dir"
    run cp -r "$COMFYUI_OWN_NODES_DIR/." "$own_dir/"

    # A running ComfyUI only loads nodes when it starts.
    if systemctl --user is-active --quiet comfyui 2>/dev/null; then
        run systemctl --user restart comfyui
    fi

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
