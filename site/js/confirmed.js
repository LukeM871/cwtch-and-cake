// Booking confirmed: the details come from the address the booking form sent us to
// (?ref=CC-7F3K9Q&type=room&date=...), so nothing personal is kept in the browser.
import { $, h, formatDate, toast } from "./core.js";

const p = new URLSearchParams(location.search);
const ref = (p.get("ref") || "").toUpperCase();
const type = p.get("type");
const date = p.get("date");
const time = p.get("time");
const rawParty = Number(p.get("party"));
const party = Number.isInteger(rawParty) && rawParty >= 1 && rawParty <= 20 ? rawParty : 0; // anything else was edited by hand
const kind = p.get("kind");
const emailed = p.get("emailed") === "1";

const LABELS = { room: "Study room", group: "Group table", class: "Saturday class" };
const KINDS = { "latte-art": "Latte art class", "welsh-cakes": "Welsh cake baking class" };
const MINUTES = { room: 120, group: 120, class: 90 };
const valid = /^CC-[0-9A-HJKMNP-TV-Z]{6}$/.test(ref) && LABELS[type] && /^\d{4}-\d{2}-\d{2}$/.test(date || "") && /^\d{2}:\d{2}$/.test(time || "");

if (!valid) {
  $("[data-missing]").hidden = false;
} else {
  render();
}

function endTime() {
  const [hh, mm] = time.split(":").map(Number);
  const end = hh * 60 + mm + MINUTES[type];
  return `${String(Math.floor(end / 60)).padStart(2, "0")}:${String(end % 60).padStart(2, "0")}`;
}

function render() {
  const what = KINDS[kind] || LABELS[type];
  $("[data-ticket]").hidden = false;
  $("[data-when]").textContent = `Diolch! See you on ${formatDate(date)} at ${time}.`;
  $("[data-ref]").textContent = ref;
  $("[data-details]").replaceChildren(
    h("dt", {}, "What"), h("dd", {}, what),
    h("dt", {}, "Day"), h("dd", {}, formatDate(date, "full")),
    h("dt", {}, "Time"), h("dd", {}, `${time} to ${endTime()}`),
    ...(party ? [h("dt", {}, "People"), h("dd", {}, `${party} ${party === 1 ? "person" : "people"}`)] : []));
  $("[data-email-note]").textContent = emailed
    ? "We've emailed you a confirmation too. You'll need your reference and email to cancel."
    : "Save this reference (a screenshot is fine). You'll need it, with your email, to cancel.";
  $("[data-cancel]").href = `/book/cancel/?ref=${encodeURIComponent(ref)}`;
  document.title = `You're booked in (${ref}) · Cwtch & Cake`;

  $("[data-copy]").addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(ref);
      toast("Reference copied");
    } catch {
      toast(`Your reference is ${ref}`);
    }
  });
  $("[data-calendar]").addEventListener("click", () => downloadIcs(what));
}

// A calendar file in UK local time, so it lands at the right time in any calendar app.
function downloadIcs(what) {
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace(/\.\d+/, "");
  const local = (t) => `${date.replace(/-/g, "")}T${t.replace(":", "")}00`;
  const ics = [
    "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Cwtch & Cake//Bookings//EN", "CALSCALE:GREGORIAN",
    "BEGIN:VEVENT",
    `UID:${ref}@cwtch-and-cake`,
    `DTSTAMP:${stamp}`,
    `DTSTART;TZID=Europe/London:${local(time)}`,
    `DTEND;TZID=Europe/London:${local(endTime())}`,
    `SUMMARY:${what} at Cwtch & Cake`,
    `DESCRIPTION:Booking reference ${ref}. To cancel: ${location.origin}/book/cancel/?ref=${ref}`,
    "LOCATION:Cwtch & Cake\\, Cathays\\, Cardiff",
    "END:VEVENT", "END:VCALENDAR", "",
  ].join("\r\n");
  const url = URL.createObjectURL(new Blob([ics], { type: "text/calendar" }));
  const a = h("a", { href: url, download: `cwtch-and-cake-${ref}.ics` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
