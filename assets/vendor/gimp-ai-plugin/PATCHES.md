# Vendored GIMP AI Plugin — gimp-setup patches

Upstream: https://github.com/lukaso/gimp-ai — release **v0.14.0**, MIT
license (see [LICENSE](./LICENSE), © 2025 Lukas Oberhuber).

`coordinate_utils.py` is pristine upstream. `gimp-ai-plugin.py` carries
the following gimp-setup patches, and `ai_providers.py` is new:

1. **"Inpainting" renamed to "Generative Fill"** (menu label, dialog
   title, result layer name, messages) to match Photoshop's name.
2. **Multi-provider support** — `ai_providers.py` adds:
   - Google **Gemini / Nano Banana** (online, free API tier)
   - **ComfyUI** (local **FLUX.2 klein** or **Qwen-Image-Edit**), through
     `comfyui_client.py`, which `features/ai-plugins.sh` installs next to
     this plug-in from `assets/plug-ins/comfyui/` (it is shared with AI
     Remove Selection, so it is not vendored here)
   - **Stable Diffusion WebUI** (local AUTOMATIC1111 with `--api`)
   - OpenAI **gpt-image-1** remains the default.
   The provider is chosen in *Filters → AI → Settings*. Generative Fill
   and Image Generator honor it; **Layer Composite always uses OpenAI**
   (multi-image composition is a gpt-image-1 feature).
3. **Shared key files** — API keys are also read from
   `~/.config/PhotoGIMP/openai-api-key` and `gemini-api-key` (host and
   Flatpak-sandbox locations), which `features/ai-plugins.sh` writes from
   `config.sh`. Keys set in the Settings dialog take precedence.

4. **Local providers in the UI** — a *ComfyUI URL* field in Settings; the
   wait for a result is raised from 300 s to the client's timeout for
   ComfyUI providers (a first run loads the model); cancelling also
   interrupts the job on the ComfyUI server.
5. **Empty edit mask fixed** (upstream bug, v0.14.0) — in Focused mode
   `_create_full_size_mask_then_scale` composited the image-sized
   selection channel, untranslated, into a mask the size of the extract
   region: the mask came out empty unless that region started at the
   image's top-left corner. Online providers repaint loosely and hide it;
   a local inpainter given an empty mask returns the input unchanged. The
   mask is now built with plain GIMP calls on a cropped duplicate of the
   image (fill black, clear the selection), which keeps it aligned.

When bumping the upstream release, re-apply these patches (grep for
`gimp-setup patch` markers) and update this file.
