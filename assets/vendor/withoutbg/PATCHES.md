# Vendored WithoutBG GIMP plug-in — gimp-setup patches

Upstream: https://github.com/withoutbg/withoutbg-gimp — pinned to commit
`ceccd5ea973274131143e7d1c65b8e721008a552`, GPL v3 or later (license
notice kept in the file header).

`withoutbg.py` carries the following gimp-setup patches (grep for
`gimp-setup patch`):

1. **`SERVER_URL` points to the self-hosted instance**
   `https://withoutbg.diegochagas.com` (upstream default is a local
   Docker/Mac server on `http://127.0.0.1:8000`). The URL can still be
   overridden per run in the plug-in dialog.
2. **API layout adapted to that instance** (service `withoutbg-api`):
   - health check at `GET /api/health` (upstream: `/health`),
   - removal via **multipart** `file` upload to
     `POST /api/remove-background` (upstream: raw `image/png` body to
     `/v1/remove-background?output=...`),
   - FastAPI-style `{"detail": ...}` error bodies parsed too.
3. **Local cutout → matte conversion** — that API returns the RGBA
   cutout instead of the grayscale matte the plug-in expects, so
   `_cutout_to_matte()` rebuilds the matte from the cutout's alpha
   channel (alpha → selection → white-on-black fill) before it is
   applied as the layer mask.

When bumping the upstream commit, re-apply these patches and update this
file.
