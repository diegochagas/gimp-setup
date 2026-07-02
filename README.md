# GIMP Setup

Personal one-command installer for the complete GIMP ecosystem on Linux:
Flatpak GIMP 3, plug-ins, brushes, presets and extra features such as
Photoshop-style shortcuts and AI tools.

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

### Configuration

Optional. Copy the example file and fill in your values:

```bash
cp config.sh.example config.sh
```

| Variable         | Purpose                                                           |
| ---------------- | ----------------------------------------------------------------- |
| `GEMINI_API_KEY` | Saved to `~/.config/PhotoGIMP/gemini-api-key` for the AI Tools    |
| `OPENAI_API_KEY` | Reference only — set it inside GIMP via `Filters > AI > Settings` |
| `GIMP_SHORTCUTS` | Extra menu shortcuts, one `'action\|binding\|comment'` per entry  |

`config.sh` is gitignored. Every variable also falls back to an environment
variable of the same name, so a parent script can `export GEMINI_API_KEY=...`
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
| 20       | [`ai-remove-background.sh`](features/ai-remove-background.sh) | AI background removal (local, offline)          | [AI_REMOVE_BACKGROUND.md](docs/AI_REMOVE_BACKGROUND.md) |
| 30       | [`photogimp.sh`](features/photogimp.sh)               | Photoshop-inspired interface and configuration          | [PHOTOGIMP.md](docs/PHOTOGIMP.md)                     |
| 40       | [`slos-gimpainter.sh`](features/slos-gimpainter.sh)   | Painting brushes, dynamics and tool presets             | [SLOS_GIMPAINTER.md](docs/SLOS_GIMPAINTER.md)         |
| 50       | [`linuxbeaver.sh`](features/linuxbeaver.sh)           | LinuxBeaver GEGL effect plug-ins                        | [LINUXBEAVER.md](docs/LINUXBEAVER.md)                 |
| 60       | [`gimp-ai-plugin.sh`](features/gimp-ai-plugin.sh)     | OpenAI-powered Inpainting / Image Generator             | [GIMP_AI_PLUGIN.md](docs/GIMP_AI_PLUGIN.md)           |
| 70       | [`menu-shortcuts.sh`](features/menu-shortcuts.sh)     | Photoshop-style menu shortcuts (+ your own from config) | [MENU_SHORTCUTS.md](docs/MENU_SHORTCUTS.md)           |
| 80       | [`ai-tools.sh`](features/ai-tools.sh)                 | AI Remove + Generative Fill (bundled plug-in)           | [AI_TOOLS.md](docs/AI_TOOLS.md)                       |

The order matters: GIMP is installed first; PhotoGIMP runs after the
plug-ins because it layers its configuration on top of them;
SLOS-GIMPainter, the shortcuts and the AI tools run after PhotoGIMP so their
changes survive it.

#### GIMP (Flatpak) — `features/gimp.sh`

GIMP from Flathub with the G'MIC and Resynthesizer plug-ins. The plug-in
branches follow the installed GIMP branch automatically. Resynthesizer adds
`Filters > Enhance > Heal Selection`. See [docs/GIMP.md](docs/GIMP.md).

#### AI Remove Background — `features/ai-remove-background.sh`

The [AI Remove Background for GIMP 3](https://github.com/galixstroyer/ai-remove-background-g3)
plug-in, patched to run inside Flatpak GIMP's Python with `rembg` and
`onnxruntime`. Use it from `Filters > AI > AI Remove Background`; the first
run downloads a ~176 MB model. See
[docs/AI_REMOVE_BACKGROUND.md](docs/AI_REMOVE_BACKGROUND.md).

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

#### GIMP AI Plugin — `features/gimp-ai-plugin.sh`

The [GIMP AI Plugin](https://github.com/lukaso/gimp-ai) by lukaso
(Inpainting, Image Generator, Layer Composite under `Filters > AI`).
Requires an OpenAI API key, set inside GIMP via `Filters > AI > Settings`.
See [docs/GIMP_AI_PLUGIN.md](docs/GIMP_AI_PLUGIN.md).

#### Menu Shortcuts — `features/menu-shortcuts.sh`

Photoshop-style shortcuts added to every GIMP 3.x profile:

| Shortcut     | Menu entry           | Action         |
| ------------ | -------------------- | -------------- |
| `Ctrl+Alt+I` | Image > Scale Image… | `image-scale`  |
| `Ctrl+Alt+C` | Image > Canvas Size… | `image-resize` |

Add your own through the `GIMP_SHORTCUTS` array in `config.sh` — no code
changes needed. GIMP must be closed while this feature runs. See
[docs/MENU_SHORTCUTS.md](docs/MENU_SHORTCUTS.md) and
[docs/SHORTCUTS.md](docs/SHORTCUTS.md) for the full PhotoGIMP mapping.

#### AI Tools — `features/ai-tools.sh`

The bundled PhotoGIMP AI tools plug-in
(`assets/plug-ins/photogimp-ai/photogimp-ai.py`):

- `Filters > AI > Remove Selection (AI)…` — inpaints (removes) whatever is
  inside the current selection, reconstructing the background.
- `Filters > AI > Generative Fill…` — fills the current selection from a text
  prompt (also in the Edit menu).

Backends: Gemini / Nano Banana (online, free tier — set `GEMINI_API_KEY` in
`config.sh`), IOPaint (local) or Stable Diffusion WebUI (local). See
[docs/AI_TOOLS.md](docs/AI_TOOLS.md).

## Notes

- If GIMP has not been opened before the setup runs, the features that need
  an existing GIMP profile are skipped with a warning. Open GIMP once, close
  it, and re-run `./setup.sh`.
- The AI Remove Background installation patches the current upstream plug-in.
  If its code structure changes, the setup stops instead of installing a
  potentially broken patch.
- Flatpak GIMP receives access to the entire home directory through
  `flatpak override --user org.gimp.GIMP --filesystem=home`.
- The GEGL plug-in directory must contain only `.so` files at its top level.
  Subdirectories or other file types may prevent GIMP from starting.
- The script downloads software from third-party projects, so review the
  feature files before running it.
