# 🖼 PhotoGIMP

Installed by `features/photogimp.sh` (priority 30 — after the plug-ins, so it
may layer its configuration on top of them).

Installs [PhotoGIMP 3.0](https://github.com/Diolinux/PhotoGIMP) by Diolinux,
which applies a Photoshop-inspired experience to GIMP:

- Tool organization and interface layout similar to Photoshop.
- Photoshop-style keyboard shortcuts (see [SHORTCUTS.md](SHORTCUTS.md) —
  note the [Photoshop Keymap](PHOTOSHOP_KEYMAP.md) feature runs afterwards
  and its shortcuts win).
- New splash screen and Python filters enabled by default.

## 📂 Profile handling

The PhotoGIMP release ships its configuration as `~/.config/GIMP/3.0/`,
but the active GIMP may use a newer profile (GIMP 3.2 reads
`~/.config/GIMP/3.2`). The feature therefore copies the PhotoGIMP
configuration into **every existing GIMP 3.x profile** (native and
Flatpak sandbox), so it is applied to the profile GIMP actually uses.

The feature skips (with a warning) while GIMP is running — GIMP rewrites
its configuration on exit and would undo the install.

## 💾 Backups

Each profile is first backed up to a timestamped folder such as
`~/GIMP-3.2-backup-20260704_120000`. Restart GIMP to see the PhotoGIMP
layout.

To restore a backup, replace the profile directory (e.g.
`~/.config/GIMP/3.2`) with the contents of the desired backup.

A marker file (`.photogimp-installed` inside each profile) keeps reruns
from overwriting your configuration again. Delete it to force a
reinstall into that profile.

## 📝 Notes

- PhotoGIMP may overwrite matching GIMP configuration files — that is the
  point — which is why it runs after the other plug-in features and why the
  keymap/AI features run after it.
