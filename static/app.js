// Small helpers. Every form works without this file.
(function () {
  "use strict";
  document.documentElement.classList.add("js");

  // Request a tool: check what we have when the task box loses focus or the person pauses.
  var form = document.getElementById("request-form");
  var panel = document.getElementById("match-panel");
  if (form && panel) {
    var task = document.getElementById("task");
    var timer = null;
    var last = null;
    var check = function () {
      var data = new FormData(form);
      var key = (data.get("task") || "").trim() + "|" + data.getAll("info").join(",");
      if (key === last || !(data.get("task") || "").trim()) return;
      last = key;
      var missing = document.getElementById("whats_missing");
      var body = new FormData();
      body.append("task", data.get("task"));
      data.getAll("info").forEach(function (v) { body.append("info", v); });
      if (missing) body.append("whats_missing", missing.value);
      panel.setAttribute("aria-busy", "true");
      fetch(form.getAttribute("data-check-url"), { method: "POST", body: body })
        .then(function (r) { return r.ok ? r.text() : null; })
        .then(function (html) { if (html !== null) panel.innerHTML = html; })
        .catch(function () {})
        .then(function () { panel.setAttribute("aria-busy", "false"); });
    };
    task.addEventListener("blur", check);
    task.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(check, 1200);
    });
    form.querySelectorAll('input[name="info"]').forEach(function (el) {
      el.addEventListener("change", function () { if (task.value.trim()) { last = null; check(); } });
    });
    last = (task.value || "").trim() + "|" + new FormData(form).getAll("info").join(",");
    document.querySelectorAll(".js-hide").forEach(function (el) { el.hidden = true; });
  }

  // Review queue: show only the fields the chosen outcome needs, and the sends warning.
  var decision = document.getElementById("decision-form");
  if (decision) {
    var update = function () {
      var chosen = decision.querySelector('input[name="outcome"]:checked');
      var value = chosen ? chosen.value : "";
      decision.querySelectorAll(".js-cond").forEach(function (el) {
        var wanted = (el.getAttribute("data-for") || "").split(" ");
        el.hidden = wanted.indexOf(value) === -1;
      });
      var sends = decision.querySelector('input[name="sends_without_check"]:checked');
      var warning = document.getElementById("sends-warning");
      if (warning) warning.hidden = !(sends && sends.value === "yes");
    };
    decision.addEventListener("change", update);
    update();

    // "Draft the reason for me" without a page reload.
    var btn = document.getElementById("draft-btn");
    var note = document.getElementById("draft-note");
    btn.addEventListener("click", function (e) {
      e.preventDefault();
      var body = new FormData(decision);
      btn.disabled = true;
      note.textContent = "Claude is drafting...";
      fetch(decision.getAttribute("data-draft-url"), { method: "POST", body: body })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (data.error) {
            note.innerHTML = "";
            var err = document.createElement("span");
            err.className = "field-error";
            err.textContent = data.error;
            note.appendChild(err);
            return;
          }
          document.getElementById("reason").value = data.reason;
          document.getElementById("what_would_change").value = data.what_would_change;
          document.getElementById("drafted_reason").value = data.reason;
          note.innerHTML = "";
          var span = document.createElement("span");
          span.className = "claude-note";
          span.style.margin = "8px 0 0";
          span.textContent = data.note + " A person decides.";
          note.appendChild(span);
        })
        .catch(function () { note.textContent = "Claude couldn't draft a reason just now. You can write it yourself."; })
        .then(function () { btn.disabled = false; });
    });
  }
})();
