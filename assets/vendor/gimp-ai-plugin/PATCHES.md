# Vendored GIMP AI Plugin — gimp-setup patches

Upstream: https://github.com/lukaso/gimp-ai — release **v0.14.0**, MIT
license (see [LICENSE](./LICENSE), © 2025 Lukas Oberhuber).

`coordinate_utils.py` is pristine upstream. `gimp-ai-plugin.py` carries
the following gimp-setup patches, and `ai_providers.py` is new:

1. **"Inpainting" renamed to "Generative Fill"** (menu label, dialog
   title, result layer name, messages) to match Photoshop's name.
2. **ComfyUI only** — `ai_providers.py` is the single backend: the two
   fully local **ComfyUI** models, **FLUX.2 klein** and
   **Qwen-Image-Edit**, through `comfyui_client.py`, which
   `features/ai-plugins.sh` installs next to this plug-in from
   `assets/plug-ins/comfyui/` (it is shared with AI Remove Selection, so
   it is not vendored here). The plug-in registers three procedures under
   *Filters → AI*: **Generative Fill**, **Image Generator** and
   **Settings**. The model is chosen in Settings (default FLUX.2 klein);
   Image Generator always runs text-to-image on FLUX.2 klein.
3. **Removed on 2026-09-21, because the owner only uses local models:**
   **Layer Composite** (an OpenAI-only multi-image feature) and every
   direct **OpenAI (gpt-image-1)**, **Google Gemini / Nano Banana** and
   **Stable Diffusion WebUI** code path, with their Settings fields, the
   "API key not configured" banner and the URL-download and multipart
   helpers only they used. No API keys are read or written any more, and
   the shared key files under `~/.config/PhotoGIMP/` are no longer used.
   A saved config from an older version still loads: its `openai`,
   `gemini`, `sdwebui` and `last_use_mask` entries are dropped when it is
   read, so they are never written back (an old key disappears from the
   config at the next save), and a saved provider that no longer exists
   falls back to FLUX.2 klein.
4. **Local models in the UI** — a *ComfyUI URL* field in Settings; the
   wait for a result is raised from 300 s to the client's timeout (a first
   run loads the model); cancelling also interrupts the job on the ComfyUI
   server.
5. **Empty edit mask fixed** (upstream bug, v0.14.0) — in Focused mode
   `_create_full_size_mask_then_scale` composited the image-sized
   selection channel, untranslated, into a mask the size of the extract
   region: the mask came out empty unless that region started at the
   image's top-left corner. A loosely repainting model hides it; a local
   inpainter given an empty mask returns the input unchanged. The mask is
   now built with plain GIMP calls on a cropped duplicate of the image
   (fill black, clear the selection), which keeps it aligned.

When bumping the upstream release, re-apply these patches (grep for
`gimp-setup patch` markers) and update this file. The features removed in
item 3 must stay removed on a bump: do not bring back Layer Composite or
the OpenAI, Gemini and Stable Diffusion WebUI code from the new upstream
release.
