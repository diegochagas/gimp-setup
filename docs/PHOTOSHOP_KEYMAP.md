# Photoshop Keymap — `features/photoshop-keymap.sh`

Installs the community [Photoshop keymap for GIMP](https://github.com/loloolooo/photoshop-keymap-for-gimp)
— GIMP 3 `shortcutsrc` + `controllerrc` files that remap GIMP's keyboard
shortcuts to Photoshop's (CC 2019+) defaults, shown next to the menu
entries like in Photoshop.

## What it does

- Downloads `shortcutsrc` and `controllerrc` **pinned to a commit**
  (reproducible installs; bump `PHOTOSHOP_KEYMAP_COMMIT` to update).
- Copies them into **every GIMP 3.x profile** (native `~/.config/GIMP/3.*`
  and Flatpak `~/.var/app/org.gimp.GIMP/config/GIMP/3.*`).
- Creates a timestamped `.bak-...` backup next to any file it replaces.
- Skips (with a warning) while GIMP is running — GIMP rewrites
  `shortcutsrc` on exit and would undo the change.

## Ordering

Priority **40**, after PhotoGIMP (30) on purpose: PhotoGIMP also ships a
`shortcutsrc`, and the last writer wins. This keymap is the one you get.

## Restoring

Pick the newest backup in your profile:

```bash
cp ~/.config/GIMP/3.0/shortcutsrc.bak-<STAMP> ~/.config/GIMP/3.0/shortcutsrc
```

Or delete `shortcutsrc` and restart GIMP for factory defaults.
