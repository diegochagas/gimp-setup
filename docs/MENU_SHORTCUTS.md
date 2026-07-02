# ⌨ Menu Shortcuts

Installed by `features/menu-shortcuts.sh` (priority 70 — after PhotoGIMP, so
the bindings survive its configuration).

Adds Photoshop-style shortcuts to every GIMP 3.x profile (native
`~/.config/GIMP/3.x` and Flatpak). GIMP shows assigned shortcuts next to the
menu entries automatically, so after a restart the items display their
shortcut like "New... Ctrl+N".

## Default shortcuts

| Shortcut | Menu entry | Action |
|---|---|---|
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>I</kbd> | Image → Scale Image… | `image-scale` |
| <kbd>Ctrl</kbd>+<kbd>Alt</kbd>+<kbd>C</kbd> | Image → Canvas Size… | `image-resize` |

For the full Photoshop-style mapping applied by PhotoGIMP itself, see
[SHORTCUTS.md](SHORTCUTS.md).

## ➕ Adding your own shortcuts

No code changes needed — declare them in `config.sh` through the
`GIMP_SHORTCUTS` array, one entry per shortcut, in the form
`'action|binding|comment'`:

```bash
GIMP_SHORTCUTS=(
    'view-zoom-fit-in|<Primary>0|Fit image in window'
    'layers-new|<Primary><Shift>n|Photoshop: New Layer'
)
```

- `action` — GIMP action name. Find it with GIMP's
  **Edit → Keyboard Shortcuts** dialog or in the `shortcutsrc` file of an
  existing profile.
- `binding` — GTK accelerator: `<Primary>` is Ctrl, plus `<Alt>`, `<Shift>`
  and a key.
- `comment` — optional note written next to the binding in `shortcutsrc`.

Re-run `./setup.sh` after editing.

## 📝 Notes

- Only the managed bindings are touched; the rest of your configuration is
  left as-is. A timestamped backup of each `shortcutsrc` is created next to
  it before patching.
- GIMP must be **closed** while this feature runs — GIMP rewrites
  `shortcutsrc` on exit and would overwrite the change. The feature skips
  itself with a warning otherwise.
