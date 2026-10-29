// app.js - only used by the "New request" page.
// It collects the form values, sends them as JSON to /api/preview/... or /api/submit/...
// and draws the answer. All rules run on the server (Python), none in the browser.

function csrfToken() {
  return document.querySelector("[name=csrfmiddlewaretoken]").value;
}

async function post(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken() },
    body: JSON.stringify(payload),
  });
  return response.json();
}

function show(html) {
  document.getElementById("result").innerHTML = html;
}

function esc(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function drawRoute(data) {
  const facts = [];
  if (data.kind === "leave") {
    facts.push(`Policy: ${esc(data.policy)} (max ${data.max_days} business days in a row)`);
    facts.push(`${data.calendar_days} calendar days = ${data.business_days} business days`);
    if (data.available !== null) facts.push(`Available balance: ${data.available} days`);
    if (data.clashes.length) facts.push(`Overlaps: ${esc(data.clashes.join(", "))}`);
  } else {
    facts.push(`Total: ${data.total} USD, cost centre ${esc(data.cost_center)}`);
    facts.push(`Worst line vs policy limit: ${esc(data.worst)}`);
    facts.push(`Budget exceeded: ${data.budget_exceeded ? "yes (" + (data.overshoot * 100).toFixed(1) + "% over)" : "no"}`);
  }
  const failed = data.failed.length
    ? `<div class="alert alert-danger">Screening failed: <strong>${esc(data.failed.join(", "))}</strong>. No approvers are needed - the request is rejected.</div>`
    : "";
  const steps = data.plan.map((s) => `
    <div class="route-step ${s.duplicate ? "dup" : ""}">
      <strong>Step ${s.step}: ${esc(s.role)}</strong> &rarr; ${esc(s.approver_name)} (${esc(s.approver_id)})
      ${s.duplicate ? '<span class="badge text-bg-secondary">skipped: same person as an earlier step</span>' : ""}
      <div class="small text-muted">${esc(s.why)}</div>
    </div>`).join("");
  return `<div class="card"><div class="card-header">Router answer</div><div class="card-body">
    <ul>${facts.map((f) => `<li>${f}</li>`).join("")}</ul>${failed}
    <p><strong>${esc(data.outcome || "")}</strong></p>${steps}</div></div>`;
}

async function run(kind, action) {
  const payload = { employee_id: document.getElementById("employee").value };
  if (kind === "leave") {
    payload.leave_type = document.getElementById("leave-type").value;
    payload.start = document.getElementById("leave-start").value;
    payload.end = document.getElementById("leave-end").value;
    payload.reason = document.getElementById("leave-reason").value;
  } else {
    payload.purpose = document.getElementById("exp-purpose").value;
    payload.lines = [...document.querySelectorAll("#lines tr")].map((row) => ({
      category: row.querySelector(".l-category").value,
      amount: row.querySelector(".l-amount").value,
      expense_date: row.querySelector(".l-date").value,
      receipt_no: row.querySelector(".l-receipt").value,
    }));
  }
  const data = await post(`/api/${action}/${kind}/`, payload);
  if (data.errors && data.errors.length) {
    show(`<div class="alert alert-danger">${data.errors.map(esc).join("<br>")}</div>`);
  } else if (action === "submit") {
    window.location = data.url;          // go to the saved request
  } else {
    show(drawRoute(data));
  }
}

function addLine() {
  const template = document.getElementById("line-template");
  document.getElementById("lines").appendChild(template.content.cloneNode(true));
}

document.addEventListener("DOMContentLoaded", () => {
  if (!document.getElementById("employee")) return;     // not on the New request page
  addLine();
  document.getElementById("add-line").addEventListener("click", addLine);
  document.getElementById("lines").addEventListener("click", (event) => {
    if (event.target.classList.contains("l-remove")) event.target.closest("tr").remove();
  });
  document.getElementById("leave-preview").addEventListener("click", () => run("leave", "preview"));
  document.getElementById("leave-submit").addEventListener("click", () => run("leave", "submit"));
  document.getElementById("exp-preview").addEventListener("click", () => run("expense", "preview"));
  document.getElementById("exp-submit").addEventListener("click", () => run("expense", "submit"));
});
