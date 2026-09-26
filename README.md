# GIMP Setup

![Bash](https://img.shields.io/badge/Bash-5%2B-green)
![License](https://img.shields.io/github/license/diegochagas/homelab-backup)
![Version](https://img.shields.io/badge/version-1.0.0-blue)

One-command installer for the complete GIMP ecosystem on Linux:
Flatpak GIMP 3, plug-ins, brushes, presets and extra features such as
Photoshop-style shortcuts and fully local AI tools.

Companion project of
[linux-mint-setup](https://github.com/diegochagas/linux-mint-setup), which
runs this setup automatically as part of a full machine install. It also
works standalone on any distribution with Flatpak.

## Installation

Run everything with a single command:

```bash
git clone https://github.com/diegochagas/gimp-setup.git && cd gimp-setup && ./setup.sh
```

To preview the actions without changing anything:

```bash
./setup.sh --dry-run
```

The script is idempotent: run it again at any time to add what is missing.
Each run writes a log to `logs/`.

### Requirements

`curl`, `unzip`, `jq`, `git`, `flatpak` and `python3` must be available.
No `sudo` is required — everything installs to Flatpak and the user home.

This installs on top of whatever machine already runs Flatpak, so there's
no separate hardware bar beyond what GIMP itself needs:

| Resource | Minimum | Comfortable |
| --- | --- | --- |
| RAM | 4 GB | 8 GB+ — large images with G'MIC, Resynthesizer and the LinuxBeaver GEGL filters all in play |
| Disk (free space) | ~2 GB | 5 GB+ — GIMP plus all the plug-ins/brushes/presets this script adds |
| CPU | 64-bit CPU | — |
| GPU | None required | — |

The AI plug-ins never run inference inside GIMP: WithoutBG needs a
reachable server (local Docker/Mac app by default, per
`WITHOUTBG_SERVER_URL`), and Generative Fill/AI Remove Selection/AI Restore Photo use a
local [ComfyUI](https://github.com/comfyanonymous/ComfyUI) server running
FLUX.2 klein or Qwen-Image-Edit. That ComfyUI is the one heavy piece, and it
is **opt-in** (`COMFYUI_DIR`, see [Configuration](#configuration)): about
42 GB of disk and an NVIDIA GPU (the
[examples below](#local-ai-models-comfyui) were made on a 6 GB laptop GPU).
Without it the GIMP install stays light, and the AI tools work against any
ComfyUI you already run.

### Configuration

Optional. Copy the example file and fill in your values:

```bash
cp config.sh.example config.sh
```

| Variable               | Purpose                                                                    |
| ---------------------- | -------------------------------------------------------------------------- |
| `COMFYUI_DIR`          | Where to install ComfyUI and its models (empty = do not install it)        |
| `COMFYUI_MODEL_SETS`   | Model sets to download: `qwen`, `klein` or both (default), empty = none    |
| `COMFYUI_PORT`         | Port of the ComfyUI user service (default `8188`, localhost only)          |
| `COMFYUI_URL`          | ComfyUI server the AI tools use (default: `COMFYUI_PORT` on this machine)  |
| `WITHOUTBG_SERVER_URL` | WithoutBG server used by the background removal plug-in (default: local)   |

`COMFYUI_REPO`, `COMFYUI_GGUF_NODE_REPO` and `COMFYUI_TORCH_INDEX_URL`
(see `config.sh.example`) can point the ComfyUI install at a fork or another
CUDA build.

`WITHOUTBG_SERVER_URL` and the ComfyUI address are written to
`~/.config/PhotoGIMP/withoutbg-server-url` and
`~/.config/PhotoGIMP/comfyui-url` on the host **and** inside the
GIMP Flatpak sandbox, where every AI plug-in finds them (see
[docs/AI_PLUGINS.md](docs/AI_PLUGINS.md)).

`config.sh` is gitignored. Every variable also falls back to an environment
variable of the same name, so a parent script can `export COMFYUI_DIR=...`
and run `./setup.sh` without creating a `config.sh`.

## What `setup.sh` Does

The script stops if an unhandled command fails. It checks the dependencies,
the internet connection and the Flathub remote, then installs **all the
features** found in `features/`, in priority order. Everything the setup
does — including the GIMP install itself — is a feature file.

## Features

Every `features/*.sh` file is a self-contained part of the GIMP ecosystem:
the GIMP install, plug-ins, resources, shortcuts, menu options. New features
are added by dropping a new file into `features/`, without touching
`setup.sh`.

A feature file defines:

```bash
FEATURE_NAME="My Feature"       # Display name for logs and summary
FEATURE_PRIORITY=65             # Execution order (lower runs first;
                                # optional, default 50)

feature_install() {             # The work, using setup.sh helpers:
    ...                         # run, print_info, file_exists,
}                               # install_flatpak_package,
                                # gimp_profile_dirs, SUMMARY, DRY_RUN...
```

Features must be idempotent and honor `--dry-run` (use the `run` helper for
commands and guard direct file writes with `DRY_RUN`).

### Included Features

| Priority | Feature                                              | What it installs                                        | Docs                                                 |
| -------- | ---------------------------------------------------- | ------------------------------------------------------- | ---------------------------------------------------- |
| 10       | [`gimp.sh`](features/gimp.sh)                         | Flatpak GIMP + G'MIC + Resynthesizer                    | [GIMP.md](docs/GIMP.md)                               |
| 30       | [`photogimp.sh`](features/photogimp.sh)               | Photoshop-inspired interface and configuration          | [PHOTOGIMP.md](docs/PHOTOGIMP.md)                     |
| 40       | [`photoshop-keymap.sh`](features/photoshop-keymap.sh) | Photoshop keyboard shortcuts (shortcutsrc + controllerrc) | [PHOTOSHOP_KEYMAP.md](docs/PHOTOSHOP_KEYMAP.md)     |
| 40       | [`comfyui.sh`](features/comfyui.sh)                   | ComfyUI + FLUX.2 klein / Qwen-Image-Edit models (opt-in, ~42 GB) | [Local AI models](#local-ai-models-comfyui) |
| 40       | [`slos-gimpainter.sh`](features/slos-gimpainter.sh)   | Painting brushes, dynamics and tool presets             | [SLOS_GIMPAINTER.md](docs/SLOS_GIMPAINTER.md)         |
| 50       | [`linuxbeaver.sh`](features/linuxbeaver.sh)           | LinuxBeaver GEGL effect plug-ins                        | [LINUXBEAVER.md](docs/LINUXBEAVER.md)                 |
| 60       | [`ai-plugins.sh`](features/ai-plugins.sh)             | The four AI plug-ins (fully local) + shared settings  | [AI_PLUGINS.md](docs/AI_PLUGINS.md)           |

The order matters: GIMP is installed first; PhotoGIMP layers its
configuration on top; the Photoshop keymap runs after PhotoGIMP on purpose
so its shortcuts win; the AI plug-ins run last so their files survive the
configuration overwrites.

#### GIMP (Flatpak) — `features/gimp.sh`

GIMP from Flathub with the G'MIC and Resynthesizer plug-ins. The plug-in
branches follow the installed GIMP's **major version** (Flathub publishes
them as branch `3`, not `stable`). Resynthesizer adds
`Filters > Enhance > Heal Selection`. See [docs/GIMP.md](docs/GIMP.md).

#### PhotoGIMP — `features/photogimp.sh`

[PhotoGIMP 3.0](https://github.com/Diolinux/PhotoGIMP): a Photoshop-inspired
interface and configuration for Flatpak GIMP. An existing GIMP 3.0
configuration is backed up to a timestamped folder first. See
[docs/PHOTOGIMP.md](docs/PHOTOGIMP.md).

#### SLOS-GIMPainter — `features/slos-gimpainter.sh`

The [SLOS-GIMPainter](https://github.com/SenlinOS/SLOS-GIMPainter) brush,
dynamics and tool-preset package, registered in GIMP's `gimprc`. See
[docs/SLOS_GIMPAINTER.md](docs/SLOS_GIMPAINTER.md).

#### LinuxBeaver GEGL Plug-ins — `features/linuxbeaver.sh`

The [LinuxBeaver](https://github.com/LinuxBeaver/LinuxBeaver) GEGL effect
collection (`Filters > Text Styling`, `Filters > Render > Fun`, ...), with a
manifest so reruns replace stale binaries cleanly. See
[docs/LINUXBEAVER.md](docs/LINUXBEAVER.md).

#### Photoshop Keymap — `features/photoshop-keymap.sh`

Two layers, installed into every GIMP 3.x profile with timestamped
backups (details and customization in
[docs/PHOTOSHOP_KEYMAP.md](docs/PHOTOSHOP_KEYMAP.md)):

- **Photoshop keymap for GIMP** — the community
  [photoshop-keymap-for-gimp](https://github.com/loloolooo/photoshop-keymap-for-gimp)
  (`shortcutsrc` + `controllerrc`, pinned to a commit and sanitized of a
  malformed upstream line). GIMP's shortcuts follow Photoshop's and show
  next to the menu entries like in Photoshop: `Ctrl+Alt+I` Image Size,
  `Ctrl+Alt+C` Canvas Size, `Ctrl+L` Levels, `Ctrl+E` Merge Down...
- **Keymap Extras** — extra bindings for GIMP-only actions, layered on
  top through the `PHOTOSHOP_KEYMAP_EXTRAS` array on shortcuts nothing
  else uses: `Ctrl+Alt+E` File > Overwrite and `Ctrl+Alt+Shift+W`
  File > Export As.

GIMP must be closed while this feature runs.

#### AI Plug-ins — `features/ai-plugins.sh`

The four AI plug-ins, installed as one feature (details in
[docs/AI_PLUGINS.md](docs/AI_PLUGINS.md)). Everything runs on this machine:
no account, no API key, nothing is uploaded.

- **WithoutBG** — `Tools > WithoutBG > Remove Background…`. Cuts out the
  subject via the WithoutBG server set in `WITHOUTBG_SERVER_URL` and adds
  the matte as an unapplied layer mask.
- **Generative Fill** — `Filters > AI > Generative Fill…`. Fills the
  selection from a text prompt; also Image Generator. Vendored patched
  [GIMP AI Plugin](https://github.com/lukaso/gimp-ai) on the local ComfyUI
  models (FLUX.2 klein or Qwen-Image-Edit).
- **AI Remove Selection** — `Filters > AI > Remove Selection (AI)…`.
  Photoshop-style Remove tool from PhotoGIMP: Quick Mask-paint the object,
  run, gone. Same two local models.
- **AI Restore Photo** — `Filters > AI > Restore Photo (AI)…`. Repairs a
  scanned photo print (blotches, stains, scratches, specks, or chemical
  burns) with the [photo-restore](https://github.com/diegochagas/photo-restore)
  method: the model's pixels are kept only where the print was damaged,
  as a new layer whose mask you can paint. Same two local models.

The shared settings from `config.sh` (the server URLs) are written for all
of them, host and Flatpak sandbox alike. Earlier versions also offered
OpenAI, Google Gemini and Stable Diffusion WebUI; those were removed, and
the setup deletes the API keys they had saved.

#### Local AI models (ComfyUI) — `features/comfyui.sh`

The AI tools run on a local
[ComfyUI](https://github.com/comfyanonymous/ComfyUI) server serving
open-weight image models, with no accounts, credits or limits. This feature
installs it; the whole feature is **skipped unless `COMFYUI_DIR` is set** in
`config.sh`, because the models are tens of GB.

- Installs ComfyUI in `COMFYUI_DIR` with its own Python virtual environment
  and PyTorch built for CUDA (`COMFYUI_TORCH_INDEX_URL`, CUDA 12.8 by
  default). AMD64 only; needs an NVIDIA GPU with the proprietary driver
  (Driver Manager on Linux Mint) and `python3-venv`.
- Adds the [ComfyUI-GGUF](https://github.com/city96/ComfyUI-GGUF) custom
  node, which loads quantized models: a 20B editing model then runs on a
  6 GB card, keeping the rest of its weights in RAM.
- Downloads the model sets named in `COMFYUI_MODEL_SETS` (see
  [`assets/comfyui/models.tsv`](assets/comfyui/models.tsv)), each file
  verified against the SHA-256 Hugging Face publishes for it and marked as
  verified so later runs do not re-hash it. An interrupted download resumes
  on the next run.

  | Set | Models | Size | Good at |
  | --- | --- | --- | --- |
  | `qwen` | Qwen-Image-Edit-2511 (4-bit GGUF) + Qwen2.5-VL text encoder, VAE and the 4-step Lightning LoRA | ~22 GB | Best quality: instruction edits that keep characters and text consistent. ~100 s per 1 MP image on a 6 GB GPU |
  | `klein` | FLUX.2 klein 4B (fp8) + Qwen3-4B text encoder and VAE | ~12 GB | Three times faster (~35 s), lower quality on detailed art. The only one that also generates images from text |

  Both are installed by default (about 34 GB of models plus 8 GB for ComfyUI
  and PyTorch, and it wants 45 GB free); name only one to save disk. Both
  are Apache 2.0, so they can be used commercially.
- Writes a `comfyui` **systemd user service** on
  `127.0.0.1:COMFYUI_PORT` (8188 by default). It is deliberately **not
  enabled at boot**: it holds GPU memory while it runs.

ComfyUI has to be **running while the tools are used** — GIMP's Flatpak
sandbox cannot start it; when it is down, the tools' error message shows
the command that starts it. Start it before, and stop it when you are done: a
loaded model keeps several GB of GPU memory and up to ~23 GB of RAM (Qwen)
until the service stops.

```bash
systemctl --user start comfyui     # then open http://127.0.0.1:8188
systemctl --user stop comfyui      # frees the GPU and the RAM
systemctl --user status comfyui    # is it running?
```

Pick a model in the Remove Selection dialog or in `Filters > AI > Settings`;
the model files are found by name in what the server has installed. Setup,
timings and limits are in
[docs/AI_PLUGINS.md](docs/AI_PLUGINS.md#fully-local-ai-comfyui). To use a
ComfyUI you already run instead, leave `COMFYUI_DIR` empty and set
`COMFYUI_URL`.

In the ComfyUI web interface, open a workflow from **Templates** (for
example "Qwen Image Edit"), pick the installed model files in the loader
nodes, load an image, write the instruction and run. Results are saved in
`COMFYUI_DIR/output`.

Scripts can also drive it through its HTTP API, and start the service
themselves. That is what
[comic-skills](https://github.com/diegochagas/comic-skills) does to erase
text from comic pages without paying for an image API:

```bash
INPAINT=qwen COMFYUI_SERVICE=comfyui \
  ~/Projects/comic-skills/venv/bin/python \
  ~/Projects/comic-skills/clean-texts/scripts/clean_texts.py "<folder>" --backend local
```

The examples below were all made locally with these models on a laptop
RTX 3050 (6 GB): 12–35 s per edit with FLUX.2 klein, 70–125 s with
Qwen-Image-Edit.

**Remove Selection (AI)** — select the object (red = the Quick Mask
selection), run, and the background behind it is rebuilt:

![AI Remove Selection removing a backpack from a bench](docs/images/ai-remove-object.jpg)

It also removes **text or marks printed over a texture**, continuing the
print's own halftone pattern. *What is selected: Auto* tries the object
method first and switches to the texture method by itself when the fill
comes back flat:

![AI Remove Selection erasing a block of text from a halftone scan](docs/images/ai-remove-text.jpg)

**Restore Photo (AI)** — a scanned print goes in; the model's repair is
added as a layer masked to the damage it fixed, the rest of the scan stays
exactly as it was. Details and options in
[docs/AI_PLUGINS.md](docs/AI_PLUGINS.md#ai-restore-photo).

![AI Restore Photo repairing a water-damaged wedding print](docs/images/ai-restore-photo.jpg)

**Generative Fill** — the prompt replaces what is selected… (prompt: *a
sleeping orange cat curled up on the bench*)

![Generative Fill replacing the backpack with a cat](docs/images/ai-fill-replace.jpg)

…or adds something new on the real background, kept whole inside the
selection (prompt: *a shiny golden five-pointed star*, both models):

![Generative Fill adding a golden star with FLUX.2 klein and Qwen-Image-Edit](docs/images/ai-fill-add.jpg)

It also **continues the picture into a blank border** (white, transparent,
or a canvas made bigger): select the blank part and prompt `continue the
image` (or `extend the background`, `continuar a imagem`, `fill`). Details
in [docs/AI_PLUGINS.md](docs/AI_PLUGINS.md#generative-fill).

## Notes

- If GIMP has not been opened before the setup runs, the features that need
  an existing GIMP profile are skipped with a warning. Open GIMP once, close
  it, and re-run `./setup.sh`.
- The GEGL plug-in directory must contain only `.so` files at its top level.
  Subdirectories or other file types may prevent GIMP from starting.
- The script downloads software from third-party projects, so review the
  feature files before running it.
