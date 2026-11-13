// Photo credits for every photo on the site, from /img/credits.json
// (written by scripts/photos/build_photos.py, so it can't fall out of step with the photos).
import { $, h, photo } from "./core.js";

const SOURCES = { Unsplash: "on Unsplash", "Wikimedia Commons": "on Wikimedia Commons" };
const list = $("[data-credits]");

load();

async function load() {
  try {
    const res = await fetch("/img/credits.json");
    const credits = await res.json();
    // One entry per original photo (some photos are used in several crops).
    const seen = new Set();
    const items = [];
    for (const [name, c] of Object.entries(credits)) {
      const key = c.page;
      if (seen.has(key)) continue;
      seen.add(key);
      items.push(h("li", {},
        photo(name, { sizes: "64px", alt: "" }),
        h("span", {},
          h("span", { class: "what" }, c.alt),
          h("br"),
          h("span", { class: "by" },
            "Photo by ",
            c.author_url ? h("a", { href: c.author_url, rel: "noopener" }, c.author) : c.author,
            " ",
            h("a", { href: c.page, rel: "noopener" }, SOURCES[c.source] || c.source),
            " · ",
            h("a", { href: c.license_url, rel: "license noopener" }, c.license),
            c.changes ? ` · ${c.changes}` : null))));
    }
    list.replaceChildren(...items);
  } catch {
    list.replaceChildren(h("li", {}, "The credits couldn't load just now. Please try again."));
  }
}
