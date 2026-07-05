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

| Variable         | Purpose                                                             |
| ---------------- | ------------------------------------------------------------------- |
| `GEMINI_API_KEY` | Free key for the Gemini provider — saved to the shared key files    |
| `OPENAI_API_KEY` | Paid key for the OpenAI provider — saved to the shared key files    |

The keys are written to `~/.config/PhotoGIMP/{gemini,openai}-api-key` on
the host **and** inside the GIMP Flatpak sandbox, where every AI plug-in
finds them (see [docs/AI_PLUGINS.md](docs/AI_PLUGINS.md)).

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
| 30       | [`photogimp.sh`](features/photogimp.sh)               | Photoshop-inspired interface and configuration          | [PHOTOGIMP.md](docs/PHOTOGIMP.md)                     |
| 40       | [`photoshop-keymap.sh`](features/photoshop-keymap.sh) | Photoshop keyboard shortcuts (shortcutsrc + controllerrc) | [PHOTOSHOP_KEYMAP.md](docs/PHOTOSHOP_KEYMAP.md)     |
| 40       | [`slos-gimpainter.sh`](features/slos-gimpainter.sh)   | Painting brushes, dynamics and tool presets             | [SLOS_GIMPAINTER.md](docs/SLOS_GIMPAINTER.md)         |
| 50       | [`linuxbeaver.sh`](features/linuxbeaver.sh)           | LinuxBeaver GEGL effect plug-ins                        | [LINUXBEAVER.md](docs/LINUXBEAVER.md)                 |
| 60       | [`ai-plugins.sh`](features/ai-plugins.sh)             | The three AI plug-ins + shared API keys                 | [AI_PLUGINS.md](docs/AI_PLUGINS.md)                   |

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

The [Photoshop keymap for GIMP](https://github.com/loloolooo/photoshop-keymap-for-gimp)
(`shortcutsrc` + `controllerrc`, pinned to a commit) installed into every
GIMP 3.x profile with timestamped backups. Shortcuts show next to the menu
entries like in Photoshop (`Ctrl+Alt+I` Image Size, `Ctrl+Alt+C` Canvas
Size, `Ctrl+L` Levels...). GIMP must be closed while this feature runs.
See [docs/PHOTOSHOP_KEYMAP.md](docs/PHOTOSHOP_KEYMAP.md).

#### AI Plug-ins — `features/ai-plugins.sh`

The three AI plug-ins, installed as one feature (details and API key setup
in [docs/AI_PLUGINS.md](docs/AI_PLUGINS.md)):

- **WithoutBG** — `Tools > WithoutBG > Remove Background…`. Cuts out the
  subject via the self-hosted WithoutBG server
  (withoutbg.diegochagas.com) and adds the matte as an unapplied layer
  mask. No key needed.
- **Generative Fill** — `Filters > AI > Generative Fill…`. Fills the
  selection from a text prompt; also Image Generator and Layer Composite.
  Vendored patched [GIMP AI Plugin](https://github.com/lukaso/gimp-ai)
  with a provider switch: OpenAI (default), Gemini or SD WebUI.
- **AI Remove Selection** — `Filters > AI > Remove Selection (AI)…`.
  Photoshop-style Remove tool from PhotoGIMP: Quick Mask-paint the object,
  run, gone. Backends: Gemini, IOPaint (local), SD WebUI (local).

Shared API keys from `config.sh` are written for all of them, host and
Flatpak sandbox alike.

## Notes

- If GIMP has not been opened before the setup runs, the features that need
  an existing GIMP profile are skipped with a warning. Open GIMP once, close
  it, and re-run `./setup.sh`.
- The GEGL plug-in directory must contain only `.so` files at its top level.
  Subdirectories or other file types may prevent GIMP from starting.
- The script downloads software from third-party projects, so review the
  feature files before running it.
