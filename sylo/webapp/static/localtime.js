// Converts server-rendered UTC timestamps (see timeutil.format_receipt_time)
// to the browser's local timezone for display. Storage/queries stay UTC --
// only this rendering step changes -- so it must re-run after every htmx
// swap, not just once on load, since paginated results and SSE live-tail
// rows arrive via htmx swaps of their own.
(function () {
  function pad(n) {
    return String(n).padStart(2, "0");
  }

  function formatLocal(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return iso;
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      " " + pad(d.getHours()) + ":" + pad(d.getMinutes()) + ":" + pad(d.getSeconds())
    );
  }

  function convertAll(root) {
    (root || document).querySelectorAll("time[datetime]").forEach(function (el) {
      if (el.dataset.localtimeDone) return;
      el.textContent = formatLocal(el.getAttribute("datetime"));
      el.dataset.localtimeDone = "1";
    });
  }

  // Mirror of formatLocal, but shaped for an <input type="datetime-local">
  // value ("YYYY-MM-DDTHH:MM", no timezone/seconds) instead of display text.
  function formatLocalInputValue(iso) {
    var d = new Date(iso);
    if (isNaN(d.getTime())) return "";
    return (
      d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
      "T" + pad(d.getHours()) + ":" + pad(d.getMinutes())
    );
  }

  // The inverse: a datetime-local input's value has no timezone, but per
  // the JS Date parsing spec a date-time string without an offset is
  // interpreted as local time (unlike a date-only string, which is UTC) --
  // exactly the local wall-clock value the widget shows, so this needs no
  // extra timezone math beyond reading it out again in UTC.
  function toUtcIsoFixed(localValue) {
    var d = new Date(localValue);
    if (isNaN(d.getTime())) return null;
    return (
      d.getUTCFullYear() + "-" + pad(d.getUTCMonth() + 1) + "-" + pad(d.getUTCDate()) +
      "T" + pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + ":" + pad(d.getUTCSeconds()) +
      "+00:00"
    );
  }

  function populateDatetimeLocalInputs(root) {
    (root || document).querySelectorAll("input[type=datetime-local][data-utc]").forEach(function (el) {
      if (!el.dataset.utc) return;
      el.value = formatLocalInputValue(el.dataset.utc);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    convertAll(document);
    populateDatetimeLocalInputs(document);
  });
  document.addEventListener("htmx:afterSettle", function (evt) {
    convertAll(evt.target);
  });

  // Runs for every htmx request (the main search form's submit and the
  // "Next page" button's hx-include alike), rewriting the raw local
  // datetime-local value htmx already collected into the fixed UTC format
  // the server's _normalize_bound expects -- storage/queries stay UTC-only
  // (section 3), only the browser-facing input/display layer deals in
  // local time (plan section 9, findings 1 and 4).
  document.addEventListener("htmx:configRequest", function (evt) {
    ["start", "end"].forEach(function (key) {
      var value = evt.detail.parameters[key];
      if (value) {
        var utc = toUtcIsoFixed(value);
        if (utc) evt.detail.parameters[key] = utc;
      }
    });
  });
})();
