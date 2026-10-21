"""Contraste WCAG 1.4.3 dos selos da configuração (texto na cor do tema sobre fundo suave da cor do selo)."""
import pytest

TONES = ["#d97736", "#10a37f", "#4285f4", "#27ae60", "#f39c12", "#7f8c8d"]
# (texto, fundo) dos esquemas Breeze Light e Breeze Dark
THEMES = {"BreezeLight": ("#232629", "#eff0f1"), "BreezeDark": ("#fcfcfc", "#31363b")}


def lum(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]


def ratio(a, b):
    la, lb = sorted((lum(a), lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def blend(fg, bg, a):
    f = [int(fg[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(bg[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(round(a * x + (1 - a) * y) for x, y in zip(f, b))


@pytest.mark.parametrize("theme", THEMES)
@pytest.mark.parametrize("tone", TONES)
def test_badge_text_is_at_least_4_5_on_its_tinted_background(theme, tone):
    text, bg = THEMES[theme]
    assert ratio(text, blend(tone, bg, 0.18)) >= 4.5  # mesma alfa 0,18 de configGeneral.qml


def test_old_white_on_solid_badges_failed():
    assert max(ratio("#ffffff", t) for t in ("#27ae60", "#f39c12", "#7f8c8d")) < 4.5  # o defeito que isto corrige


@pytest.mark.parametrize("theme,bgs", [("BreezeLight", ["#eff0f1", "#fcfcfc"]), ("BreezeDark", ["#31363b", "#232629"])])
def test_secondary_text_at_70_percent_is_at_least_4_5_on_theme_backgrounds(theme, bgs):
    for bg in bgs:  # configGeneral.qml: Qt.alpha(textColor, 0.7); o disabledTextColor antigo (#707d8a) dava 3,69:1 no claro
        assert ratio(blend(THEMES[theme][0], bg, 0.7), bg) >= 4.5
    assert ratio("#707d8a", "#eff0f1") < 4.5
