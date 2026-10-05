# PSD with editable text — `features/psd-text.sh`

GIMP opens Photoshop files with their **text still editable**, and exports
GIMP text to PSD as **Type layers Photoshop can still edit**. Nothing to
choose: *File → Open* a `.psd`, *File → Export As…* to `name.psd`.

| | GIMP alone | With this plug-in |
|---|---|---|
| Photoshop Type layer → GIMP | rasterized (pixels) | GIMP text layer: font, size, colour, justification, tracking, leading, paragraph box or point text, rotation, mixed bold/italic/colour/size runs |
| Layer Style stroke / drop shadow / colour overlay → GIMP | dropped | *Filters → Text Styling* filter, still editable |
| GIMP text layer → PSD | pixels | Type layer, Photoshop redraws it with its own fonts |
| *Text Styling* outline / shadow → PSD | merged into pixels | live Layer Style (Stroke, Drop Shadow, Color Overlay) |
| Any Layer Style (shadows, glows, stroke, bevel, color / gradient overlay), on any layer | dropped | an editable [Layer Style](LAYER_STYLE.md), written back to PSD with the same settings |

Pixels, groups, masks, blend modes and opacity are handled by GIMP's own
PSD support, which the plug-in runs first.

## Rotated and squeezed text

GIMP cannot show a rotated text layer as text: rotating one flags it as
rasterized, and clicking it with the Text tool asks to discard the rotation.
So Photoshop text that is not straight opens as:

| In Photoshop | In GIMP | Edit the text with |
|---|---|---|
| straight | text layer | the Text tool |
| rotated 90° clockwise (book spines) | **vertical text layer** (GIMP's top-to-bottom direction, lines right to left): the same picture, still plain text | the Text tool |
| any other angle (tilted balloons and sound effects), squeezed or stretched (Free Transform) | **smart object**: a link layer, rotated / scaled non-destructively, showing an XCF with the straight text | *Layer → Smart Object → Edit Contents*, edit, save (`Ctrl+S`) |

![The vertical text of a PSD edited with the Text tool; the tilted caption is a smart object](images/psd-text-vertical.jpg)

The smart object files go into `<psd name> smart objects/` next to the PSD
(or `~/.local/share/gimp-smart-objects/` when that folder is read-only); see
[Smart Objects](SMART_OBJECTS.md). Text Styling filters (stroke, shadow) go
on the rotated layer, so the outline follows the rotation as in Photoshop.

Exporting to PSD turns both back into rotated / squeezed Type layers (same
angle and box, verified on the cover spine and the tilted sound effects of
real comic pages). A smart object rotated further *in GIMP* is exported at
its original angle.

## How it works

The plug-in ([`assets/plug-ins/psd-text`](../assets/plug-ins/psd-text))
registers its own PSD open and export procedures with a lower priority value
than GIMP's built-in ones, so GIMP picks it for `.psd` files. Each wraps the
built-in procedure:

- **Open**: `file-psd-load` loads the file, then
  [ag-psd](https://github.com/Agamnentzar/ag-psd) (Node.js,
  `psd_text_info.mjs`) reads the Type layers and Layer Styles and
  `psd_text_gimp.py` swaps each rasterized text layer for a GIMP text layer
  at the same place in the stack. GIMP's own "text layers will be
  rasterized" notice no longer applies, so it is not shown.
- **Export**: the text layers and Text Styling filters are described,
  `file-psd-export` writes the PSD, and `write_psd_text.mjs` turns the
  rasterized text of that file back into Type layers and Layer Styles. The
  flattened preview inside the PSD keeps the outlines. If that last step
  fails, the export still happens with the text as pixels, and GIMP says
  why.

Fonts are matched through fontconfig (PostScript name ⇄ GIMP's
"Family Style"). A font that is not installed is replaced by the closest
installed one, and GIMP shows a note. The original name is kept in the
layer, so exporting back to PSD restores it.

Code vendored from
[comic-skills/psd-xcf-convert](https://github.com/diegochagas/comic-skills)
(the batch PSD ⇄ XCF converter); the changes are in
[`PATCHES.md`](../assets/plug-ins/psd-text/PATCHES.md).

## Requirements

**Node.js and npm on the host.** The GIMP Flatpak can run the host's Node
binary from the home folder. The setup installs ag-psd next to the plug-in
(`npm ci`) and saves the Node path to `~/.config/PhotoGIMP/node-path`
(`PSD_TEXT_NODE` overrides it). Without Node the feature is skipped and GIMP
keeps its own PSD support.

## Text language

Photoshop stores a language per text run (spell check, hyphenation). A
PSD in English, Portuguese or Brazilian Portuguese keeps its language on
the GIMP layer, and it is written back on export (other languages are not
mapped yet). A GIMP text
layer with no language gets `PSD_TEXT_LANGUAGE` from `config.sh` (`en-us`
by default; `pt-br`, `pt`, or an Adobe text engine code number).

## Known approximations

GIMP shows a short note after opening or exporting when something was
approximated:

- Photoshop's own *vertical* text (upright CJK columns) becomes
  horizontal; a layer mask on a text layer is not
  carried over;
- a stroke inside / centred is drawn as an outside outline; bevel, inner
  glow and image overlay are not converted;
- GIMP does not hyphenate and measures lines slightly differently, so a
  word can wrap differently; a paragraph box that would cut the last line
  is made a little taller;
- a text layer freely rotated or scaled *in GIMP* is exported as pixels
  (rotate text with a smart object instead: *Layer → Smart Object →
  Convert to Smart Object*, then rotate it).

Verified on real comic PSDs: the Type layers come back with the same font,
effective size, box size and Layer Style strokes after GIMP opens and
re-exports them.
