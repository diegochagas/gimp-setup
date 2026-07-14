# Photoshop Keymap — `features/photoshop-keymap.sh`

Installs the community [Photoshop keymap for GIMP](https://github.com/loloolooo/photoshop-keymap-for-gimp)
— GIMP 3 `shortcutsrc` + `controllerrc` files that remap GIMP's keyboard
shortcuts to Photoshop's (CC 2019+) defaults, shown next to the menu
entries like in Photoshop.

## What it does

- Downloads `shortcutsrc` and `controllerrc` **pinned to a commit**
  (reproducible installs; bump `PHOTOSHOP_KEYMAP_COMMIT` to update).
- **Sanitizes** the downloaded `shortcutsrc`: the pinned upstream contains
  a malformed line (a doubled quote on `edit-paste-as-new-layer-in-place`)
  that makes GIMP abort parsing at that point and silently ignore the
  whole rest of the file. Unparseable lines are dropped before
  installing.
- Layers the **extra bindings** from `PHOTOSHOP_KEYMAP_EXTRAS` on top —
  GIMP-only actions on free shortcuts, so nothing the keymap or PhotoGIMP
  binds is displaced:

  | Shortcut | Menu entry | Action |
  |---|---|---|
  | `Ctrl+Alt+E` | File > Overwrite | `file-overwrite` |
  | `Ctrl+Alt+Shift+W` | File > Export As… | `file-export-as` |

  To add your own, append `'action|binding|comment'` entries to the array
  in `features/photoshop-keymap.sh` (empty binding = unbind). Pick a
  shortcut nothing else uses, write modifiers in GIMP's canonical order
  (`<Primary><Shift><Alt>`), and if another action in the upstream file
  holds the same accelerator, unbind it in the array too.
- Copies the result into **every GIMP 3.x profile** (native
  `~/.config/GIMP/3.*` and Flatpak
  `~/.var/app/org.gimp.GIMP/config/GIMP/3.*`).
- Creates a timestamped `.bak-...` backup next to any file it replaces.
- Skips (with a warning) while GIMP is running — GIMP rewrites
  `shortcutsrc` on exit and would undo the change.
- Reruns are detected through the extra bindings (GIMP reformats
  `shortcutsrc` on every exit, so file comparison would reinstall
  forever); profiles that already carry them are left untouched,
  including any shortcuts you customized in GIMP afterwards.

## Ordering

Priority **40**, after PhotoGIMP (30) on purpose: PhotoGIMP also ships a
`shortcutsrc`, and the last writer wins. This keymap is the one you get.

## Restoring

Pick the newest backup in your profile:

```bash
cp ~/.config/GIMP/3.0/shortcutsrc.bak-<STAMP> ~/.config/GIMP/3.0/shortcutsrc
```

Or delete `shortcutsrc` and restart GIMP for factory defaults.
