"""The validation dashboard for founder-validate: one self-contained HTML file, no network.

Real and simulated data never share a chart. Real marks are solid blue. Simulated
marks are orange, hatched, dashed and carry the word SIMULATED, so the difference
survives a black-and-white print and colour blindness. Grade meters fill only
from real evidence.
"""

import json

from fv_report import clean

TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Validation dashboard</title>
<style>
:root {
  color-scheme: light;
  --page: #f4f3ef; --surface: #fcfcfb; --line: #dedcd3; --text: #0b0b0b; --text-2: #52514e; --text-3: #7a7872;
  --real: #2a78d6; --real-soft: #cde2fb; --sim: #eb6834; --sim-soft: #fbe3d8; --track: #e8e6df;
  --critical: #d03b3b; --good: #0ca30c;
}
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    color-scheme: dark;
    --page: #111110; --surface: #1a1a19; --line: #34332f; --text: #f0efec; --text-2: #c3c2b7; --text-3: #8f8d84;
    --real: #3987e5; --real-soft: #173659; --sim: #d95926; --sim-soft: #47210f; --track: #2a2926;
    --critical: #e66767; --good: #0ca30c;
  }
}
:root[data-theme="dark"] {
  color-scheme: dark;
  --page: #111110; --surface: #1a1a19; --line: #34332f; --text: #f0efec; --text-2: #c3c2b7; --text-3: #8f8d84;
  --real: #3987e5; --real-soft: #173659; --sim: #d95926; --sim-soft: #47210f; --track: #2a2926;
  --critical: #e66767; --good: #0ca30c;
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--page); color: var(--text); font: 15px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif; }
main { max-width: 1180px; margin: 0 auto; padding: 28px 16px 64px; }
h1 { font-size: 26px; line-height: 1.2; margin: 0 0 4px; letter-spacing: -0.01em; }
h2 { font-size: 13px; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-2); margin: 36px 0 12px; font-weight: 650; }
h3 { font-size: 15px; margin: 0 0 6px; }
p { margin: 0 0 8px; }
.muted { color: var(--text-2); } .small { font-size: 13px; }
.card { background: var(--surface); border: 1px solid var(--line); border-radius: 10px; padding: 16px; }
.grid { display: grid; gap: 12px; }
.g2 { grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); }
.g4 { grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); }
.g3 { grid-template-columns: repeat(auto-fit, minmax(250px, 1fr)); }
.verdict { display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; margin-top: 18px; }
.pill { display: inline-block; border: 1.5px solid var(--text); border-radius: 999px; padding: 4px 14px; font-weight: 650; white-space: nowrap; }
.pill.no { border-color: var(--critical); color: var(--critical); }
.zone { border-radius: 10px; padding: 14px; }
.zone.real { background: var(--surface); border: 1.5px solid var(--real); }
.zone.sim { border: 1.5px dashed var(--sim);
  background: repeating-linear-gradient(135deg, var(--surface) 0 9px, var(--sim-soft) 9px 10px); }
.tag { display: inline-block; font-size: 11px; font-weight: 700; letter-spacing: 0.08em; padding: 1px 7px; border-radius: 4px; white-space: nowrap; }
.tag.real { background: var(--real); color: #fff; }
.tag.sim { border: 1.5px dashed var(--sim); color: var(--text); background: var(--surface); }
.tag.assume { border: 1.5px dotted var(--text-3); color: var(--text-2); }
.tag.research { border: 1.5px solid var(--text-3); color: var(--text-2); }
.stat b { display: block; font-size: 30px; line-height: 1.1; font-weight: 650; font-variant-numeric: tabular-nums; }
.stat span { color: var(--text-2); font-size: 13px; }
.meter { display: flex; gap: 2px; margin: 10px 0 8px; }
.meter i { flex: 1; height: 8px; border-radius: 4px; background: var(--track); }
.meter i.on { background: var(--real); }
.meter.contra i { background: var(--critical); }
.level { font-weight: 650; }
.level.contra { color: var(--critical); }
.bars { display: grid; grid-template-columns: minmax(80px, 30%) 1fr auto; gap: 6px 10px; align-items: center; margin: 8px 0; }
.bars .lab { font-size: 13px; color: var(--text-2); overflow-wrap: anywhere; }
.bar { position: relative; height: 22px; }
.bar .fill { position: absolute; left: 0; top: 3px; height: 16px; border-radius: 0 4px 4px 0; min-width: 2px; }
.bar.real .fill { background: var(--real); }
.bar.sim .fill { background: repeating-linear-gradient(135deg, var(--sim) 0 4px, var(--sim-soft) 4px 7px); outline: 1.5px dashed var(--sim); outline-offset: -1px; }
.bar .whisker { position: absolute; top: 10px; height: 2px; background: var(--text); }
.bar .whisker::before, .bar .whisker::after { content: ""; position: absolute; top: -4px; width: 2px; height: 10px; background: var(--text); }
.bar .whisker::before { left: 0; } .bar .whisker::after { right: 0; }
.bars .val { font-size: 12px; color: var(--text); white-space: nowrap; font-variant-numeric: tabular-nums; text-align: right; }
.axis { display: flex; justify-content: space-between; font-size: 11px; color: var(--text-3); border-top: 1px solid var(--line); padding-top: 2px; margin-top: -2px; }
.filters { display: flex; flex-wrap: wrap; gap: 10px; align-items: end; }
.filters label { font-size: 12px; color: var(--text-2); display: grid; gap: 3px; }
select, input[type=date], button { font: inherit; font-size: 13px; color: var(--text); background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 5px 8px; }
button { cursor: pointer; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 13px; }
th { text-align: left; font-weight: 600; color: var(--text-2); border-bottom: 1px solid var(--line); padding: 6px 8px; white-space: nowrap; }
td { border-bottom: 1px solid var(--line); padding: 7px 8px; vertical-align: top; }
td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
tr.retracted td { text-decoration: line-through; color: var(--text-3); }
ul { margin: 6px 0; padding-left: 18px; } li { margin: 2px 0; }
.against { border-left: 3px solid var(--critical); padding-left: 10px; margin: 8px 0; }
#tip { position: fixed; pointer-events: none; background: var(--text); color: var(--page); font-size: 12px; padding: 5px 8px; border-radius: 6px; max-width: 320px; display: none; z-index: 9; }
</style>
</head>
<body>
<main id="app"></main>
<div id="tip" role="status"></div>
<script id="data" type="application/json">__DATA__</script>
<script>
const S = JSON.parse(document.getElementById("data").textContent);
const esc = v => String(v == null ? "" : v).replace(/[&<>"]/g, c => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;"}[c]));
const pct = v => v == null ? "n/a" : (v * 100).toFixed(1) + "%";
const LEVELS = ["Unknown", "Weakly supported", "Moderately supported", "Strongly supported"];
const CONTRA = "Contradicted by evidence";
const segName = id => (S.segments.find(s => s.id === id) || {}).name || "no segment";
const claimOf = id => S.claims.find(c => c.id === id) || {};
const tagFor = c => c === "B" ? '<span class="tag sim">SIMULATED</span>' : c === "A" ? '<span class="tag assume">ASSUMPTION</span>'
  : c === "C" ? '<span class="tag research">RESEARCH</span>' : '<span class="tag real">REAL</span>';
const WHAT = {A: "assumed", B: "AI predicted", C: "external research", D: "customers said (interview)", E: "customers said (survey)", F: "customers did", G: "customers paid"};

function bar(kind, label, value, max, text, tip, lo, hi) {
  const w = max > 0 && value != null ? Math.max(0, Math.min(100, value / max * 100)) : 0;
  let whisk = "";
  if (lo != null && hi != null && max > 0) {
    whisk = `<span class="whisker" style="left:${lo / max * 100}%;width:${Math.max(0.5, (hi - lo) / max * 100)}%"></span>`;
  }
  return `<div class="lab">${esc(label)}</div><div class="bar ${kind}" data-tip="${esc(tip)}"><span class="fill" style="width:${w}%"></span>${whisk}</div><div class="val">${esc(text)}</div>`;
}
const axis = (a, b) => `<div></div><div class="axis"><span>${esc(a)}</span><span>${esc(b)}</span></div><div></div>`;

function meter(d) {
  if (d.level === CONTRA) return `<div class="meter contra"><i></i><i></i><i></i></div>`;
  return `<div class="meter">${[1, 2, 3].map(i => `<i class="${d.tier >= i ? "on" : ""}"></i>`).join("")}</div>`;
}

function header() {
  const v = S.verdict, c = S.counts;
  return `<p class="muted small">Market validation · generated ${esc(S.generated_at)} · grading rules ${esc(S.rules_version)}</p>
  <h1>${esc(S.project)}</h1>
  <div class="verdict"><span class="pill ${v.decision === "No-Go" ? "no" : ""}">${esc(v.decision)}</span><p style="flex:1;min-width:260px">${esc(v.text)}</p></div>
  <h2>What this rests on</h2>
  <div class="grid g2">
    <div class="zone real"><p><span class="tag real">REAL</span> <span class="small muted">counted toward every grade</span></p>
      <div class="grid g4">
        <div class="stat"><b>${c.real_people_interviewed}</b><span>people interviewed</span></div>
        <div class="stat"><b>${c.valid_survey_responses}</b><span>valid survey answers</span></div>
        <div class="stat"><b>${c.qualified_actions}</b><span>qualified actions on a primary metric</span></div>
        <div class="stat"><b>${c.paying_customers}</b><span>paying customers, net</span></div>
      </div></div>
    <div class="zone sim"><p><span class="tag sim">SIMULATED</span> <span class="small muted">carries no weight, at any number</span></p>
      <div class="grid g4">
        <div class="stat"><b>${c.synthetic_responses}</b><span>synthetic answers</span></div>
        <div class="stat"><b>${S.synthetic_runs.length}</b><span>synthetic runs</span></div>
      </div>
      <p class="small muted" style="margin-top:8px">Language-model profiles. Useful for questions and objections. Not customers, not a sample, not a forecast.</p></div>
  </div>`;
}

function grades() {
  const cards = S.dimensions.map(d => {
    const contra = d.level === CONTRA;
    const units = Object.entries(d.support).map(([k, v]) => `${v.units} ${esc(WHAT[k])}`).join(" · ") || "no real evidence";
    return `<div class="card"><p class="small muted">${esc(d.question)}</p>
      ${meter(d)}<p class="level ${contra ? "contra" : ""}">${contra ? "✕ " : ""}${esc(d.level)}${d.contested ? " · contested" : ""}</p>
      <p class="small muted">For: ${units}${Object.keys(d.contra).length ? "<br>Against: " + Object.entries(d.contra).map(([k, v]) => `${v.units} ${esc(WHAT[k])}`).join(" · ") : ""}</p>
      ${d.missing.length ? `<p class="small">Missing: ${esc(d.missing[0])}</p>` : ""}</div>`;
  }).join("");
  return `<h2>Seven questions, graded separately</h2><div class="grid g3">${cards}</div>
  <p class="small muted" style="margin-top:8px">There is no overall score on purpose. Meters fill from real evidence only; thresholds are cautious conventions, not statistical proof.</p>`;
}

function nextStep() {
  const r = S.recommendation;
  if (!r.question) return `<h2>Next step</h2><div class="card"><p>${esc(r.note)}</p></div>`;
  const e = r.experiment;
  return `<h2>Next step</h2><div class="card">
    <p class="small muted">Most important unanswered question · ${esc(r.hypothesis_id)} · priority ${r.priority}</p>
    <h3>${esc(r.question)}</h3><p class="small muted">${esc(r.why)}</p>
    ${r.prerequisite ? `<p class="against"><b>First:</b> ${esc(r.prerequisite)}</p>` : ""}
    <p><b>Cheapest credible experiment: ${esc(e.name)}</b> · ${esc(e.cost)} · about ${esc(e.days)} days</p>
    <ul class="small"><li>Who: ${esc(e.population)}</li><li>How: ${esc(e.method)}</li><li>Primary metric: ${esc(e.metric)}</li><li>Stop: ${esc(e.stop)}</li>
    <li>If it supports: ${esc(e.outcomes.supports)}</li><li>If it contradicts: ${esc(e.outcomes.contradicts)}</li><li>If unclear: ${esc(e.outcomes.unclear)}</li></ul>
    ${r.do_not_build ? `<p><b>${esc(r.do_not_build)}</b></p>` : ""}</div>`;
}

const F = {segment: "", category: "", concept: "", price: "", from: "", to: ""};
function filters() {
  const prices = [...new Set(S.experiments.flatMap(x => x.arms.map(a => a.price_point)).filter(p => p != null))].sort((a, b) => a - b);
  const opt = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`;
  return `<h2>Evidence record</h2><div class="card filters" id="filters">
    <label>Customer segment<select data-f="segment">${opt("", "All segments")}${S.segments.map(s => opt(s.id, s.name)).join("")}</select></label>
    <label>Evidence category<select data-f="category">${opt("", "All categories")}${opt("real", "Real only (D to G)")}${opt("synthetic", "Simulated and assumed (A, B)")}
      ${"ABCDEFG".split("").map(c => opt(c, c + " · " + WHAT[c])).join("")}</select></label>
    <label>Product concept<select data-f="concept">${opt("", "All concepts")}${S.concepts.map(c => opt(c.id, c.name)).join("")}</select></label>
    <label>Price point<select data-f="price">${opt("", "All prices")}${prices.map(p => opt(p, p)).join("")}</select></label>
    <label>From<input type="date" data-f="from"></label><label>To<input type="date" data-f="to"></label>
    <button id="reset" type="button">Reset</button></div>
  <div id="filtered"></div>`;
}

function pass(e) {
  const cl = claimOf(e.claim_id);
  if (F.segment && (e.segment_id || cl.segment_id) !== F.segment) return false;
  if (F.category === "real" && !e.real) return false;
  if (F.category === "synthetic" && !(e.category === "A" || e.category === "B")) return false;
  if (F.category.length === 1 && e.category !== F.category) return false;
  if (F.concept && cl.concept_id !== F.concept) return false;
  if (F.from && e.collected_on < F.from) return false;
  if (F.to && e.collected_on > F.to) return false;
  if (F.price) {
    const x = S.experiments.find(x => x.id === (e.ref || {}).experiment);
    if (!x || !x.arms.some(a => String(a.price_point) === F.price)) return false;
  }
  return true;
}

function xpass(x) {
  if (F.segment && x.segment_id !== F.segment) return false;
  if (F.price && !x.arms.some(a => String(a.price_point) === F.price)) return false;
  if (F.category && !["real", "F", "G"].includes(F.category)) return false;
  if (F.from && x.launched_at && x.launched_at.slice(0, 10) < F.from) return false;
  if (F.to && x.launched_at && x.launched_at.slice(0, 10) > F.to) return false;
  return true;
}

function ledger() {
  const all = S.dimensions.flatMap(d => d.items);
  const rows = all.filter(pass);
  const body = rows.map(e => `<tr class="${e.retracted_at ? "retracted" : ""}"><td>${esc(e.id)}</td><td>${tagFor(e.category)}<br><span class="small muted">${esc(e.category)} · ${esc(WHAT[e.category])}</span></td>
    <td>${esc(e.stance)}</td><td>${esc(e.dimension)}<br><span class="small muted">${esc(e.claim_id)} · ${esc(segName(e.segment_id || claimOf(e.claim_id).segment_id))}</span></td>
    <td>${esc(e.summary)}${e.retracted_at ? ` <span class="small">(retracted: ${esc(e.retract_reason)})</span>` : ""}<br><span class="small muted">${esc(e.resolved)} · ${esc(e.method)}</span></td>
    <td class="num">${e.real ? e.units : 0}</td><td>${esc(e.collected_on)}</td></tr>`).join("");
  return `<h3 style="margin-top:16px">Evidence items <span class="muted small">${rows.length} of ${all.length}</span></h3>
  <div class="card scroll"><table><thead><tr><th>Id</th><th>Kind</th><th>Stance</th><th>Bears on</th><th>What it says</th><th class="num">Real units</th><th>Collected</th></tr></thead>
  <tbody>${body || `<tr><td colspan="7" class="muted">Nothing matches these filters.</td></tr>`}</tbody></table></div>`;
}

function hypotheses() {
  const rows = S.hypotheses.filter(h => (!F.segment || h.segment_id === F.segment || !h.segment_id) && (!F.concept || h.concept_id === F.concept || !h.concept_id));
  return `<h3 style="margin-top:16px">Hypotheses, most important unanswered first</h3><div class="card scroll"><table>
  <thead><tr><th>Id</th><th>Area</th><th>Must be true</th><th class="num">Priority</th><th>Status</th></tr></thead><tbody>${rows.map(h => `<tr>
    <td>${esc(h.id)}</td><td>${esc(h.area)}</td><td>${esc(h.statement)}${h.origin === "ai" ? ' <span class="tag assume">AI-DRAFTED</span>' : ""}</td><td class="num">${h.priority.toFixed(1)}</td>
    <td>${h.status === CONTRA ? "✕ " : ""}${esc(h.status)}${h.explored_synthetically && !h.real_items ? '<br><span class="small muted">simulated exploration only</span>' : ""}</td></tr>`).join("")
    || `<tr><td colspan="5" class="muted">No hypotheses yet.</td></tr>`}</tbody></table></div>`;
}

function experimentsBlock() {
  const xs = S.experiments.filter(xpass);
  if (!S.experiments.length) return `<h3 style="margin-top:16px">Behavioural experiments</h3><div class="card muted">None yet. Nobody has been observed doing anything.</div>`;
  return `<h3 style="margin-top:16px">Behavioural experiments <span class="tag real">REAL</span></h3><div class="grid g2">${xs.map(x => {
    const max = Math.max(0.05, ...x.arms.map(a => a.high || a.rate || 0)) * 1.15;
    const pm = x.design.primary_metric;
    const bars = x.arms.map(a => a.n ? bar("real", a.variant + (a.price_point != null ? " at " + a.price_point : ""), a.rate, max,
      `${pct(a.rate)} (${a.k} of ${a.n})`, `${a.k} of ${a.n} qualified ${pm.denominator}; 95% interval ${pct(a.low)} to ${pct(a.high)}; left out: ${a.unqualified_n} unqualified, ${a.unknown_n} unknown`, a.low, a.high)
      : `<div class="lab">${esc(a.variant)}</div><div class="small muted">no qualified data (${a.unqualified_n} unqualified, ${a.unknown_n} unknown)</div><div></div>`).join("");
    return `<div class="card"><p class="small muted">${esc(x.id)} · ${esc(x.type.replace("_", " "))} · ${esc(x.status)}${x.interim ? " · interim" : ""}</p><h3>${esc(x.title)}</h3>
      <p class="small muted">Qualified ${esc(pm.event)} per qualified ${esc(pm.denominator)}, with 95% interval</p>
      <div class="bars">${bars}${axis("0%", pct(max))}</div>
      <p class="small" style="margin-top:8px"><b>${esc((x.outcome || "").replace(/_/g, " "))}.</b> ${esc(x.reading || "Not launched.")}</p>
      ${x.money.transactions.length ? `<p class="small">Money: ${x.money.n_payers} paying customer(s) net, ${x.money.cancelled_or_refunded.length} cancelled or refunded.</p>` : ""}</div>`;
  }).join("") || `<div class="card muted">No experiment matches these filters.</div>`}</div>`;
}

function people() {
  const iv = S.interviews;
  let out = `<h2>What real customers said <span class="tag real">REAL</span></h2><div class="grid g2"><div class="card"><h3>Interviews</h3><p class="small muted">${esc(iv.generalise)}</p>`;
  if (iv.participants) {
    out += `<div class="bars">${iv.themes.slice(0, 8).map(t => bar("real", t.theme, t.participants, iv.participants, `${t.participants} of ${t.of}`,
      `${t.participants} of ${t.of} people; ${t.with_past_behaviour} describing past behaviour${t.outlier ? "; outlier: one person" : ""}`)).join("")}${axis("0 people", iv.participants)}</div>`;
    const q = iv.themes.flatMap(t => t.quotes).slice(0, 4);
    out += q.map(x => `<p class="small" style="margin-top:8px">Verbatim, ${esc(x.participant)}: "${esc(x.text)}"</p>`).join("");
  }
  out += `</div><div class="card"><h3>Surveys</h3>`;
  if (!S.surveys.length) out += `<p class="muted small">No surveys.</p>`;
  S.surveys.forEach(s => {
    out += `<p class="small muted">${esc(s.title)} · ${s.valid} valid of ${s.received} received · ${esc(s.representative)}</p>`;
    s.questions.filter(q => q.options && q.kind !== "demographic").slice(0, 3).forEach(q => {
      out += `<p class="small" style="margin-top:8px">${esc(q.text)} <span class="muted">(${q.kind === "behavioral" || q.kind === "screening" ? "reported past behaviour" : "stated preference, not demand"}, n = ${q.n})</span></p>
      <div class="bars">${q.options.map(o => bar("real", o.option, o.share, 1, `${pct(o.share)} (${o.k})`, `${o.k} of ${q.n}; 95% interval ${pct(o.low)} to ${pct(o.high)}`, o.low, o.high)).join("")}</div>`;
    });
  });
  return out + `</div></div>`;
}

function synthetic() {
  if (!S.synthetic_runs.length) return "";
  let out = `<h2>Synthetic customer lab</h2><div class="zone sim"><p><span class="tag sim">SIMULATED</span> <b>Not customers.</b> <span class="small muted">Everything in this box was produced by a language model. It generates questions; it proves nothing.</span></p><div class="grid g2">`;
  S.synthetic_runs.forEach(r => {
    const t = r.tally;
    out += `<div class="card"><p class="small muted">Run ${esc(r.id)} · model ${esc(r.model)} · seed ${esc(r.seed)} · ${r.n_personas} profiles · ${r.repeats} repeat(s) · 0 independent observations</p>`;
    if (!t) { out += `<p class="muted small">No answers filed.</p></div>`; return; }
    Object.entries(t.concept || {}).forEach(([arm, c]) => {
      const total = c.answered || 1;
      out += `<h3>Simulated stance, arm ${esc(arm)}</h3><p class="small muted">Set largely by the dispositions dealt into the panel. Not a buy rate.</p>
      <div class="bars">${Object.entries(c.stance_mix).map(([k, v]) => bar("sim", k.replace(/_/g, " "), v, total, `${v} simulated`, `${v} of ${total} simulated profiles`)).join("")}</div>
      <p class="small" style="margin-top:8px"><b>Simulated reasons to reject:</b> ${c.reasons_to_reject.map(x => `${esc(x.code)} (${x.profiles})`).join(", ") || "none"}</p>`;
    });
    if (t.panel) out += `<p class="small">Imported panel: ${t.panel.said_buy} simulated said buy, ${t.panel.said_pass} said pass. ${esc(t.panel.note)}</p>`;
    out += `<p class="small" style="margin-top:8px"><b>Questions to take to real customers:</b></p><ul class="small">${t.questions_for_real_customers.slice(0, 6).map(q => `<li>${esc(q)}</li>`).join("")}</ul></div>`;
  });
  return out + `</div></div>`;
}

function calibrationBlock() {
  const c = S.calibration;
  if (!c.pairs.length && !c.open_predictions.length) return "";
  let out = `<h2>Predictions against reality</h2><div class="card"><p>${esc(c.statement)}</p>`;
  c.pairs.forEach(p => {
    const max = Math.max(p.predicted, p.actual_high || p.actual || 0, 0.05) * 1.15;
    out += `<p class="small muted" style="margin-top:12px">${esc(p.prediction_id)} against ${esc(p.experiment_id)} · ${p.comparable ? "marked comparable" : "marked NOT comparable"}: ${esc(p.comparable_note)}</p>
    <div class="bars">${bar(p.source === "synthetic" ? "sim" : "real", (p.source === "synthetic" ? "SIMULATED prediction" : "Prediction (" + p.source + ")"), p.predicted, max, pct(p.predicted), p.predicted_measure)}
    ${bar("real", "REAL result", p.actual, max, p.actual == null ? "unreadable" : `${pct(p.actual)} (${p.actual_k} of ${p.actual_n})`, p.actual_measure, p.actual_low, p.actual_high)}${axis("0%", pct(max))}</div>
    <p class="small">These measure different things and are never averaged. Possible reasons for the gap:</p><ul class="small">${p.possible_reasons.map(r => `<li>${esc(r)}</li>`).join("")}</ul>`;
  });
  c.summary.forEach(r => { out += `<p class="small">${esc(r.source)} / ${esc(r.model || "no model")} / ${esc(r.prediction_type)}: ${esc(r.says)}</p>`; });
  if (c.open_predictions.length) out += `<p class="small muted">${c.open_predictions.length} prediction(s) still waiting for a real result.</p>`;
  return out + `</div>`;
}

function against() {
  const items = S.dimensions.flatMap(d => d.items).filter(e => e.stance === "contradicts" || e.retracted_at);
  const failed = S.experiments.filter(x => x.outcome === "failure");
  let body = items.map(e => `<div class="against"><p class="small">${tagFor(e.category)} ${esc(e.id)} · ${esc(e.dimension)}${e.retracted_at ? " · retracted: " + esc(e.retract_reason) : ""}</p><p>${esc(e.summary)}</p><p class="small muted">${esc(e.resolved)}</p></div>`).join("")
    + failed.map(x => `<div class="against"><p class="small"><span class="tag real">REAL</span> ${esc(x.id)} failed its pre-set line</p><p>${esc(x.reading)}</p></div>`).join("")
    + S.interviews.contradictions.map(x => `<div class="against"><p class="small"><span class="tag real">REAL</span> interview extract ${esc(x.id)} · ${x.verbatim ? "verbatim" : "summary"}</p><p>${esc(x.text)}</p></div>`).join("");
  if (!body) body = `<p class="muted">None recorded. With little real evidence collected, that is absence of testing, not absence of problems.</p>`;
  return `<h2>Contradictory findings</h2><div class="card">${body}</div>`;
}

function footer() {
  return `<p class="small muted" style="margin-top:28px">Audit trail: ${S.audit.entries} entries, hash chain ${S.audit.ok ? "intact" : "BROKEN at entry " + S.audit.first_bad}.
  Counts describe the people reached, not the market. Stated intentions are capped at weak. Percentages carry a 95% interval.</p>`;
}

function renderFiltered() { document.getElementById("filtered").innerHTML = hypotheses() + ledger() + experimentsBlock(); }

document.getElementById("app").innerHTML = header() + grades() + nextStep() + filters() + people() + synthetic() + calibrationBlock() + against() + footer();
renderFiltered();
document.getElementById("filters").addEventListener("input", ev => { const k = ev.target.dataset.f; if (k) { F[k] = ev.target.value; renderFiltered(); } });
document.getElementById("reset").addEventListener("click", () => { Object.keys(F).forEach(k => F[k] = ""); document.querySelectorAll("[data-f]").forEach(el => el.value = ""); renderFiltered(); });
const tip = document.getElementById("tip");
document.addEventListener("mousemove", ev => {
  const el = ev.target.closest && ev.target.closest("[data-tip]");
  if (!el || !el.dataset.tip) { tip.style.display = "none"; return; }
  tip.textContent = el.dataset.tip; tip.style.display = "block";
  tip.style.left = Math.min(ev.clientX + 12, window.innerWidth - tip.offsetWidth - 8) + "px"; tip.style.top = (ev.clientY + 14) + "px";
});
</script>
</body>
</html>
"""


def render(snap):
    data = json.dumps(clean(snap), ensure_ascii=False).replace("</", "<\\/")
    title = "%s · Validation dashboard" % snap["project"]
    html = TEMPLATE.replace("<title>Validation dashboard</title>", "<title>%s</title>" % (
        title.replace("&", "&amp;").replace("<", "&lt;")))
    return html.replace("__DATA__", data)
