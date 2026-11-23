import re
from pathlib import Path

import pytest

import ui_theme as ui

ROOT = Path(__file__).resolve().parent.parent
EVIL = '<script>alert(1)</script>"><img src=x onerror=alert(2)>'
# Pictographs, dingbats, variation selector, regional indicators. Plain typographic
# marks such as quotes, dashes and arrows are deliberately not in this range.
EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍]")


def _all_markup() -> list[str]:
    return [
        ui.masthead(), ui.notice(), ui.footer(), ui.section_title("Results"),
        ui.result_block("Acne", 0.9, "high", "hint"), ui.bar_row("Acne", 0.4),
        ui.product_card("Acne", 0.5, "https://amzn.to/x", "acne treatment", True),
        ui.product_card("Facial Hair", 0.2, "https://www.amazon.in/s?k=x", None, False),
        ui.step_label("Preparing photo"), ui.progress_bar(0.5), ui.css("Atelier"),
    ]


# --- safety -----------------------------------------------------------------

def test_product_card_escapes_untrusted_search_terms():
    # Search terms come from an Amazon redirect header, so they are untrusted.
    out = ui.product_card("Acne", 0.9, "https://amzn.to/x", EVIL, curated=True)
    # Text like "onerror=" may remain as visible, harmless text; live tags must not.
    assert "<script" not in out and "<img" not in out
    assert "&lt;script&gt;" in out and "&lt;img" in out
    assert out.count("<a ") == 1  # no injected extra elements


def test_product_card_escapes_condition_and_url():
    out = ui.product_card(EVIL, 0.5, 'https://amzn.to/x"><script>alert(1)</script>', None, False)
    assert "<script" not in out
    assert len(re.findall(r'href="', out)) == 1  # exactly one, still well formed


def test_product_link_is_sponsored_and_new_tab():
    out = ui.product_card("Acne", 0.9, "https://amzn.to/x", None, True)
    assert 'rel="noopener noreferrer sponsored"' in out and 'target="_blank"' in out


def test_result_and_bars_escape_labels():
    assert "<script" not in ui.result_block(EVIL, 0.5, "high", EVIL)
    assert "<script" not in ui.bar_row(EVIL, 0.2)
    assert "<script" not in ui.step_label(EVIL) and "<script" not in ui.section_title(EVIL)


# --- numbers ----------------------------------------------------------------

@pytest.mark.parametrize("p", [-1, 0, 0.5, 1, 7])
def test_probabilities_are_clamped(p):
    out = ui.bar_row("x", p) + ui.result_block("x", p, "low", "") + ui.progress_bar(p)
    widths = [float(n) for n in re.findall(r"width:(-?[\d.]+)%", out)]
    assert widths and all(0 <= w <= 100 for w in widths)


def test_score_never_claims_100():
    # Regression: 99.75% used to be rounded to "100%".
    assert ">99%+<" in ui.result_block("Acne", 0.9975, "high", "")
    assert ">85%<" in ui.result_block("Rosacea", 0.854, "high", "")
    assert ">31%<" in ui.result_block("Blemishes", 0.309, "low", "")
    assert ui.pct_text(0.9999) == "99%+" and ui.pct_text(0.854) == "85.4%"


# --- palettes & css ---------------------------------------------------------

@pytest.mark.parametrize("name", list(ui.PALETTES))
@pytest.mark.parametrize("mode", ["light", "dark"])
def test_every_palette_defines_every_colour(name, mode):
    colours = ui.palette(name, mode)
    assert set(colours) == {"bg", "side", "accent", "on"}
    assert all(re.fullmatch(r"#[0-9A-Fa-f]{6}", v) for v in colours.values())


@pytest.mark.parametrize("name", list(ui.PALETTES))
def test_css_contains_both_modes_and_is_balanced(name):
    css = ui.css(name)
    for mode in ("light", "dark"):
        assert ui.palette(name, mode)["accent"] in css
    assert "prefers-color-scheme:dark" in css
    assert css.count("{") == css.count("}")


def test_accents_are_readable_on_their_buttons():
    """Button text (on) must contrast with the accent fill: WCAG ratio >= 4.5."""
    def lum(hex_):
        r, g, b = (int(hex_[i:i + 2], 16) / 255 for i in (1, 3, 5))
        f = lambda c: c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
        return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b)

    for name in ui.PALETTES:
        for mode in ("light", "dark"):
            c = ui.palette(name, mode)
            hi, lo = sorted((lum(c["accent"]), lum(c["on"])), reverse=True)
            assert (hi + 0.05) / (lo + 0.05) >= 4.5, (name, mode)


def test_unknown_palette_falls_back():
    assert ui.palette("nope") == ui.palette(ui.DEFAULT_PALETTE)


def test_no_gradients_in_the_design():
    assert "gradient" not in ui.css("Atelier")


# --- no external requests ---------------------------------------------------

def test_fonts_are_embedded_not_fetched():
    fonts = ui.font_css()
    assert "Inter" in fonts and "Newsreader" in fonts
    assert "data:font/woff2;base64," in fonts
    assert "http" not in fonts and "@import" not in fonts
    assert "http" not in ui.css("Atelier")


def test_font_files_ship_with_a_licence_note():
    assert (ROOT / "assets/fonts/Inter.woff2").stat().st_size > 10_000
    assert (ROOT / "assets/fonts/Newsreader.woff2").stat().st_size > 10_000
    assert "Open Font License" in (ROOT / "assets/fonts/README.md").read_text()


# --- no emoji ---------------------------------------------------------------

def test_no_emoji_in_generated_markup():
    for markup in _all_markup():
        assert not EMOJI.search(markup), EMOJI.search(markup)


@pytest.mark.parametrize("name", ["streamlit_app.py", "ui_theme.py", "recommendations.py", "model.py"])
def test_no_emoji_in_source(name):
    text = (ROOT / name).read_text()
    assert not EMOJI.search(text), f"{name}: {EMOJI.search(text).group()!r}"


# --- markup hygiene ---------------------------------------------------------

def test_html_builders_have_no_newlines():
    # Streamlit's markdown renderer turns these into paragraph breaks / code blocks.
    for s in _all_markup()[:-1]:  # the CSS block is not passed through that renderer's HTML rules
        assert "\n" not in s


def test_masthead_heading_children_inherit_the_serif():
    # Regression: Streamlit wraps heading text in a span with an st-emotion class, and the
    # global sans rule hit that span, so the title rendered in Inter instead of Newsreader.
    assert ".mast h1 *{font-family:inherit!important}" in ui.css("Atelier")
