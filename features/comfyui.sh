#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: ComfyUI
#
# The local AI models behind GIMP's AI
# tools (Filters > AI > Remove Selection /
# Generative Fill / Image Generator): a
# ComfyUI server serving open-weight image
# models on this machine, with no accounts,
# credits or limits.
#
# - ComfyUI itself in COMFYUI_DIR, with its
#   own Python virtual environment and
#   PyTorch built for CUDA.
# - The ComfyUI-GGUF custom node, which
#   loads quantized (GGUF) models, so a 20B
#   editing model fits in a 6 GB GPU by
#   keeping the rest of its weights in RAM.
# - The model sets listed in
#   COMFYUI_MODEL_SETS (see
#   assets/comfyui/models.tsv), each file
#   verified against the SHA-256 Hugging
#   Face publishes for it.
# - A systemd user service, NOT enabled at
#   boot: it holds GPU memory while it
#   runs, so it is started when needed
#   (`systemctl --user start comfyui`) and
#   stopped afterwards. Scripts can start
#   it themselves, which is what
#   comic-skills' INPAINT=qwen does through
#   COMFYUI_SERVICE.
#
# The whole feature is opt-in: without
# COMFYUI_DIR nothing is installed, because
# the models are tens of GB.
#
# See docs/AI_PLUGINS.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, file_exists, directory_exists,
# SUMMARY...).
########################################

FEATURE_NAME="ComfyUI"
FEATURE_PRIORITY=40

: "${COMFYUI_DIR:=}"
: "${COMFYUI_REPO:=https://github.com/comfyanonymous/ComfyUI.git}"
: "${COMFYUI_GGUF_NODE_REPO:=https://github.com/city96/ComfyUI-GGUF.git}"
: "${COMFYUI_TORCH_INDEX_URL:=https://download.pytorch.org/whl/cu128}"
: "${COMFYUI_MODEL_SETS=qwen,klein,sam}"
: "${COMFYUI_SAM2_NODE_REPO:=https://github.com/kijai/ComfyUI-segment-anything-2.git}"
: "${COMFYUI_PORT:=8188}"

COMFYUI_MODELS_FILE="$ASSETS_DIR/comfyui/models.tsv"
COMFYUI_SERVICE_UNIT="$HOME/.config/systemd/user/comfyui.service"
# Pinned commit of ComfyUI-segment-anything-2 (SAM 2 nodes, used by the
# Object Selection plug-in); bump it to update.
COMFYUI_SAM2_NODE_COMMIT="0c35fff5f382803e2310103357b5e985f5437f32"
# gimp-setup's own nodes (GimpSetupBBox), copied into custom_nodes/.
COMFYUI_OWN_NODES_DIR="$ASSETS_DIR/comfyui/custom_nodes/gimp_setup_nodes"

# The models are downloaded into a checkout that also holds PyTorch and
# CUDA libraries (~8 GB) on top of them.
COMFYUI_MIN_FREE_GB=45

comfyui_python() {
    echo "$COMFYUI_DIR/.venv/bin/python"
}

comfyui_is_installed() {
    file_exists "$COMFYUI_DIR/main.py" && file_exists "$(comfyui_python)"
}

comfyui_free_space_gb() {
    df -BG --output=avail "$1" 2> /dev/null | tail -1 | tr -dc '0-9'
}

########################################
# Installs ComfyUI and its Python
# environment (PyTorch built for CUDA).
########################################
comfyui_install() {
    local parent

    if comfyui_is_installed; then
        SUMMARY+=("ComfyUI|⏭️ Already installed")
        return 0
    fi

    parent="$(dirname "$COMFYUI_DIR")"
    run mkdir -p "$parent"

    if [[ "$DRY_RUN" == false ]] && (( $(comfyui_free_space_gb "$parent") < COMFYUI_MIN_FREE_GB )); then
        print_info "   Less than ${COMFYUI_MIN_FREE_GB} GB free in $parent"
        print_info "   Point COMFYUI_DIR at a disk with more room in config.sh."
        SUMMARY+=("ComfyUI|⚠️ Not enough disk space")
        return 0
    fi

    # Debian and Ubuntu ship venv's bootstrap in a separate package.
    if ! python3 -c 'import ensurepip, venv' 2> /dev/null; then
        print_info "   python3 cannot create virtual environments: install python3-venv"
        print_info "   (sudo apt install python3-venv) and re-run the setup."
        SUMMARY+=("ComfyUI|⚠️ python3-venv is missing")
        return 0
    fi

    if ! directory_exists "$COMFYUI_DIR/.git"; then
        run git clone "$COMFYUI_REPO" "$COMFYUI_DIR"
    fi

    run python3 -m venv "$COMFYUI_DIR/.venv"
    # PyTorch first: its CUDA build comes from PyTorch's own index, not
    # from PyPI, and ComfyUI's requirements would otherwise pull the
    # CPU-only wheel.
    run "$(comfyui_python)" -m pip install --upgrade pip
    run "$(comfyui_python)" -m pip install torch torchvision torchaudio --index-url "$COMFYUI_TORCH_INDEX_URL"
    run "$(comfyui_python)" -m pip install -r "$COMFYUI_DIR/requirements.txt"

    SUMMARY+=("ComfyUI|$INSTALLATION_MESSAGE")
}

########################################
# Installs the ComfyUI-GGUF custom node.
########################################
comfyui_install_gguf_node() {
    local node_dir="$COMFYUI_DIR/custom_nodes/ComfyUI-GGUF"

    if ! comfyui_is_installed && [[ "$DRY_RUN" == false ]]; then
        SUMMARY+=("ComfyUI GGUF Node|⏭️ ComfyUI not installed")
        return 0
    fi

    if directory_exists "$node_dir"; then
        SUMMARY+=("ComfyUI GGUF Node|⏭️ Already installed")
        return 0
    fi

    run git clone "$COMFYUI_GGUF_NODE_REPO" "$node_dir"
    run "$(comfyui_python)" -m pip install -r "$node_dir/requirements.txt"

    SUMMARY+=("ComfyUI GGUF Node|$INSTALLATION_MESSAGE")
}

########################################
# Installs the SAM 2 nodes (pinned) and
# gimp-setup's own nodes, both needed by
# the Object Selection plug-in. The SAM 2
# nodes need no extra Python packages.
########################################
comfyui_install_sam_nodes() {
    local node_dir="$COMFYUI_DIR/custom_nodes/ComfyUI-segment-anything-2"
    local own_dir="$COMFYUI_DIR/custom_nodes/gimp_setup_nodes"
    local changed=false

    if ! comfyui_is_installed && [[ "$DRY_RUN" == false ]]; then
        SUMMARY+=("ComfyUI SAM 2 Nodes|⏭️ ComfyUI not installed")
        return 0
    fi

    if ! directory_exists "$node_dir/.git"; then
        run git clone "$COMFYUI_SAM2_NODE_REPO" "$node_dir"
        changed=true
    fi
    if [[ "$DRY_RUN" == true ]] ||
       [[ "$(git -C "$node_dir" rev-parse HEAD 2> /dev/null)" != "$COMFYUI_SAM2_NODE_COMMIT" ]]; then
        run git -C "$node_dir" fetch --quiet origin
        run git -C "$node_dir" checkout --quiet "$COMFYUI_SAM2_NODE_COMMIT"
        changed=true
    fi

    if ! diff -rq "$COMFYUI_OWN_NODES_DIR" "$own_dir" -x __pycache__ > /dev/null 2>&1; then
        run mkdir -p "$own_dir"
        run cp -r "$COMFYUI_OWN_NODES_DIR/." "$own_dir/"
        changed=true
    fi

    if [[ "$changed" == true ]]; then
        # A running ComfyUI only loads nodes at start.
        if systemctl --user is-active --quiet comfyui 2> /dev/null; then
            run systemctl --user restart comfyui
        fi
        SUMMARY+=("ComfyUI SAM 2 Nodes|$INSTALLATION_MESSAGE")
    else
        SUMMARY+=("ComfyUI SAM 2 Nodes|⏭️ Already installed")
    fi
}

########################################
# Prints "directory<tab>sha256<tab>url"
# for every model of the sets in
# COMFYUI_MODEL_SETS (comma or space
# separated).
########################################
comfyui_selected_models() {
    local sets="${COMFYUI_MODEL_SETS//,/ }"
    local set

    for set in $sets; do
        awk -F'\t' -v set="$set" '$1 == set { print $2 "\t" $3 "\t" $4 }' "$COMFYUI_MODELS_FILE"
    done
}

########################################
# Checks a model file against its SHA-256.
# A verified file keeps a marker next to
# it holding its checksum, so later runs
# do not re-hash tens of GB.
#
# Arguments:
#   $1 - File
#   $2 - Expected SHA-256
########################################
comfyui_file_has_checksum() {
    local file="$1"
    local checksum="$2"
    local marker="$file.sha256"

    if file_exists "$marker" && [[ "$(< "$marker")" == "$checksum" ]]; then
        return 0
    fi

    print_info "   Verifying ${file##*/} ..."

    if [[ "$(sha256sum "$file" | awk '{ print $1 }')" != "$checksum" ]]; then
        return 1
    fi

    if [[ "$DRY_RUN" == false ]]; then
        printf '%s\n' "$checksum" > "$marker"
    fi
}

########################################
# Downloads one model file, resuming a
# partial download, and keeps it only when
# its checksum matches.
#
# Arguments:
#   $1 - Directory under ComfyUI's models/
#   $2 - Expected SHA-256
#   $3 - URL
#
# Returns:
#   0 - downloaded now
#   1 - failed
#   2 - already there and verified
########################################
comfyui_download_model() {
    local directory="$1"
    local checksum="$2"
    local url="$3"
    local target="$COMFYUI_DIR/models/$directory/${url##*/}"

    if file_exists "$target" && comfyui_file_has_checksum "$target" "$checksum"; then
        return 2
    fi

    print_info "➜ Download ${url##*/} ($directory)"

    if [[ "$DRY_RUN" == true ]]; then
        return 0
    fi

    mkdir -p "${target%/*}"

    # </dev/null keeps curl from ever reading the model list off stdin.
    if ! curl -fSL --progress-bar -C - -o "$target" "$url" < /dev/null; then
        print_info "   ⚠️ Download failed: $url"
        return 1
    fi

    if ! comfyui_file_has_checksum "$target" "$checksum"; then
        print_info "   ⚠️ Checksum mismatch, removing ${url##*/}"
        rm -f "$target"
        return 1
    fi
}

########################################
# Downloads the models of the selected
# sets.
########################################
comfyui_configure_models() {
    local failed=0
    local wanted=0
    local present=0
    local status
    local directory checksum url

    if [[ -z "$COMFYUI_MODEL_SETS" ]]; then
        SUMMARY+=("ComfyUI Models|⏭️ COMFYUI_MODEL_SETS empty")
        return 0
    fi

    if ! comfyui_is_installed && [[ "$DRY_RUN" == false ]]; then
        SUMMARY+=("ComfyUI Models|⏭️ ComfyUI not installed")
        return 0
    fi

    while IFS=$'\t' read -r directory checksum url; do
        [[ -n "$url" ]] || continue
        wanted=$((wanted + 1))
        status=0
        comfyui_download_model "$directory" "$checksum" "$url" || status=$?
        case "$status" in
            0) ;;
            2) present=$((present + 1)) ;;
            *) failed=$((failed + 1)) ;;
        esac
    done < <(comfyui_selected_models)

    if (( wanted == 0 )); then
        print_info "   Known sets: $(awk -F'\t' '!/^#/ && NF { print $1 }' "$COMFYUI_MODELS_FILE" | sort -u | tr '\n' ' ')"
        SUMMARY+=("ComfyUI Models|⚠️ No models match COMFYUI_MODEL_SETS=$COMFYUI_MODEL_SETS")
        return 0
    fi

    if (( failed > 0 )); then
        print_info "   Re-run the setup to resume the downloads."
        SUMMARY+=("ComfyUI Models|⚠️ $failed of $wanted model file(s) failed")
        return 0
    fi

    if (( present == wanted )); then
        SUMMARY+=("ComfyUI Models|⏭️ All $wanted model file(s) already present")
    else
        SUMMARY+=("ComfyUI Models|$CONFIGURATION_MESSAGE")
    fi
}

comfyui_service_unit() {
    cat << EOF
[Unit]
Description=ComfyUI (local image generation and editing) on 127.0.0.1:$COMFYUI_PORT

[Service]
WorkingDirectory=$COMFYUI_DIR
ExecStart=$(comfyui_python) main.py --listen 127.0.0.1 --port $COMFYUI_PORT
Restart=on-failure

[Install]
WantedBy=default.target
EOF
}

########################################
# Writes the `comfyui` systemd user
# service. Deliberately not enabled: it
# holds GPU memory while it runs.
########################################
comfyui_configure_service() {
    if ! comfyui_is_installed && [[ "$DRY_RUN" == false ]]; then
        SUMMARY+=("ComfyUI Service|⏭️ ComfyUI not installed")
        return 0
    fi

    if comfyui_service_unit | cmp -s - "$COMFYUI_SERVICE_UNIT" 2> /dev/null; then
        SUMMARY+=("ComfyUI Service|⏭️ Already configured")
        return 0
    fi

    run mkdir -p "${COMFYUI_SERVICE_UNIT%/*}"

    if [[ "$DRY_RUN" == true ]]; then
        print_info "➜ Write $COMFYUI_SERVICE_UNIT"
    else
        comfyui_service_unit > "$COMFYUI_SERVICE_UNIT"
    fi

    run systemctl --user daemon-reload

    # Deliberately not enabled: the service holds GPU memory while it
    # runs. Start it when it is needed.
    print_info "   Start it with: systemctl --user start comfyui"
    print_info "   Open http://127.0.0.1:$COMFYUI_PORT"

    SUMMARY+=("ComfyUI Service|$CONFIGURATION_MESSAGE")
}

feature_install() {
    if [[ -z "$COMFYUI_DIR" ]]; then
        print_info "COMFYUI_DIR not set in config.sh — the local AI models are not installed."
        SUMMARY+=("$FEATURE_NAME|⏭️ COMFYUI_DIR not set")
        return 0
    fi

    if [[ "$(uname -m)" != "x86_64" ]]; then
        SUMMARY+=("$FEATURE_NAME|⏭️ Not available for $(uname -m)")
        return 0
    fi

    print_step "Installing ComfyUI..."
    comfyui_install

    print_step "Installing the ComfyUI-GGUF node..."
    comfyui_install_gguf_node

    print_step "Installing the SAM 2 nodes (Object Selection)..."
    comfyui_install_sam_nodes

    print_step "Downloading the ComfyUI models..."
    comfyui_configure_models

    print_step "Configuring the ComfyUI service..."
    comfyui_configure_service
}
