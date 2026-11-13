// Student deals, live from GET /api/menu (the API decides which deals are active today).
import { $, h, api, money, friendly, photo, stagger } from "./core.js";

const DEAL_PHOTOS = {
  "cwtch-deal": ["latte", "welsh-cakes-round"],
  "exam-fuel": ["night-study"],
  "early-lecture-cuppa": ["tea-and-welsh-cakes"],
  "study-session": ["study-desk"],
  "bring-your-own-cup": ["byo-cup"],
  "stamp-card": ["coffee-beans"],
};

const grid = $("[data-deals]");
load();

async function load() {
  grid.replaceChildren(...Array.from({ length: 3 }, () => h("div", { class: "card deal-card", "aria-hidden": "true" },
    h("div", { class: "media skeleton" }), h("div", { class: "body" }, h("div", { class: "skeleton skel-line" }), h("div", { class: "skeleton skel-line short" })))));
  try {
    const { deals } = await api("/api/menu");
    grid.replaceChildren(...deals.map(dealCard));
    stagger(grid);
  } catch (err) {
    grid.replaceChildren(h("p", { class: "notice notice-error" }, `${friendly(err)} `,
      h("button", { class: "btn btn-secondary btn-sm", type: "button", onclick: load }, "Try again")));
  }
}

function priceText(d) {
  if (d.price !== null && d.price !== undefined) return money(d.price);
  if (d.discount) return `${money(d.discount)} off`;
  if (d.id === "stamp-card") return "10th coffee free";
  return "";
}

function dealCard(d) {
  const [main, inset] = DEAL_PHOTOS[d.id] || ["coffee-beans"];
  const featured = d.id === "cwtch-deal";
  return h("article", {
    class: "card deal-card",
    "data-featured": featured ? "" : null,
    "data-inactive": d.active ? null : "",
    "data-flavour": inset ? "" : null,
  },
  h("div", { class: "media-wrap" },
    h("div", { class: "media" },
      photo(main, { sizes: featured ? "(max-width: 760px) 100vw, 760px" : "(max-width: 760px) 100vw, 380px", alt: "" }),
      d.when ? h("span", { class: "when" }, d.when) : null),
    inset ? h("span", { class: "flavour" }, photo(inset, { sizes: "72px", alt: "" })) : null),
  h("div", { class: "body" },
    h("h2", { class: "h3" }, d.name),
    h("p", { class: "muted" }, d.description),
    h("p", { class: "price-tag" }, priceText(d)),
    d.normalPrice ? h("p", { class: "muted" }, `Normally ${money(d.normalPrice.from)} to ${money(d.normalPrice.to)}`) : null,
    h("ul", { class: "tags" },
      d.studentOnly ? h("li", { class: "tag" }, "Student card") : null,
      d.active ? h("li", { class: "tag tag-ok" }, "On now") : null),
    d.active ? null : h("p", { class: "inactive-note" }, "Back in exam season: 5 to 30 January, and 11 May to 12 June.")));
}
