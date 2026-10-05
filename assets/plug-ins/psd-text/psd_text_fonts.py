# Font matching for the "PSD with editable text" plug-in: Photoshop
# PostScript names <-> the "Family Style" names GIMP 3 lists, through
# fontconfig (fc-list / fc-match, available inside the GIMP Flatpak too).
#
# Vendored from comic-skills/psd-xcf-convert/scripts/convert.py
# (https://github.com/diegochagas/comic-skills), see PATCHES.md.

from __future__ import annotations

import re
import subprocess


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


# ------------------------------------------------------------------ fonts

class Fonts:
    """fontconfig's view of the installed fonts: PostScript name <-> the
    "Family Style" names GIMP 3 lists."""

    def __init__(self) -> None:
        self.entries: list[dict] = []
        try:
            out = subprocess.run(["fc-list", "-f", "%{family}\t%{style}\t%{fullname}\t%{postscriptname}\n"],
                                 capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            out = ""
        seen = set()
        for line in out.splitlines():
            parts = line.split("\t")
            if len(parts) != 4 or line in seen:
                continue
            seen.add(line)
            fam, sty, full, ps = ([p.strip().replace("\\-", "-") for p in x.split(",") if p.strip()] for x in parts)
            if fam:
                self.entries.append({"family": fam, "style": sty or ["Regular"], "fullname": full, "ps": ps[0] if ps else ""})
        self.by_ps = {norm(e["ps"]): e for e in self.entries if e["ps"]}
        self.by_name: dict[str, dict] = {}
        # A font's own (first) family wins over the alias families other fonts
        # declare: "Impacted" also calls itself "Impact", and must not take
        # "Impact Regular" from Impact just because fontconfig lists it first.
        for primary in (True, False):
            for e in self.entries:
                fams = e["family"][:1] if primary else e["family"][1:]
                for f in fams:
                    for s in e["style"]:
                        self.by_name.setdefault(norm(f + s), e)
                    if any(norm(s) in ("regular", "normal", "book", "roman") for s in e["style"]):
                        self.by_name.setdefault(norm(f), e)
                if primary:
                    for n in e["fullname"][:1]:
                        self.by_name.setdefault(norm(n), e)
                else:
                    for n in e["fullname"][1:]:
                        self.by_name.setdefault(norm(n), e)

    @staticmethod
    def gimp_names(e: dict) -> list[str]:
        names = [f"{f} {s}" for f in e["family"] for s in e["style"]] + e["fullname"] + e["family"]
        return list(dict.fromkeys(names))

    def _fc_match(self, pattern: str) -> dict | None:
        try:
            out = subprocess.run(["fc-match", "-f", "%{family}\t%{style}\t%{fullname}\t%{postscriptname}", pattern],
                                 capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            return None
        parts = out.split("\t")
        if len(parts) != 4:
            return None
        fam, sty, full, ps = ([p.strip() for p in x.split(",") if p.strip()] for x in parts)
        return {"family": fam, "style": sty or ["Regular"], "fullname": full, "ps": ps[0] if ps else ""} if fam else None

    def to_gimp(self, psname: str, font_map: dict[str, str]) -> dict:
        """{"gimp": [candidate names], "substitute": bool} for a Photoshop font name."""
        if psname in font_map:
            e = self.by_name.get(norm(font_map[psname]))
            return {"gimp": [font_map[psname]] + (self.gimp_names(e) if e else []), "substitute": False}
        e = self.by_ps.get(norm(psname)) or self.by_name.get(norm(psname))
        if e:
            return {"gimp": self.gimp_names(e), "substitute": False}
        # not installed: "Arial-BoldMT" -> family "Arial", style "Bold" -> fontconfig's closest font
        fam, _, sty = psname.partition("-")
        strip = lambda s: re.sub(r"(PS)?MT$|PS$", "", s)
        fam = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", strip(fam))
        sty = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", strip(sty)).strip()
        m = self._sibling(fam, sty) or self._fc_match(fam + (f":style={sty}" if sty else ""))
        return {"gimp": self.gimp_names(m) if m else [], "substitute": True}

    @staticmethod
    def _flags(style: str) -> tuple[bool, bool]:
        s = norm(style)
        return (any(k in s for k in ("bold", "black", "heavy")), any(k in s for k in ("italic", "oblique")))

    def _sibling(self, fam: str, sty: str) -> dict | None:
        """An installed font of the same type family ("CCWildWordsLower-BoldItalic"
        missing, "CCWildWords Bold Italic" installed) beats fontconfig's generic
        sans: same bold/italic first, then the longest shared family name."""
        want, key, best = self._flags(sty), norm(fam), None
        for e in self.entries:
            for f in e["family"]:
                n = norm(f)
                if len(n) >= 5 and (key.startswith(n) or n.startswith(key)):
                    score = (self._flags(" ".join(e["style"]) + " " + f[len(fam):]) == want, min(len(n), len(key)))
                    if best is None or score > best[0]:
                        best = (score, e)
        return best[1] if best else None

    def family_variant(self, e: dict, bold: bool, italic: bool) -> dict | None:
        def flags(x: dict) -> tuple[bool, bool]:
            return self._flags(" ".join(x["style"]))
        have = flags(e)
        want = (have[0] or bold, have[1] or italic)
        for x in self.entries:
            if set(x["family"]) & set(e["family"]) and flags(x) == want and x["ps"]:
                return x
        return None

    def to_ps(self, run: dict, font_back: dict[str, str]) -> tuple[str, bool, bool, str | None]:
        """(PostScript name, fauxBold, fauxItalic, note) for a run described by GIMP."""
        name = run.get("gimp_font") or ""
        bold, italic = bool(run.get("bold")), bool(run.get("italic"))
        if name in font_back and not bold and not italic:
            return font_back[name], False, False, None      # the font the PSD originally asked for
        e = self.by_ps.get(norm(run.get("psname") or "")) or self.by_name.get(norm(name))
        note = None
        if e is None:
            e = self._fc_match(name) if name else None
            note = f'font "{name}" not found by fontconfig: wrote "{e["ps"] if e else "ArialMT"}"'
        if e is None or not e["ps"]:
            return run.get("psname") or "ArialMT", bold, italic, note
        if bold or italic:
            v = self.family_variant(e, bold, italic)
            if v:
                return v["ps"], False, False, note
            return e["ps"], bold, italic, note                # no such cut installed: Photoshop's faux style
        return e["ps"], False, False, note
