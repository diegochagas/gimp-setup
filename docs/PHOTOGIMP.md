# 🖼 PhotoGIMP

Installed by `features/photogimp.sh` (priority 30 — after the plug-ins, so it
may layer its configuration on top of them).

Installs [PhotoGIMP 3.0](https://github.com/Diolinux/PhotoGIMP) by Diolinux,
which applies a Photoshop-inspired experience to Flatpak GIMP:

- Tool organization and interface layout similar to Photoshop.
- Photoshop-style keyboard shortcuts (see [SHORTCUTS.md](SHORTCUTS.md)).
- New splash screen and Python filters enabled by default.

## 💾 Backups

If `~/.config/GIMP/3.0` already exists, the feature first creates a
timestamped backup such as `~/GIMP-3.0-backup-20260614_120000`, then copies
the PhotoGIMP files into the home directory. Restart GIMP to see the
PhotoGIMP layout.

To restore a backup, replace `~/.config/GIMP/3.0` with the contents of the
desired timestamped backup directory.

A marker file (`~/.config/GIMP/.photogimp-installed`) keeps reruns from
overwriting your configuration again.

## 📝 Notes

- PhotoGIMP may overwrite matching GIMP configuration files — that is the
  point — which is why it runs after the other plug-in features and why the
  shortcut/AI-tool features run after it.
