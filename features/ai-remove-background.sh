#!/usr/bin/env bash
# shellcheck disable=SC2034  # FEATURE_NAME/FEATURE_PRIORITY are read by setup.sh

########################################
# Feature: AI Remove Background
#
# Installs the AI Remove Background
# plug-in for Flatpak GIMP 3:
#
#   https://github.com/galixstroyer/ai-remove-background-g3
#
# Installs rembg and onnxruntime inside
# the Flatpak GIMP Python environment and
# patches the plug-in to use them.
#
# After restarting GIMP:
#   Filters > AI > AI Remove Background
#
# See docs/AI_REMOVE_BACKGROUND.md.
#
# This file is sourced by setup.sh, which
# provides the helpers it uses (run,
# print_info, file_exists, SUMMARY...).
########################################

FEATURE_NAME="AI Remove Background"
FEATURE_PRIORITY=20

feature_install() {
    if file_exists "$HOME/.config/GIMP/3.0/plug-ins/ai-remove-background-g3/ai-remove-background-g3.py" ||
    file_exists "$HOME/.config/GIMP/3.2/plug-ins/ai-remove-background-g3/ai-remove-background-g3.py" ||
    file_exists "$HOME/.var/app/org.gimp.GIMP/config/GIMP/3.2/plug-ins/ai-remove-background-g3/ai-remove-background-g3.py"; then
        print_info "⏭️ AI Remove Background already installed"
        SUMMARY+=("$FEATURE_NAME|⏭️ Already installed")
        return
    fi

    local AI_PLUGIN_NAME="ai-remove-background-g3"
    local AI_PLUGIN_TEMP_DIR
    AI_PLUGIN_TEMP_DIR="$(mktemp -d)"
    local AI_PLUGIN_FILE
    AI_PLUGIN_FILE="$AI_PLUGIN_TEMP_DIR/$AI_PLUGIN_NAME/$AI_PLUGIN_NAME.py"

    run git clone https://github.com/galixstroyer/ai-remove-background-g3.git "$AI_PLUGIN_TEMP_DIR/$AI_PLUGIN_NAME"

    run flatpak run --command=bash org.gimp.GIMP -c "
    python3 -m ensurepip --user 2>/dev/null || true
    python3 -m pip install --user 'rembg[cpu,cli]' onnxruntime
    "

    local AI_SITE_PACKAGES
    AI_SITE_PACKAGES="$(flatpak run --command=bash org.gimp.GIMP -c "python3 -c 'import site; print(site.getusersitepackages())'")"
    export AI_PLUGIN_FILE AI_SITE_PACKAGES

    if [[ "$DRY_RUN" == true ]]; then
        print_info "➜ Patch AI Remove Background plugin"
    else
        python3 <<'PYEOF'
import os
import re

plugin_file = os.environ["AI_PLUGIN_FILE"]
site_packages = os.environ["AI_SITE_PACKAGES"]

with open(plugin_file, encoding="utf-8") as file:
    content = file.read()

content = content.replace(
    'DEFAULT_PYTHON = os.path.expanduser("~/.rembg/bin/python")',
    'DEFAULT_PYTHON = "/usr/bin/python3"',
)

new_func = f'''def _run_rembg(python_exe: str, model: str, alpha_matting: bool,
               ae_value: int, in_path: str, out_path: str):
    script = (
        "import sys\\n"
        "sys.path.insert(0, {site_packages!r})\\n"
        "from rembg import remove, new_session\\n"
        "from PIL import Image\\n"
        "kwargs = {{'alpha_matting': " + str(alpha_matting) + ", 'alpha_matting_erode_size': " + str(int(ae_value)) + "}}\\n"
        "session = new_session('" + model + "')\\n"
        "inp = Image.open('" + in_path + "')\\n"
        "out = remove(inp, session=session, **kwargs)\\n"
        "out.save('" + out_path + "')\\n"
    )
    proc = subprocess.Popen(["/usr/bin/python3", "-c", script],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, shell=False)
    _, stderr = proc.communicate()
    if proc.returncode != 0:
        msg = stderr.decode("utf-8", errors="ignore").strip()
        raise RuntimeError(msg or "rembg exited with an error")
'''

content, replacements = re.subn(
    r"def _run_rembg\(.*?\n(?=def |\Z)",
    lambda _: new_func + "\n",
    content,
    flags=re.DOTALL,
)
if replacements != 1:
    raise RuntimeError(f"Expected to patch one _run_rembg function, patched {replacements}")

with open(plugin_file, "w", encoding="utf-8") as file:
    file.write(content)
PYEOF
    fi

    run flatpak override --user org.gimp.GIMP --filesystem=home

    for AI_PLUGIN_DIR in \
        "$HOME/.var/app/org.gimp.GIMP/config/GIMP/3.2/plug-ins/$AI_PLUGIN_NAME" \
        "$HOME/.config/GIMP/3.2/plug-ins/$AI_PLUGIN_NAME" \
        "$HOME/.config/GIMP/3.0/plug-ins/$AI_PLUGIN_NAME"
    do
        run mkdir -p "$AI_PLUGIN_DIR"
        run install -m 755 "$AI_PLUGIN_FILE" "$AI_PLUGIN_DIR/$AI_PLUGIN_NAME.py"
    done

    run rm -rf "$AI_PLUGIN_TEMP_DIR"

    SUMMARY+=("$FEATURE_NAME|$INSTALLATION_MESSAGE")
}
