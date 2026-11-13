// DEV ONLY (served by scripts/dev_server.py, never deployed): a "Demo / Worst case / Empty / One"
// switch for break-ui testing. It puts ?data=<mode> in the address bar; the dev server then answers
// /api/* calls from scripts/ui-fixtures/<mode>.json instead of the live API.
const modes = [["demo", "Demo data"], ["worst", "Worst case"], ["empty", "Empty"], ["one", "One"]];
const current = new URLSearchParams(location.search).get("data") || "demo";
const bar = document.createElement("div");
bar.className = "dev-data-toggle";
bar.setAttribute("role", "group");
bar.setAttribute("aria-label", "Test data (dev only)");
for (const [mode, label] of modes) {
  const b = document.createElement("button");
  b.type = "button";
  b.textContent = label;
  b.setAttribute("aria-pressed", String(mode === current));
  b.addEventListener("click", () => {
    const url = new URL(location.href);
    if (mode === "demo") url.searchParams.delete("data"); else url.searchParams.set("data", mode);
    location.assign(url);
  });
  bar.append(b);
}
document.body.append(bar);
