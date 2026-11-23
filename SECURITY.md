# Security

Face Skin AI handles photos of people's faces, which is sensitive data. This document
says what is protected, how that was checked, what is **not** protected, and what you
must do when deploying. It does not promise "unhackable": nothing can. It lists the
specific attacks that were tried and the ones that remain.

Report a vulnerability to: `<add your security contact email here>`.

## Threat model in one paragraph

Visitors are anonymous (no accounts). The assets are the photo a visitor uploads or
captures and the analysis derived from it. We defend against: other websites abusing
the camera permission (clickjacking), injected script stealing photos or using the
camera, hostile files sent to the image decoder, a swapped model file, one visitor
reaching another visitor's data, resource-exhaustion floods, and accidental leaks
through URLs, logs, caches or error pages.

## The webcam, specifically

| Question | Answer | How it was checked |
|---|---|---|
| Does the app keep the camera on after the photo is taken? | No. The video track ends immediately after capture. | Chrome fake camera; track `readyState` read after capture |
| ...or when the visitor switches away without taking a photo? | No. It ends. | Same |
| Can the camera be used after the visitor leaves the site? | No. A web page cannot touch the camera once it is closed. | Browser behaviour. The only way is a permission the visitor chose to remember (see below) |
| Can another website embed our page and trick the visitor into clicking "Allow"? | Not with the proxy headers in `deploy/`. **Without them it works.** | Embedded the app in a hostile page: rendered and its camera controls worked with bare Streamlit; blocked behind the headers |
| Can injected script use the camera or send photos elsewhere? | With the Content-Security-Policy in `deploy/`: no code from strings, no inline script, no outside scripts, no requests to other hosts. | Simulated XSS in a real browser: with the headers nothing reached the attacker's server (the browser refused script, image and stylesheet loads) |

**What we cannot control:** the browser's remembered permission. If a visitor chose
"Always allow camera" for your domain, any script that ever runs on your domain can use
the camera without asking. That is why the Content-Security-Policy and HTML escaping
matter, and why the page should tell visitors to choose **"Allow this time"**. A domain
takeover or a compromised deployment would defeat all of this.

## Photo handling

Verified by experiment (a unique marker was embedded in an uploaded photo, then searched
for):

- **Never written to disk.** The marker appeared nowhere in temp folders, the project,
  `~/.streamlit`, `~/.cache`, or the server log.
- **Never served from a URL.** Streamlit's `st.image` publishes pictures at a public
  `/media/<hash>` address that anyone with the link can download, and in testing the
  photo was still downloadable several seconds after the visitor had closed the page (I
  did not measure how long it lasts). The app no longer
  uses it: photos are embedded in the visitor's own page as data URIs. The only
  `/media/` file left is the logo.
- **Private to one session.** Results are kept in that visitor's session state (they used
  to be in a global cache keyed by the photo's hash, shared by everyone for an hour). They
  are dropped as soon as the photo is removed.
- **Metadata stripped.** The photo shown is re-encoded, which removes EXIF (GPS, device).
- **No third parties.** Fonts are embedded, there is no analytics, and Streamlit telemetry
  is off. The only outbound request the server makes is a redirect lookup on the
  affiliate short link, which carries no user data. Links open with
  `noopener noreferrer sponsored` and the page sends `Referrer-Policy: no-referrer`.

## Hostile uploads

The browser's `jpg/png` filter is cosmetic. On the server:

- Only JPEG and PNG decoders may run, chosen by file **content**. Before this, GIF, BMP,
  TIFF, WebP, ICO and PPM were accepted by renaming a file, and PostScript would have
  been handed to Ghostscript on any server that has it.
- The declared pixel count is read from the header and checked **before** decoding. A
  435 KB PNG used to grow server memory by about 1 GB; oversized files are now refused in
  milliseconds with no allocation. Large JPEGs are decoded at reduced size.
- At most 2 images decode at once and at most 8 analyses are queued; beyond that visitors
  get a "busy" message instead of the server running out of memory.
- Upload size is capped at 15 MB (Streamlit and the proxy).

## The model file is code

`export.pkl` is a Python pickle: loading it **runs code**. Anyone who could replace it
(compromised repository, deploy pipeline or server) would run code next to every
visitor's photo. The app pins its SHA-256, checks the bytes it is about to load, and
refuses on mismatch, showing visitors only "temporarily unavailable" and logging the
reason. A single flipped bit was tested end to end. After deliberately replacing the
model, run `python model.py` and paste the printed value into `MODEL_SHA256`.

## What you must do when deploying (the app cannot do these itself)

1. **Serve over HTTPS.** Browsers refuse the camera on plain HTTP anyway.
2. **Put a reverse proxy in front** using `deploy/nginx.conf` or `deploy/Caddyfile`. This is
   where the security headers, per-IP rate limits and body-size limit live. Streamlit
   cannot set response headers itself, and to my knowledge Streamlit Community Cloud
   does not let you either, so camera features there lack clickjacking and CSP protection.
3. **Bind Streamlit to localhost** behind the proxy: `--server.address 127.0.0.1`.
4. **Set `server.allowedHosts`** in `.streamlit/config.toml` to your real domain (blocks
   DNS-rebinding).
5. **Run the checker against the live site and in CI:**
   `python scripts/check_security.py https://your-domain`. Bare Streamlit fails 6 checks;
   behind the proxy it passes them all.
6. **Install from `requirements.lock.txt`** and run `pip-audit -r requirements.lock.txt` regularly.

## Known limitations and residual risk

- **Operators and the host can see photos.** Images exist in server memory while a session
  is active. Anyone with access to the server process or a memory dump can read them. Use
  least privilege, no debug endpoints, and a trusted host. Python does not zero memory on
  release, and I did not measure how quickly Streamlit frees session data after a visitor
  leaves.
- **`torch 2.6.0` has 25 published advisories**, and `pip-audit` found nothing else among
  91 packages. It cannot simply be upgraded: `fastai 2.7.19` requires `torch<2.7`, and
  newer fastai cannot load this model. I did not triage each advisory; the app only gives
  torch decoded pixel tensors and one verified model file. The proper fix is to re-export
  the model to a non-pickle format in the original training environment.
- **Rate limiting inside the app is per session.** It stops accidental loops, not someone
  opening many sessions. Per-IP limits are in `deploy/nginx.conf`. Caddy needs an extra
  module or a CDN for that.
- **The nginx and Caddy files were not run here** (neither is installed in the test
  environment); the header *policy* in them was tested through a test proxy and a
  consistency test keeps the files in sync with it. Run `nginx -t` or `caddy validate` first.
- **The CSP allows Streamlit's one inline script by hash.** If a Streamlit upgrade changes
  that script, the browser console will report it; the app still works. Update the hash in
  `deploy/security_headers.json` and the two config files.
- **`.devcontainer/devcontainer.json` turns off CORS and XSRF protection** so uploads work
  through the Codespaces proxy. It is for development only; do not expose that port publicly.
- **No authentication.** Anyone can use the app. It stores no personal data.
- **Legal:** face photos and derived health-like inferences are regulated personal data in
  many places (GDPR, CCPA, India's DPDP Act, and others). Add a privacy notice and
  consent text appropriate to where you operate. This file is engineering guidance, not
  legal advice.

## Re-verifying

```bash
pip install -r requirements-dev.txt && pytest                  # includes the security tests
python scripts/check_security.py https://your-domain           # headers, framing, legacy files
python model.py                                                # prints the model fingerprint
pip-audit -r requirements.lock.txt                             # known vulnerabilities
```
