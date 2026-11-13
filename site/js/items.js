// How a menu item looks, shared by the home page and the menu page.
import { h, money, photo } from "./core.js";

// Every item has a real photo. Welsh cake flavours share real Welsh cake photos (different crops),
// with a small round photo of the ingredient that makes the flavour different.
export const ITEM_PHOTOS = {
  espresso: ["espresso"], americano: ["americano"], "flat-white": ["flat-white"], latte: ["latte"],
  cappuccino: ["cappuccino"], mocha: ["mocha"], "flavoured-latte": ["flavoured-latte"], "chai-latte": ["chai-latte"],
  "hot-chocolate": ["hot-chocolate"],
  "iced-latte": ["iced-latte"], "iced-americano": ["iced-americano"], "iced-flavoured-latte": ["iced-flavoured-latte"],
  "iced-mocha": ["iced-mocha"], "cold-brew": ["cold-brew"], "iced-chai-latte": ["iced-chai-latte"],
  "iced-matcha-latte": ["iced-matcha-latte"],
  "builders-tea": ["builders-tea"], "herbal-tea": ["herbal-tea"], "matcha-latte": ["matcha-latte"],
  "orange-juice": ["orange-juice"], "sparkling-water": ["sparkling-water"],
  classic: ["welsh-closeup"],
  "chocolate-chip": ["welsh-stand", "chocolate-chips"],
  "white-chocolate-chip": ["welsh-tin", "white-chocolate"],
  "double-chocolate": ["welsh-pile", "dark-chocolate"],
  "white-chocolate-raspberry": ["welsh-stand-tall", "raspberries"],
  "lemon-blueberry": ["welsh-bakestone", "lemon-blueberry"],
  "cinnamon-sugar": ["welsh-closeup-b", "cinnamon"],
  "salted-caramel": ["welsh-stand-b", "caramel"],
  "vegan-classic": ["welsh-tin-b"],
  "seasonal-special": ["welsh-pile-b", "pumpkin"],
  "bara-brith": ["bara-brith"], "welsh-cake-sandwich": ["welsh-stand-b", "jam"],
  "ham-cheese-toastie": ["ham-cheese-toastie"], "leek-cheese-toastie": ["leek-cheese-toastie", "leeks"],
  "plant-milk": ["plant-milk"], "extra-shot": ["extra-shot"], syrup: ["syrup"], "cream-marshmallows": ["cream-marshmallows"],
};

export const TAG_LABELS = {
  V: "Vegetarian", VG: "Vegan", "VG-available": "Vegan option", "GF-available": "Gluten-free option",
};
const SIZE_LABELS = { regular: "Regular", large: "Large", each: "" };

const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);

/** One menu card. `sizes` is the section's cup sizes ({ regular: "240ml", ... }), if it has any. */
export function itemCard(item, { sizes, cardSizes = "(max-width: 600px) 100vw, (max-width: 1000px) 50vw, 300px", headingLevel = "h3" } = {}) {
  const [main, inset] = ITEM_PHOTOS[item.id] || [];
  const prices = Object.entries(item.prices).map(([size, pence]) =>
    h("li", {},
      SIZE_LABELS[size] ? h("span", { class: "size" }, sizes?.[size] ? `${SIZE_LABELS[size]} ${sizes[size]}` : SIZE_LABELS[size]) : null,
      h("span", { class: "price" }, money(pence))));

  const card = h("article", {
    class: "card item",
    dataset: { id: item.id, tags: item.tags.join(" ") },
    "data-flavour": inset ? "" : null,
    "data-sold-out": item.soldOut ? "" : null,
  },
  h("div", { class: "media-wrap" },
    h("div", { class: "media" },
      main ? photo(main, { sizes: cardSizes, alt: "" }) : null,
      item.soldOut ? h("span", { class: "sold-out-badge" }, "Sold out today") : null),
    inset ? h("span", { class: "flavour" }, photo(inset, { sizes: "64px", alt: "" })) : null),
  h("div", { class: "body" },
    h("div", { class: "name-row" }, h(headingLevel, {}, item.name)),
    item.description ? h("p", { class: "desc" }, item.description) : null,
    h("ul", { class: "prices", "aria-label": item.soldOut ? "Price (sold out today)" : "Price" }, prices),
    item.tags.length ? h("ul", { class: "tags", "aria-label": "Dietary" },
      item.tags.map((t) => h("li", { class: t === "VG" || t === "VG-available" ? "tag tag-ok" : "tag" }, TAG_LABELS[t] || t))) : null,
    item.allergens.length
      ? h("details", { class: "allergens" }, h("summary", {}, "Allergens"), h("p", {}, item.allergens.map(cap).join(", ")))
      : h("p", { class: "allergens" }, "No allergens")));
  return card;
}

/** A placeholder card with the same shape while the menu loads (no layout jump when it arrives). */
export function skeletonCard() {
  return h("div", { class: "card item", "aria-hidden": "true" },
    h("div", { class: "media skeleton" }),
    h("div", { class: "body" }, h("div", { class: "skeleton", style: null }), h("div", { class: "skeleton" })));
}
