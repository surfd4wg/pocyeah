"""Pure terminal colour themes (part of N7). No I/O, no font, no screen.

The emulator (pyte) reports each cell's colour as one of the eight ANSI names
('red', 'blue', …), the literal 'default', or a six-hex-digit string for
256-colour / true-colour output. `Theme.rgb()` turns any of those into a
concrete `(r, g, b)` for the renderer, so the mapping is data, not scattered
conditionals — and unit-testable without drawing a pixel.
"""
from __future__ import annotations

from dataclasses import dataclass

RGB = tuple[int, int, int]

# The eight ANSI names in their normal and bold ("bright") shades. Values are the
# widely-used "campbell"-ish palette — readable on a dark ground and recognisable.
_NORMAL: dict[str, RGB] = {
    "black": (40, 42, 46),
    "red": (224, 108, 117),
    "green": (152, 195, 121),
    "brown": (229, 192, 123),  # pyte calls ANSI yellow "brown"
    "blue": (97, 175, 239),
    "magenta": (198, 120, 221),
    "cyan": (86, 182, 194),
    "white": (220, 223, 228),
}
_BRIGHT: dict[str, RGB] = {
    "black": (90, 93, 100),
    "red": (255, 133, 141),
    "green": (176, 220, 143),
    "brown": (255, 215, 145),
    "blue": (130, 200, 255),
    "magenta": (222, 145, 245),
    "cyan": (110, 206, 218),
    "white": (255, 255, 255),
}


@dataclass(frozen=True)
class Theme:
    name: str
    bg: RGB  # canvas / terminal background
    fg: RGB  # default foreground
    title_bg: RGB  # pane title-bar fill
    title_fg: RGB  # pane title-bar text
    cursor: RGB  # block-cursor colour

    def rgb(self, color: str, *, bold: bool = False, foreground: bool = True) -> RGB:
        """Resolve a pyte colour token to an (r, g, b).

        'default' maps to this theme's fg (foreground) or bg (background). A named
        ANSI colour uses the bright shade when `bold` is set — the common terminal
        convention. A six-hex-digit string is parsed literally. Anything
        unrecognised falls back to the sensible default for its role.
        """
        if color == "default" or not color:
            return self.fg if foreground else self.bg
        table = _BRIGHT if bold else _NORMAL
        if color in table:
            return table[color]
        if len(color) == 6:
            try:
                return (int(color[0:2], 16), int(color[2:4], 16), int(color[4:6], 16))
            except ValueError:
                pass
        return self.fg if foreground else self.bg


DARK = Theme(
    name="dark",
    bg=(24, 26, 30),
    fg=(220, 223, 228),
    title_bg=(52, 56, 64),
    title_fg=(255, 255, 255),
    cursor=(200, 203, 208),
)

LIGHT = Theme(
    name="light",
    bg=(250, 250, 250),
    fg=(40, 42, 46),
    title_bg=(220, 222, 226),
    title_fg=(20, 20, 20),
    cursor=(40, 42, 46),
)

_THEMES = {t.name: t for t in (DARK, LIGHT)}


def get_theme(name: str) -> Theme:
    """Look up a theme by name ('dark' | 'light'). Raises KeyError otherwise."""
    return _THEMES[name]


def theme_names() -> tuple[str, ...]:
    return tuple(_THEMES)
