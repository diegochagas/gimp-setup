# ✂️ AI Remove Background

Installed by `features/ai-remove-background.sh` (priority 20).

Installs the
[AI Remove Background for GIMP 3](https://github.com/galixstroyer/ai-remove-background-g3)
plug-in, which removes an image's background with a local AI model
([rembg](https://github.com/danielgatis/rembg)) — no API key, fully offline.

## ⚙ What the installation does

- Installs `rembg` and `onnxruntime` inside the Flatpak GIMP Python
  environment.
- Patches the plug-in to use Flatpak's Python and its installed packages.
- Installs the plug-in for Flatpak GIMP 3.2 and the GIMP 3.2/3.0 user config
  directories.
- Grants Flatpak GIMP access to the home directory
  (`flatpak override --user org.gimp.GIMP --filesystem=home`) so the plug-in
  can process files there.

## 🖱 How to use

1. Open an image.
2. Run **Filters → AI → AI Remove Background**.
3. Pick a model and press OK. The background becomes transparent.

The **first run downloads an AI model of approximately 176 MB** — give it a
minute; later runs are fast.

## 🧰 Troubleshooting

- **The setup stopped during installation** — the installation patches the
  current upstream plug-in. If upstream changes its code structure, the setup
  stops instead of installing a potentially broken patch. Check for a newer
  gimp-setup.
- **The menu item does not appear** — restart GIMP; if it still does not
  appear, delete GIMP's `pluginrc` files and start GIMP again.
