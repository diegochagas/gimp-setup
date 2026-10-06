"""ComfyUI nodes gimp-setup's GIMP plug-ins need (features/comfyui-nodes.sh
installs this folder into ComfyUI's custom_nodes/).

GimpSetupBBox: box prompts for SAM 2 (ComfyUI-segment-anything-2's
Sam2Segmentation). Its `bboxes` input only takes a link - in the API
format a literal list is read as a [node, slot] link - so the GIMP
Object Selection tool sends its boxes as a JSON string through this
node instead.
"""

import json


class GimpSetupBBox:
    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "boxes": ("STRING", {"default": "[[0, 0, 64, 64]]",
                                 "tooltip": "JSON list of [x1, y1, x2, y2] boxes in image pixels"}),
        }}

    RETURN_TYPES = ("BBOX",)
    RETURN_NAMES = ("bboxes",)
    FUNCTION = "make"
    CATEGORY = "gimp-setup"

    def make(self, boxes):
        parsed = json.loads(boxes)
        if not parsed or not all(isinstance(b, list) and len(b) == 4 for b in parsed):
            raise ValueError("boxes must be a JSON list of [x1, y1, x2, y2]")
        # Sam2Segmentation expects one list of boxes per image of the batch
        return ([[[float(v) for v in b] for b in parsed]],)


NODE_CLASS_MAPPINGS = {"GimpSetupBBox": GimpSetupBBox}
NODE_DISPLAY_NAME_MAPPINGS = {"GimpSetupBBox": "Boxes from JSON (gimp-setup)"}
