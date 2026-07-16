// Two small conveniences for the user-management page (/settings/users):
// a copy-to-clipboard button on the one-time password reveal panel, and an
// optional "Generate" button that fills a password field with a random
// value client-side (never sent anywhere until the surrounding form submits).
(function () {
  function copyPassword(btn) {
    var target = document.getElementById(btn.dataset.copyTarget);
    if (!target) return;
    navigator.clipboard.writeText(target.textContent).then(
      function () {
        var original = btn.textContent;
        btn.textContent = "Copied!";
        setTimeout(function () {
          btn.textContent = original;
        }, 1500);
      },
      function () {}
    );
  }

  function generatePassword(btn) {
    var form = btn.closest("form");
    var input = form && form.querySelector('[name="' + btn.dataset.targetInput + '"]');
    if (!input) return;
    var bytes = new Uint8Array(18);
    crypto.getRandomValues(bytes);
    input.type = "text";
    input.value = btoa(String.fromCharCode.apply(null, bytes)).replace(/[+/=]/g, "").slice(0, 20);
  }

  document.addEventListener("click", function (evt) {
    var copyBtn = evt.target.closest(".copy-password-btn");
    if (copyBtn) {
      copyPassword(copyBtn);
      return;
    }
    var genBtn = evt.target.closest(".generate-password-btn");
    if (genBtn) {
      generatePassword(genBtn);
    }
  });
})();
