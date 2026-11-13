// The menu page: the live menu from GET /api/menu, with section shortcuts that follow you
// as you scroll, and diet filters kept in the address bar (so a filtered menu can be shared).
import { $, $$, h, api, money, friendly, stagger } from "./core.js";
import { itemCard, skeletonCard } from "./items.js";

const FILTERS = {
  all: { label: "everything", test: () => true },
  vegan: { label: "vegan, or can be made vegan", test: (t) => t.includes("VG") || t.includes("VG-available") },
  veggie: { label: "vegetarian", test: (t) => t.some((x) => x === "V" || x === "VG" || x === "VG-available") },
  gf: { label: "gluten-free option", test: (t) => t.includes("GF-available") },
};
const SIZE_NAMES = { regular: "Regular", large: "Large" };

const root = $("[data-menu]");
const chipsBar = $("[data-section-chips]");
const status = $("[data-filter-status]");
const filterButtons = $$("[data-filter]");
let menu = null;
let filter = new URLSearchParams(location.search).get("diet");
if (!FILTERS[filter]) filter = "all";
let spy = null;

filterButtons.forEach((btn) => {
  btn.setAttribute("aria-pressed", String(btn.dataset.filter === filter));
  btn.addEventListener("click", () => {
    if (btn.dataset.filter === filter) return;
    filter = btn.dataset.filter;
    filterButtons.forEach((b) => b.setAttribute("aria-pressed", String(b === btn)));
    const url = new URL(location.href);
    if (filter === "all") url.searchParams.delete("diet"); else url.searchParams.set("diet", filter);
    history.replaceState(null, "", url);
    render(false); // filtering is a frequent action: instant, no animation
  });
});

load();

async function load() {
  root.replaceChildren(h("div", { class: "item-grid menu-section" }, Array.from({ length: 8 }, skeletonCard)));
  try {
    menu = await api("/api/menu");
    render(true);
    if (location.hash) $(location.hash)?.scrollIntoView();
  } catch (err) {
    root.replaceChildren(h("div", { class: "notice notice-error menu-section" },
      h("span", {}, `${friendly(err)} `),
      h("button", { class: "btn btn-secondary btn-sm", type: "button", onclick: load }, "Try again")));
  }
}

function render(animate) {
  const test = FILTERS[filter].test;
  const sections = [];
  const chips = [];
  let shown = 0;
  for (const section of menu.sections) {
    const items = section.items.filter((i) => test(i.tags));
    if (!items.length) continue;
    shown += items.length;
    const id = `s-${section.id}`;
    chips.push(h("a", { class: "chip", href: `#${id}`, dataset: { target: id } }, section.title));
    const meta = [];
    if (section.sizes) {
      meta.push(...Object.entries(section.sizes).map(([k, v]) => h("span", { class: "offer-pill" }, `${SIZE_NAMES[k]} ${v}`)));
    }
    for (const offer of section.offers || []) meta.push(h("span", { class: "offer-pill" }, `${offer.label} ${money(offer.price)}`));
    const grid = h("div", { class: "item-grid" }, items.map((item) => itemCard(item, { sizes: section.sizes })));
    sections.push(h("section", { class: "menu-section", id, "aria-labelledby": `${id}-title` },
      h("div", { class: "menu-section-head" },
        h("div", { class: "stack" }, h("h2", { id: `${id}-title` }, section.title), section.note ? h("p", { class: "muted" }, section.note) : null),
        meta.length ? h("div", { class: "meta" }, meta) : null),
      grid));
    if (animate) stagger(grid);
  }
  if (!sections.length) {
    sections.push(h("div", { class: "card menu-empty menu-section" }, "Nothing on the menu matches that filter yet. Try another one."));
  }
  root.replaceChildren(...sections);
  chipsBar.replaceChildren(...chips);
  status.textContent = filter === "all" ? `Showing all ${shown} items` : `Showing ${shown} items that are ${FILTERS[filter].label}`;
  watchSections();
}

// Highlight the shortcut for the section you're reading: the last section whose top has
// passed under the sticky bars. Worked out from the scroll position (once per frame), so it's
// right whichever way you scroll, and nothing is highlighted above the first section.
// It changes constantly while scrolling, so it's instant: no animation for a frequent change.
const bar = $("[data-menu-bar]");
let frame = 0;
let activeId = null;
function updateActive() {
  frame = 0;
  const line = bar.getBoundingClientRect().bottom + 64; // generous: a jump link lands its section here
  let current = null;
  for (const s of $$(".menu-section[id]", root)) {
    if (s.getBoundingClientRect().top <= line) current = s.id;
  }
  if (current === activeId) return;
  activeId = current;
  $$(".chip", chipsBar).forEach((c) => {
    if (c.dataset.target === current) c.setAttribute("aria-current", "true");
    else c.removeAttribute("aria-current");
  });
  const chip = current && $(`[data-target="${current}"]`, chipsBar);
  if (chip) chipsBar.scrollTo({ left: chip.offsetLeft - 24, behavior: "auto" });
}
function watchSections() {
  activeId = null;
  updateActive();
  if (spy) return;
  spy = true;
  window.addEventListener("scroll", () => { frame ||= requestAnimationFrame(updateActive); }, { passive: true });
}
