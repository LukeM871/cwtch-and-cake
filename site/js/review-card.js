// One review, shared by the home page, the reviews page and the admin page.
// Everything a visitor wrote goes in with textContent (via h), never as HTML.
import { h, icon, stars, timeAgo } from "./core.js";

export const REVIEW_TAGS = {
  "best-welsh-cakes": "Best Welsh cakes",
  "great-coffee": "Great coffee",
  quiet: "Quiet",
  "fast-wifi": "Fast Wi-Fi",
  "plenty-of-plugs": "Plenty of plugs",
  "friendly-staff": "Friendly staff",
  "good-value": "Good value",
  cosy: "Cosy",
};

export function reviewCard(r, { extra } = {}) {
  return h("article", { class: "card review" },
    stars(r.rating),
    h("p", { class: "quote", dir: "auto" }, r.comment),
    h("p", { class: "who" },
      h("strong", { dir: "auto" }, r.displayName),
      r.courseYear ? h("span", {}, r.courseYear) : null,
      r.verified ? h("span", { class: "tag tag-ok" }, icon("check"), "Verified visit") : null,
      h("span", {}, timeAgo(r.createdAt))),
    r.tags && r.tags.length ? h("ul", { class: "tags", "aria-label": "Tags" }, r.tags.map((t) => h("li", { class: "tag" }, REVIEW_TAGS[t] || t))) : null,
    extra || null);
}
