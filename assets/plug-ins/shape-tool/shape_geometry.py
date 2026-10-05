# Shape geometry for the Shape Tool plug-in: Photoshop's Rectangle, Ellipse,
# Triangle, Polygon, Line and Custom Shape tools as paths fitted to a box.
#
# A shape is a list of subpaths; a subpath is (closed, [anchor, ...]) and an
# anchor is (in-handle, point, out-handle), each an (x, y) pair: the
# control-point order GIMP's bezier strokes use. Ellipses use GIMP's own
# ellipse stroke instead: ("ellipse", cx, cy, rx, ry).

import math

KAPPA = 0.5522847498          # cubic bezier handle length for a quarter circle

SHAPES = [
    ("rectangle", "Rectangle Tool"),
    ("ellipse", "Ellipse Tool"),
    ("triangle", "Triangle Tool"),
    ("polygon", "Polygon Tool"),
    ("line", "Line Tool"),
    ("custom", "Custom Shape Tool"),
]

# Custom shapes in a unit square, as path data (absolute M, L, C, Z only),
# like Photoshop's default custom shapes.
CUSTOM = {
    "heart": ("Heart",
              "M 0.5 0.95 C 0.1 0.66 0 0.42 0 0.27 C 0 0.1 0.13 0 0.28 0 C 0.39 0 0.47 0.07 0.5 0.16 "
              "C 0.53 0.07 0.61 0 0.72 0 C 0.87 0 1 0.1 1 0.27 C 1 0.42 0.9 0.66 0.5 0.95 Z"),
    "star": ("Star", None),                     # built by polygon(), 5 points
    "arrow": ("Arrow", "M 0 0.32 L 0.58 0.32 L 0.58 0.05 L 1 0.5 L 0.58 0.95 L 0.58 0.68 L 0 0.68 Z"),
    "speech": ("Speech Bubble",
               "M 0.18 0 L 0.82 0 C 0.92 0 1 0.08 1 0.18 L 1 0.58 C 1 0.68 0.92 0.76 0.82 0.76 L 0.42 0.76 "
               "L 0.2 1 L 0.25 0.76 L 0.18 0.76 C 0.08 0.76 0 0.68 0 0.58 L 0 0.18 C 0 0.08 0.08 0 0.18 0 Z"),
    "burst": ("Burst", None),                   # built by polygon(), 16 points
    "check": ("Check Mark", "M 0 0.55 L 0.14 0.41 L 0.38 0.65 L 0.86 0.08 L 1 0.22 L 0.38 0.94 Z"),
    "lightning": ("Lightning", "M 0.55 0 L 0.12 0.58 L 0.45 0.58 L 0.32 1 L 0.88 0.36 L 0.52 0.36 L 0.7 0 Z"),
    "cross": ("Cross", "M 0.35 0 L 0.65 0 L 0.65 0.35 L 1 0.35 L 1 0.65 L 0.65 0.65 L 0.65 1 L 0.35 1 "
                       "L 0.35 0.65 L 0 0.65 L 0 0.35 L 0.35 0.35 Z"),
}

DEFAULTS = {"shape": "rectangle", "radius": 0, "sides": 5, "star": False, "indent": 50,
            "line_direction": "horizontal", "custom": "heart",
            "fill": True, "fill_color": "#000000", "stroke": False, "stroke_color": "#000000",
            "stroke_width": 3}


def corner(p):
    return (p, p, p)


def polyline(points, closed=True):
    return [(closed, [corner(p) for p in points])]


def rounded_rect(x, y, w, h, r):
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    if r < 0.5:
        return polyline([(x, y), (x + w, y), (x + w, y + h), (x, y + h)])
    k = r * KAPPA
    x2, y2 = x + w, y + h
    # each corner: the point where the straight edge meets the arc, with
    # the handle pointing along the arc
    anchors = [
        ((x + r - k, y), (x + r, y), (x + r, y)), ((x2 - r, y), (x2 - r, y), (x2 - r + k, y)),
        ((x2, y + r - k), (x2, y + r), (x2, y + r)), ((x2, y2 - r), (x2, y2 - r), (x2, y2 - r + k)),
        ((x2 - r + k, y2), (x2 - r, y2), (x2 - r, y2)), ((x + r, y2), (x + r, y2), (x + r - k, y2)),
        ((x, y2 - r + k), (x, y2 - r), (x, y2 - r)), ((x, y + r), (x, y + r), (x, y + r - k)),
    ]
    return [(True, anchors)]


def polygon(x, y, w, h, sides, star=False, indent=50):
    """Regular polygon or star inscribed in the box's ellipse, a point up."""
    cx, cy, rx, ry = x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0
    n = max(3, int(sides))
    pts = []
    steps = n * 2 if star else n
    for i in range(steps):
        a = -math.pi / 2 + i * math.pi * 2 / steps
        f = (1 - indent / 100.0) if (star and i % 2) else 1.0
        pts.append((cx + rx * f * math.cos(a), cy + ry * f * math.sin(a)))
    return polyline(pts)


def parse_path(data, x, y, w, h):
    """Unit-square path data -> subpaths in the box."""
    tok = data.replace(",", " ").split()
    i, subpaths, anchors = 0, [], []

    def pt():
        nonlocal i
        p = (x + float(tok[i]) * w, y + float(tok[i + 1]) * h)
        i += 2
        return p

    while i < len(tok):
        cmd = tok[i]
        i += 1
        if cmd == "M":
            if anchors:
                subpaths.append((False, anchors))
            anchors = [corner(pt())]
        elif cmd == "L":
            anchors.append(corner(pt()))
        elif cmd == "C":
            c1, c2, p = pt(), pt(), pt()
            inn, a, _out = anchors[-1]
            anchors[-1] = (inn, a, c1)
            anchors.append((c2, p, p))
        elif cmd == "Z":
            # a closing point on the start merges into it
            if len(anchors) > 1 and math.dist(anchors[-1][1], anchors[0][1]) < 1e-6:
                last = anchors.pop()
                anchors[0] = (last[0], anchors[0][1], anchors[0][2])
            subpaths.append((True, anchors))
            anchors = []
    if anchors:
        subpaths.append((False, anchors))
    return subpaths


def line(x, y, w, h, direction):
    if direction == "vertical":
        a, b = (x + w / 2.0, y), (x + w / 2.0, y + h)
    elif direction == "diagonal_down":
        a, b = (x, y), (x + w, y + h)
    elif direction == "diagonal_up":
        a, b = (x, y + h), (x + w, y)
    else:
        a, b = (x, y + h / 2.0), (x + w, y + h / 2.0)
    return polyline([a, b], closed=False)


def build(settings, box):
    """settings (DEFAULTS keys) + box (x, y, w, h) -> subpaths or an
    ("ellipse", cx, cy, rx, ry) tuple."""
    s = {**DEFAULTS, **settings}
    x, y, w, h = box
    kind = s["shape"]
    if kind == "rectangle":
        return rounded_rect(x, y, w, h, float(s["radius"]))
    if kind == "ellipse":
        return ("ellipse", x + w / 2.0, y + h / 2.0, w / 2.0, h / 2.0)
    if kind == "triangle":
        return polyline([(x + w / 2.0, y), (x + w, y + h), (x, y + h)])
    if kind == "polygon":
        return polygon(x, y, w, h, s["sides"], s["star"], s["indent"])
    if kind == "line":
        return line(x, y, w, h, s["line_direction"])
    name = s["custom"]
    if name == "star":
        return polygon(x, y, w, h, 5, True, 55)
    if name == "burst":
        return polygon(x, y, w, h, 16, True, 22)
    return parse_path(CUSTOM.get(name, CUSTOM["heart"])[1], x, y, w, h)


def is_closed(settings):
    return {**DEFAULTS, **settings}["shape"] != "line"
