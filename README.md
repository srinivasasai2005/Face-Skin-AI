# Face Skin AI

A Streamlit app that looks at a photo of your face and suggests **possible** skin
concerns (acne, rosacea, dark circles, ...) using a pre-trained fastai image
classifier, then links to Amazon searches for each one.

> **Not medical advice.** The model is an educational project and can be wrong.
> See a dermatologist for anything persistent, painful or changing.

## How it works

1. Upload a JPG/PNG (or use the camera). The app fixes orientation, flattens
   transparency and downsizes big images before analysis.
2. The model ranks 40 skin conditions. You see the most likely one, a confidence
   level (high / moderate / low), the next two possibilities and a chart.
3. Conditions with at least 10% probability get a **product card**, in order of
   likelihood. Cards are built from `amazon_categories.xlsx`: the short link is
   resolved with a single redirect lookup to show its real search terms and store
   region. Conditions with no curated link get a plain Amazon search instead.
4. Photos that are blank or contain almost no skin colour get a warning and no
   product suggestions.

Photos are processed in memory only: never written to disk, never served from a URL,
and private to the visitor's session. See [SECURITY.md](SECURITY.md) for exactly what
was verified, what was not, and what to do when deploying.

## Look and feel

A quiet, editorial design: flat surfaces, hairline dividers, a serif for headings
(Newsreader) and a sans for text (Inter), one muted accent colour, no gradients and
no emoji. Choose a palette in the sidebar: **Atelier** (ink on ivory, default),
**Sage**, **Marine**, **Clay** or **Aubergine**. The choice is kept in the URL
(`?theme=Marine`) so it survives a refresh and can be shared. Light and dark mode
follow the device setting, and each palette has a variant for both.

Colours live in `PALETTES` in `ui_theme.py` (background, sidebar, accent and the
text colour used on the accent, per mode); a test checks that button text meets the
WCAG 4.5:1 contrast ratio for every palette. The fonts are embedded from
`assets/fonts/` (SIL Open Font License), so the page makes no external requests.
All UI text that comes from outside (condition names, Amazon search terms) is
HTML-escaped. Tested on Streamlit 1.67.

## Project layout

| File | Purpose |
|---|---|
| `streamlit_app.py` | Page layout only |
| `image_utils.py` | Safe image loading (RGBA/CMYK/EXIF/size limits) and the skin sanity check |
| `model.py` | Cached model loading, predictions, confidence tiers |
| `recommendations.py` | Link validation/resolution and product cards |
| `ui_theme.py` | Colour palettes, CSS and escaped HTML builders for the interface |
| `security.py` | Model fingerprint check and rate limiter |
| `deploy/` | Security headers, nginx and Caddy configs for a safe deployment |
| `scripts/check_security.py` | Checks a running site against the security baseline |
| `SECURITY.md` | Threat model, what is protected, residual risks, deployment checklist |
| `requirements.lock.txt` | Exact dependency versions the app was verified with |
| `export.pkl` | Exported fastai learner (40 classes) |
| `amazon_categories.xlsx` | Condition -> Amazon link (columns `class`, `profit_link`) |
| `tests/` | pytest suite |

## Security

Read [SECURITY.md](SECURITY.md) before putting this on the internet. In short: run it
behind the proxy in `deploy/` over HTTPS (Streamlit alone has no security headers and
can be framed by other sites), then check it with
`python scripts/check_security.py https://your-domain`. The model file is pinned by SHA-256;
after replacing `export.pkl` run `python model.py` and update `MODEL_SHA256`.

## Run it

Python 3.11-3.13 recommended.

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Run the tests:

```bash
pip install -r requirements-dev.txt
pytest
```

## Updating product links

Edit `amazon_categories.xlsx`: one row per condition, `class` must match a model
label exactly. Links must be `https` and point at Amazon or an official short-link
domain (`amzn.to`, `a.co`, ...); anything else is ignored. The model has four
classes without a curated link (Dryness Around the Eyes, Enlarged Pores,
Facial Hair, Nasolabial Folds); add rows for them to replace the fallback search.

## Known limitations

- The skin check is heuristic. It catches blank images and clearly non-skin
  photos, but skin-coloured non-skin subjects (e.g. a tabby cat, some food) can
  still produce a prediction. A reliable fix needs a "not skin" class in the model.
- The model predicts one label per photo (softmax), so percentages compete with
  each other even when several conditions are present.
- Accuracy varies by condition; for example some eczema/psoriasis photos are
  mislabelled. Always treat results as a hint.
- `export.pkl` is a pickle file: only load files you trust.

## License

MIT, see [LICENSE](LICENSE).
