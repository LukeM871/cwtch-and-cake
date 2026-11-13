// Reviews: the approved reviews and summary (GET /api/reviews, paged with a cursor),
// and the form (POST /api/reviews). What the API checks, in order: fields and the word
// filter, then the booking for a Verified visit, then (when switched on) the AI check.
import { $, $$, h, api, count, friendly, busy, showFieldErrors, photo, stars, stagger } from "./core.js";
import { reviewCard, REVIEW_TAGS } from "./review-card.js";

const MAX_TAGS = 3;
const REF = /^CC-[0-9A-HJKMNP-TV-Z]{6}$/;

// ---------- the list ----------
const list = $("[data-reviews]");
const more = $("[data-more]");
let cursor = null;

loadPage(true);
more.addEventListener("click", () => loadPage(false));

async function loadPage(first) {
  busy(more, true, "Loading…");
  if (first) list.replaceChildren(...Array.from({ length: 3 }, () => h("div", { class: "card review", "aria-hidden": "true" },
    h("div", { class: "skeleton skel-line short" }), h("div", { class: "skeleton skel-line" }), h("div", { class: "skeleton skel-line" }))));
  try {
    const qs = new URLSearchParams({ limit: "10" });
    if (cursor) qs.set("cursor", cursor);
    const data = await api(`/api/reviews?${qs}`);
    if (first) {
      renderSummary(data.summary);
      list.replaceChildren();
    }
    if (first && !data.reviews.length) list.replaceChildren(emptyState());
    const cards = data.reviews.map((r) => reviewCard(r));
    list.append(...cards);
    if (!first) cards[0]?.setAttribute("tabindex", "-1");
    stagger(list, ":scope > .review:not(.enter)");
    if (!first) cards[0]?.focus({ preventScroll: true });
    cursor = data.nextCursor;
    more.hidden = !cursor;
  } catch (err) {
    if (first) list.replaceChildren(h("p", { class: "notice notice-error" }, friendly(err)));
    else list.append(h("p", { class: "notice notice-error" }, friendly(err)));
  } finally {
    busy(more, false, "Show more reviews");
  }
}

// The summary card always keeps its size (so nothing below it jumps): only its words change.
function renderSummary(s) {
  if (!s.count) {
    $("[data-avg]").textContent = "New";
    $("[data-stars-wrap]").replaceChildren(stars(0), h("span", { class: "muted" }, "No reviews yet. Yours could be the first."));
    return;
  }
  $("[data-avg]").textContent = s.averageRating.toFixed(1);
  $("[data-stars-wrap]").replaceChildren(
    stars(Math.round(s.averageRating)),
    h("span", { class: "muted" }, `from ${count(s.count)} review${s.count === 1 ? "" : "s"}`));
  $("[data-top-tags]").replaceChildren(...s.topTags.map((t) => h("li", { class: "tag" }, REVIEW_TAGS[t] || t)));
}

function emptyState() {
  return h("div", { class: "card reviews-empty" },
    photo("tea-and-welsh-cakes", { sizes: "(max-width: 980px) 100vw, 700px", alt: "" }),
    h("div", { class: "reviews-empty-copy" },
      h("h2", { class: "h3" }, "Be the first to review Cwtch & Cake"),
      h("p", { class: "muted" }, "Been in for a coffee and a Welsh cake? Tell other students what you thought."),
      h("a", { class: "btn btn-primary", href: "#leave-a-review" }, "Leave a review")));
}

// ---------- the form ----------
const form = $("[data-review-form]");
const el = (name) => form.elements.namedItem(name);
const submit = $("[data-submit]");
const formError = $("[data-form-error]");
const counter = $("[data-counter]");

// Tag chips: checkboxes styled as chips, at most 3.
$("[data-tags]").replaceChildren(...Object.entries(REVIEW_TAGS).map(([value, label]) =>
  h("span", { class: "chip-input" },
    h("input", { type: "checkbox", name: "tags", id: `tag-${value}`, value }),
    h("label", { class: "chip", for: `tag-${value}` }, label))));
const tagBoxes = $$('input[name="tags"]', form);
const syncTags = () => {
  const full = tagBoxes.filter((b) => b.checked).length >= MAX_TAGS;
  tagBoxes.forEach((b) => { b.disabled = full && !b.checked; });
};
tagBoxes.forEach((b) => b.addEventListener("change", syncTags));

const comment = el("comment");
const updateCounter = () => {
  const n = [...comment.value.trim()].length;
  counter.textContent = n < 20 ? `${n} / 500 · at least 20` : `${n} / 500`;
  counter.dataset.state = n > 480 ? "low" : "";
};
comment.addEventListener("input", updateCounter);

const refInput = el("reference");
refInput.addEventListener("input", () => {
  const raw = refInput.value.toUpperCase().replace(/[^0-9A-Z]/g, "");
  const body = raw.startsWith("CC") ? raw.slice(2) : raw;
  refInput.value = body ? `CC-${body.slice(0, 6)}` : raw;
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.hidden = true;
  const rating = Number(new FormData(form).get("rating"));
  const reference = refInput.value.trim().toUpperCase();
  const email = el("email").value.trim();
  const body = {
    rating,
    tags: tagBoxes.filter((b) => b.checked).map((b) => b.value),
    comment: comment.value,
    displayName: el("displayName").value,
    courseYear: el("courseYear").value,
    website: el("website").value,
  };
  if (reference || email) Object.assign(body, { reference, email });

  const errors = {};
  if (!rating) errors.rating = "Choose a rating from 1 to 5 stars";
  if ([...comment.value.trim()].length < 20) errors.comment = "Write at least 20 characters";
  if (!body.displayName.trim()) errors.displayName = "Enter a name to show with your review";
  if (reference || email) {
    if (!REF.test(reference)) errors.reference = "References look like CC-7F3K9Q";
    if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) errors.email = "Enter the email you booked with";
  }
  if (Object.keys(errors).length) {
    if (errors.reference || errors.email) $("[data-verify]").open = true;
    showFieldErrors(form, errors)?.focus();
    return;
  }
  showFieldErrors(form, {});
  busy(submit, true, "Sending…");
  try {
    const res = await api("/api/reviews", { method: "POST", body });
    form.hidden = true;
    $("[data-thanks-text]").textContent = res.verified
      ? `${res.message} It'll have a Verified visit badge.`
      : res.message;
    const thanks = $("[data-thanks]");
    thanks.hidden = false;
    thanks.focus();
  } catch (err) {
    busy(submit, false, "Send review");
    if (err.status === 400 && Object.keys(err.fields).length) {
      if (err.fields.reference || err.fields.email) $("[data-verify]").open = true;
      showFieldErrors(form, err.fields)?.focus();
    } else if (err.status === 404) {
      $("[data-verify]").open = true;
      showFieldErrors(form, { reference: "We couldn't find a booking with that reference and email." })?.focus();
    } else if (err.status === 409) {
      $("[data-verify]").open = true;
      showFieldErrors(form, { reference: "That booking has already been used for a review. You can still post without the badge." })?.focus();
    } else {
      formError.textContent = friendly(err);
      formError.hidden = false;
    }
  }
});

$("[data-another]").addEventListener("click", () => {
  form.reset();
  syncTags();
  updateCounter();
  busy(submit, false, "Send review");
  $("[data-thanks]").hidden = true;
  form.hidden = false;
  el("comment").focus();
});
