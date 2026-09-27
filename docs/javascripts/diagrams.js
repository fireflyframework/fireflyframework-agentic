/* Keep dense Mermaid diagrams readable without changing Material's renderer. */
(function () {
  "use strict";

  function enhance() {
    document.querySelectorAll("div.mermaid:not([data-ff-diagram])").forEach(function (diagram) {
      diagram.dataset.ffDiagram = "1";
      var frame = document.createElement("div");
      frame.className = "ff-diagram";
      var button = document.createElement("button");
      button.type = "button";
      button.className = "ff-diagram-toggle";
      button.textContent = "Expand diagram";
      button.setAttribute("aria-expanded", "false");
      var viewport = document.createElement("div");
      viewport.className = "ff-diagram-scroll";
      viewport.tabIndex = 0;
      viewport.setAttribute("role", "region");
      viewport.setAttribute("aria-label", "Diagram; expand to read labels and scroll horizontally");
      diagram.before(frame);
      frame.append(button, viewport);
      viewport.append(diagram);
      button.addEventListener("click", function () {
        var expanded = frame.classList.toggle("ff-diagram--expanded");
        button.textContent = expanded ? "Fit diagram to page" : "Expand diagram";
        button.setAttribute("aria-expanded", String(expanded));
        viewport.scrollLeft = expanded ? (viewport.scrollWidth - viewport.clientWidth) / 2 : 0;
      });
    });
  }

  function start() {
    enhance();
    // Rendering is asynchronous, including after Material instant navigation.
    new MutationObserver(enhance).observe(document.body, { childList: true, subtree: true });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", start, { once: true });
  } else {
    start();
  }
})();
