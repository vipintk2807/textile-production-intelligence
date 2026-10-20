/* Minimal vanilla JavaScript. Server-side validation remains authoritative. */
(function () {
  "use strict";

  // Collapsible navigation on small screens.
  var toggle = document.getElementById("nav-toggle");
  var sidebar = document.getElementById("sidebar");
  if (toggle && sidebar) {
    toggle.addEventListener("click", function () {
      var open = sidebar.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // Warn before leaving an edit form with unsaved changes.
  var form = document.querySelector("form[data-warn-unsaved]");
  if (form) {
    var dirty = false;
    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("submit", function () { dirty = false; });
    window.addEventListener("beforeunload", function (event) {
      if (dirty) {
        event.preventDefault();
        event.returnValue = "";
      }
    });
  }
})();
