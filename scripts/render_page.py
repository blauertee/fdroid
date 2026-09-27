#!/usr/bin/env python3
"""Write the site's index.html and qr.svg from config/config.yml.

The About text is repo_description, inserted verbatim (HTML-escaped).
Also warns when README.md no longer carries the same description or the
current add-repo link, since README.md is static and edited by hand.
Usage: render_page.py <config.yml> <fingerprint> <site dir> <README.md>
"""

import html
import sys
from pathlib import Path

import qrcode
import qrcode.image.svg
import yaml

config_file, fingerprint, site, readme = sys.argv[1:5]
config = yaml.safe_load(Path(config_file).read_text())
name = config["repo_name"]
description = config["repo_description"].strip()
link = f"{config['repo_url']}?fingerprint={fingerprint}"

qrcode.make(link, image_factory=qrcode.image.svg.SvgPathImage,
            border=2).save(str(Path(site) / "qr.svg"))

e = html.escape
Path(site, "index.html").write_text(f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{e(name)}</title>
<style>
  :root {{ color-scheme: light dark; --fg: #1a1a1a; --bg: #fafafa; --muted: #666; }}
  @media (prefers-color-scheme: dark) {{
    :root {{ --fg: #e8e8e8; --bg: #161616; --muted: #9a9a9a; }}
  }}
  body {{ margin: 0 auto; max-width: 36rem; padding: 2rem 1rem;
         font: 1rem/1.5 system-ui, sans-serif; color: var(--fg); background: var(--bg); }}
  img {{ display: block; width: min(16rem, 100%); background: #fff;
        border-radius: .5rem; }}
  .link {{ display: flex; gap: .5rem; margin: 1rem 0 2rem; }}
  code {{ flex: 1; overflow-wrap: anywhere; font-size: .85rem; color: var(--muted); }}
  button {{ font: inherit; padding: .25rem .75rem; align-self: start; }}
</style>
</head>
<body>
<h1>{e(name)}</h1>
<a href="{e(link)}"><img src="qr.svg" alt="QR code: {e(link)}"></a>
<div class="link">
  <code id="link">{e(link)}</code>
  <button type="button" onclick="navigator.clipboard.writeText(document.getElementById('link').textContent).then(() => this.textContent = 'Copied')">Copy</button>
</div>
<h2>About this repo</h2>
<p>{e(description)}</p>
</body>
</html>
""")

text = Path(readme).read_text()
for label, needle in (("repo_description", description), ("add-repo link", link)):
    if needle not in text:
        print(f"::warning::README.md does not contain the current {label}; update it by hand")
