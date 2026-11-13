// Shared helpers for every page. Plain JavaScript modules, no libraries.
// Security rule (docs/SECURITY.md): page content is built with DOM nodes and textContent,
// never innerHTML, so text from the API (a review, a name) can never become code.

import { PHOTOS } from "./photo-data.js";

// ---------- DOM ----------
export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

/** h("a", { class: "btn", href: "/" }, "Text", childNode) → element. Text children are always text. */
export function h(tag, props, ...children) {
  const el = document.createElement(tag);
  setProps(el, props);
  append(el, children);
  return el;
}

const SVG_NS = "http://www.w3.org/2000/svg";
/** Same as h(), for SVG elements. */
export function s(tag, props, ...children) {
  const el = document.createElementNS(SVG_NS, tag);
  setProps(el, props);
  append(el, children);
  return el;
}

function setProps(el, props) {
  for (const [key, value] of Object.entries(props || {})) {
    if (value === null || value === undefined || value === false) continue;
    if (key === "class") el.setAttribute("class", value);
    else if (key === "text") el.textContent = value;
    else if (key === "dataset") Object.assign(el.dataset, value);
    else if (key.startsWith("on") && typeof value === "function") el.addEventListener(key.slice(2).toLowerCase(), value);
    else if (value === true) el.setAttribute(key, "");
    else el.setAttribute(key, String(value));
  }
}

function append(el, children) {
  for (const child of children.flat(Infinity)) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
}

// ---------- Icons (simple 24×24 line icons drawn for this site) ----------
const ICONS = {
  star: "M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z",
  check: "M5 12.5l4.5 4.5L19 7.5",
  arrow: "M5 12h14M13 6l6 6-6 6",
  info: "M12 8h.01M11 12h1v5h1M12 21a9 9 0 100-18 9 9 0 000 18z",
  alert: "M12 8v5M12 16.5h.01M10.3 3.9L2.6 17.2A2 2 0 004.3 20h15.4a2 2 0 001.7-2.8L13.7 3.9a2 2 0 00-3.4 0z",
  copy: "M9 9h10v11H9zM5 15V4h10",
  calendar: "M4 6h16v14H4zM4 10h16M8 3v4M16 3v4",
  x: "M6 6l12 12M18 6L6 18",
  clock: "M12 21a9 9 0 100-18 9 9 0 000 18zM12 7v5l3 2",
  pin: "M12 21s-7-6.2-7-11.5A7 7 0 0119 9.5C19 14.8 12 21 12 21zM12 12a2.5 2.5 0 100-5 2.5 2.5 0 000 5z",
};
export function icon(name, cls = "") {
  const solid = name === "star";
  return s("svg", { viewBox: "0 0 24 24", "aria-hidden": "true", focusable: "false", class: cls },
    s("path", {
      d: ICONS[name], fill: solid ? "currentColor" : "none", stroke: solid ? "none" : "currentColor",
      "stroke-width": "2", "stroke-linecap": "round", "stroke-linejoin": "round",
    }));
}
export function stars(rating, label = true) {
  const wrap = h("span", { class: "stars", role: label ? "img" : null, "aria-label": label ? `${rating} out of 5 stars` : null });
  for (let i = 1; i <= 5; i++) wrap.append(icon("star", i <= rating ? "" : "off"));
  return wrap;
}

// ---------- Photos ----------
/** A responsive <img> for a photo built by scripts/photos/build_photos.py. */
export function photo(name, { sizes = "100vw", alt, loading = "lazy", priority = false, cls } = {}) {
  const p = PHOTOS[name];
  if (!p) return h("span", { class: "photo-missing" });
  const [aw, ah] = p.aspect.split(":").map(Number);
  const w0 = p.widths[0];
  return h("img", {
    src: `/img/${p.group}/${name}-${p.widths[p.widths.length > 1 ? 1 : 0]}.webp`,
    srcset: p.widths.map((w) => `/img/${p.group}/${name}-${w}.webp ${w}w`).join(", "),
    sizes,
    alt: alt ?? p.alt,
    width: w0,
    height: Math.round((w0 * ah) / aw),
    loading: priority ? "eager" : loading,
    decoding: "async",
    fetchpriority: priority ? "high" : null,
    class: cls,
  });
}

// ---------- Money, dates and times (the café is in the UK; the API uses UK local time) ----------
const nf = new Intl.NumberFormat("en-GB");
/** 1284 → "1,284" */
export const count = (n) => nf.format(n);

export function money(pence) {
  if (pence === 0) return "Free";
  if (pence < 100) return `${pence}p`;
  return `£${(pence / 100).toFixed(2)}`;
}
/** Today's date in the UK as YYYY-MM-DD, whatever the visitor's own time zone. */
export function ukToday(offsetDays = 0) {
  const now = new Date(Date.now() + offsetDays * 86400000);
  const parts = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/London", year: "numeric", month: "2-digit", day: "2-digit" })
    .formatToParts(now).reduce((acc, p) => ({ ...acc, [p.type]: p.value }), {});
  return `${parts.year}-${parts.month}-${parts.day}`;
}
/** Add days to a YYYY-MM-DD date (calendar arithmetic, no time zones involved). */
export function addDays(iso, days) {
  const d = new Date(`${iso}T12:00:00Z`);
  d.setUTCDate(d.getUTCDate() + days);
  return d.toISOString().slice(0, 10);
}
const fmtCache = {};
export function formatDate(iso, style = "long") {
  const opts = {
    long: { weekday: "long", day: "numeric", month: "long" },
    short: { weekday: "short", day: "numeric", month: "short" },
    full: { weekday: "long", day: "numeric", month: "long", year: "numeric" },
  }[style];
  fmtCache[style] ||= new Intl.DateTimeFormat("en-GB", { ...opts, timeZone: "UTC" });
  return fmtCache[style].format(new Date(`${iso}T12:00:00Z`));
}
export function weekday(iso) { return new Date(`${iso}T12:00:00Z`).getUTCDay(); } // 0 = Sunday
export function timeAgo(isoUtc) {
  const mins = Math.round((Date.now() - Date.parse(isoUtc)) / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins} min ago`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours} hour${hours === 1 ? "" : "s"} ago`;
  const days = Math.round(hours / 24);
  if (days < 30) return `${days} day${days === 1 ? "" : "s"} ago`;
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "long", year: "numeric" }).format(new Date(isoUtc));
}

// ---------- The API (same domain, through CloudFront) ----------
export class ApiError extends Error {
  constructor(status, body) {
    super((body && body.message) || `HTTP ${status}`);
    this.status = status;
    this.body = body || {};
    this.fields = (body && body.fields) || {};
  }
}
export async function api(path, { method = "GET", body, token, signal, timeout = 15000 } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;
  const timer = new AbortController();
  const stop = setTimeout(() => timer.abort(), timeout);
  signal?.addEventListener("abort", () => timer.abort(), { once: true });
  let res;
  try {
    res = await fetch(path, {
      method, headers, credentials: "same-origin", signal: timer.signal,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch (err) {
    if (signal?.aborted) throw err;
    throw new ApiError(0, { error: "network" });
  } finally {
    clearTimeout(stop);
  }
  let data = null;
  try { data = await res.json(); } catch { /* empty or not JSON */ }
  if (!res.ok) throw new ApiError(res.status, data);
  return data;
}
/** A sentence a visitor can act on, for any API failure. */
export function friendly(err) {
  if (!(err instanceof ApiError)) return "Sorry, something went wrong. Please try again.";
  if (err.status === 0) return "We couldn't reach the café. Check your connection and try again.";
  if (err.status === 429) return "Lots of people are doing that right now. Please wait a few seconds and try again.";
  if (err.status >= 500) return "Sorry, something went wrong on our side. Please try again in a moment.";
  return err.body.message || "Sorry, something went wrong. Please try again.";
}

// ---------- "How busy is it?" ----------
export const LEVELS = {
  quiet: "Quiet", steady: "Steady", busy: "Busy", packed: "Packed", unknown: "Not updated", closed: "Closed",
};
/** Fill a .status-pill element from GET /api/status. */
export async function loadStatus(pill) {
  if (!pill) return null;
  try {
    const st = await api("/api/status");
    renderStatus(pill, st);
    return st;
  } catch {
    pill.dataset.level = "unknown";
    $(".status-label", pill).textContent = "Status";
    $(".status-detail", pill).textContent = "Couldn't check right now";
    pill.setAttribute("aria-busy", "false");
    return null;
  }
}

/** Draw a status (the shape of GET /api/status) into a .status-pill element. */
export function renderStatus(pill, st) {
  const live = ["quiet", "steady", "busy", "packed"].includes(st.level);
  pill.dataset.level = st.level;
  pill.toggleAttribute("data-live", live);
  let text;
  let words;
  if (st.level === "closed") {
    text = "Closed";
    words = [st.message]; // "Opens at 08:00" / "Opens tomorrow at 09:00"
  } else if (live) {
    text = LEVELS[st.level];
    words = [st.message, st.hoursToday && `Open until ${st.hoursToday.closes}`];
  } else {
    // Open, but nobody has said how busy it is in the last 3 hours: never show an old "Quiet".
    text = "Open now";
    words = [st.hoursToday && `Until ${st.hoursToday.closes}`];
  }
  $(".status-label", pill).textContent = text;
  $(".status-detail", pill).textContent = words.filter(Boolean).join(" · ");
  pill.setAttribute("aria-busy", "false");
}

// ---------- Small UI pieces ----------
let toastRegion;
export function toast(message, ms = 2600) {
  toastRegion ||= document.body.appendChild(h("div", { class: "toast-region", role: "status", "aria-live": "polite" }));
  const el = toastRegion.appendChild(h("div", { class: "toast" }, icon("check"), message));
  setTimeout(() => {
    el.setAttribute("data-leaving", "");
    setTimeout(() => el.remove(), 220);
  }, ms);
}

/** Show or clear field errors from a 400 response: { fields: { name: "message" } }. */
export function showFieldErrors(form, fields = {}) {
  $$("[data-error-for]", form).forEach((el) => { el.textContent = ""; el.hidden = true; });
  $$("[aria-invalid]", form).forEach((el) => el.removeAttribute("aria-invalid"));
  let first = null;
  for (const [name, message] of Object.entries(fields)) {
    const out = $(`[data-error-for="${CSS.escape(name)}"]`, form);
    const input = form.elements.namedItem(name);
    if (out) { out.textContent = message; out.hidden = false; }
    const target = input instanceof RadioNodeList ? input[0] : input;
    if (target && target.setAttribute) {
      target.setAttribute("aria-invalid", "true");
      if (out) {
        out.id ||= `err-${name}`;
        target.setAttribute("aria-describedby", out.id); // screen readers read the message with the field
      }
      // The message goes away as soon as you start fixing that field.
      target.addEventListener("input", () => {
        target.removeAttribute("aria-invalid");
        if (out) { out.hidden = true; out.textContent = ""; }
      }, { once: true });
      first ||= target;
    }
  }
  return first;
}

export function busy(button, on, label) {
  if (on) {
    button.dataset.label = button.textContent;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    button.replaceChildren(spinner(), label || "Sending…");
  } else {
    button.disabled = false;
    button.removeAttribute("aria-busy");
    button.textContent = button.dataset.label || label || "Send";
  }
}
function spinner() {
  return s("svg", { class: "spinner", viewBox: "0 0 24 24", "aria-hidden": "true" },
    s("circle", { cx: "12", cy: "12", r: "9", fill: "none", stroke: "currentColor", "stroke-width": "3", opacity: "0.25" }),
    s("path", { d: "M21 12a9 9 0 00-9-9", fill: "none", stroke: "currentColor", "stroke-width": "3", "stroke-linecap": "round" }));
}

// ---------- Page chrome: header, phone menu, theme switch, reveal-on-scroll ----------
function initHeader() {
  const header = $("[data-header]");
  if (!header) return;
  const onScroll = () => header.toggleAttribute("data-scrolled", window.scrollY > 4);
  onScroll();
  window.addEventListener("scroll", onScroll, { passive: true });

  const toggle = $(".nav-toggle", header);
  const menu = $("#mobile-menu");
  if (!toggle || !menu) return;
  const setOpen = (open, focusToggle = false) => {
    toggle.setAttribute("aria-expanded", String(open));
    toggle.setAttribute("aria-label", open ? "Close menu" : "Open menu");
    menu.toggleAttribute("data-open", open);
    menu.inert = !open;
    document.documentElement.style.overflow = open ? "hidden" : "";
    if (open) $("a", menu)?.focus({ preventScroll: true });
    else if (focusToggle) toggle.focus();
  };
  menu.inert = true;
  toggle.addEventListener("click", () => setOpen(toggle.getAttribute("aria-expanded") !== "true"));
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && menu.hasAttribute("data-open")) setOpen(false, true);
  });
  menu.addEventListener("click", (e) => { if (e.target.closest("a")) setOpen(false); });
  window.matchMedia("(min-width: 981px)").addEventListener("change", (e) => { if (e.matches) setOpen(false); });
}

function initThemeSwitch() {
  const meta = $$('meta[name="theme-color"]');
  const apply = (choice) => {
    const root = document.documentElement;
    if (choice === "auto") root.removeAttribute("data-theme");
    else root.setAttribute("data-theme", choice);
    try { choice === "auto" ? localStorage.removeItem("theme") : localStorage.setItem("theme", choice); } catch { /* ignore */ }
    // Keep the phone's browser bar in step with the chosen theme.
    meta.forEach((m) => {
      const wantsDark = m.media.includes("dark");
      if (choice === "auto") m.setAttribute("content", wantsDark ? "#140d0a" : "#fbf5ec");
      else m.setAttribute("content", choice === "dark" ? "#140d0a" : "#fbf5ec");
    });
  };
  let saved = "auto";
  try { saved = localStorage.getItem("theme") || "auto"; } catch { /* ignore */ }
  $$('input[name="theme"]').forEach((input) => {
    input.checked = input.value === saved;
    input.addEventListener("change", () => apply(input.value));
  });
  if (saved !== "auto") apply(saved);
}

function initReveal() {
  const els = $$(".reveal");
  if (!els.length || !("IntersectionObserver" in window)) return;
  const fold = window.innerHeight;
  const io = new IntersectionObserver((entries) => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      e.target.classList.add("is-in");
      io.unobserve(e.target);
    }
  }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });
  for (const el of els) {
    // Only things below the first screen are hidden and faded in: nothing visible ever blinks.
    if (el.getBoundingClientRect().top < fold * 0.92) continue;
    el.classList.add("reveal-armed");
    io.observe(el);
  }
}

/** Stagger children of a freshly rendered list (decorative, 40ms apart, max 8 steps). */
export function stagger(container, selector = ":scope > *") {
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  $$(selector, container).forEach((el, i) => {
    el.classList.add("enter");
    el.style.animationDelay = `${Math.min(i, 8) * 40}ms`;
  });
}

function init() {
  initHeader();
  initThemeSwitch();
  initReveal();
  const year = $("[data-year]");
  if (year) year.textContent = String(new Date().getFullYear());
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init, { once: true });
else init();
