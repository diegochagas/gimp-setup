# Smart Objects — `features/smart-objects.sh`

Photoshop's Smart Object workflow for GIMP 3.2, on top of GIMP's
**link layers**: a layer rendered from a file, re-rendered whenever that
file changes, whose moves, scales and rotations stay non-destructive
(scale it down and back up and it is sharp again).

![A normal layer and a smart object scaled to 15% and back](images/smart-object.png)

*Layer → Smart Object*. (Not in the Layers panel's right-click menu: a
plug-in entry there makes GIMP fold its whole menu into a "Layers Menu"
submenu.)

| Command | Photoshop equivalent | What it does |
|---|---|---|
| **Convert to Smart Object** | Convert to Smart Object | The selected layers (groups, text and filters included) move into an XCF of their own, cropped to them, and one link layer showing it takes their place in the stack and on the canvas |
| **Edit Contents** | Edit Contents | Opens that XCF in a new tab. Edit, **save (Ctrl+S)**, and every link layer showing it updates |
| **Replace Contents…** | Replace Contents | Points the selected smart object at another image file |
| *Layer → Rasterize* (GIMP's own) | Rasterize Layer | Turns it into plain pixels |

## Where the contents live

Photoshop embeds a smart object inside the PSD; a GIMP link layer points
at a file. The files go into a folder next to the image:

```
poster.xcf
poster smart objects/
    Logo.xcf
    Smart Object.xcf
```

**Copy or move that folder together with the image.** For an image never
saved, the files go to `~/.local/share/gimp-smart-objects/`; save the image
first, then convert, to keep them together.

Several link layers can show the same file (duplicate the layer): editing
the contents updates all of them, like Photoshop's duplicated smart
objects.

## Limits

- Needs GIMP 3.2+ (link layers). On older GIMP the menu is not added.
- Exporting to PSD writes smart objects as pixels: the PSD exporter
  (GIMP's own and [PSD with editable text](PSD_TEXT.md)) does not write
  Photoshop placed layers.
- Smart filters: GIMP 3 filters (*Filters → …* applied to a layer) are
  already non-destructive on any layer, smart object or not.
