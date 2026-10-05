# Layer via Copy / Cut — `features/layer-via.sh`

Photoshop's **Ctrl+J** with a selection makes a new layer from just the
selected area, in place (*Layer > New > Layer via Copy*); **Ctrl+Shift+J**
does the same and removes that area from the original (*Layer via Cut*).
GIMP has neither; this plug-in adds both as *Layer > Layer via Copy* and
*Layer > Layer via Cut*, and the [Photoshop Keymap](PHOTOSHOP_KEYMAP.md)
puts them on Photoshop's keys.

![Ctrl+J with a selection: a new layer with only the selected area](images/layer-via-copy.png)

| Case | What happens |
|---|---|
| Selection, Ctrl+J | A new layer above, with only the selected area, at the same place |
| Selection, Ctrl+Shift+J | The same, and the area becomes transparent in the original layer |
| No selection, Ctrl+J | The selected layers are duplicated (Photoshop's Ctrl+J without a selection) |
| No selection, Ctrl+Shift+J | Nothing, with a message: Layer via Cut needs a selection |
| Layer without transparency (an opened JPEG) | It gets an alpha channel, so the cut leaves transparency |

As in Photoshop the selection is dropped and the new layer selected; each
command is one undo step.

The upstream Photoshop keymap had Ctrl+J / Ctrl+Shift+J on *Select >
Float*, which makes a floating selection rather than a layer; the keymap's
extras unbind those.

It is the same plug-in as [GIMPhoto](https://github.com/diegochagas/gimphoto)'s
(`plugins/layer-via/`), with gimp-setup's procedure names
(`layer-via-copy`, `layer-via-cut`).
