// Home page: live status, today's Welsh cakes, the Cwtch Deal price, today's study rooms,
// this week's hours and the latest reviews. Each part fails gently on its own.
import { $, h, api, count as fmt, money, ukToday, weekday, loadStatus, stagger, friendly } from "./core.js";
import { itemCard, skeletonCard } from "./items.js";
import { reviewCard } from "./review-card.js";

const FRESH = ["classic", "salted-caramel", "white-chocolate-raspberry", "double-chocolate"];

loadStatus($("[data-status]"));
renderWeekHours();
loadMenu();
loadRoomToday();
loadReviews();

function isExamSeason(iso) {
  const md = iso.slice(5);
  return (md >= "01-05" && md <= "01-30") || (md >= "05-11" && md <= "06-12");
}

function renderWeekHours() {
  const dl = $("[data-week-hours]");
  if (!dl) return;
  const today = ukToday();
  const todayDow = weekday(today); // 0 = Sunday
  const late = isExamSeason(today);
  const days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
  days.forEach((name, i) => {
    const dow = (i + 1) % 7;
    const weekend = dow === 0 || dow === 6;
    const hours = weekend ? "09:00 to 18:00" : `08:00 to ${late ? "21:00" : "20:00"}`;
    const isToday = dow === todayDow;
    dl.append(
      h("dt", { class: isToday ? "today" : null }, isToday ? `${name} (today)` : name),
      h("dd", { class: isToday ? "today" : null }, hours));
  });
}

async function loadMenu() {
  const grid = $("[data-fresh]");
  grid.replaceChildren(...FRESH.map(skeletonCard));
  try {
    const menu = await api("/api/menu");
    const items = menu.sections.flatMap((s) => s.items);
    let picked = FRESH.map((id) => items.find((i) => i.id === id)).filter(Boolean);
    const cakes = menu.sections.find((s) => s.id === "welsh-cakes")?.items || [];
    for (const extra of cakes) {
      if (picked.length >= FRESH.length) break;
      if (!picked.includes(extra)) picked.push(extra);
    }
    if (!picked.length) {
      grid.replaceChildren(h("p", { class: "notice" }, "Today's bakes are on the menu page. ", h("a", { class: "link", href: "/menu/" }, "See the menu")));
      return;
    }
    grid.replaceChildren(...picked.map((item) => itemCard(item, { cardSizes: "(max-width: 600px) 100vw, (max-width: 1000px) 50vw, 290px" })));
    stagger(grid);
    const deal = menu.deals.find((d) => d.id === "cwtch-deal");
    if (deal && deal.price) {
      $("[data-deal-price]").textContent = money(deal.price);
      if (deal.normalPrice) {
        $("[data-deal-was]").textContent = `Normally ${money(deal.normalPrice.from)} to ${money(deal.normalPrice.to)} · just show your student card`;
      }
    }
  } catch (err) {
    grid.replaceChildren(h("p", { class: "notice notice-error" }, `${friendly(err)} `, h("a", { class: "link", href: "/menu/" }, "Try the menu page")));
  }
}

async function loadRoomToday() {
  const out = $("[data-room-today-text]");
  if (!out) return;
  try {
    const { slots } = await api(`/api/availability?type=room&date=${ukToday()}`);
    const free = slots.filter((s) => s.available > 0);
    if (free.length) {
      const next = free[0];
      out.textContent = `A study room is free today from ${next.time}${next.available === 1 ? " (the last one)" : ""}. ${free.length} slot${free.length === 1 ? "" : "s"} left today.`;
    } else if (slots.length) {
      out.textContent = "Today's study rooms are all booked. Tomorrow is wide open.";
    } else {
      out.textContent = "No more study room slots today. Book one for tomorrow in under a minute.";
    }
  } catch {
    out.textContent = "Book a study room for up to 6 people, in 2-hour slots.";
  }
}

async function loadReviews() {
  const list = $("[data-latest-reviews]");
  const summary = $("[data-review-summary]");
  try {
    const data = await api("/api/reviews?limit=3");
    const { averageRating: avg, count } = data.summary;
    summary.textContent = count ? `${avg.toFixed(1)} out of 5 from ${fmt(count)} review${count === 1 ? "" : "s"}` : "";
    if (!data.reviews.length) {
      list.replaceChildren(h("div", { class: "card card-pad stack" },
        h("p", { class: "muted" }, "No reviews yet. Been in for a coffee? You could be the first."),
        h("a", { class: "btn btn-secondary", href: "/reviews/#leave-a-review" }, "Leave a review")));
      return;
    }
    list.replaceChildren(...data.reviews.map((r) => reviewCard(r)));
    stagger(list);
  } catch (err) {
    list.replaceChildren(h("p", { class: "notice notice-error" }, friendly(err)));
  }
}
