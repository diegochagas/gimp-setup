# 🎨 GIMP (Flatpak) — Core Install

Installed by `features/gimp.sh` (priority 10 — always first, everything else
builds on it).

Installs from [Flathub](https://flathub.org):

| Package | What it is |
|---|---|
| [GIMP](https://www.gimp.org) | The image editor itself (GIMP 3) |
| [G'MIC-Qt](https://github.com/flathub/org.gimp.GIMP.Plugin.GMic) | 500+ filters and effects under **Filters → G'MIC-Qt** |
| [Resynthesizer](https://github.com/bootchk/resynthesizer) | Texture synthesis, including **Filters → Enhance → Heal Selection** |

The plug-in branches follow the installed GIMP branch automatically, so
G'MIC and Resynthesizer always match the GIMP version Flathub delivered.

## 🧰 Troubleshooting

- **GIMP does not detect a plug-in** — open
  **Edit → Preferences → Folders → Plugins**, add
  `~/.var/app/org.gimp.GIMP/data/gimp/3.0/plug-ins`, and restart GIMP.
- **Flathub missing** — the setup adds the Flathub remote automatically when
  it is not configured (`flatpak remote-add --if-not-exists flathub ...`).
