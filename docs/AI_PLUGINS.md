# AI Plug-ins — `features/ai-plugins.sh`

One feature installs the three AI plug-ins and their shared API keys.
All tools appear under **Filters → AI** after restarting GIMP.

| Tool | What it does | Providers | Key needed |
|---|---|---|---|
| **AI Remove Background** | Cuts the subject out / deletes the background | rembg / U2Net (local) | None (offline) |
| **Generative Fill** | Fills the **selection** from a **text prompt**; also *Image Generator* (text → new layer) and *Layer Composite* (AI-blend layers) | OpenAI gpt-image-1 (default) · Gemini "Nano Banana" · Stable Diffusion WebUI (local) | OpenAI: paid · Gemini: free tier · SD WebUI: none |
| **AI Remove Selection** | Photoshop-style **Remove tool**: select (or Quick Mask-paint) an object, run, it's gone | Gemini · IOPaint/LaMa (local) · SD WebUI (local) | Gemini: free tier · locals: none |

## The tools

### AI Remove Background

From [galixstroyer/ai-remove-background-g3](https://github.com/galixstroyer/ai-remove-background-g3).
The setup installs `rembg` + `onnxruntime` inside the Flatpak GIMP Python
and patches the plug-in to use them. Fully local — nothing is uploaded.
Requires Flatpak GIMP.

### Generative Fill (GIMP AI Plugin)

A **vendored, patched** copy of [lukaso/gimp-ai](https://github.com/lukaso/gimp-ai)
v0.14.0 (MIT) from `assets/vendor/gimp-ai-plugin/` — see
[PATCHES.md](../assets/vendor/gimp-ai-plugin/PATCHES.md) for the diff:

- *AI Inpainting* is renamed **Generative Fill** (Photoshop's name).
- A **provider selector** in *Filters → AI → Settings* switches between
  OpenAI, Gemini and Stable Diffusion WebUI for Generative Fill and the
  Image Generator. **Layer Composite always uses OpenAI** (multi-image
  composition is a gpt-image-1 feature).

Usage: make a selection → *Filters → AI → Generative Fill...* → type the
prompt → the AI fills only the selection, blended with the image.

### AI Remove Selection

The PhotoGIMP plug-in (synced from the PhotoGIMP repo into
`assets/plug-ins/ai-remove-selection/`). Photoshop-like Remove workflow:
press <kbd>Q</kbd> (Quick Mask), paint the object with a brush (red
overlay), press <kbd>Q</kbd>, run the tool. The reconstructed background
comes back as a separately masked layer. Replaces (and removes) the old
`photogimp-ai` plug-in.

## API keys and providers

Set the keys in `config.sh`; the setup writes them to shared key files
read by **all** the plug-ins, on the host **and** inside the Flatpak
sandbox (this is what fixes "No Gemini API key found" on Flatpak GIMP):

```
~/.config/PhotoGIMP/gemini-api-key
~/.config/PhotoGIMP/openai-api-key
~/.var/app/org.gimp.GIMP/config/PhotoGIMP/…   (sandbox copies)
```

| Provider | Key / requirement | Cost |
|---|---|---|
| **Gemini / Nano Banana** | Free key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey) | Free tier (daily quota) |
| **OpenAI gpt-image-1** | Key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys); may require one-time organization verification | Paid (prepaid credits, ~US$0.02–0.19/image) |
| **IOPaint / LaMa** | `pipx install iopaint && iopaint start --model=lama --port=8080` | Free, local |
| **Stable Diffusion WebUI** | [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui) with `--api` on port 7860 | Free, local |

Environment overrides: `PHOTOGIMP_IOPAINT_URL`, `PHOTOGIMP_A1111_URL`,
`GEMINI_IMAGE_MODEL`.

> **Privacy:** online providers (Gemini, OpenAI) upload the selected
> region plus some context. Use the local providers for images you can't
> share.

## Troubleshooting

- **Tools missing from Filters → AI** — restart GIMP; the setup clears
  `pluginrc` so GIMP re-scans plug-ins on the next start.
- **"No Gemini API key found"** — re-run `./setup.sh` with
  `GEMINI_API_KEY` set in `config.sh`, or create the key files above
  manually.
- **"HTTP 429: Too Many Requests" from Gemini** — the free tier only
  allows a few image requests per minute and per day. The plug-ins retry
  once automatically when Google suggests a short delay; otherwise wait a
  minute, check your quota at
  [aistudio.google.com/usage](https://aistudio.google.com/usage), or use
  a local backend (IOPaint / SD WebUI), which has no limits.
- **OpenAI 403 / verification error** — gpt-image-1 may require verifying
  your organization at platform.openai.com → Settings → Organization.
- **Layer Composite fails with a Gemini key** — it always uses OpenAI;
  set an OpenAI key.
