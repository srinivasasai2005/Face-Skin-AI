"""Look & feel for Face Skin AI: palettes, typography, CSS and HTML builders.

Design language: quiet and editorial. Flat surfaces, hairline borders, a serif for
headings and a sans for text, one muted accent colour per palette. No gradients,
no emoji, no drop shadows.

Rules that keep it safe and maintainable:

* Every string that did not come from this file is passed through ``html.escape``
  (condition names, and especially Amazon search terms, which are read from a
  redirect header and are therefore untrusted).
* HTML is emitted as single compact strings. Streamlit's markdown renderer treats
  indented lines and blank lines inside HTML as code / paragraph breaks.
* Neutral tones (borders, muted text, card fill) are derived from the current text
  colour with ``color-mix``, so they work in light and dark without extra values.
  Each palette only defines background, sidebar, accent and on-accent colours for
  each mode.
* No external requests: the fonts are embedded from ``assets/fonts``.
"""

from __future__ import annotations

import base64
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import quote

FONT_DIR = Path(__file__).with_name("assets") / "fonts"

# name -> mode -> colours. Accents are deliberately desaturated.
PALETTES: dict[str, dict[str, dict[str, str]]] = {
    "Atelier": {  # ink on warm ivory
        "light": {"bg": "#FAF8F4", "side": "#F1EDE6", "accent": "#242321", "on": "#FAF8F4"},
        "dark": {"bg": "#131312", "side": "#1A1A18", "accent": "#E9E4DA", "on": "#131312"},
    },
    "Sage": {  # deep sage on pale stone
        "light": {"bg": "#F7F8F4", "side": "#ECEFE7", "accent": "#4B6653", "on": "#F7F8F4"},
        "dark": {"bg": "#111412", "side": "#171B18", "accent": "#A8C1B0", "on": "#111412"},
    },
    "Marine": {  # navy on cool white
        "light": {"bg": "#F7F8FA", "side": "#ECEFF4", "accent": "#1F3A5F", "on": "#F7F8FA"},
        "dark": {"bg": "#0F131A", "side": "#151B24", "accent": "#A5BEE0", "on": "#0F131A"},
    },
    "Clay": {  # muted terracotta on warm paper
        "light": {"bg": "#FBF7F3", "side": "#F3EBE4", "accent": "#92503C", "on": "#FBF7F3"},
        "dark": {"bg": "#16120F", "side": "#1D1815", "accent": "#DBA894", "on": "#16120F"},
    },
    "Aubergine": {  # dusky plum on soft grey
        "light": {"bg": "#F8F6F8", "side": "#EEEAEF", "accent": "#573A55", "on": "#F8F6F8"},
        "dark": {"bg": "#141114", "side": "#1B171B", "accent": "#CDB0CB", "on": "#141114"},
    },
}
DEFAULT_PALETTE = "Atelier"

TIER_LABEL = {
    "high": ("tier-high", "High confidence"),
    "moderate": ("tier-moderate", "Moderate confidence"),
    "low": ("tier-low", "Low confidence"),
}


def palette(name: str, mode: str = "light") -> dict[str, str]:
    colours = PALETTES.get(name, PALETTES[DEFAULT_PALETTE])
    return colours["dark" if mode == "dark" else "light"]


@lru_cache(maxsize=1)
def font_css() -> str:
    """@font-face rules with the font files embedded as data URIs."""
    faces = []
    for family, filename, weights in (
        ("Inter", "Inter.woff2", "400 700"),
        ("Newsreader", "Newsreader.woff2", "400 600"),
    ):
        path = FONT_DIR / filename
        if not path.exists():  # fall back to the system stack instead of failing
            continue
        data = base64.b64encode(path.read_bytes()).decode()
        faces.append(
            f"@font-face{{font-family:'{family}';font-style:normal;font-weight:{weights};"
            f"font-display:swap;src:url(data:font/woff2;base64,{data}) format('woff2')}}"
        )
    return f"<style>{''.join(faces)}</style>"


def _vars(c: dict[str, str]) -> str:
    return f"--bg:{c['bg']};--side:{c['side']};--accent:{c['accent']};--on:{c['on']};"


def css(name: str) -> str:
    light, dark = palette(name, "light"), palette(name, "dark")
    return f"""<style>
:root{{{_vars(light)}--serif:Newsreader,"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
--sans:Inter,ui-sans-serif,-apple-system,"SF Pro Text","Segoe UI",Roboto,Helvetica,Arial,sans-serif;
--line:color-mix(in srgb,currentColor 14%,transparent);--fill:color-mix(in srgb,currentColor 4%,transparent);
--muted:color-mix(in srgb,currentColor 62%,transparent);--radius:8px}}
@media (prefers-color-scheme:dark){{:root{{{_vars(dark)}}}}}

html,body,.stApp,[class*="st-"]:not([data-testid="stIconMaterial"]){{font-family:var(--sans)}}
.stApp{{background:var(--bg)}}
[data-testid="stHeader"]{{background:transparent}}
[data-testid="stSidebar"],[data-testid="stSidebar"]>div{{background:var(--side)}}
[data-testid="stSidebar"]{{border-right:1px solid var(--line)}}
[data-testid="stMainBlockContainer"],.block-container{{max-width:860px;padding-top:2.6rem}}
#MainMenu,footer{{visibility:hidden}}

/* typography */
.eyebrow{{font-size:.7rem;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}}
.mast h1{{font-family:var(--serif);font-size:3.4rem;line-height:1.02;font-weight:500;letter-spacing:-.025em;
margin:.5rem 0 .9rem;padding:0}}
/* Streamlit wraps heading text in a span with an st-emotion class; without this it picks up the sans rule above */
.mast h1 *{{font-family:inherit!important}}
.lede{{font-size:1.08rem;line-height:1.6;max-width:540px;margin:0 0 1.4rem;color:var(--muted)}}
.facts{{display:flex;flex-wrap:wrap;gap:0;list-style:none;margin:0;padding:1rem 0 0;border-top:1px solid var(--line)}}
.facts li{{font-size:.72rem;font-weight:600;letter-spacing:.14em;text-transform:uppercase;padding:0 1.2rem 0 0;margin:0 1.2rem 0 0;
border-right:1px solid var(--line);line-height:1}}
.facts li:last-child{{border:0}}
.section-title{{font-family:var(--serif);font-size:1.7rem;font-weight:500;letter-spacing:-.015em;margin:2.4rem 0 .8rem;
padding-bottom:.6rem;border-bottom:1px solid var(--line)}}
.notice{{margin:1.4rem 0 1rem;padding:.9rem 1.1rem;border:1px solid var(--line);border-left:3px solid var(--accent);
border-radius:var(--radius);font-size:.88rem;line-height:1.55;background:var(--fill)}}
.notice b{{font-weight:600}}
.fine{{font-size:.76rem;line-height:1.55;color:var(--muted);margin-top:.9rem}}

/* result */
.result{{padding:.2rem 0 .2rem 1.6rem;border-left:1px solid var(--line)}}
.condition{{font-family:var(--serif);font-size:2.9rem;font-weight:500;line-height:1.05;letter-spacing:-.025em;margin:.35rem 0 .9rem}}
.score{{display:flex;align-items:baseline;gap:.9rem;flex-wrap:wrap}}
.num{{font-family:var(--serif);font-size:2rem;font-weight:500;letter-spacing:-.02em;font-variant-numeric:lining-nums}}
.tier{{font-size:.7rem;font-weight:600;letter-spacing:.14em;text-transform:uppercase}}
.tier:before{{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:.55rem;background:currentColor;vertical-align:.05em}}
.tier-high{{color:#4C7A5A}}.tier-moderate{{color:#A8741A}}.tier-low{{color:#A5483B}}
.meter{{height:3px;background:var(--line);margin:.9rem 0 .2rem;overflow:hidden}}
.meter>div{{height:100%;background:var(--accent);animation:grow .9s cubic-bezier(.2,.8,.2,1) both}}
.hint{{margin:.7rem 0 0;font-size:.9rem;line-height:1.55;color:var(--muted)}}

/* bars */
.bar-row{{margin:1rem 0}}
.bar-label{{display:flex;justify-content:space-between;font-size:.9rem;font-weight:500;margin-bottom:.45rem}}
.bar-label span:last-child{{color:var(--muted);font-variant-numeric:tabular-nums}}
.bar{{height:3px;background:var(--line);overflow:hidden}}
.bar-fill{{height:100%;background:var(--accent);min-width:2px;animation:grow .9s cubic-bezier(.2,.8,.2,1) both}}

/* product cards */
.product{{display:flex;flex-direction:column;gap:.35rem;height:100%;padding:1.3rem;border:1px solid var(--line);
border-radius:var(--radius);background:var(--fill);transition:border-color .2s ease}}
.product:hover{{border-color:var(--accent)}}
.p-match{{font-size:.68rem;font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--muted)}}
.p-title{{font-family:var(--serif);font-size:1.45rem;font-weight:500;letter-spacing:-.015em;line-height:1.15}}
.p-desc{{font-size:.84rem;line-height:1.5;color:var(--muted);flex:1;min-height:2.6em;margin-bottom:.6rem}}
a.p-cta{{display:block;text-align:center;font-size:.72rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;
color:var(--on)!important;background:var(--accent);text-decoration:none!important;padding:.8rem 1rem;border-radius:6px;
transition:opacity .15s ease}}
a.p-cta:hover{{opacity:.88}}

/* analysing animation */
.scan-wrap{{position:relative;max-width:320px;margin:0 auto 1rem;border-radius:var(--radius);overflow:hidden;border:1px solid var(--line)}}
.scan-wrap img{{width:100%;display:block;filter:grayscale(.25) brightness(.95)}}
.scan-line{{position:absolute;left:0;right:0;top:0;height:1px;background:var(--accent);
box-shadow:0 0 14px 3px color-mix(in srgb,var(--accent) 55%,transparent);animation:scan 1.5s ease-in-out infinite alternate}}
.step{{text-align:center;margin:.4rem 0 .7rem}}
.pbar{{max-width:320px;margin:0 auto;height:2px;background:var(--line);overflow:hidden}}
.pbar>div{{height:100%;background:var(--accent);transition:width .5s ease}}

/* streamlit widgets, quieted down */
[data-testid="stFileUploaderDropzone"]{{border:1px solid var(--line);border-radius:var(--radius);background:var(--fill);padding:1.6rem;transition:border-color .2s}}
[data-testid="stFileUploaderDropzone"]:hover{{border-color:var(--accent)}}
[data-testid="stFileUploaderDropzone"] button{{border-radius:6px}}
[data-testid="stButtonGroup"] button{{border-radius:6px;font-size:.85rem}}
[data-testid="stButtonGroup"] button[aria-checked="true"]{{background:var(--accent)!important;color:var(--on)!important;
border-color:var(--accent)!important;font-weight:600}}
[data-testid="stAlert"]{{border-radius:var(--radius)}}
[data-testid="stExpander"]{{border-radius:var(--radius);border-color:var(--line)}}
.photo{{display:block;width:100%;height:auto;border-radius:var(--radius);border:1px solid var(--line)}}
.st-key-summary{{animation:rise .5s ease-out both}}
.st-key-products{{animation:rise .6s .2s ease-out both}}

@keyframes scan{{from{{top:0}}to{{top:calc(100% - 1px)}}}}
@keyframes grow{{from{{width:0!important}}}}
@keyframes rise{{from{{opacity:0;transform:translateY(10px)}}to{{opacity:1;transform:none}}}}
@media (max-width:640px){{
.mast h1{{font-size:2.6rem}}.condition{{font-size:2.3rem}}
.result{{padding:1.2rem 0 0;border-left:0;border-top:1px solid var(--line);margin-top:1rem}}
.facts li{{border:0;margin:0 1rem .5rem 0;padding:0}}}}
@media (prefers-reduced-motion:reduce){{
.meter>div,.bar-fill,.st-key-summary,.st-key-products{{animation:none}}.scan-line{{animation:none;top:50%}}.pbar>div{{transition:none}}}}
</style>"""


def masthead() -> str:
    return (
        '<header class="mast"><div class="eyebrow">Skin analysis</div>'
        "<h1>Face Skin AI</h1>"
        '<p class="lede">Upload a photo to see possible skin concerns, with considered '
        "product suggestions for each one.</p>"
        '<ul class="facts"><li>Instant analysis</li><li>Photos are never saved</li>'
        "<li>Curated product links</li></ul></header>"
    )


def notice() -> str:
    return (
        '<div class="notice"><b>Not medical advice.</b> This is an educational AI and it '
        "can be wrong. For persistent, painful, changing or worrying skin problems, "
        "please see a dermatologist.</div>"
    )


def section_title(text: str) -> str:
    return f'<div class="section-title">{escape(text)}</div>'


def pct_text(p: float) -> str:
    return f"{p * 100:.1f}%" if p < 0.995 else "99%+"


def _width(p: float) -> float:
    return max(0.0, min(p, 1.0)) * 100


def result_block(label: str, probability: float, tier: str, hint: str) -> str:
    tier_cls, tier_text = TIER_LABEL.get(tier, TIER_LABEL["low"])
    score = "99%+" if probability >= 0.995 else f"{_width(probability):.0f}%"  # never claim 100%
    return (
        '<div class="result"><div class="eyebrow">Most likely</div>'
        f'<div class="condition">{escape(label)}</div>'
        f'<div class="score"><span class="num">{score}</span>'
        f'<span class="tier {tier_cls}">{tier_text}</span></div>'
        f'<div class="meter"><div style="width:{_width(probability):.1f}%"></div></div>'
        f'<p class="hint">{escape(hint)}</p></div>'
    )


def bar_row(label: str, probability: float) -> str:
    return (
        f'<div class="bar-row"><div class="bar-label"><span>{escape(label)}</span>'
        f"<span>{pct_text(probability)}</span></div>"
        f'<div class="bar"><div class="bar-fill" style="width:{_width(probability):.1f}%"></div></div></div>'
    )


def product_card(condition: str, probability: float, url: str, search_terms: str | None,
                 curated: bool) -> str:
    if curated and search_terms:
        desc = f"Amazon search: “{search_terms}”"
    elif curated:
        desc = "Curated Amazon search"
    else:
        desc = "General Amazon search (no curated pick yet)"
    # URL was validated upstream (https + Amazon hosts). quote() keeps it attribute-safe.
    safe_url = quote(url, safe=":/?&=%+#~,;@!$*()'-._")
    return (
        '<div class="product">'
        f'<div class="p-match">{pct_text(probability)} match</div>'
        f'<div class="p-title">{escape(condition)}</div>'
        f'<div class="p-desc">{escape(desc)}</div>'
        f'<a class="p-cta" href="{escape(safe_url, quote=True)}" target="_blank" '
        'rel="noopener noreferrer sponsored">View on Amazon &rarr;</a></div>'
    )


def photo(b64_jpeg: str, alt: str = "Your photo", max_width: int | None = None) -> str:
    """The user's photo embedded in the page as a data URI.

    st.image() would instead park the picture on the server and publish it at a
    public /media/<hash> URL that anyone holding the link can download, with no
    session check, even after the owner has left. A data URI travels only inside this
    session's own page and has no URL at all.
    """
    style = f' style="max-width:{int(max_width)}px"' if max_width else ""
    return f'<img class="photo" alt="{escape(alt)}" src="data:image/jpeg;base64,{escape(b64_jpeg)}"{style}/>'


def scan_card(b64_jpeg: str) -> str:
    return (
        '<div class="scan-wrap"><img alt="Photo being analysed" '
        f'src="data:image/jpeg;base64,{b64_jpeg}"/><div class="scan-line"></div></div>'
    )


def progress_bar(fraction: float) -> str:
    return f'<div class="pbar"><div style="width:{_width(fraction):.0f}%"></div></div>'


def step_label(text: str) -> str:
    return f'<div class="step eyebrow">{escape(text)}</div>'


def footer() -> str:
    return (
        '<div class="fine" style="text-align:center;margin:2.4rem 0 .4rem">'
        "Photos are analysed in memory and are not saved by this app. "
        "Results are AI estimates, not a diagnosis.</div>"
    )
