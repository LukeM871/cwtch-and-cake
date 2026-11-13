// Runs in <head> before the page is drawn (an ordinary script file, so the CSP allows it).
// 1. Applies a saved theme choice straight away, so there's no flash of the wrong colours.
//    With no saved choice, the CSS follows the device's light/dark setting by itself.
// 2. Marks that JavaScript is running, so the CSS can enhance things safely.
(function () {
  var root = document.documentElement;
  root.classList.add("js");
  try {
    var saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") root.setAttribute("data-theme", saved);
  } catch (e) {
    // Storage blocked (private mode, strict settings): just follow the device.
  }
})();
