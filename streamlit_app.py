"""Face Skin AI - Streamlit front end.

All logic lives in small modules; this file only lays out the page:
    image_utils.py     - safe image loading + sanity checks
    model.py           - cached model + ranked predictions
    recommendations.py - product cards built from the curated Amazon links
    ui_theme.py        - palettes, typography, CSS and escaped HTML builders
"""

import base64
import io
import logging
import time

import pandas as pd
import plotly.express as px
import streamlit as st
from PIL import Image, ImageDraw

import recommendations
import ui_theme as ui
from image_utils import ImageError, load_image
from model import Analysis, BusyError, analyze_bytes, get_learner
from security import IntegrityError, RateLimiter, sha256_hex

log = logging.getLogger(__name__)

# Per session: at most this many fresh analyses in this many seconds. This only slows
# accidental loops; per-IP limits belong in the reverse proxy (see SECURITY.md).
ANALYSES_PER_WINDOW, ANALYSIS_WINDOW_SECONDS = 10, 300


def make_favicon() -> Image.Image:
    """Plain monogram (an 'F' in a ring) drawn in code: no emoji, no image file."""
    size = 128
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    ink = (36, 35, 33, 255)
    draw.ellipse((4, 4, size - 4, size - 4), fill=ink)
    paper = (250, 248, 244, 255)
    draw.rectangle((44, 34, 58, 94), fill=paper)  # stem
    draw.rectangle((44, 34, 90, 46), fill=paper)  # top bar
    draw.rectangle((44, 58, 82, 69), fill=paper)  # middle bar
    return img


st.set_page_config(page_title="Face Skin AI", page_icon=make_favicon(), layout="centered")

CONFIDENCE_HINT = {
    "high": "The model is fairly sure about this one.",
    "moderate": "Treat this as a hint, not a verdict.",
    "low": "The model is unsure. Try a sharper, evenly lit, close-up photo without filters.",
}
SOURCE_UPLOAD, SOURCE_CAMERA = "Upload", "Camera"

ANALYSIS_STEPS = [
    "Preparing photo",
    "Mapping skin regions",
    "Running the model",
    "Ranking conditions",
]
MIN_ANALYSIS_SECONDS = 2.6  # total time the animation stays up (real work happens inside)
MODEL_STEP = 2  # index of the step during which the real prediction runs


def stretch(fn) -> dict:
    """Full-width kwargs for whichever API this Streamlit version supports.

    ``use_container_width`` is deprecated in favour of ``width="stretch"``; older
    releases only know the former. The new API documents "stretch" in its docstring.
    """
    return {"width": "stretch"} if '"stretch"' in (fn.__doc__ or "") else {"use_container_width": True}


def theme_mode() -> str:
    """'dark' or 'light', as reported by the browser (defaults to light)."""
    reported = getattr(getattr(st.context, "theme", None), "type", None)
    return "dark" if reported == "dark" else "light"


@st.cache_resource(show_spinner="Loading the model (first run only)...")
def load_model():
    return get_learner()


class RateLimited(RuntimeError):
    def __init__(self, wait_seconds: float):
        super().__init__("rate limited")
        self.wait_seconds = wait_seconds


def run_analysis(data: bytes, key: str | None = None) -> Analysis:
    """Analyse a photo, remembering the result for THIS session only.

    This used to be a global @st.cache_data keyed by the photo's hash, which kept
    every visitor's derived skin results for an hour and let other sessions hit them.
    Session state is private to one visitor and is freed when they leave.
    """
    key = key or sha256_hex(data)
    cached = st.session_state.get("analysis")
    if cached and cached[0] == key:
        return cached[1]  # rerun of the photo already on screen: no new work, no new quota

    limiter = st.session_state.setdefault(
        "limiter", RateLimiter(ANALYSES_PER_WINDOW, ANALYSIS_WINDOW_SECONDS)
    )
    if not limiter.allow():
        raise RateLimited(limiter.retry_after())

    analysis = analyze_bytes(data)
    st.session_state["analysis"] = (key, analysis)
    return analysis


def forget_photo() -> None:
    """Drop everything derived from the user's photo (called when the photo is removed)."""
    for name in ("analysis", "animated_key"):
        st.session_state.pop(name, None)


def encode_photo(img: Image.Image, max_side: int = 900) -> str:
    """Base64 JPEG of the photo for embedding. Re-encoding also strips EXIF (GPS etc.)."""
    view = img.copy()
    view.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    view.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def html(markup: str) -> None:
    st.markdown(markup, unsafe_allow_html=True)


# --- sidebar & header -------------------------------------------------------

def choose_theme() -> str:
    """Sidebar palette picker. The choice is mirrored into ?theme= so refresh keeps it."""
    names = list(ui.PALETTES)
    requested = st.query_params.get("theme")
    start = requested if requested in ui.PALETTES else ui.DEFAULT_PALETTE

    # Seed the widget through session_state instead of ``default=``: a ``default`` that
    # changes between runs makes Streamlit treat it as a new widget and reset it,
    # which silently ignored every theme click after the first.
    if "theme_pills" not in st.session_state:
        st.session_state["theme_pills"] = start

    def keep_selection() -> None:
        # Clicking the active pill deselects it (value None); put the theme back.
        if st.session_state.get("theme_pills") is None:
            st.session_state["theme_pills"] = st.session_state.get("theme_last", start)

    with st.sidebar:
        html('<div class="eyebrow" style="margin-bottom:.6rem">Appearance</div>')
        picked = st.pills(
            "Colour theme",
            names,
            key="theme_pills",
            label_visibility="collapsed",
            on_change=keep_selection,
        )
        choice = picked or st.session_state.get("theme_last", start)
        st.session_state["theme_last"] = choice
        st.caption("Light and dark mode follow your device setting.")
        st.divider()
        html('<div class="eyebrow" style="margin-bottom:.6rem">How it works</div>')
        st.markdown(
            "1. Add a clear photo\n2. The model ranks 40 skin conditions\n"
            "3. You see the closest matches and product suggestions"
        )
        st.caption("Educational project. Not a medical device.")
    if choice != requested:
        st.query_params["theme"] = choice
    return choice


def render_header() -> None:
    html(ui.masthead())
    html(ui.notice())
    with st.expander("Tips for a good photo"):
        st.markdown(
            "- Use **natural, even light** (a window works well); avoid harsh flash.\n"
            "- Face the camera, **close enough** that skin fills most of the frame.\n"
            "- No filters, heavy makeup or sunglasses.\n"
            "- JPG or PNG, up to 15 MB."
        )


def get_image_bytes() -> bytes | None:
    mode = st.segmented_control(
        "Photo source",
        [SOURCE_UPLOAD, SOURCE_CAMERA],
        default=SOURCE_UPLOAD,
        label_visibility="collapsed",
    ) or SOURCE_UPLOAD  # clicking the active segment deselects it; treat as upload
    if mode == SOURCE_UPLOAD:
        file = st.file_uploader(
            "Choose an image", type=["jpg", "jpeg", "png"], key="uploader",
            label_visibility="collapsed",
        )
    else:
        file = st.camera_input("Take a photo", key="camera", label_visibility="collapsed")
    return file.getvalue() if file is not None else None


# --- analysing animation ----------------------------------------------------

def analyse_with_animation(data: bytes, img) -> Analysis:
    """Run the real analysis behind a short staged animation.

    The animation plays once per photo. Streamlit reruns the whole script on every
    click, so we remember which photo was already shown and skip straight to the
    (cached) result afterwards.
    """
    key = sha256_hex(data)
    if st.session_state.get("animated_key") == key:
        return run_analysis(data, key)

    slot = st.empty()
    try:
        with slot.container():
            html(ui.scan_card(encode_photo(img, 480)))
            label, bar = st.empty(), st.empty()

        started = time.monotonic()
        step_len = MIN_ANALYSIS_SECONDS / len(ANALYSIS_STEPS)
        analysis = None
        for i, text in enumerate(ANALYSIS_STEPS):
            label.markdown(ui.step_label(text), unsafe_allow_html=True)
            bar.markdown(ui.progress_bar((i + 1) / len(ANALYSIS_STEPS)), unsafe_allow_html=True)
            if i == MODEL_STEP:
                analysis = run_analysis(data, key)  # real work; may take longer than step_len
            time.sleep(max(0.0, started + (i + 1) * step_len - time.monotonic()))
    finally:
        slot.empty()  # also clears the animation if the photo turns out to be invalid

    st.session_state["animated_key"] = key
    return analysis


# --- results ----------------------------------------------------------------

def render_prediction_summary(analysis: Analysis, img, theme: str) -> None:
    top = analysis.top
    left, right = st.columns([5, 6], vertical_alignment="center")
    with left:
        html(ui.photo(encode_photo(img)))  # embedded, never served from a public /media URL
    with right:
        html(ui.result_block(top.label, top.probability, analysis.confidence_tier,
                             CONFIDENCE_HINT[analysis.confidence_tier]))

    html(ui.section_title("Other possibilities"))
    html("".join(ui.bar_row(p.label, p.probability) for p in analysis.predictions[1:3]))

    with st.expander("Probability chart"):
        top5 = analysis.predictions[:5]
        df = pd.DataFrame(
            {"Condition": [p.label for p in top5], "Confidence": [p.probability * 100 for p in top5]}
        ).iloc[::-1]  # plotly draws the first bar at the bottom; flip so #1 is on top
        fig = px.bar(df, x="Confidence", y="Condition", orientation="h", text="Confidence")
        fig.update_traces(
            texttemplate="%{x:.1f}%", textposition="outside", cliponaxis=False,
            marker_color=ui.palette(theme, theme_mode())["accent"],
        )
        fig.update_layout(
            height=260, margin=dict(l=0, r=30, t=10, b=0),
            xaxis=dict(range=[0, 105], title=None, ticksuffix="%"), yaxis_title=None,
            font=dict(family="Inter, sans-serif"),
        )
        st.plotly_chart(fig, **stretch(st.plotly_chart))
        st.caption(
            "The model picks the single best match, so these percentages compete "
            "with each other; several real conditions can be present at once."
        )


def render_products(analysis: Analysis) -> None:
    targets = analysis.recommend
    if not targets:
        return
    html(ui.section_title("Suggested products"))
    products = recommendations.build_products([p.label for p in targets])
    prob = {p.label: p.probability for p in targets}

    for col, product in zip(st.columns(len(products)), products):
        with col:
            html(ui.product_card(product.condition, prob[product.condition], product.url,
                                 product.search_terms, product.curated))

    region = products[0].domain.removeprefix("www.")
    html(
        f'<div class="fine">Opens {region} in a new tab. Prices and availability vary by '
        "region. Some links are affiliate links: we may earn a small commission at no "
        "cost to you.</div>"
    )


def render_results(analysis: Analysis, img, theme: str) -> None:
    html(ui.section_title("Results"))
    # Keyed containers get a stable "st-key-<name>" CSS class used for the fade-in.
    with st.container(key="summary"):
        render_prediction_summary(analysis, img, theme)
    with st.container(key="products"):
        render_products(analysis)


# --- page -------------------------------------------------------------------

def stop_page(show) -> None:
    """Render a message, the footer, and end this run."""
    show()
    html(ui.footer())
    st.stop()


theme = choose_theme()
html(ui.font_css())  # constant, so Streamlit can cache it between reruns
html(ui.css(theme))
render_header()

try:
    load_model()  # warm the cache before the first upload so the first result is fast
except IntegrityError:
    log.critical("export.pkl does not match the pinned SHA-256; refusing to load it")
    stop_page(lambda: st.error("This service is temporarily unavailable. Please try again later."))
except Exception:
    log.exception("The model could not be loaded")  # details stay in the server log
    stop_page(lambda: st.error("This service is temporarily unavailable. Please try again later."))

data = get_image_bytes()
if data is None:
    forget_photo()  # photo removed (or never added): drop every result derived from it
    html('<div class="notice">Add a photo to get started.</div>')
    html(ui.footer())
    st.stop()

try:
    img = load_image(data)
    analysis = analyse_with_animation(data, img)
except ImageError as exc:
    stop_page(lambda: st.error(str(exc)))
except RateLimited as exc:
    wait = max(1, int(exc.wait_seconds) + 1)
    stop_page(lambda: st.warning(
        f"You have analysed several photos in a short time. Please wait about {wait} seconds and try again."
    ))
except BusyError:
    stop_page(lambda: st.warning("The service is busy right now. Please try again in a moment."))
except Exception:
    log.exception("Unexpected failure while analysing an upload")  # details stay in the server log
    stop_page(lambda: st.error("Something went wrong while analysing this photo. Please try another one."))

if analysis.quality.ok:
    render_results(analysis, img, theme)
else:
    html(ui.photo(encode_photo(img), max_width=280))
    st.warning(
        "This doesn't look like a clear photo of skin "
        f"({'; '.join(analysis.quality.reasons)}). Please try a well-lit, "
        "close-up photo of your face. Product suggestions are hidden because the "
        "results would probably be unreliable."
    )
    with st.expander("Show the model's output anyway"):
        render_prediction_summary(analysis, img, theme)

html(ui.footer())
