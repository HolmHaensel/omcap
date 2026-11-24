# Mobile use: from phone web view to an installable app

The phone path already exists and works: start with `--lan`, click **Phone**, scan the QR code, and the
phone gets a key and the full UI at phone width (REQ-F45/F47/F49). So "an app for the field" is not a new
product — it is the current page, made installable and reliable to wake up. Three steps, in order of value
per line of code.

## Step 1 — make the existing phone page a PWA (small, no new runtime)

Today `omcap/web/index.html` has no `manifest`, no `theme-color`, no apple meta tags and no service worker,
so the phone always opens a browser tab with browser chrome, and iOS forgets the session.

- Add `omcap/web/manifest.webmanifest`: `name`/`short_name` ("E-M1 Capture"), `start_url: "/"`,
  `display: "standalone"`, `background_color` dark, `orientation: "any"`, 192/512 icons (a camera glyph on
  the app's dark background — the existing banner art can be reduced).
- In `index.html`: `<link rel="manifest">`, `<meta name="theme-color">`,
  `<meta name="apple-mobile-web-app-capable" content="yes">`, `apple-mobile-web-app-status-bar-style`,
  `apple-touch-icon`.
- Serve `manifest.webmanifest` and the icons from the existing static handler (content type
  `application/manifest+json`); they must be reachable **before** the LAN key cookie is set, otherwise the
  install prompt never appears.

Result: Add to Home Screen → full-screen live view, no address bar. Both iOS and Android, no store, no
build step, nothing to sign.

## Step 2 — keep the screen awake and the stream honest (small, high field value)

Two things ruin a field session on a phone: the screen sleeping mid-shoot and the stream silently stopping.

- Use the **Screen Wake Lock API** while live view is on (`navigator.wakeLock.request('screen')`,
  re-acquire on `visibilitychange`). Fall back silently where unsupported.
- Show the existing performance figure as a badge and step the live view size down automatically — the
  auto-size logic (REQ-F45) already exists for Wi-Fi; on a phone it should be the default and visible.
- Add a `Service-Worker` that caches **only the shell** (HTML/CSS/JS/icons) so a reconnect shows the UI
  instantly, and never caches `/api/*`, `/live.mjpg` or any photo. Cache-first for the shell, network-only
  for everything else, and delete the old cache on version bump.

## Step 3 — only if step 1–2 is not enough: a native shell

If the field use needs things the browser cannot do (background upload of shots, Bluetooth remote, locking
exposure while the app is backgrounded, an app-store presence), wrap the same page in **Capacitor** rather
than rewriting it:

- One `capacitor.config.json` pointing at the app's LAN URL after the QR handshake, or bundle the shell and
  talk to the computer over the LAN.
- iOS: `WKWebView` with `allowsInlineMediaPlayback`; Android: keep the existing WebView settings.
- Nothing in the camera protocol changes — the phone already has a key-based HTTP API.

Do **not** start here. Steps 1–2 give 90 % of the field value with a fraction of the maintenance, keep the
"one HTML file" property the project relies on, and ship to a user by scanning a QR code rather than by
installing from a store.

## Notes and pitfalls

- **The phone talks to the computer, not the camera.** The camera has one AP and one client slot that the
  computer already occupies; the phone must stay on the home Wi-Fi (`--lan`).
- **HTTPS is not available** on the LAN (self-signed would break the QR flow), so keep to same-origin
  relative URLs — no `fetch` to absolute `http://` hosts, which some mobile browsers block on a
  non-secure origin.
- **Wake Lock needs a user gesture** and dies when the tab is hidden; re-acquire on `visibilitychange` and
  tell the user if it was refused (battery saver does refuse it).
- **iOS home-screen apps get their own cookie jar.** The LAN key cookie (12 h) must be set again after
  installing; the QR flow already does that, so keep the QR screen reachable from inside the app.
