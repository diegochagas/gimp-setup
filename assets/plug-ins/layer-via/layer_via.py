"""Photoshop's Layer via Copy (Ctrl+J) and Layer via Cut (Ctrl+Shift+J).

With a selection, the new layer holds only the selected part of the layer,
in place, above it; Layer via Cut also clears that part of the layer.
Without one, Layer via Copy duplicates the selected layers (Photoshop's
Ctrl+J without a selection). The selection is dropped afterwards and the
new layer selected, as in Photoshop. Used by layer-via.py; kept apart so
the smoke test can run it headless.
"""

from gi.repository import Gimp


def layer_via(image, cut=False):
    """Make the new layer(s); return them. Raises ValueError with the
    message to show when there is nothing to do."""
    layers = list(image.get_selected_layers())
    if not layers:
        raise ValueError("Select a layer.")

    if Gimp.Selection.is_empty(image):
        if cut:
            raise ValueError("Layer via Cut needs a selection.")
        copies = []
        for layer in layers:
            copy = layer.copy()
            image.insert_layer(copy, layer.get_parent(), image.get_item_position(layer))
            copies.append(copy)
        image.set_selected_layers(copies)
        return copies

    if len(layers) != 1 or layers[0].is_group():
        raise ValueError("Select one layer that is not a group.")
    layer = layers[0]
    # the selection's bounds inside the layer, relative to the layer
    inside, x, y, width, height = layer.mask_intersect()
    if not inside:
        raise ValueError("The selected area is empty.")

    new = layer.copy()
    image.insert_layer(new, layer.get_parent(), image.get_item_position(layer))
    if not new.has_alpha():
        new.add_alpha()
    saved = Gimp.Selection.save(image)
    try:
        # keep only what is selected
        Gimp.Selection.invert(image)
        new.edit_clear()
        image.select_item(Gimp.ChannelOps.REPLACE, saved)
        new.resize(width, height, -x, -y)
        if cut:
            # Photoshop layers have transparency where the cut was
            if not layer.has_alpha():
                layer.add_alpha()
            layer.edit_clear()
    finally:
        image.remove_channel(saved)
    Gimp.Selection.none(image)
    image.set_selected_layers([new])
    return [new]
