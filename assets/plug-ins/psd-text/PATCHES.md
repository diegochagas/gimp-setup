# Vendored code

From [comic-skills](https://github.com/diegochagas/comic-skills)
`psd-xcf-convert/` (the batch PSD ⇄ XCF converter), commit `baa299d`:

| Here | There | Changes |
|---|---|---|
| `psd_text_gimp.py` | `scripts/gimp_convert_job.py` | Batch-job wrapper removed (job JSON, log file, `load`/`save`, `main`); the two halves are importable functions: `apply_psd_text()` (was `psd2xcf`) and `describe_image()` (was `xcf2psd`). Fonts come in as a mapping instead of a task. Text language follows the PSD (Adobe code ⇄ GIMP tag for en-us / pt / pt-br) instead of always `pt-br`, and is written per layer on export. A text layer made in the running session (no `gimp-text-layer` parasite yet) gets its box mode from our own parasite or from a size that is not the text's natural one. |
| `psd_text_fonts.py` | `scripts/convert.py` | Only the `Fonts` class and `norm()`. |
| `psd_text_info.mjs` | `scripts/psd_text_info.mjs` | Also reports each run's `language`. Comments. |
| `write_psd_text.mjs` | `scripts/write_psd_text.mjs` | Language from the description (`t.language`), English: USA when absent, instead of always Portuguese: Brazilian. Comments. |
| `package.json`, `package-lock.json` | same | Package renamed; same pinned ag-psd 31.0.2. |

`psd-text.py` (the GIMP plug-in that registers the PSD open/export
procedures and calls the above) is new here.

Later changes here (not upstream): Photoshop text rotated 90° opens as GIMP
vertical text and tilted / squeezed text as a rotated text smart object
(both exported back as rotated Type layers); every Layer Style effect opens
as an editable Layer Style through `layer_style_engine.py` (from
`assets/plug-ins/layer-style`) and is written back as the matching
Photoshop effect; `psd_text_fonts.py` lets a font's own family win over
alias families other fonts declare ("Impacted" also calls itself "Impact").
