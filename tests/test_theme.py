import pytest

from pocyeah.theme import DARK, LIGHT, get_theme, theme_names


def test_default_maps_to_fg_or_bg_by_role():
    assert DARK.rgb("default", foreground=True) == DARK.fg
    assert DARK.rgb("default", foreground=False) == DARK.bg
    assert DARK.rgb("", foreground=True) == DARK.fg


def test_named_ansi_colour_resolves_and_bold_brightens():
    normal = DARK.rgb("red", bold=False)
    bright = DARK.rgb("red", bold=True)
    assert normal != bright  # bold selects the bright shade
    assert all(0 <= c <= 255 for c in normal)


def test_six_hex_digit_colour_is_parsed_literally():
    assert DARK.rgb("ff8800") == (255, 136, 0)


def test_unrecognised_token_falls_back_to_role_default():
    assert DARK.rgb("nonsense", foreground=True) == DARK.fg
    assert DARK.rgb("zzzzzz", foreground=False) == DARK.bg


def test_registry_lookup():
    assert get_theme("dark") is DARK
    assert get_theme("light") is LIGHT
    assert set(theme_names()) == {"dark", "light"}
    with pytest.raises(KeyError):
        get_theme("solarized")
