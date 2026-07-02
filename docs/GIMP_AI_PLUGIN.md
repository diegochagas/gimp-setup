# 🧠 GIMP AI Plugin

Installed by `features/gimp-ai-plugin.sh` (priority 60).

Installs the [GIMP AI Plugin](https://github.com/lukaso/gimp-ai) by lukaso
into the active Flatpak GIMP configuration directory. The plugin is
OpenAI-powered and **requires an OpenAI API key**.

## 🖱 How to use

After restarting GIMP, find the plugin under **Filters → AI**:

| Tool | What it does |
|---|---|
| **Inpainting** | Fill a selected area with AI-generated content |
| **Image Generator** | Generate a new image from a text prompt |
| **Layer Composite** | Blend layers together using AI |

Configure your OpenAI API key via **Filters → AI → Settings**.

## ⚙ Version detection

The GIMP version subfolder is detected automatically, preferring the latest
stable even-numbered release (3.0, 3.2, 3.4, ...). Plugin files are installed
to the real `~/.config/GIMP/<version>/plug-ins/gimp-ai-plugin/` path, which
is what the Flatpak sandbox reads.

## 🧰 Troubleshooting

- **"Waiting for GIMP" in the setup summary** — the GIMP configuration
  directory did not exist yet (GIMP has never been opened). Open GIMP once,
  close it, and re-run `./setup.sh`.
- **The menu items do not appear** — the installation deletes GIMP's
  `pluginrc` caches so plug-ins are re-scanned; if needed, delete them again
  and restart GIMP.
