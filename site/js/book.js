// Booking: type → day → time (live availability) → details → POST /api/booking.
// The API is the real judge of every rule (docs/API.md section 4); the page just makes
// the right choices easy and explains the answers. A slot taken a moment ago (409) is the
// DynamoDB transaction doing its job: we say sorry and show the latest times.
import { $, $$, h, api, friendly, ukToday, addDays, formatDate, weekday, busy, showFieldErrors } from "./core.js";

const RULES = {
  room: { label: "Study room", party: [2, 6], start: 4, minutes: 120 },
  class: { label: "Saturday class", party: [1, 4], start: 2, minutes: 90 },
  group: { label: "Group table", party: [5, 20], start: 8, minutes: 120 },
};
const CLASS_NAMES = { "latte-art": "Latte art class", "welsh-cakes": "Welsh cake baking class" };
const WINDOW_DAYS = 60;
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

const form = $("[data-booking]");
const field = (name) => form.elements.namedItem(name);
const steps = { date: $('[data-step="date"]'), time: $('[data-step="time"]'), details: $('[data-step="details"]') };
const partyOut = $("[data-party-out]");
const [minus, plus] = $$("[data-party]");
const submit = $("[data-submit]");
const formError = $("[data-form-error]");
const state = { type: null, date: null, slot: null, party: 2 };
let slotsRequest = null;

// ---------- step 1: type ----------
$$('input[name="type"]', form).forEach((radio) => radio.addEventListener("change", () => chooseType(radio.value)));
const fromUrl = new URLSearchParams(location.search).get("type");
if (RULES[fromUrl]) {
  $(`#type-${fromUrl}`).checked = true;
  chooseType(fromUrl);
}

function chooseType(type) {
  const changed = state.type !== type;
  state.type = type;
  if (changed) {
    state.slot = null;
    state.party = RULES[type].start;
  }
  $("[data-society-field]").hidden = type !== "group";
  const url = new URL(location.href);
  url.searchParams.set("type", type);
  history.replaceState(null, "", url);
  setEnabled(steps.date, true);
  renderDates();
  updateParty(0);
}

// ---------- step 2: day ----------
function dateOptions(type) {
  const today = ukToday();
  const out = [];
  if (type === "class") {
    for (let i = 0; i <= WINDOW_DAYS && out.length < 9; i++) {
      const d = addDays(today, i);
      if (weekday(d) === 6) out.push(d);
    }
  } else {
    for (let i = 0; i < 14; i++) out.push(addDays(today, i));
  }
  return out;
}

function renderDates() {
  const today = ukToday();
  const dates = dateOptions(state.type);
  $("[data-dates]").replaceChildren(...dates.map((d) => {
    const name = d === today ? "Today" : d === addDays(today, 1) ? "Tomorrow" : null;
    const [, month, day] = d.split("-");
    return h("button", {
      type: "button", class: "date-btn", "aria-pressed": "false", dataset: { date: d },
      "aria-label": `${name ? `${name}, ` : ""}${formatDate(d)}`, onclick: () => chooseDate(d),
    },
    h("span", { class: "dow" }, name || formatDate(d, "short").split(" ")[0]),
    h("span", { class: "day" }, String(Number(day))),
    h("span", { class: "mon" }, new Intl.DateTimeFormat("en-GB", { month: "short", timeZone: "UTC" }).format(new Date(`2026-${month}-15T12:00:00Z`))));
  }));
  const other = $("[data-other-date]");
  other.min = today;
  other.max = addDays(today, WINDOW_DAYS);
  $("[data-date-more]").hidden = state.type === "class"; // the strip already shows every Saturday you can book
  const stillValid = state.date && state.date >= today && (state.type !== "class" || weekday(state.date) === 6);
  chooseDate(stillValid ? state.date : dates[0]);
}

$("[data-other-date]").addEventListener("change", (e) => {
  const d = e.target.value;
  if (!d) return;
  if (d < e.target.min || d > e.target.max) {
    $("[data-slots-note]").textContent = "You can book from today up to 60 days ahead.";
    return;
  }
  chooseDate(d);
});

function chooseDate(d) {
  state.date = d;
  state.slot = null;
  let inStrip = false;
  $$(".date-btn").forEach((b) => {
    const on = b.dataset.date === d;
    inStrip ||= on;
    b.setAttribute("aria-pressed", String(on));
  });
  $("[data-other-date]").value = inStrip ? "" : d;
  setEnabled(steps.time, true);
  setEnabled(steps.details, false);
  updateSummary();
  loadSlots();
}

// ---------- step 3: time ----------
async function loadSlots() {
  slotsRequest?.abort();
  slotsRequest = new AbortController();
  const box = $("[data-slots]");
  const note = $("[data-slots-note]");
  note.textContent = "";
  box.setAttribute("aria-busy", "true");
  box.replaceChildren(...Array.from({ length: state.type === "class" ? 2 : 4 }, () => h("div", { class: "slot skeleton", "aria-hidden": "true" }, h("span", { class: "time" }, " "))));
  try {
    const data = await api(`/api/availability?type=${state.type}&date=${state.date}`, { signal: slotsRequest.signal });
    renderSlots(data.slots);
  } catch (err) {
    if (err.name === "AbortError") return;
    box.replaceChildren();
    note.textContent = friendly(err);
  } finally {
    box.setAttribute("aria-busy", "false");
  }
}

function leftText(s) {
  if (s.available <= 0) return "Full";
  if (state.type === "class") return s.available === 1 ? "1 place left" : `${s.available} places left`;
  if (state.type === "room") return s.available === 1 ? "Last room" : `${s.available} rooms free`;
  return "Table free";
}
function endTime(time) {
  const [hh, mm] = time.split(":").map(Number);
  const end = hh * 60 + mm + RULES[state.type].minutes;
  return `${String(Math.floor(end / 60)).padStart(2, "0")}:${String(end % 60).padStart(2, "0")}`;
}

function renderSlots(slots) {
  const box = $("[data-slots]");
  const note = $("[data-slots-note]");
  if (!slots.length) {
    box.replaceChildren();
    note.textContent = state.date === ukToday()
      ? "There are no more times left today. Try another day."
      : "There's nothing to book on this day. Try another day.";
    return;
  }
  note.textContent = state.type === "class" ? "Each class lasts 90 minutes." : "Bookings last 2 hours.";
  box.replaceChildren(...slots.map((s) => {
    const full = s.available <= 0;
    const few = !full && s.available <= (state.type === "class" ? 3 : 1);
    return h("button", {
      type: "button", class: "slot", disabled: full, "aria-pressed": "false", "data-few": few ? "" : null,
      dataset: { time: s.time },
      "aria-label": `${s.time} to ${endTime(s.time)}${s.classKind ? `, ${CLASS_NAMES[s.classKind]}` : ""}, ${leftText(s)}`,
      onclick: () => chooseSlot(s),
    },
    h("span", { class: "time" }, s.time),
    s.classKind ? h("span", { class: "kind" }, CLASS_NAMES[s.classKind].replace(" class", "")) : null,
    h("span", { class: "left" }, leftText(s)));
  }));
}

function chooseSlot(s) {
  state.slot = s;
  $$(".slot").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.time === s.time)));
  setEnabled(steps.details, true);
  hideFormError();
  updateParty(0);
}

// ---------- step 4: details ----------
function partyRange() {
  const [lo, hi] = RULES[state.type].party;
  const max = state.type === "class" && state.slot ? Math.min(hi, state.slot.available) : hi;
  return [lo, Math.max(lo, max)];
}
function updateParty(delta) {
  if (!state.type) return;
  const [lo, hi] = partyRange();
  state.party = Math.min(Math.max(state.party + delta, lo), hi);
  partyOut.textContent = String(state.party);
  minus.disabled = state.party <= lo;
  plus.disabled = state.party >= hi;
  const [, typeMax] = RULES[state.type].party;
  $("[data-party-hint]").textContent = state.type === "class" && hi < typeMax
    ? `Only ${hi} place${hi === 1 ? "" : "s"} left at this time.`
    : `${lo} to ${typeMax} people.`;
  updateSummary();
}
minus.addEventListener("click", () => updateParty(-1));
plus.addEventListener("click", () => updateParty(1));

const notes = field("notes");
const counter = $('[data-counter-for="notes"]');
notes.addEventListener("input", () => {
  const n = [...notes.value].length;
  counter.textContent = `${n} / 500`;
  counter.dataset.state = n > 480 ? "low" : "";
});

// ---------- summary ----------
function updateSummary() {
  const set = (k, v) => { $(`[data-sum="${k}"]`).textContent = v; };
  const kind = state.slot?.classKind;
  set("type", state.type ? (kind ? CLASS_NAMES[kind] : RULES[state.type].label) : "Choose below");
  set("date", state.date ? formatDate(state.date) : "–");
  set("time", state.slot ? `${state.slot.time} to ${endTime(state.slot.time)}` : "–");
  set("party", state.type ? `${state.party} ${state.party === 1 ? "person" : "people"}` : "–");
}

// ---------- submit ----------
form.addEventListener("submit", async (e) => {
  e.preventDefault();
  hideFormError();
  if (!state.type || !state.date || !state.slot) {
    showFormError("Pick a day and a time first.");
    return;
  }
  const body = {
    type: state.type, date: state.date, time: state.slot.time, partySize: state.party,
    name: field("name").value, email: field("email").value, notes: notes.value, website: field("website").value,
  };
  if (state.type === "group") body.society = field("society").value;

  // Quick checks for the obvious; the API checks everything properly.
  const errors = {};
  if (!body.name.trim()) errors.name = "Enter your name";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(body.email.trim())) errors.email = "Enter a valid email address";
  if (state.type === "group" && !body.society.trim()) errors.society = "Enter the society or group name";
  if (Object.keys(errors).length) {
    showFieldErrors(form, errors)?.focus();
    return;
  }
  showFieldErrors(form, {});
  busy(submit, true, "Booking…");
  try {
    const res = await api("/api/booking", { method: "POST", body });
    const done = new URL("/book/confirmed/", location.origin);
    const params = {
      ref: res.reference, type: state.type, date: state.date, time: state.slot.time, party: state.party,
      kind: state.slot.classKind || "", emailed: res.emailSent ? "1" : "0",
    };
    for (const [k, v] of Object.entries(params)) if (v !== "") done.searchParams.set(k, v);
    location.assign(done);
  } catch (err) {
    busy(submit, false, "Book it");
    if (err.status === 409) {
      showFormError("Sorry, someone has just taken that time. Here are the latest times: pick another one.");
      state.slot = null;
      setEnabled(steps.details, false);
      loadSlots();
      steps.time.scrollIntoView({ block: "start", behavior: reduced ? "auto" : "smooth" });
      return;
    }
    if (err.status === 400 && Object.keys(err.fields).length) {
      const { type, date, time, classKind, ...rest } = err.fields;
      const top = [type, date, time, classKind].filter(Boolean);
      const first = showFieldErrors(form, rest);
      if (top.length) showFormError(top.join(". "));
      else if (!first) showFormError(friendly(err));
      first?.focus();
      return;
    }
    showFormError(friendly(err));
  }
});

function showFormError(text) {
  formError.replaceChildren(text);
  formError.hidden = false;
}
function hideFormError() { formError.hidden = true; }

function setEnabled(step, on) {
  step.toggleAttribute("data-disabled", !on);
  step.inert = !on;
}
setEnabled(steps.date, Boolean(state.type));
setEnabled(steps.time, Boolean(state.date));
setEnabled(steps.details, Boolean(state.slot));
