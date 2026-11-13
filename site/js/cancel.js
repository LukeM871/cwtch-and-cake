// Cancel a booking: POST /api/booking/cancel with the reference and email.
// A wrong reference and a wrong email get the same 404 on purpose (docs/API.md section 4),
// so references can't be probed; the page says so kindly.
import { $, api, friendly, busy, showFieldErrors } from "./core.js";

const form = $("[data-cancel-form]");
const ref = form.elements.namedItem("reference");
const email = form.elements.namedItem("email");
const submit = $("[data-submit]");
const formError = $("[data-form-error]");
const REF = /^CC-[0-9A-HJKMNP-TV-Z]{6}$/;

const fromUrl = new URLSearchParams(location.search).get("ref");
if (fromUrl) {
  ref.value = fromUrl.toUpperCase().slice(0, 9);
  email.focus();
}
// Typing "cc7f3k9q" still works: tidy it into CC-7F3K9Q as you go.
ref.addEventListener("input", () => {
  const raw = ref.value.toUpperCase().replace(/[^0-9A-Z]/g, "");
  const body = raw.startsWith("CC") ? raw.slice(2) : raw;
  ref.value = body ? `CC-${body.slice(0, 6)}` : raw;
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  formError.hidden = true;
  const reference = ref.value.trim().toUpperCase();
  const errors = {};
  if (!REF.test(reference)) errors.reference = "References look like CC-7F3K9Q";
  if (!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email.value.trim())) errors.email = "Enter a valid email address";
  if (Object.keys(errors).length) {
    showFieldErrors(form, errors)?.focus();
    return;
  }
  showFieldErrors(form, {});
  busy(submit, true, "Cancelling…");
  try {
    await api("/api/booking/cancel", {
      method: "POST",
      body: { reference, email: email.value, website: form.elements.namedItem("website").value },
    });
    form.hidden = true;
    $("[data-done-text]").textContent = `${reference} is cancelled, and the place is free for someone else. Hwyl!`;
    const done = $("[data-done]");
    done.hidden = false;
    done.focus();
  } catch (err) {
    busy(submit, false, "Cancel my booking");
    if (err.status === 404) {
      formError.textContent = "We couldn't find a booking with that reference and email. Check both: the email needs to be the one you booked with.";
      formError.hidden = false;
    } else if (err.status === 400 && Object.keys(err.fields).length) {
      showFieldErrors(form, err.fields)?.focus();
    } else {
      formError.textContent = friendly(err);
      formError.hidden = false;
    }
  }
});
