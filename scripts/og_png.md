# Regenerating the social-share image (`public/assets/og.png`)

`og.png` is the 1200×630 PNG that platforms (Discord, X/Twitter, iMessage, Slack,
Facebook, LinkedIn) show when the site link is pasted. Those platforms do **not**
render SVG, so the card must be a raster image — that's why we ship a PNG even
though the design lives in `OG_SVG` in `wc/render.py`.

It's a committed static asset. `render.write_site` only clears `*.html` and
rewrites the assets it lists, so `og.png` persists untouched across builds. It
does **not** change with results — it's a generic branded card — so it only needs
regenerating if the card art (`OG_SVG`) changes.

## How to regenerate

There's no SVG rasterizer in the build/CI environment, so render it in a browser:

1. Wrap `OG_SVG` in a minimal HTML page with the `<svg>` sized `width="1200"
   height="630"` and `body{margin:0}`.
2. Open it in a browser (or headless Chromium) and screenshot just the `<svg>`
   element — it captures at exactly 1200×630.
3. Save the result to `public/assets/og.png`.

Verify: `python3 -c "from PIL import Image; print(Image.open('public/assets/og.png').size)"`
should print `(1200, 630)`.

Then rebuild (`python3 scripts/build.py`) and commit `public/assets/og.png`.
