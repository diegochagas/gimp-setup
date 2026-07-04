# Vendored GIMP AI Plugin — gimp-setup patches

Upstream: https://github.com/lukaso/gimp-ai — release **v0.14.0**, MIT
license (see [LICENSE](./LICENSE), © 2025 Lukas Oberhuber).

`coordinate_utils.py` is pristine upstream. `gimp-ai-plugin.py` carries
the following gimp-setup patches, and `ai_providers.py` is new:

1. **"Inpainting" renamed to "Generative Fill"** (menu label, dialog
   title, result layer name, messages) to match Photoshop's name.
2. **Multi-provider support** — `ai_providers.py` adds:
   - Google **Gemini / Nano Banana** (online, free API tier)
   - **Stable Diffusion WebUI** (local AUTOMATIC1111 with `--api`)
   - OpenAI **gpt-image-1** remains the default.
   The provider is chosen in *Filters → AI → Settings*. Generative Fill
   and Image Generator honor it; **Layer Composite always uses OpenAI**
   (multi-image composition is a gpt-image-1 feature).
3. **Shared key files** — API keys are also read from
   `~/.config/PhotoGIMP/openai-api-key` and `gemini-api-key` (host and
   Flatpak-sandbox locations), which `features/ai-plugins.sh` writes from
   `config.sh`. Keys set in the Settings dialog take precedence.

When bumping the upstream release, re-apply these patches (grep for
`gimp-setup patch` markers) and update this file.
