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

// ------------------------------------------------------------------ color maps (platform-owned presentation)
const RAMPS = {
  greens: ["#f7fcf5", "#c7e9c0", "#74c476", "#238b45", "#00441b"],
  blues: ["#f7fbff", "#c6dbef", "#6baed6", "#2171b5", "#08306b"],
  reds: ["#fff5f0", "#fcbba1", "#fb6a4a", "#cb181d", "#67000d"],
  purples: ["#fcfbfd", "#dadaeb", "#9e9ac8", "#6a51a3", "#3f007d"],
  ylorrd: ["#ffffcc", "#fed976", "#fd8d3c", "#e31a1c", "#800026"],
};
const hex = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
function rampColor(name, t) {
  const stops = RAMPS[name] || RAMPS.purples;
  const x = Math.min(1, Math.max(0, t)) * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(x)), f = x - i;
  const a = hex(stops[i]), b = hex(stops[i + 1]);
  return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * f)).join(",")})`;
}
const fmtNum = (v) => (v === null || v === undefined ? "–" : Number.isInteger(v) ? String(v) : Math.abs(v) >= 100 ? v.toFixed(1) : Number(v.toPrecision(4)).toString());

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
  state.lastVis = a.visualization;
  drawGrid(tr, a.visualization);
  const head = a.source === "new"
    ? `<div class="card new"><h3>New capability created, evaluated and saved</h3><p class="small">No existing capability matched, so AgriMon generated <b>${esc(a.capability_id)}</b>, passed every blocking check and committed it. It will be reused for similar questions.</p><button class="chip" id="open-cap">View capability</button></div>`
    : `<div class="card"><h3>Answered by an existing capability</h3><p class="small"><b>${esc(a.capability_id)} ${esc(a.capability_version)}</b> matched deterministically. <button class="chip" id="open-cap">View capability</button></p></div>`;
  const layer = `<dl class="kv"><dt>Layer</dt><dd>${esc(tr.layer_name)}</dd><dt>Analysis type</dt><dd class="code">${esc(tr.analysis_type)}</dd>
      <dt>Asset</dt><dd class="code">${esc(tr.asset_id)}</dd><dt>Matrix</dt><dd>${tr.grid_size.rows}×${tr.grid_size.cols} · color map ${esc(tr.color_map)}</dd></dl>`;
  const metrics = tr.metrics.map((m) => `<tr><td>${esc(m.description || m.name)}<br><span class="code muted">${esc(m.name)} · ${esc(m.source)}</span></td><td>${esc(fmtNum(m.value))} ${esc(m.unit === "percent" ? "%" : m.unit)}</td></tr>`).join("");
  const findings = tr.findings.map((f) => `<li>${esc(f.statement)}<br>${f.evidence.map((e) => `<span class="ev">${esc(e)}</span>`).join("")}</li>`).join("");
  const steps = tr.next_steps.map((s) => `<li><span class="steptype">${s.type === "human_inspection" ? "Inspect" : "Follow-up"}</span>${esc(s.description)} <span class="ev">from ${esc(s.follows_from)}</span></li>`).join("");
  const classes = tr.classification ? `<div><h2>Classes</h2><table class="metrics">${tr.classification.classes.map((c) =>
      `<tr><td>${esc(c.label)}<br><span class="muted small">${esc(c.description)}</span></td><td>${c.share_pct}% · ${c.cell_count} cells</td></tr>`).join("")}</table></div>` : "";
  const zones = tr.zones && tr.zones.length ? `<div><h2>Zones</h2><table class="metrics">${tr.zones.map((z) =>
      `<tr><td><span class="code">${esc(z.id)}</span></td><td>${z.cell_count} cells · ${z.share_pct}% · mean ${esc(fmtNum(z.mean_value))}</td></tr>`).join("")}</table></div>` : "";
  $("#tab-analysis").innerHTML = `${head}
    <div><h2>Summary</h2><p>${esc(tr.summary)}</p></div>
    <div><h2>Findings</h2><ol class="findings">${findings}</ol></div>
    <div><h2>Next steps</h2><ul class="steps">${steps || '<li class="muted">None</li>'}</ul></div>
    ${evalBlock(a.evaluation)}
    <div><h2>Metrics</h2><table class="metrics">${metrics}</table></div>
    ${classes}${zones}
    <div><h2>Result</h2>${layer}</div>
    <div><h2>Request</h2>${intent}</div>
    <details><summary>Matrix (${tr.grid_size.rows}×${tr.grid_size.cols} values)</summary><pre class="json">${esc(tr.matrix.map((r) => r.map((v) => (v === null ? "null" : v)).join(", ")).join("\n"))}</pre></details>
    <details><summary>ToolResult JSON</summary><pre class="json">${esc(JSON.stringify({ ...tr, matrix: `[${tr.grid_size.rows} rows omitted: see Matrix]` }, null, 2))}</pre></details>`;
  $("#open-cap")?.addEventListener("click", () => showCapability(a.capability_id, a.capability_version));
  tab("analysis");
}

async function showCapability(id, version) {
  document.querySelectorAll(".cap").forEach((b) => b.classList.toggle("on", b.dataset.id === id));
  const d = await api(`/api/capabilities/${encodeURIComponent(id)}/${encodeURIComponent(version)}`);
  const m = d.manifest, e = d.entry;
  const classes = m.classification ? `<dt>Classes</dt><dd>${m.classification.map((c) => `${c.id}: ${esc(c.label)}${c.description ? " — " + esc(c.description) : ""}`).join("<br>")}</dd>` : "<dt>Classes</dt><dd>none (continuous result)</dd>";
  const ramp = (RAMPS[m.color_map] || []).map((c) => `<i style="background:${c}"></i>`).join("");
  const creating = d.creating_run ? `<div class="card"><h3>Created from</h3><p class="small">“${esc(d.creating_run.question)}”</p><p class="small">${esc(d.creating_run.summary)}</p></div>` : "";
  $("#tab-capability").innerHTML = `
    <div class="card ${e.origin === "generated" ? "new" : ""}"><h3>${esc(m.name)}</h3>
      <p class="small">${esc(m.description)}</p>
      <dl class="kv">
        <dt>Id · version</dt><dd class="code">${esc(e.id)} · ${esc(e.version)}</dd>
        <dt>Analysis key</dt><dd class="code">${esc(e.analysis_key)}${e.aliases.length ? " (aliases: " + e.aliases.map(esc).join(", ") + ")" : ""}</dd>
        <dt>Analysis type</dt><dd class="code">${esc(m.analysis_type)}</dd>
        <dt>Layer</dt><dd>${esc(m.layer_name)} · ${esc(m.value_label)}${m.value_unit ? " (" + esc(m.value_unit) + ")" : ""}</dd>
        <dt>Method</dt><dd>${esc(m.method)}</dd>
        <dt>Citation</dt><dd>${esc(m.citation || "none given")}</dd>
        <dt>Bands</dt><dd>${esc(m.required_bands.join(", "))}</dd>
        <dt>Aggregation</dt><dd>${esc(m.aggregation)} per cell</dd>
        ${classes}
        <dt>Color map</dt><dd><span class="swatches">${esc(m.color_map)} ${ramp}</span></dd>
        <dt>Origin</dt><dd>${esc(e.origin)} · committed ${esc(e.committed_at)} · ${esc(e.contract)}</dd>
        <dt>Content hash</dt><dd class="code">${esc(e.content_hash.slice(0, 16))}…</dd>
      </dl>
    </div>
    ${evalBlock(d.evaluation)}
    ${creating}
    <details><summary>Capability source (read-only)</summary><pre class="json">${esc(d.source)}</pre></details>`;
  tab("capability");
}

// ------------------------------------------------------------------ matrix canvas
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

function drawGrid(tr, vis) {
  const g = tr.grid_size;
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
  ctx.clearRect(0, 0, w, h);
  const cw = w / g.cols, ch = h / g.rows;
  const classes = tr.classification ? tr.classification.classes : null;
  const classColor = {};
  if (classes) classes.forEach((c, i) => { classColor[c.id] = rampColor(tr.color_map, classes.length === 1 ? 1 : 0.15 + 0.85 * i / (classes.length - 1)); });
  const lo = vis?.display_min ?? 0, hi = vis?.display_max ?? 1, span = hi > lo ? hi - lo : 1;
  for (let r = 0; r < g.rows; r++) for (let c = 0; c < g.cols; c++) {
    const v = tr.matrix[r][c];
    ctx.fillStyle = v === null ? "rgba(128,128,128,.25)" : classes ? (classColor[v] || "#999") : rampColor(tr.color_map, (v - lo) / span);
    ctx.fillRect(c * cw, r * ch, Math.ceil(cw), Math.ceil(ch));
  }
  // outline the largest zone of each region type the analysis defined (zones are optional)
  const firsts = (tr.zones || []).filter((z) => z.id.endsWith("-1"));
  const outline = ["#e0452f", "#2f7de0", "#8a2be2", "#111111"];
  firsts.forEach((z, i) => {
    ctx.strokeStyle = outline[i % outline.length];
    ctx.lineWidth = 1.5;
    const inZone = new Set(z.cells.map(([r, c]) => `${r},${c}`));
    ctx.beginPath();
    for (const [r, c] of z.cells) {
      const x = c * cw, y = r * ch;
      if (!inZone.has(`${r - 1},${c}`)) { ctx.moveTo(x, y); ctx.lineTo(x + cw, y); }
      if (!inZone.has(`${r + 1},${c}`)) { ctx.moveTo(x, y + ch); ctx.lineTo(x + cw, y + ch); }
      if (!inZone.has(`${r},${c - 1}`)) { ctx.moveTo(x, y); ctx.lineTo(x, y + ch); }
      if (!inZone.has(`${r},${c + 1}`)) { ctx.moveTo(x + cw, y); ctx.lineTo(x + cw, y + ch); }
    }
    ctx.stroke();
  });
  canvas.hidden = state.view !== "grid";
  $("#source-img").hidden = state.view !== "image";
  $("#viz-empty").hidden = true;
  $("#viz-title").textContent = `${tr.layer_name} · ${g.rows}×${g.cols}`;
  const zoneLegend = firsts.map((z, i) => `<span style="color:${outline[i % outline.length]}">▭ ${esc(z.id)}</span>`).join("");
  if (classes) {
    $("#legend").innerHTML = classes.map((c) => `<span><i style="background:${classColor[c.id]}"></i>${esc(c.label)} (${c.share_pct}%)</span>`).join("")
      + `<span><i style="background:rgba(128,128,128,.25)"></i>no data</span>${zoneLegend}`;
  } else {
    const grad = (RAMPS[tr.color_map] || []).join(",");
    $("#legend").innerHTML = `<span class="gradient"><b>${esc(fmtNum(lo))}</b><i class="bar" style="background:linear-gradient(90deg,${grad})"></i><b>${esc(fmtNum(hi))}</b></span>`
      + `<span class="muted">observed ${esc(fmtNum(vis?.observed_min))} to ${esc(fmtNum(vis?.observed_max))}; colors span the 2nd–98th percentile</span>`
      + `<span><i style="background:rgba(128,128,128,.25)"></i>no data</span>${zoneLegend}`;
  }
  canvas.onmousemove = (ev) => {
    const rect = canvas.getBoundingClientRect();
    const c = Math.floor((ev.clientX - rect.left) / (rect.width / g.cols)), r = Math.floor((ev.clientY - rect.top) / (rect.height / g.rows));
    if (r < 0 || c < 0 || r >= g.rows || c >= g.cols) return;
    const v = tr.matrix[r][c];
    const cls = classes && v !== null ? classes.find((x) => x.id === v) : null;
    const zone = (tr.zones || []).find((z) => z.cells.some(([zr, zc]) => zr === r && zc === c));
    const tip = $("#tooltip");
    tip.innerHTML = `row ${r}, col ${c}<br>${v === null ? "no data" : cls ? esc(cls.label) : `${esc(tr.layer_name)}: ${esc(fmtNum(v))}`}${zone ? `<br>zone ${esc(zone.id)}` : ""}`;
    const wrap = $("#canvas-wrap").getBoundingClientRect();
    tip.style.left = `${ev.clientX - wrap.left + 12}px`; tip.style.top = `${ev.clientY - wrap.top + 12}px`;
    tip.hidden = false;
  };
  canvas.onmouseleave = () => { $("#tooltip").hidden = true; };
}

boot().catch((err) => setStatus(`Could not load: ${err.message}`));
