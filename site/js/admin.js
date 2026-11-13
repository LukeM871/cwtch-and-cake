// The café admin page.
// Login: Amazon Cognito managed login, authorization code flow with PKCE (no client secret in a
// browser app). Tokens live in sessionStorage only, so they go when the tab closes, and the
// strict CSP stops injected scripts from reading them. Every admin request is checked by API
// Gateway's JWT authorizer AND by the admin Lambda (access token + "admins" group), so this page
// is just a friendly front end: hiding it or editing it gives no extra power.
import { $, $$, h, api, ApiError, friendly, busy, showFieldErrors, toast, money, formatDate, ukToday, timeAgo, loadStatus, renderStatus } from "./core.js";
import { reviewCard } from "./review-card.js";
import { COGNITO } from "./admin-config.js";

const REDIRECT = `${location.origin}/admin/`;
const KEYS = { tokens: "cwtch.admin.tokens", verifier: "cwtch.admin.pkce", state: "cwtch.admin.state" };
const store = {
  get: (k) => { try { return sessionStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { sessionStorage.setItem(k, v); } catch { /* storage blocked */ } },
  del: (k) => { try { sessionStorage.removeItem(k); } catch { /* storage blocked */ } },
};
class NeedLogin extends Error {}

// ---------- login (PKCE) ----------
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const randomString = (bytes) => b64url(crypto.getRandomValues(new Uint8Array(bytes)));

async function startLogin() {
  const verifier = randomString(48);
  const state = randomString(16);
  store.set(KEYS.verifier, verifier);
  store.set(KEYS.state, state);
  const challenge = b64url(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(verifier)));
  const params = new URLSearchParams({
    response_type: "code", client_id: COGNITO.clientId, redirect_uri: REDIRECT, scope: "openid",
    state, code_challenge: challenge, code_challenge_method: "S256",
  });
  location.assign(`${COGNITO.domain}/oauth2/authorize?${params}`);
}

async function tokenRequest(fields) {
  const res = await fetch(`${COGNITO.domain}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ client_id: COGNITO.clientId, ...fields }),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new NeedLogin(data.error || `token request failed (${res.status})`);
  return data;
}

function saveTokens(t, keepRefresh) {
  store.set(KEYS.tokens, JSON.stringify({
    access: t.access_token,
    refresh: t.refresh_token || keepRefresh || null,
    expiresAt: Date.now() + t.expires_in * 1000,
  }));
}
function tokens() {
  try { return JSON.parse(store.get(KEYS.tokens)); } catch { return null; }
}

async function finishLogin(code, state) {
  const expected = store.get(KEYS.state);
  const verifier = store.get(KEYS.verifier);
  store.del(KEYS.state);
  store.del(KEYS.verifier);
  history.replaceState(null, "", "/admin/"); // the code is single-use: don't leave it in the address bar
  if (!expected || state !== expected || !verifier) throw new NeedLogin("state mismatch");
  saveTokens(await tokenRequest({ grant_type: "authorization_code", code, redirect_uri: REDIRECT, code_verifier: verifier }));
}

async function accessToken() {
  const t = tokens();
  if (!t) throw new NeedLogin();
  if (Date.now() < t.expiresAt - 60000) return t.access;
  if (!t.refresh) throw new NeedLogin();
  try {
    const fresh = await tokenRequest({ grant_type: "refresh_token", refresh_token: t.refresh });
    saveTokens(fresh, t.refresh);
    return fresh.access_token;
  } catch {
    store.del(KEYS.tokens);
    throw new NeedLogin();
  }
}

async function adminApi(path, opts = {}) {
  try {
    return await api(path, { ...opts, token: await accessToken() });
  } catch (err) {
    if (err instanceof ApiError && err.status === 401) {
      // The token was refused: try one refresh, then ask for a fresh login.
      const t = tokens();
      if (t?.refresh) {
        store.set(KEYS.tokens, JSON.stringify({ ...t, expiresAt: 0 }));
        try { return await api(path, { ...opts, token: await accessToken() }); } catch { /* fall through */ }
      }
      store.del(KEYS.tokens);
      showLogin("Your login has expired. Please log in again.");
    } else if (err instanceof NeedLogin) {
      showLogin("Please log in again.");
    }
    throw err;
  }
}

async function logout() {
  const t = tokens();
  store.del(KEYS.tokens);
  if (t?.refresh) {
    // Revoke the refresh token at Cognito, so it can't be used again even if copied.
    try {
      await fetch(`${COGNITO.domain}/oauth2/revoke`, {
        method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: new URLSearchParams({ token: t.refresh, client_id: COGNITO.clientId }),
      });
    } catch { /* still log out locally */ }
  }
  location.assign(`${COGNITO.domain}/logout?${new URLSearchParams({ client_id: COGNITO.clientId, logout_uri: REDIRECT })}`);
}

function claims(token) {
  try { return JSON.parse(atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/"))); } catch { return {}; }
}

function showLogin(message) {
  $("[data-app]").hidden = true;
  $("[data-who]").hidden = true;
  $("[data-login]").hidden = false;
  const err = $("[data-login-error]");
  err.hidden = !message;
  err.textContent = message || "";
}

function showApp() {
  $("[data-login]").hidden = true;
  $("[data-app]").hidden = false;
  $("[data-who]").hidden = false;
  const name = claims(tokens().access).username;
  $("[data-who-name]").textContent = name ? `Logged in as ${name}` : "Logged in";
  openTab("reviews");
}

$("[data-login-btn]").addEventListener("click", (e) => { busy(e.currentTarget, true, "Opening the login…"); startLogin(); });
$("[data-logout]").addEventListener("click", (e) => { busy(e.currentTarget, true, "Logging out…"); logout(); });

// ---------- tabs (ARIA tabs: arrow keys move between them) ----------
const tabs = $$('[role="tab"]');
const loaded = new Set();
function openTab(name) {
  tabs.forEach((t) => {
    const on = t.id === `tab-${name}`;
    t.setAttribute("aria-selected", String(on));
    t.tabIndex = on ? 0 : -1;
    $(`#${t.getAttribute("aria-controls")}`).hidden = !on;
  });
  if (!loaded.has(name)) {
    loaded.add(name);
    ({ reviews: () => loadReviews(true), status: initStatus, menu: loadMenu, bookings: initBookings })[name]();
  }
}
tabs.forEach((t, i) => {
  t.addEventListener("click", () => openTab(t.id.slice(4)));
  t.addEventListener("keydown", (e) => {
    const step = { ArrowRight: 1, ArrowLeft: -1 }[e.key];
    if (!step) return;
    const next = tabs[(i + step + tabs.length) % tabs.length];
    next.focus();
    openTab(next.id.slice(4));
  });
});

// ---------- reviews ----------
let rStatus = "pending";
let rCursor = null;
const rList = $("[data-admin-reviews]");
const rMore = $("[data-admin-more]");
const HINTS = { pending: "Oldest first, so nobody waits too long.", approved: "Newest first. Reject to hide one again.", rejected: "Newest first. You can still approve these." };

$$("[data-rstatus]").forEach((chip) => chip.addEventListener("click", () => {
  if (chip.dataset.rstatus === rStatus) return;
  rStatus = chip.dataset.rstatus;
  $$("[data-rstatus]").forEach((c) => c.setAttribute("aria-pressed", String(c === chip)));
  $("[data-review-hint]").textContent = HINTS[rStatus];
  loadReviews(true);
}));
rMore.addEventListener("click", () => loadReviews(false));

async function loadReviews(reset) {
  if (reset) {
    rCursor = null;
    rList.replaceChildren(h("div", { class: "card review", "aria-hidden": "true" }, h("div", { class: "skeleton" }), h("div", { class: "skeleton" })));
  }
  busy(rMore, true, "Loading…");
  try {
    const qs = new URLSearchParams({ status: rStatus, limit: "20" });
    if (rCursor) qs.set("cursor", rCursor);
    const data = await adminApi(`/api/admin/reviews?${qs}`);
    if (reset) rList.replaceChildren();
    rList.append(...data.reviews.map(adminReviewCard));
    if (!rList.children.length) {
      rList.append(h("div", { class: "card card-pad muted" }, rStatus === "pending" ? "All caught up: no reviews waiting." : "Nothing here yet."));
    }
    rCursor = data.nextCursor;
    rMore.hidden = !rCursor;
    if (rStatus === "pending") setPendingCount(data.reviews.length, Boolean(data.nextCursor));
  } catch (err) {
    if (!(err instanceof NeedLogin)) rList.replaceChildren(h("p", { class: "notice notice-error" }, friendly(err)));
  } finally {
    busy(rMore, false, "Load more");
  }
}

function setPendingCount(n, more) {
  const el = $("[data-pending-count]");
  el.textContent = n ? (more ? `${n}+` : String(n)) : "";
  el.hidden = !n;
}

function adminReviewCard(r) {
  let card;
  const act = (action) => () => moderate(r, action, card);
  const meta = h("p", { class: "review-meta" },
    r.flagged ? h("span", { class: "tag tag-warn" }, "Flagged by the AI check") : null,
    h("span", {}, r.toxicityScore === null ? "AI check: off" : `AI score: ${Number(r.toxicityScore).toFixed(2)}`),
    r.moderatedAt ? h("span", {}, `Last changed ${timeAgo(r.moderatedAt)}`) : null);
  const actions = h("div", { class: "review-actions" },
    r.status !== "approved" ? h("button", { class: "btn btn-primary btn-sm", type: "button", onclick: act("approve") }, "Approve") : null,
    r.status !== "rejected" ? h("button", { class: "btn btn-secondary btn-sm", type: "button", onclick: act("reject") }, r.status === "approved" ? "Hide it" : "Reject") : null,
    holdButton("Hold to delete", () => moderate(r, "delete", card)));
  card = reviewCard(r, { extra: h("div", { class: "admin-extra" }, meta, actions) });
  return card;
}

const DONE = {
  approve: "Approved: it's on the site within 5 minutes",
  reject: "Rejected: it won't be shown",
  delete: "Deleted for good",
};
async function moderate(r, action, card) {
  const buttons = $$("button", card);
  buttons.forEach((b) => { b.disabled = true; });
  try {
    await adminApi(`/api/admin/reviews/${encodeURIComponent(r.reviewId)}`, { method: "POST", body: { action } });
    toast(DONE[action]);
    card.classList.add("leaving");
    setTimeout(() => {
      card.remove();
      if (!rList.children.length) loadReviews(true);
      else if (rStatus === "pending") setPendingCount(rList.children.length, Boolean(rCursor));
    }, 200);
  } catch (err) {
    buttons.forEach((b) => { b.disabled = false; });
    if (err instanceof NeedLogin) return;
    toast(err.status === 409 ? "Someone else just changed this review. Refreshing." : friendly(err));
    if (err.status === 409 || err.status === 404) loadReviews(true);
  }
}

// Press and hold to delete (from Emil Kowalski's design engineering notes): deciding is slow and
// deliberate (1.2 s, linear fill), letting go is instant. Works with a pointer, Space or Enter.
function holdButton(label, onDone) {
  const btn = h("button", { class: "btn btn-danger btn-sm hold", type: "button", "aria-label": `${label}: press and hold for a second` },
    h("span", {}, label), h("span", { class: "hold-fill", "aria-hidden": "true" }, label));
  let timer = null;
  const start = (e) => {
    if (e.type === "keydown" && (e.repeat || !(e.key === " " || e.key === "Enter"))) return;
    if (e.type === "pointerdown" && e.button !== 0) return;
    e.preventDefault();
    btn.setAttribute("data-holding", "");
    timer = setTimeout(() => { btn.removeAttribute("data-holding"); onDone(); }, 1200);
  };
  const stop = () => { clearTimeout(timer); btn.removeAttribute("data-holding"); };
  btn.addEventListener("pointerdown", start);
  btn.addEventListener("keydown", start);
  ["pointerup", "pointerleave", "pointercancel", "keyup", "blur"].forEach((ev) => btn.addEventListener(ev, stop));
  btn.addEventListener("click", (e) => e.preventDefault()); // a quick click does nothing
  return btn;
}

// ---------- "How busy is it?" ----------
function initStatus() {
  const form = $("[data-status-form]");
  const pill = $("[data-status]", form);
  const message = form.elements.namedItem("message");
  const counter = $("[data-status-counter]");
  const submit = $("[data-status-submit]");
  loadStatus(pill).then((st) => {
    if (st && ["quiet", "steady", "busy", "packed"].includes(st.level)) {
      $(`#lv-${st.level}`).checked = true;
      message.value = st.message || "";
      counter.textContent = `${[...message.value].length} / 60`;
    }
  });
  message.addEventListener("input", () => { counter.textContent = `${[...message.value].length} / 60`; });
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const level = new FormData(form).get("level");
    if (!level) {
      showFieldErrors(form, { level: "Choose how busy it is" });
      return;
    }
    showFieldErrors(form, {});
    busy(submit, true, "Updating…");
    try {
      const st = await adminApi("/api/admin/status", { method: "PUT", body: { level, message: message.value } });
      renderStatus(pill, st);
      toast(st.level === "closed" ? "Saved. The site says Closed until we open." : "Updated: the site shows it within 30 seconds");
    } catch (err) {
      if (err instanceof ApiError && err.status === 400) showFieldErrors(form, err.fields);
      else if (!(err instanceof NeedLogin)) toast(friendly(err));
    } finally {
      busy(submit, false, "Update the site");
    }
  });
}

// ---------- menu: sold out and prices ----------
async function loadMenu() {
  const box = $("[data-admin-menu]");
  box.replaceChildren(h("div", { class: "card card-pad" }, h("div", { class: "skeleton" })));
  try {
    const menu = await api("/api/menu");
    box.replaceChildren(...menu.sections.map((s) => h("section", { class: "card admin-section" },
      h("h2", { class: "h3" }, s.title),
      h("div", { class: "admin-rows" }, s.items.map((item) => menuRow(item))))));
  } catch (err) {
    box.replaceChildren(h("p", { class: "notice notice-error" }, friendly(err)));
  }
}

function menuRow(item) {
  const sizes = Object.keys(item.prices);
  const inputs = sizes.map((size) => h("label", { class: "price-input" },
    h("span", { class: "size" }, size === "each" ? "Price" : `${size[0].toUpperCase()}${size.slice(1)}`),
    h("span", { class: "pound" }, "£",
      h("input", { class: "input", type: "number", inputmode: "decimal", min: "0", max: "50", step: "0.05", value: (item.prices[size] / 100).toFixed(2), dataset: { size } }))));
  const save = h("button", { class: "btn btn-primary btn-sm", type: "button", hidden: true }, "Save price");
  const sold = h("input", { type: "checkbox", role: "switch", class: "switch", "aria-label": `${item.name} sold out today` });
  sold.checked = item.soldOut;
  const row = h("div", { class: "admin-row", "data-sold-out": item.soldOut ? "" : null },
    h("div", { class: "admin-row-name" }, h("strong", {}, item.name)),
    h("div", { class: "admin-row-prices" }, inputs, save),
    h("label", { class: "switch-label" }, sold, h("span", {}, "Sold out today")));

  const current = () => Object.fromEntries($$("input[data-size]", row).map((i) => [i.dataset.size, Math.round(Number(i.value) * 100)]));
  $$("input[data-size]", row).forEach((i) => i.addEventListener("input", () => {
    const changed = Object.entries(current()).some(([k, v]) => v !== item.prices[k]);
    save.hidden = !changed;
  }));
  save.addEventListener("click", async () => {
    const changed = Object.fromEntries(Object.entries(current()).filter(([k, v]) => v !== item.prices[k]));
    if (Object.values(changed).some((v) => !Number.isInteger(v) || v < 0 || v > 5000)) {
      toast("Prices are between £0 and £50");
      return;
    }
    busy(save, true, "Saving…");
    try {
      const updated = await adminApi(`/api/admin/menu/${encodeURIComponent(item.id)}`, { method: "PATCH", body: { prices: changed } });
      Object.assign(item.prices, updated.prices);
      save.hidden = true;
      toast(`${item.name}: ${Object.entries(updated.prices).map(([k, v]) => `${k === "each" ? "" : `${k} `}${money(v)}`).join(", ")}`);
    } catch (err) {
      if (!(err instanceof NeedLogin)) toast(err.status === 400 ? Object.values(err.fields).join(". ") || friendly(err) : friendly(err));
    } finally {
      busy(save, false, "Save price");
    }
  });
  sold.addEventListener("change", async () => {
    const want = sold.checked;
    sold.disabled = true;
    try {
      const updated = await adminApi(`/api/admin/menu/${encodeURIComponent(item.id)}`, { method: "PATCH", body: { soldOut: want } });
      item.soldOut = updated.soldOut;
      row.toggleAttribute("data-sold-out", updated.soldOut);
      toast(updated.soldOut ? `${item.name}: sold out until 06:00 tomorrow` : `${item.name}: back on`);
    } catch (err) {
      sold.checked = !want;
      if (!(err instanceof NeedLogin)) toast(friendly(err));
    } finally {
      sold.disabled = false;
    }
  });
  return row;
}

// ---------- bookings for a day ----------
const KINDS = { "latte-art": "Latte art class", "welsh-cakes": "Welsh cake class" };
const TYPES = { room: "Study room", group: "Group table", class: "Class" };
function initBookings() {
  const input = $("[data-booking-date]");
  input.value = ukToday();
  input.addEventListener("change", () => input.value && loadBookings(input.value));
  loadBookings(input.value);
}
async function loadBookings(date) {
  const box = $("[data-admin-bookings]");
  const count = $("[data-booking-count]");
  box.replaceChildren(h("div", { class: "card card-pad" }, h("div", { class: "skeleton" })));
  count.textContent = "";
  try {
    const data = await adminApi(`/api/admin/bookings?date=${date}`);
    const people = data.bookings.reduce((n, b) => n + b.partySize, 0);
    count.textContent = data.bookings.length
      ? `${data.bookings.length} booking${data.bookings.length === 1 ? "" : "s"}, ${people} ${people === 1 ? "person" : "people"} · ${formatDate(date)}`
      : formatDate(date);
    if (!data.bookings.length) {
      box.replaceChildren(h("div", { class: "card card-pad muted" }, "No bookings on this day."));
      return;
    }
    box.replaceChildren(h("div", { class: "table-wrap" }, h("table", { class: "data-table stack-on-phone" },
      h("thead", {}, h("tr", {}, ["Time", "What", "People", "Name", "Email", "Notes"].map((c) => h("th", { scope: "col" }, c)))),
      h("tbody", {}, data.bookings.map((b) => h("tr", {},
        h("td", { "data-label": "Time" }, h("strong", {}, b.time)),
        h("td", { "data-label": "What" }, h("div", {}, KINDS[b.classKind] || TYPES[b.type], b.society ? h("div", { class: "hint", dir: "auto" }, b.society) : null, h("div", { class: "hint" }, b.reference))),
        h("td", { "data-label": "People" }, String(b.partySize)),
        h("td", { "data-label": "Name", dir: "auto" }, b.name),
        h("td", { "data-label": "Email" }, h("a", { href: `mailto:${b.email}` }, b.email)),
        h("td", { "data-label": "Notes", class: "notes-cell", dir: "auto" }, b.notes || "–")))))));
  } catch (err) {
    if (!(err instanceof NeedLogin)) box.replaceChildren(h("p", { class: "notice notice-error" }, friendly(err)));
  }
}

// ---------- start ----------
(async function init() {
  const p = new URLSearchParams(location.search);
  if (p.get("error")) {
    history.replaceState(null, "", "/admin/");
    showLogin("The login didn't finish. Please try again.");
    return;
  }
  if (p.get("code")) {
    try {
      await finishLogin(p.get("code"), p.get("state"));
    } catch {
      showLogin("That login link didn't work (it may be old or used already). Please log in again.");
      return;
    }
  }
  if (!tokens()) {
    showLogin();
    return;
  }
  showApp();
})();
