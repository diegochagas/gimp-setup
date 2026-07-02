# 🤖 PhotoGIMP AI Tools — Remove & Generative Fill

A GIMP 3 plug-in that brings two Photoshop AI features to GIMP:

| Tool | Photoshop equivalent | Where it appears in GIMP |
|---|---|---|
| **Remove Selection (AI)** | Remove Tool | **Filters → AI → Remove Selection (AI)...** |
| **Generative Fill** | Generative Fill | **Edit → Generative Fill...** and **Filters → AI** |

> **Why not toolbox tools?** GIMP plug-ins cannot add new tools to the toolbox
> (tools and tool groups, like Clone/Perspective Clone, are core C code).
> Menu actions + shortcuts are the plug-in equivalent — and GIMP's **Quick
> Mask** gives you the same brush-to-select feel as Photoshop's Remove tool
> (see below).

## 🖱 How to use

### Remove an object (like Photoshop's Remove Tool)

1. Press <kbd>Q</kbd> (Quick Mask) and **paint over the object with any
   brush** — the painted area shows as a semi-transparent red overlay,
   exactly like Photoshop's Remove brush. Press <kbd>Q</kbd> again to turn
   your painting into a selection.
   *(Any selection works too: Lasso, rectangle, Fuzzy Select...)*
2. Run **Filters → AI → Remove Selection (AI)...**
3. Pick a backend and press OK. The reconstructed background appears as a
   new layer, masked so **only the selected area changes**.

### Generative Fill (text prompt)

1. Select the area you want to replace or generate into.
2. Run **Edit → Generative Fill...**
3. Type a prompt (e.g. *"a wooden fence with ivy"*), pick a backend, OK.
4. The result comes back **only inside the selection**, on its own layer
   with a feathered layer mask so it blends with the rest of the image.
   Don't like it? Delete the layer and run it again.

The plug-in sends the selection *plus some surrounding context* (the
"Context padding" option) so the AI matches the scene's lighting, texture
and perspective.

## ⚙ Installation

Installed by `features/ai-tools.sh` (priority 80) as part of the setup:

```bash
./setup.sh
```

Then restart GIMP. The feature installs the bundled plug-in
(`assets/plug-ins/photogimp-ai/photogimp-ai.py`) into every GIMP 3.x
profile it finds (native `~/.config/GIMP/3.x` and Flatpak), and saves the
`GEMINI_API_KEY` from `config.sh` to `~/.config/PhotoGIMP/gemini-api-key`
automatically when set.

## 🔌 Backends

Pick the backend in the tool dialog (your choice is remembered).

### Gemini / Nano Banana (online — default)

Google's image model, with a **free API tier**. Works for both Remove and
Generative Fill; no local install needed.

1. Create a free key at <https://aistudio.google.com/apikey>
2. Save it (recommended):
   ```bash
   mkdir -p ~/.config/PhotoGIMP
   echo "YOUR_KEY_HERE" > ~/.config/PhotoGIMP/gemini-api-key
   chmod 600 ~/.config/PhotoGIMP/gemini-api-key
   ```
   or export `GEMINI_API_KEY` in the environment GIMP starts from.

> **Privacy note:** the selected region + padding is uploaded to Google.
> Don't use the online backend for images you can't share; use a local
> backend instead.

### IOPaint / LaMa (local — best for Remove)

Fast, free, runs fully on your machine, no prompt support (Remove only):

```bash
pipx install iopaint
iopaint start --model=lama --port=8080
```

Custom address: set `PHOTOGIMP_IOPAINT_URL`.

### Stable Diffusion WebUI (local — prompt fills)

Run [AUTOMATIC1111](https://github.com/AUTOMATIC1111/stable-diffusion-webui)
with the `--api` flag (an inpainting model is recommended). Works for both
tools. Custom address: set `PHOTOGIMP_A1111_URL`.

### What about Adobe Firefly?

Firefly's Generative Fill API is **enterprise-only** (paid OAuth
server-to-server credentials; there are no free personal API keys), so it
is not included. The backend system is pluggable — a Firefly backend would
slot into `photogimp-ai.py` next to the others if you have enterprise
access.

## 🧰 Troubleshooting

- **The menu items don't appear** — make sure the file is executable
  (`chmod +x .../plug-ins/photogimp-ai/photogimp-ai.py`) and that the
  folder name matches the file name (`photogimp-ai/photogimp-ai.py`).
  Restart GIMP.
- **"Select the area first"** — both tools operate on the current
  selection; make one (or paint it with Quick Mask).
- **Gemini errors** — check the API key, and note the free tier has daily
  quotas. The model may also refuse certain content.
- **Result looks slightly off in tone (Gemini)** — Gemini re-renders the
  whole context crop; only the selection is composited back, but tones
  inside it can shift. Local Stable Diffusion inpainting is usually more
  seamless; or increase context padding.
- **Errors mid-run** — the plug-in adds its result as a new layer at the
  end; a failed run leaves your image untouched.
