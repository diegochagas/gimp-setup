#!/usr/bin/env python3
"""Points a GIMP 3 profile at the Photoshop theme (features/photoshop-theme.sh).

Usage: apply_photoshop_layout.py <profile dir> [--check]

  gimprc     (theme "Photoshop"), and the canvas padding (the area around
             the image) set to Photoshop's pasteboard grey, #282828, in both
             the normal and the fullscreen view.
  sessionrc  dock tabs that show only an icon show the dialog name instead
             ("Layers", "Channels", "Paths"), like Photoshop's panel tabs.
             Tabs with previews (brushes, patterns...) are left alone.

Idempotent. With --check nothing is written: exit 0 when the profile is
already configured, 1 when it would change. Prints one line per change.
"""

import re
import sys
from pathlib import Path

THEME = "Photoshop"
# GIMP 3 color serialization: format, byte count, bytes, ICC profile length
# (40,40,40 = #282828, octal escapes as GIMP itself writes them, so its
# own rewrite of gimprc on exit leaves the line byte-identical)
PADDING_COLOR = '(color "R\'G\'B\' u8" 3 "\\50\\50\\50" 0)'
PADDING_COLORS = (PADDING_COLOR, '(color "R\'G\'B\' u8" 3 "(((" 0)')
PADDING = f"    (padding-mode custom)\n    (padding-color\n        {PADDING_COLOR})"
VIEWS = ("default-view", "default-fullscreen-view")


def top_level_forms(text):
    """(start, end, name) of every top-level (name ...) form, aware of strings."""
    forms, depth, start, in_str, esc = [], 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            if depth == 0:
                start = i
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0 and start is not None:
                m = re.match(r"\(([\w-]+)", text[start:])
                forms.append((start, i + 1, m.group(1) if m else ""))
                start = None
    return forms


def strip_comments(text):
    """Comment lines blanked with spaces: same length, so offsets still match."""
    return "\n".join(" " * len(l) if l.startswith("#") else l for l in text.split("\n"))


def set_padding(form):
    """Replace padding-mode / padding-color inside a (default-view ...) form."""
    for key in ("padding-mode", "padding-color"):
        form = remove_child(form, key)
    return form[:-1].rstrip() + "\n" + PADDING + ")"


def remove_child(form, key):
    """Remove the child (key ...) of a form given as text starting with '('."""
    body = form[1:]
    for s, e, name in top_level_forms(body):
        if name == key:
            # forms are relative to body; drop the whole line(s) it occupies
            before = body[:s].rstrip(" ")
            after = body[e:]
            return "(" + before.rstrip("\n") + after
    return form


def configure_gimprc(text):
    changes = []
    clean = strip_comments(text)
    forms = top_level_forms(clean)
    names = {n: (s, e) for s, e, n in forms}

    out = text
    for view in VIEWS:
        if view in names:
            s, e = names[view]
            form = out[s:e]
            if any(c in form for c in PADDING_COLORS) and "(padding-mode custom)" in form:
                continue
            new = set_padding(form)
            out = out[:s] + new + out[e:]
            changes.append(f"gimprc: {view} padding -> #282828")
        else:
            out = out.rstrip("\n") + f"\n({view}\n{PADDING})\n"
            changes.append(f"gimprc: {view} padding -> #282828")
        clean = strip_comments(out)
        names = {n: (s, e) for s, e, n in top_level_forms(clean)}

    theme = f'(theme "{THEME}")'
    if "theme" in names:
        s, e = names["theme"]
        if out[s:e] != theme:
            out = out[:s] + theme + out[e:]
            changes.append(f"gimprc: {theme}")
    else:
        out = out.rstrip("\n") + f"\n{theme}\n"
        changes.append(f"gimprc: {theme}")
    return out, changes


def configure_sessionrc(text):
    n = text.count("(tab-style icon)")
    if not n:
        return text, []
    return text.replace("(tab-style icon)", "(tab-style name)"), [f"sessionrc: {n} dock tab(s) show their name"]


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    profile = Path(sys.argv[1])
    check = "--check" in sys.argv[2:]
    all_changes = []
    for name, fn in (("gimprc", configure_gimprc), ("sessionrc", configure_sessionrc)):
        path = profile / name
        text = path.read_text() if path.exists() else ""
        if name == "sessionrc" and not text:
            continue                     # GIMP writes it on first exit; default docks use icons
        new, changes = fn(text)
        all_changes += changes
        if changes and not check:
            path.write_text(new)
    for c in all_changes:
        print(c)
    return 1 if (check and all_changes) else 0


if __name__ == "__main__":
    sys.exit(main())
