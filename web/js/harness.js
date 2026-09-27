// Evaluation harness page: one row per committed capability and quarantined attempt.
const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const CATS = ["Contract", "Execution", "Data", "Analytical quality", "Grounding", "User value", "Governance"];

async function load() {
  const rows = await (await fetch("/api/evaluations")).json();
  const head = `<tr><th>Capability / attempt</th><th>Status</th><th>Stage</th><th>Blocking</th><th>Warnings</th><th>Overall</th>${CATS.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>`;
  const body = rows.map((r) => {
    const cats = Object.fromEntries((r.categories || []).map((c) => [c.category, c]));
    const cells = CATS.map((c) => {
      const x = cats[c];
      if (!x) return '<td class="score">—</td>';
      const cls = !x.passed ? "fail" : x.score >= 1 ? "full" : "part";
      return `<td class="score ${cls}">${Math.round(x.score * 100)}%</td>`;
    }).join("");
    const status = r.kind === "committed" ? '<span class="res pass">committed</span>' : '<span class="res fail">quarantined</span>';
    return `<tr class="row" data-ref="${esc(r.report_ref)}"><td><b>${esc(r.title)}</b><br><span class="code muted small">${esc(r.capability_id)} ${esc(r.version)}</span></td>
      <td>${status}</td><td>${esc(r.stage || "")}</td>
      <td class="num">${r.blocking_total ? `${r.blocking_passed}/${r.blocking_total}` : "—"}</td>
      <td class="num">${r.warnings_raised ?? "—"}</td><td class="num">${r.overall_score != null ? r.overall_score.toFixed(2) : "—"}</td>${cells}</tr>`;
  }).join("");
  $("#matrix").innerHTML = head + (body || `<tr><td colspan="${6 + CATS.length}" class="muted">No evaluations yet.</td></tr>`);
  document.querySelectorAll("tr.row").forEach((tr) => tr.addEventListener("click", () => show(tr.dataset.ref)));
  const want = new URLSearchParams(location.search).get("report") || rows[rows.length - 1]?.report_ref;
  if (want) show(want);
}

async function show(ref) {
  document.querySelectorAll("tr.row").forEach((tr) => tr.classList.toggle("on", tr.dataset.ref === ref));
  history.replaceState(null, "", `?report=${encodeURIComponent(ref)}`);
  const res = await fetch(`/api/evaluations/${encodeURIComponent(ref)}`);
  if (!res.ok) { $("#detail").innerHTML = `<p class="muted">Report ${esc(ref)} not found.</p>`; return; }
  const d = await res.json();
  const rep = d.report;
  let header = "";
  if (d.kind === "quarantined" && d.attempt) {
    header = `<div class="card failed"><h3>Quarantined at “${esc(d.attempt.failure_stage)}”</h3><p class="small">${esc(d.attempt.failure_reason)}</p>
      ${d.attempt.admission_violations?.length ? `<p class="small">Admission: ${d.attempt.admission_violations.map(esc).join("<br>")}</p>` : ""}</div>`;
  }
  if (!rep) { $("#detail").innerHTML = header + '<p class="muted">This candidate was rejected before evaluation, so there is no harness report.</p>'; return; }
  const rows = CATS.map((cat) => {
    const checks = rep.checks.filter((c) => c.category === cat);
    const sc = rep.categories.find((c) => c.category === cat);
    return `<tr class="cat"><td colspan="3">${esc(cat)}</td><td class="num">${Math.round(sc.score * 100)}%</td><td></td></tr>` + checks.map((c) => {
      const res = c.passed ? '<span class="res pass">pass</span>' : c.blocking ? '<span class="res fail">fail</span>' : '<span class="res warn">warning</span>';
      return `<tr><td>${esc(c.name)}</td><td>${c.blocking ? "blocking" : "warning"}</td><td>${res}</td><td class="num">${c.score.toFixed(2)}</td>
        <td class="obs">${esc(c.observed)}${c.expected ? `<br><span class="small">expected: ${esc(c.expected)}</span>` : ""}</td></tr>`;
    }).join("");
  }).join("");
  $("#detail").innerHTML = `${header}
    <h2>${esc(rep.capability_id)} ${esc(rep.capability_version)} · verdict <span class="res ${rep.verdict === "pass" ? "pass" : "fail"}">${esc(rep.verdict)}</span></h2>
    <p class="small muted">${rep.blocking_passed}/${rep.blocking_total} blocking checks passed · ${rep.warnings_raised} warning(s) · overall score ${rep.overall_score.toFixed(3)} · harness ${esc(rep.harness_version)} · content hash <span class="code">${esc(rep.content_hash.slice(0, 16))}…</span> · ${esc(rep.created_at)}</p>
    <table class="checks"><tr><th>Check</th><th>Type</th><th>Result</th><th>Score</th><th>Observed</th></tr>${rows}</table>`;
}

load();
