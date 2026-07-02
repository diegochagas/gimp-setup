# 🖌 SLOS-GIMPainter

Installed by `features/slos-gimpainter.sh` (priority 40 — after PhotoGIMP so
its resource paths stay registered in GIMP's configuration).

Installs the
[SLOS-GIMPainter](https://github.com/SenlinOS/SLOS-GIMPainter) brush,
dynamics and tool-preset package for digital painting into
`~/.local/share/SLOS-GIMPainter`, and registers the package folders in
`~/.config/GIMP/3.0/gimprc`.

## 🖱 How to use

After restarting GIMP:

1. Open **Windows → Dockable Dialogs → Tool Presets**.
2. Open the dialog menu and select **View as Grid**.
3. Set the preview size to **Large**.
4. Select the **SLOS** tab to show the SLOS-GIMPainter presets.

## 🧰 Troubleshooting

- **GIMP does not detect the folders** — add the corresponding `brushes`,
  `dynamics`, and `tool-presets` subdirectories of
  `~/.local/share/SLOS-GIMPainter` manually through
  **Edit → Preferences → Folders**.
