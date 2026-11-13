"""Keep the header and footer identical on every page.

Each page in site/ has marker comments:
    <!-- @header --> ... <!-- /@header -->
    <!-- @footer --> ... <!-- /@footer -->
This script replaces what's between them with scripts/site-partials/{header,footer}.html,
and marks the current page's nav link with aria-current="page".
Plain HTML stays the source of truth, so there is no build step in the pipeline.

Usage: python scripts/site_partials.py           (rewrite pages)
       python scripts/site_partials.py --check   (exit 1 if any page is out of date; for CI)
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
PARTIALS = Path(__file__).with_name("site-partials")
BLOCK = re.compile(r"(<!-- @(header|footer) -->\n)(.*?)(<!-- /@\2 -->)", re.S)


def page_path(html_file: Path) -> str:
    rel = html_file.relative_to(SITE).as_posix()
    if rel == "index.html":
        return "/"
    return "/" + rel.removesuffix("index.html") if rel.endswith("index.html") else "/" + rel


def render(name: str, path: str) -> str:
    text = (PARTIALS / f"{name}.html").read_text(encoding="utf-8")
    # The current section: /book/confirmed/ still highlights nothing in the nav (it isn't a nav item).
    for href in re.findall(r'href="(/[a-z-]+/)"', text):
        if path.startswith(href):
            text = text.replace(f'<a href="{href}">', f'<a href="{href}" aria-current="page">')
    return text


def main() -> int:
    check = "--check" in sys.argv
    stale = []
    for html in sorted(SITE.rglob("*.html")):
        original = html.read_text(encoding="utf-8")
        path = page_path(html)
        updated = BLOCK.sub(lambda m: m.group(1) + render(m.group(2), path) + m.group(4), original)
        if updated != original:
            stale.append(html.relative_to(ROOT).as_posix())
            if not check:
                html.write_text(updated, encoding="utf-8")
    if check and stale:
        print("Out of date (run python scripts/site_partials.py):", *stale, sep="\n  ")
        return 1
    print("updated:" if stale and not check else "all pages up to date", *stale, sep="\n  ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
