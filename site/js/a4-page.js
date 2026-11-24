import { applyBrandBindings } from "./brand-config.js";

applyBrandBindings();

const JUDGES = [
  { key: "robodojo_astra", label: "GPT-6 Astra", pipeline: "robodojo_astra (Single)" },
  { key: "claude_opus_5_5", label: "Claude Opus 5.5", pipeline: "claude_opus_5_5 (Single)" },
  { key: "datacenterbench_dual", label: "DataCenterBench Dual", pipeline: "Astra + Opus Dual" },
  { key: "gemini_4_neon", label: "Gemini 4 Neon", pipeline: "gemini_4_neon (Single)" },
];

const JUDGE_LABELS = Object.fromEntries(JUDGES.map((j) => [j.key, j.label]));

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function pct(val) {
  if (val === null || val === undefined || Number.isNaN(val)) return "n/a";
  return `${(val * 100).toFixed(1)}%`;
}

function fmtP(val) {
  const n = Number(val);
  if (!Number.isFinite(n)) return "n/a";
  if (n < 0.001) return n.toExponential(2);
  return n.toFixed(3);
}

function verdictBadge(cat, gt) {
  if (cat === "PASS") {
    return gt === 0
      ? `<span class="badge badge-fail">PASS (FP)</span>`
      : `<span class="badge badge-pass">PASS</span>`;
  }
  if (cat === "FAIL") {
    return gt === 1
      ? `<span class="badge badge-fail">FAIL (FN)</span>`
      : `<span class="badge">FAIL</span>`;
  }
  if (cat === "PARTIAL") {
    return gt === 1
      ? `<span class="badge badge-fail">PARTIAL (FN)</span>`
      : `<span class="badge">PARTIAL</span>`;
  }
  if (cat === "UNSURE") {
    return gt === 1
      ? `<span class="badge badge-warn">UNSURE (FN)</span>`
      : `<span class="badge badge-warn">UNSURE</span>`;
  }
  return `<span class="badge">${esc(cat)}</span>`;
}

function updateDynamicKpis(judgesMap, trials) {
  const vals = JUDGES.map((j) => judgesMap[j.key]);
  const fprs = vals.map((s) => s.overall_fpr * 100);
  const kappas = vals.map((s) => s.kappa);
  const nTotal = trials.length || 60;
  const binCounts = JUDGES.map((j) =>
    trials.filter((t) => (t.verdicts[j.key].category === "PASS" ? 1 : 0) === t.ground_truth).length
  );
  const stricts = vals.map((s) => Number(String(s.strict_accuracy).split("/")[0]));
  const failedGateCount = vals.filter((s) => s.stop_use_triggered).length;

  const gateEl = document.getElementById("kpi-gate");
  const fprEl = document.getElementById("kpi-fpr");
  const strictEl = document.getElementById("kpi-strict");
  const kappaEl = document.getElementById("kpi-kappa");

  if (gateEl) gateEl.textContent = `${failedGateCount} / ${JUDGES.length}`;
  if (fprEl) fprEl.textContent = `${Math.min(...fprs).toFixed(1)}% \u2013 ${Math.max(...fprs).toFixed(1)}%`;
  if (strictEl) strictEl.textContent = `${Math.min(...binCounts)}/${nTotal} \u2013 ${Math.max(...binCounts)}/${nTotal}`;
  if (kappaEl) {
    kappaEl.textContent = `Strict exact ${Math.min(...stricts)}/${nTotal}\u2013${Math.max(...stricts)}/${nTotal} (UNSURE scored incorrect); \u03ba ${Math.min(...kappas).toFixed(3)}\u2013${Math.max(...kappas).toFixed(3)} (gate \u2265 0.80)`;
  }
}

function renderSvgChart(judgesMap) {
  const host = document.getElementById("a4-svg-chart");
  const rows = JUDGES.map((j) => {
    const st = judgesMap[j.key];
    return {
      label: j.label,
      fpr: typeof st.overall_fpr === "number" ? st.overall_fpr * 100 : null,
      s4: typeof st.per_stratum?.S4?.fpr === "number" ? st.per_stratum.S4.fpr * 100 : null,
      ffr: typeof st.overall_ffr === "number" ? st.overall_ffr * 100 : null,
    };
  });

  const width = 880;
  const height = 294;
  const padL = 56;
  const padR = 24;
  const padT = 44;
  const padB = 52;
  const chartW = width - padL - padR;
  const chartH = height - padT - padB;
  const maxVal = 50;
  const yFor = (v) => padT + chartH - (Math.min(v, maxVal) / maxVal) * chartH;

  const parts = [];
  parts.push(`<svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Bar chart of blinded VLM judge overall false-pass, S4 decoy false-pass, and S1 false-fail rates in MuJoCo simulation">`);
  parts.push(`<line x1="${padL}" y1="15" x2="${padL + 26}" y2="15" stroke="#9C2F1E" stroke-width="1.6" stroke-dasharray="5,4"/>`);
  parts.push(`<text x="${padL + 33}" y="19" text-anchor="start" font-size="10.5" font-weight="600" fill="#9C2F1E" font-family="'JetBrains Mono', ui-monospace, monospace">Overall FPR gate &le; 5.0%</text>`);
  parts.push(`<line x1="${width - padR - 275}" y1="15" x2="${width - padR - 249}" y2="15" stroke="#795B2B" stroke-width="1.6" stroke-dasharray="2,3"/>`);
  parts.push(`<text x="${width - padR}" y="19" text-anchor="end" font-size="10.5" font-weight="600" fill="#795B2B" font-family="'JetBrains Mono', ui-monospace, monospace">S4 (&lt; 10.0%) &amp; S1 (&le; 10.0%) gates</text>`);

  for (const tick of [0, 10, 20, 30, 40, 50]) {
    const y = yFor(tick);
    parts.push(`<line x1="${padL}" y1="${y}" x2="${width - padR}" y2="${y}" stroke="#DCD5C7" stroke-width="1"/>`);
    parts.push(`<text x="${padL - 8}" y="${y + 4}" text-anchor="end" font-size="11" fill="#5A606A" font-family="'JetBrains Mono', ui-monospace, monospace">${tick}%</text>`);
  }

  parts.push(`<line x1="${padL}" y1="${yFor(10)}" x2="${width - padR}" y2="${yFor(10)}" stroke="#795B2B" stroke-width="1.5" stroke-dasharray="2,3"/>`);
  parts.push(`<line x1="${padL}" y1="${yFor(5)}" x2="${width - padR}" y2="${yFor(5)}" stroke="#9C2F1E" stroke-width="1.5" stroke-dasharray="5,4"/>`);

  const groupW = chartW / rows.length;
  const barW = 34;
  const gap = 10;

  rows.forEach((row, idx) => {
    const cx = padL + idx * groupW + groupW / 2;
    const xStart = cx - (3 * barW + 2 * gap) / 2;
    const metrics = [
      { val: row.fpr, color: "#9C2F1E" },
      { val: row.s4, color: "#9C7A3C" },
      { val: row.ffr, color: "#14233C" },
    ];
    metrics.forEach((m, mIdx) => {
      const bx = xStart + mIdx * (barW + gap);
      if (m.val === null) {
        parts.push(`<text x="${bx + barW / 2}" y="${yFor(0) - 6}" text-anchor="middle" font-size="10.5" fill="#5A606A" font-family="'JetBrains Mono', ui-monospace, monospace">n/a</text>`);
        return;
      }
      const by = yFor(m.val);
      const bh = Math.max(2, yFor(0) - by);
      const labelY = m.val > 0 && m.val <= 10.0 ? by - 4 : by - 5;
      parts.push(`<rect x="${bx}" y="${by}" width="${barW}" height="${bh}" rx="0" fill="${m.color}"/>`);
      parts.push(`<text x="${bx + barW / 2}" y="${labelY}" text-anchor="middle" font-size="10.5" font-weight="600" fill="#14171D" paint-order="stroke" stroke="#FAF8F4" stroke-width="4" stroke-linejoin="round" font-family="'JetBrains Mono', ui-monospace, monospace">${m.val.toFixed(1)}%</text>`);
    });
    parts.push(`<text x="${cx}" y="${height - 16}" text-anchor="middle" font-size="12" font-weight="600" fill="#14171D" font-family="'Inter', sans-serif">${esc(row.label)}</text>`);
  });

  parts.push("</svg>");
  host.innerHTML = parts.join("");
}

function renderJudgeTable(judgesMap, trials) {
  const tbody = document.getElementById("a4-judge-body");
  const nTotal = trials.length || 60;
  const rows = JUDGES.map(({ key, label }) => {
    const s = judgesMap[key];
    const binCorrect = trials.filter((t) => (t.verdicts[key].category === "PASS" ? 1 : 0) === t.ground_truth).length;
    const s3Fp = trials.filter((t) => t.stratum === "S3" && t.verdicts[key].category === "PASS").length;
    const s4Fp = trials.filter((t) => t.stratum === "S4" && t.verdicts[key].category === "PASS").length;
    const s1Fn = trials.filter((t) => t.stratum === "S1" && t.verdicts[key].category !== "PASS").length;
    const ci = (s.overall_fpr_ci95 || []).map((x) => pct(x)).join(" \u2013 ");
    const reasons = (s.stop_use_reasons || []).map((r) => `<code>${esc(r)}</code>`).join(" ");
    const bootCi = Array.isArray(s.kappa_boot_ci95) && s.kappa_boot_ci95.length === 2
      ? `(${Number(s.kappa_boot_ci95[0]).toFixed(3)}\u2013${Number(s.kappa_boot_ci95[1]).toFixed(3)})`
      : "";
    const gateBadge = s.stop_use_triggered
      ? `<span class="badge badge-fail">TRIGGERED</span>`
      : `<span class="badge badge-pass">PASS</span>`;
    const dualNote = key === "datacenterbench_dual" ? `<div class="small muted">Astra &rarr; Opus (2-stage)</div>` : "";
    return `
      <tr>
        <td><strong>${esc(label)}</strong>${dualNote}</td>
        <td>${gateBadge}<div class="mt-05 small">${reasons}</div></td>
        <td class="num">${pct(s.overall_fpr)}<div class="muted small">(${esc(ci)})</div></td>
        <td class="num small">${s3Fp}/15 (${pct(s.per_stratum?.S3?.fpr)}) &middot; ${s4Fp}/15 (${pct(s.per_stratum?.S4?.fpr)}) &middot; ${s1Fn}/15 (${pct(s.overall_ffr)})</td>
        <td class="num">${esc(s.coverage)}</td>
        <td class="num">${binCorrect}/${nTotal}</td>
        <td class="num">${esc(s.strict_accuracy)}</td>
        <td class="num">${Number(s.kappa).toFixed(3)}<div class="muted small">${esc(bootCi)}</div></td>
      </tr>
    `;
  });
  tbody.innerHTML = rows.join("");
}

function renderConfusionMatrix(trials) {
  const tbody = document.getElementById("a4-confusion-body");
  if (!tbody) return;
  tbody.innerHTML = JUDGES.map(({ key, label }) => {
    const cnt = (gt, cat) => trials.filter((t) => t.ground_truth === gt && t.verdicts[key].category === cat).length;
    return `
      <tr>
        <td><strong>${esc(label)}</strong></td>
        <td class="num">${cnt(0, "FAIL")}</td>
        <td class="num">${cnt(0, "PARTIAL")}</td>
        <td class="num">${cnt(0, "UNSURE")}</td>
        <td class="num"><strong>${cnt(0, "PASS")}</strong></td>
        <td class="num"><strong>${cnt(1, "PASS")}</strong></td>
        <td class="num">${cnt(1, "FAIL")}</td>
        <td class="num">${cnt(1, "PARTIAL")}</td>
        <td class="num">${cnt(1, "UNSURE")}</td>
      </tr>
    `;
  }).join("");
}

function renderMcNemar(pairMap) {
  const tbody = document.getElementById("a4-mcnemar-body");
  const entries = Object.entries(pairMap || {}).map(([pairKey, stats]) => ({
    pairKey,
    stats,
    rawP: Number(stats.mcnemar_exact_p),
  }));
  const sorted = [...entries].sort((a, b) => a.rawP - b.rawP);
  const m = sorted.length;
  let runningMax = 0;
  const holmByKey = new Map();
  sorted.forEach((item, idx) => {
    const adjusted = Math.min(1, item.rawP * (m - idx));
    runningMax = Math.max(runningMax, adjusted);
    holmByKey.set(item.pairKey, runningMax);
  });

  tbody.innerHTML = entries
    .map(({ pairKey, stats, rawP }) => {
      const [a, b] = pairKey.split("__vs__");
      const labelA = JUDGE_LABELS[a] || a;
      const labelB = JUDGE_LABELS[b] || b;
      const nonIndepNote =
        (a === "datacenterbench_dual" || b === "datacenterbench_dual") &&
        (a === "robodojo_astra" || b === "robodojo_astra" || a === "claude_opus_5_5" || b === "claude_opus_5_5")
          ? ` <span class="badge">shared model family</span>`
          : "";
      const holmP = holmByKey.get(pairKey);
      const statusBadge =
        holmP < 0.05
          ? `<span class="badge badge-pass">Holm p &lt; 0.05</span>`
          : rawP < 0.05
            ? `<span class="badge badge-editorial">Exploratory</span>`
            : `<span class="badge">NS</span>`;
      return `
        <tr>
          <td>${esc(labelA)} vs ${esc(labelB)}${nonIndepNote}</td>
          <td class="num">${esc(stats.only_first_fp)}</td>
          <td class="num">${esc(stats.only_second_fp)}</td>
          <td class="num">${esc(stats.shared_fp)}</td>
          <td class="num"><code>${esc(fmtP(rawP))}</code></td>
          <td class="num"><code>${esc(fmtP(holmP))}</code> ${statusBadge}</td>
        </tr>
      `;
    })
    .join("");
}

function renderShowcase(showcase) {
  const grid = document.getElementById("a4-showcase-grid");
  grid.innerHTML = showcase
    .map((tr) => {
      const gtBadge = tr.ground_truth === 1
        ? `<span class="badge badge-pass">GT: PASS (Control)</span>`
        : `<span class="badge badge-fail">GT: FAIL</span>`;
      const badges = JUDGES.map(
        ({ key, label }) => `<div><strong>${esc(label)}:</strong> ${verdictBadge(tr.verdicts[key].category, tr.ground_truth)}</div>`
      ).join("");
      return `
        <article class="showcase-card" id="${esc(tr.opaque_id)}">
          <div class="stereo-cap"><code>${esc(tr.opaque_id)}</code> &middot; Family <code>${esc(tr.family_id)}</code> &middot; Stratum <code>${esc(tr.stratum)}</code> &middot; ${gtBadge}</div>
          <p class="small"><strong>Simulator Reference State (MuJoCo):</strong> ${esc(tr.gt_reason)}</p>
          <div class="stereo-pair">
            <div>
              <div class="stereo-cap">Left Head Stereo Frame</div>
              <img src="${esc(tr.left_img)}" width="640" height="480" alt="MuJoCo left head stereo render for trial ${esc(tr.opaque_id)}" loading="lazy"/>
            </div>
            <div>
              <div class="stereo-cap">Right Head Stereo Frame</div>
              <img src="${esc(tr.right_img)}" width="640" height="480" alt="MuJoCo right head stereo render for trial ${esc(tr.opaque_id)}" loading="lazy"/>
            </div>
          </div>
          <div class="grid-2 small">${badges}</div>
        </article>
      `;
    })
    .join("");
}

function setupTrialFilter(trials) {
  const famSel = document.getElementById("filter-family");
  const strSel = document.getElementById("filter-stratum");
  const gtSel = document.getElementById("filter-gt");
  const disSel = document.getElementById("filter-disagree");
  const countLabel = document.getElementById("trial-count-label");
  const tbody = document.getElementById("a4-trials-body");

  const families = Array.from(new Set(trials.map((t) => t.family_id))).sort();
  families.forEach((f) => {
    const opt = document.createElement("option");
    opt.value = f;
    opt.textContent = f;
    famSel.appendChild(opt);
  });

  function renderRows() {
    const fam = famSel.value;
    const str = strSel.value;
    const gtVal = gtSel.value;
    const dis = disSel.value;

    const filtered = trials.filter((t) => {
      if (fam !== "ALL" && t.family_id !== fam) return false;
      if (str !== "ALL" && t.stratum !== str) return false;
      if (gtVal !== "ALL" && String(t.ground_truth) !== gtVal) return false;
      const cats = JUDGES.map((j) => t.verdicts[j.key].category);
      if (dis === "FP" && !(t.ground_truth === 0 && cats.includes("PASS"))) return false;
      if (dis === "FN" && !(t.ground_truth === 1 && cats.some((c) => c !== "PASS"))) return false;
      if (dis === "UNSURE" && !cats.includes("UNSURE")) return false;
      if (dis === "SPLIT" && new Set(cats).size <= 1) return false;
      return true;
    });

    countLabel.textContent = `Showing ${filtered.length} of ${trials.length} trials`;
    tbody.innerHTML = filtered
      .map((t) => `
        <tr>
          <td><code>${esc(t.opaque_id)}</code></td>
          <td><code>${esc(t.family_id)}</code></td>
          <td><code>${esc(t.stratum)}</code></td>
          <td>${t.ground_truth === 1 ? `<span class="badge badge-pass">PASS</span>` : `<span class="badge badge-fail">FAIL</span>`}</td>
          <td>${verdictBadge(t.verdicts.robodojo_astra.category, t.ground_truth)}</td>
          <td>${verdictBadge(t.verdicts.claude_opus_5_5.category, t.ground_truth)}</td>
          <td>${verdictBadge(t.verdicts.datacenterbench_dual.category, t.ground_truth)}</td>
          <td>${verdictBadge(t.verdicts.gemini_4_neon.category, t.ground_truth)}</td>
          <td class="small">${esc(t.gt_reason)}</td>
        </tr>
      `)
      .join("");
  }

  [famSel, strSel, gtSel, disSel].forEach((el) => el.addEventListener("change", renderRows));
  renderRows();
}

async function init() {
  const resp = await fetch("data/a4_study.json");
  if (!resp.ok) throw new Error(`Failed loading a4_study.json (${resp.status})`);
  const data = await resp.json();
  updateDynamicKpis(data.statistics.judges, data.trials);
  renderSvgChart(data.statistics.judges);
  renderJudgeTable(data.statistics.judges, data.trials);
  renderConfusionMatrix(data.trials);
  renderMcNemar(data.statistics.pairwise_mcnemar);
  renderShowcase(data.showcase);
  setupTrialFilter(data.trials);
  if (window.location.hash) {
    const target = document.getElementById(window.location.hash.slice(1));
    if (target) target.scrollIntoView({ behavior: "auto", block: "start" });
  }
}

init().catch((err) => {
  const errHtml = `<div class="callout callout-fail">Error loading study dataset: ${esc(err.message)}. Verify <a href="data/a4_study.json" download="eutropos-a4-pilot-study.json">a4_study.json</a> download.</div>`;
  const chartEl = document.getElementById("a4-svg-chart");
  if (chartEl) chartEl.innerHTML = errHtml;
  const judgeBody = document.getElementById("a4-judge-body");
  if (judgeBody) judgeBody.innerHTML = `<tr><td colspan="8" class="muted small">Unavailable: ${esc(err.message)}</td></tr>`;
  const confBody = document.getElementById("a4-confusion-body");
  if (confBody) confBody.innerHTML = `<tr><td colspan="9" class="muted small">Unavailable: ${esc(err.message)}</td></tr>`;
});
