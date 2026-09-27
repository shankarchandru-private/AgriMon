// AgriMon Evolution 1 UI: three panels, request-status polling, canvas grid.
const $ = (sel) => document.querySelector(sel);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const api = async (path, opts) => {
  const res = await fetch(path, opts);
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json();
};

const STEPS = [
  { key: "question", label: "Question", states: ["received"] },
  { key: "intent", label: "Intent", states: ["resolving_intent"] },
  { key: "match", label: "Match", states: ["matching", "matched", "no_match"] },
  { key: "exec", label: "Execute / Generate", states: ["executing", "generating"] },
  { key: "validate", label: "Validate", states: ["admitting", "executing_staged"] },
  { key: "evaluate", label: "Evaluate", states: ["evaluating"] },
  { key: "commit", label: "Commit / Quarantine", states: ["committing"] },
  { key: "answer", label: "Answer", states: ["completed"] },
];

const state = { scene: null, scenes: [], lastResult: null, capabilities: [], view: "grid", polling: null };

// ------------------------------------------------------------------ boot
async function boot() {
  renderStepper(null);
  const [health, assets] = await Promise.all([api("/api/health"), api("/api/assets")]);
  renderHealth(health);
  state.scenes = assets.scenes;
  state.scene = assets.scenes.find((s) => s.id === "eros_reservoir_farmland")?.id || assets.scenes[0]?.id;
  renderScenes();
  await refreshCapabilities();
}

function renderHealth(h) {
  const llm = h.llm_configured
    ? `<span><i class="dot ok"></i>OpenAI: ${esc(h.models.intent)}</span>`
    : `<span><i class="dot bad"></i>No OpenAI key (.env)</span>`;
  const ok = h.ok ? `<span><i class="dot ok"></i>Registry v${h.registry_version} · ${h.capabilities} capabilities</span>`
    : `<span><i class="dot warn"></i>Check /api/health</span>`;
  $("#health").innerHTML = llm + ok;
}

function renderScenes() {
  $("#scenes").innerHTML = state.scenes.map((s) => `
    <button class="scene ${s.id === state.scene ? "on" : ""}" data-id="${esc(s.id)}" aria-pressed="${s.id === state.scene}">
      <img src="/api/assets/${encodeURIComponent(s.id)}/image" alt="">
      <span><span class="name">${esc(s.label)}</span><br>
      <span class="meta">${esc(s.bands.map((b) => b.name).join(", "))} · ${s.width}×${s.height} px<br>
      ${esc(s.acquisition_date || "date not recorded")} · ${s.crs ? esc(s.crs) : "not georeferenced"}</span></span>
    </button>`).join("");
  document.querySelectorAll(".scene").forEach((b) => b.addEventListener("click", () => {
    state.scene = b.dataset.id;
    renderScenes();
    if (state.view === "image") showImage();
  }));
}

async function refreshCapabilities(highlight) {
  const data = await api("/api/capabilities");
  state.capabilities = data.capabilities;
  $("#registry-version").textContent = `registry v${data.registry_version}`;
  $("#capabilities").innerHTML = data.capabilities.slice().reverse().map((c) => `
    <li><button class="cap ${highlight === c.id ? "on" : ""}" data-id="${esc(c.id)}" data-version="${esc(c.version)}">
      <span class="row1"><span class="title">${esc(c.name)}</span>
        ${c.is_new ? '<span class="badge new">New</span>' : c.origin === "seed" ? '<span class="badge seed">Seed</span>' : '<span class="badge gen">Generated</span>'}
      </span>
      <span class="key">${esc(c.analysis_key)} · ${esc(c.version)} · score ${c.overall_score.toFixed(2)}</span>
    </button></li>`).join("");
  document.querySelectorAll(".cap").forEach((b) => b.addEventListener("click", () => showCapability(b.dataset.id, b.dataset.version)));
}

// ------------------------------------------------------------------ asking
$("#ask").addEventListener("submit", async (e) => {
  e.preventDefault();
  const q = $("#question").value.trim();
  if (!q || !state.scene) return;
  $("#ask-btn").disabled = true;
  renderStepper({ state: "received", history: [{ state: "received" }] });
  setStatus("Submitting…");
  try {
    const { request_id } = await api("/api/requests", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question: q, scene_id: state.scene }),
    });
    poll(request_id);
  } catch (err) {
    setStatus(`Could not submit: ${err.message}`);
    $("#ask-btn").disabled = false;
  }
});
document.querySelectorAll(".chip").forEach((c) => c.addEventListener("click", () => { $("#question").value = c.dataset.q; $("#question").focus(); }));

function poll(id) {
  clearInterval(state.polling);
  const tick = async () => {
    let rec;
    try { rec = await api(`/api/requests/${id}`); } catch { return; }
    renderStepper(rec);
    const last = rec.history[rec.history.length - 1];
    setStatus(`${label(rec.state)}${last?.note ? " — " + last.note : ""}`);
    if (rec.state === "completed" || rec.state === "failed") {
      clearInterval(state.polling);
      $("#ask-btn").disabled = false;
      renderAnswer(rec);
      const newCap = rec.answer?.source === "new" ? rec.answer.capability_id : undefined;
      await refreshCapabilities(newCap);
      api("/api/health").then(renderHealth);
    }
  };
  state.polling = setInterval(tick, 1000);
  tick();
}

const LABELS = {
  received: "Question received", resolving_intent: "Resolving intent", matching: "Matching capabilities",
  matched: "Matched an existing capability", no_match: "No capability matches: creating one", executing: "Executing capability",
  generating: "Generating a new capability", admitting: "Validating: admission checks", executing_staged: "Validating: staged execution",
  evaluating: "Evaluating: 17-check harness", committing: "Committing to the registry", quarantined: "Candidate quarantined",
  completed: "Answered", failed: "Failed",
};
const label = (s) => LABELS[s] || s;
const setStatus = (t) => { $("#status").textContent = t; };

function renderStepper(rec) {
  const seen = new Set((rec?.history || []).map((h) => h.state));
  const matched = seen.has("matched");
  const failed = rec?.state === "failed";
  const cur = failed ? [...(rec.history || [])].reverse().find((h) => h.state !== "failed")?.state : rec?.state;
  $("#stepper").innerHTML = STEPS.map((s) => {
    let cls = "";
    const inStep = s.states.includes(cur);
    if (s.states.some((x) => seen.has(x))) cls = "done";
    if (inStep) cls = failed ? "failed" : rec?.state === "completed" ? "done" : "active";
    if (matched && ["validate", "evaluate", "commit"].includes(s.key)) cls = "skipped";
    if (s.key === "answer" && rec?.state === "completed") cls = "done";
    return `<li class="${cls}">${esc(s.label)}</li>`;
  }).join("");
}

// ------------------------------------------------------------------ answer panel
function tab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.classList.toggle("on", b.dataset.tab === name));
  $("#tab-analysis").hidden = name !== "analysis";
  $("#tab-capability").hidden = name !== "capability";
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => tab(b.dataset.tab)));

function evalBlock(ev) {
  if (!ev) return "";
  const bars = ev.categories.map((c) => {
    const pct = Math.round(c.score * 100);
    const cls = !c.passed ? "bad" : c.score < 1 ? "low" : "";
    return `<div class="bar"><span>${esc(c.category)}</span><span class="track"><span class="fill ${cls}" style="width:${pct}%"></span></span><span class="v">${pct}%</span></div>`;
  }).join("");
  const link = ev.report_ref ? `<a href="harness.html?report=${encodeURIComponent(ev.report_ref)}" target="_blank" rel="noopener">Open full evaluation ↗</a>` : "";
  return `<div class="card"><h3>Evaluation <span class="badge ${ev.verdict}">${esc(ev.verdict)}</span></h3>
    <p class="small muted">${ev.blocking_passed}/${ev.blocking_total} blocking checks passed · ${ev.warnings_raised} warning(s) · overall ${ev.overall_score.toFixed(2)}</p>
    <div class="bars">${bars}</div><p class="small">${link}</p></div>`;
}

function renderAnswer(rec) {
  const intent = rec.intent ? `<dl class="kv">
      <dt>Analysis key</dt><dd class="code">${esc(rec.intent.analysis_key)}${rec.intent.is_new_key ? " (new)" : ""}</dd>
      <dt>Intent</dt><dd>${esc(rec.intent.description)}</dd>
      ${rec.intent.assumptions.length ? `<dt>Assumptions</dt><dd>${rec.intent.assumptions.map(esc).join("<br>")}</dd>` : ""}
      ${rec.match ? `<dt>Match</dt><dd>${esc(rec.match.rule)}: ${esc(rec.match.reason)}</dd>` : ""}
    </dl>` : "";

  if (rec.state === "failed") {
    const f = rec.failure || {};
    const unchanged = f.committed_state_unchanged === true ? "<dt>Committed capabilities</dt><dd>Unchanged (verified)</dd>" : "";
    const q = (f.quarantined_attempts || []).map((a) => `<a href="harness.html?report=att:${encodeURIComponent(a)}" target="_blank">${esc(a)}</a>`).join("<br>");
    $("#tab-analysis").innerHTML = `<div class="card failed"><h3>Request failed at “${esc(label(f.stage))}”</h3>
      <p class="small">${esc(f.reason)}</p><dl class="kv">${unchanged}${q ? `<dt>Quarantined</dt><dd>${q}</dd>` : ""}</dl>
      <p class="small muted">Other questions keep working; the registry was not modified.</p></div>${intent}`;
    tab("analysis");
    return;
  }

  const a = rec.answer, tr = a.tool_result;
  state.lastResult = tr;
  drawGrid(tr);
  const cap = state.capabilities.find((c) => c.id === a.capability_id);
  const head = a.source === "new"
    ? `<div class="card new"><h3>New capability created, evaluated and saved</h3><p class="small">No existing capability matched, so AgriMon generated <b>${esc(a.capability_id)}</b>, passed all blocking checks and committed it. It will be reused for similar questions.</p><button class="chip" id="open-cap">View capability</button></div>`
    : `<div class="card"><h3>Answered by an existing capability</h3><p class="small"><b>${esc(a.capability_id)} ${esc(a.capability_version)}</b> matched deterministically. <button class="chip" id="open-cap">View capability</button></p></div>`;
  const metrics = tr.metrics.map((m) => `<tr><td>${esc(m.description || m.name)}<br><span class="code muted">${esc(m.name)}</span></td><td>${esc(m.value)} ${esc(m.unit === "percent" ? "%" : m.unit)}</td></tr>`).join("");
  const findings = tr.findings.map((f) => `<li>${esc(f.statement)}<br>${f.evidence.map((e) => `<span class="ev">${esc(e)}</span>`).join("")}</li>`).join("");
  const steps = tr.next_steps.map((s) => `<li><span class="steptype">${s.type === "human_inspection" ? "Inspect" : "Follow-up"}</span>${esc(s.description)} <span class="ev">from ${esc(s.follows_from)}</span></li>`).join("");
  $("#tab-analysis").innerHTML = `${head}
    <div><h2>Summary</h2><p>${esc(tr.summary)}</p></div>
    <div><h2>Findings</h2><ol class="findings">${findings}</ol></div>
    <div><h2>Next steps</h2><ul class="steps">${steps || '<li class="muted">None</li>'}</ul></div>
    ${evalBlock(a.evaluation)}
    <div><h2>Metrics</h2><table class="metrics">${metrics}</table></div>
    <div><h2>Request</h2>${intent}</div>
    <details><summary>ToolResult JSON</summary><pre class="json">${esc(JSON.stringify(tr, null, 2))}</pre></details>`;
  $("#open-cap")?.addEventListener("click", () => showCapability(a.capability_id, a.capability_version));
  tab("analysis");
  void cap;
}

async function showCapability(id, version) {
  document.querySelectorAll(".cap").forEach((b) => b.classList.toggle("on", b.dataset.id === id));
  const d = await api(`/api/capabilities/${encodeURIComponent(id)}/${encodeURIComponent(version)}`);
  const m = d.manifest, e = d.entry;
  const swatches = m.classes.map((c) => `<span><i style="background:${esc(c.color)}"></i>${esc(c.label)} (${c.min}–${c.max})</span>`).join("");
  const creating = d.creating_run ? `<div class="card"><h3>Created from</h3><p class="small">“${esc(d.creating_run.question)}”</p><p class="small">${esc(d.creating_run.summary)}</p></div>` : "";
  $("#tab-capability").innerHTML = `
    <div class="card ${e.origin === "generated" ? "new" : ""}"><h3>${esc(m.name)}</h3>
      <p class="small">${esc(m.description)}</p>
      <dl class="kv">
        <dt>Id · version</dt><dd class="code">${esc(e.id)} · ${esc(e.version)}</dd>
        <dt>Analysis key</dt><dd class="code">${esc(e.analysis_key)}${e.aliases.length ? " (aliases: " + e.aliases.map(esc).join(", ") + ")" : ""}</dd>
        <dt>Origin</dt><dd>${esc(e.origin)} · committed ${esc(e.committed_at)}</dd>
        <dt>Formula</dt><dd>${esc(m.formula)}</dd>
        <dt>Citation</dt><dd>${esc(m.citation || "—")}</dd>
        <dt>Bands</dt><dd>${esc(m.required_bands.join(", "))}</dd>
        <dt>Value</dt><dd>${esc(m.value_label)} [${m.value_min}, ${m.value_max}]</dd>
        <dt>Content hash</dt><dd class="code">${esc(e.content_hash.slice(0, 16))}…</dd>
      </dl>
      <div class="swatches" style="margin-top:8px">${swatches}</div>
    </div>
    ${evalBlock(d.evaluation)}
    ${creating}
    <details><summary>Capability source (read-only)</summary><pre class="json">${esc(d.source)}</pre></details>`;
  tab("capability");
}

// ------------------------------------------------------------------ grid canvas
document.querySelectorAll(".toggle button").forEach((b) => b.addEventListener("click", () => {
  state.view = b.dataset.view;
  document.querySelectorAll(".toggle button").forEach((x) => x.classList.toggle("on", x === b));
  if (state.view === "image") showImage(); else { $("#source-img").hidden = true; $("#grid-canvas").hidden = !state.lastResult; $("#viz-empty").hidden = !!state.lastResult; }
}));

function showImage() {
  const img = $("#source-img");
  img.src = `/api/assets/${encodeURIComponent(state.scene)}/image`;
  img.hidden = false;
  $("#grid-canvas").hidden = true;
  $("#viz-empty").hidden = true;
}

function drawGrid(tr) {
  const g = tr.grid;
  const canvas = $("#grid-canvas");
  const aspect = (g.cols * g.cell_width_px) / (g.rows * g.cell_height_px);
  const maxW = Math.min(560, $("#canvas-wrap").clientWidth - 24), maxH = 560;
  let w = maxW, h = w / aspect;
  if (h > maxH) { h = maxH; w = h * aspect; }
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.round(w * dpr); canvas.height = Math.round(h * dpr);
  canvas.style.width = `${Math.round(w)}px`; canvas.style.height = `${Math.round(h)}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  const cw = w / g.cols, ch = h / g.rows;
  const colors = Object.fromEntries(tr.color_map.map((c) => [c.id, c.color]));
  for (let r = 0; r < g.rows; r++) for (let c = 0; c < g.cols; c++) {
    const id = g.class_ids[r][c];
    ctx.fillStyle = id < 0 ? "rgba(128,128,128,.25)" : colors[id];
    ctx.fillRect(c * cw, r * ch, Math.ceil(cw), Math.ceil(ch));
  }
  // outline the largest high and low zones
  ctx.lineWidth = 2;
  for (const z of tr.zones.filter((z) => z.id === "high-1" || z.id === "low-1")) {
    ctx.setLineDash([5, 3]);
    ctx.strokeStyle = z.id.startsWith("high") ? "#e0452f" : "#2f7de0";
    ctx.strokeRect(z.col_min * cw + 1, z.row_min * ch + 1, (z.col_max - z.col_min + 1) * cw - 2, (z.row_max - z.row_min + 1) * ch - 2);
    ctx.setLineDash([]);
    ctx.fillStyle = ctx.strokeStyle;
    ctx.font = "bold 11px system-ui";
    ctx.fillText(z.id, z.col_min * cw + 4, z.row_min * ch + 13);
  }
  canvas.hidden = state.view !== "grid";
  $("#source-img").hidden = state.view !== "image";
  $("#viz-empty").hidden = true;
  $("#viz-title").textContent = `${g.value_label} · ${g.rows}×${g.cols} grid`;
  $("#legend").innerHTML = tr.color_map.map((c) => `<span><i style="background:${esc(c.color)}"></i>${esc(c.label)} (${c.min}–${c.max})</span>`).join("")
    + `<span><i style="background:rgba(128,128,128,.25)"></i>no data</span><span style="color:#e0452f">▭ high-1</span><span style="color:#2f7de0">▭ low-1</span>`;
  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const c = Math.floor((ev.clientX - rect.left) / (rect.width / g.cols)), r = Math.floor((ev.clientY - rect.top) / (rect.height / g.rows));
    if (r < 0 || c < 0 || r >= g.rows || c >= g.cols) return;
    const id = g.class_ids[r][c];
    const cls = tr.color_map.find((x) => x.id === id);
    const tip = $("#tooltip");
    const v = g.values[r][c];
    tip.innerHTML = `row ${r}, col ${c}<br>${cls ? esc(cls.label) : "no data"}${v === null ? "" : `<br>mean ${v} · min ${g.minimum[r][c]} · max ${g.maximum[r][c]}`}`;
    const wrap = $("#canvas-wrap").getBoundingClientRect();
    tip.style.left = `${ev.clientX - wrap.left + 12}px`; tip.style.top = `${ev.clientY - wrap.top + 12}px`;
    tip.hidden = false;
  };
  canvas.onmouseleave = () => { $("#tooltip").hidden = true; };
}

boot().catch((err) => setStatus(`Could not load: ${err.message}`));
