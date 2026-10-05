# Photoshop Theme — `features/photoshop-theme.sh`

Makes GIMP look like Photoshop's default **medium gray** interface, on top
of PhotoGIMP's Photoshop-style layout and the Photoshop keymap.

![GIMP with the Photoshop theme](images/photoshop-theme.jpg)

## What it does

- Installs a **"Photoshop" GIMP theme** into every GIMP 3.x profile
  (`themes/Photoshop/`), from
  [`assets/themes/Photoshop/gimp.css`](../assets/themes/Photoshop/gimp.css):

  | | Photoshop | GIMP before |
  |---|---|---|
  | Panels | `#535353` | `#3c3c3c` |
  | Tab strips, inactive tabs | `#424242`, active tab = panel colour | boxed tabs |
  | Fields | `#454545`, blue `#1473e6` border on focus | dark fields |
  | Selection, checkboxes, sliders, progress | Adobe blue `#1473e6` | grey |
  | Layers / Channels / Paths footer | slim bar of flat grey glyphs, lit on hover | boxed buttons |
  | Toolbox | flat tiles, active tool on a dark tile | boxed buttons |
  | Menus | panel grey, blue hover | — |

  The theme reuses every widget rule of GIMP's own Default theme (it
  `@import`s it from the installed GIMP, Flatpak or native) and only
  changes colours plus the overrides above, so GIMP updates keep working.
- Sets the **pasteboard** (canvas padding around the image) to Photoshop's
  `#282828`, in the normal and the fullscreen view (`gimprc`).
- Shows the **name** on dock tabs that only had an icon (*Layers*,
  *Channels*, *Paths*, *Tool Options*...), like Photoshop's panel tabs
  (`sessionrc`). Tabs that show previews (brushes, patterns) are left alone.

`gimprc` and `sessionrc` are backed up next to themselves
(`*.bak-<date>`) before each change. GIMP must be closed while the
feature runs, since it rewrites both files on exit. The feature runs after
PhotoGIMP and the keymap, which replace these files wholesale.

## Customizing

Colours are named at the top of `gimp.css` (`ps-panel`, `ps-strip`,
`ps-field`, `ps-accent`...). Edit, re-run `./setup.sh`, then in GIMP
*Edit → Preferences → Interface → Theme → Reload Current Theme*. For a
darker Photoshop look, set `ps-panel` to `rgb(50,50,50)` and `ps-strip` to
`rgb(38,38,38)`.

To inspect a widget: *File → Debug → Start GtkInspector*.

## Going back

*Edit → Preferences → Interface → Theme* and pick *Default*. The
pasteboard colour is under *Image Windows → Appearance → Canvas padding*.

## Limits

GTK CSS can restyle widgets but not move them: the footer buttons stay
spread over the panel width instead of grouped on the right, and dialogs
keep GIMP's layout.
