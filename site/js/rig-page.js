import { applyBrandBindings } from "./brand-config.js";

applyBrandBindings();

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function usd(amount) {
  return `$${Number(amount).toLocaleString("en-US")}`;
}

async function init() {
  const resp = await fetch("data/rig_frontier.json");
  if (!resp.ok) throw new Error(`Failed loading rig_frontier.json (${resp.status})`);
  const data = await resp.json();

  // Render A4 Bench
  const bench = data.a4_sensor_bench;
  document.getElementById("a4-bench-card").innerHTML = `
    <div class="grid-2">
      <div>
        <span class="badge badge-pass">Purchase Before Arms/Hands</span>
        <h3>${esc(bench.name)}</h3>
        <div class="bom-total">${usd(bench.total_usd)}</div>
        <p class="small muted">${esc(bench.note)}</p>
      </div>
      <div>
        <ul>
          ${bench.items.map((it) => `<li><strong>${usd(it.price_usd)}</strong> &mdash; ${esc(it.item)} (<code>${esc(it.source)}</code>)</li>`).join("")}
        </ul>
      </div>
    </div>
  `;

  // Populate camera buttons dynamically from data.camera_options
  const camGroup = document.getElementById("cfg-cam-group");
  data.camera_options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "pill-btn";
    btn.type = "button";
    btn.setAttribute("data-cam", String(opt.delta_vs_baseline_usd));
    const shortName = opt.model
      .replace("Stereolabs ", "")
      .replace("Luxonis ", "")
      .replace(" (2 mm IP66)", "")
      .replace("Long Range ", "LR ");
    btn.textContent = `${shortName} (${usd(opt.price_usd)}, ${opt.delta_vs_baseline_usd})`;
    camGroup.appendChild(btn);
  });

  // Render P0-P2 table
  document.getElementById("profiles-table-body").innerHTML = data.profiles
    .map((p) => `
      <tr>
        <td><code>${esc(p.profile_id)}</code></td>
        <td><code>${esc(p.title)}</code></td>
        <td>${esc(p.arms)}</td>
        <td>${esc(p.hands)}</td>
        <td class="num">${esc(p.total_dof)}</td>
        <td class="num">${esc(p.effective_reach_mm)} mm</td>
        <td class="num">${p.has_tactile ? `<span class="badge badge-pass">Yes</span>` : `<span class="badge">No</span>`}</td>
        <td class="num">${p.listed_subtotal_usd === 0 ? "$0 (Sim)" : usd(p.listed_subtotal_usd)}</td>
        <td class="small">${p.divisions.map((d) => `<code>${esc(d)}</code>`).join(" ")}</td>
        <td class="small">${esc(p.licence_summary)}</td>
      </tr>
    `)
    .join("");

  // Excluded table
  document.getElementById("excluded-table-body").innerHTML = data.excluded_candidates
    .map((c) => `<tr><td><strong>${esc(c.candidate)}</strong></td><td>${esc(c.reason)}</td></tr>`)
    .join("");

  // 15 families table
  document.getElementById("families-table-body").innerHTML = data.families
    .map((f) => `<tr><td><code>${esc(f.family_id)}</code></td><td><strong>${esc(f.name)}</strong></td><td>${esc(f.predicates)}</td></tr>`)
    .join("");

  // Configurator state
  const state = { profile: "P2", camDelta: 0, maskTactile: false };
  const profBtns = Array.from(document.querySelectorAll("#cfg-profile-group .pill-btn"));
  const camBtns = Array.from(document.querySelectorAll("#cfg-cam-group .pill-btn"));
  const tacBtns = Array.from(document.querySelectorAll("#cfg-tactile-group .pill-btn"));
  const summaryEl = document.getElementById("cfg-summary-card");

  function syncButtons() {
    profBtns.forEach((b) => b.classList.toggle("active", b.getAttribute("data-profile") === state.profile));
    camBtns.forEach((b) => b.classList.toggle("active", Number(b.getAttribute("data-cam")) === state.camDelta));
    tacBtns.forEach((b) => b.classList.toggle("active", (b.getAttribute("data-mask") === "true") === state.maskTactile));

    const pObj = data.profiles.find((p) => p.profile_id === state.profile);
    const bom = data.bom_basis.find((b) => b.id === `BOM-C-${state.profile}`);
    const total = bom.total_est_usd + state.camDelta;

    const divisions = state.profile === "P1"
      ? ["blind-stereo-nontactile (natively non-tactile)"]
      : state.maskTactile
        ? ["blind-stereo-nontactile (via mask_tactile=True parity)"]
        : ["blind-stereo-tactile (primary P2)", "blind-stereo-nontactile (available via mask_tactile=True)"];

    const maskNote = state.profile === "P1" && !state.maskTactile
      ? "P1 omits tactile hardware; enable mask_tactile=False/True identically under blind-stereo-nontactile."
      : state.maskTactile
        ? "mask_tactile_observation() + validate_dexterous_semantics() reject any tactile state key at load time."
        : "P2 runs tactile division directly, and switches into non-tactile leaderboard parity via mask_tactile=True.";

    summaryEl.innerHTML = `
      <div class="kpi-label">Configured Rig Subtotal (${esc(bom.label)})</div>
      <div class="bom-total">~${usd(total)}</div>
      <p class="small">
        Arms: <strong>${usd(bom.arms_usd)}</strong> &middot;
        Hands: <strong>${usd(bom.hands_usd)}</strong> &middot;
        Peripherals + Camera adj.: <strong>${usd(bom.peripherals_est_usd + state.camDelta)}</strong>
      </p>
      <p class="small">
        <strong>DoF:</strong> <code>${esc(pObj.total_dof)}</code> bimanual (<code>2x ${esc(pObj.arm_dof)} arm + 2x ${esc(pObj.finger_dof_per_hand)} finger</code>) &middot;
        <strong>Eff. Reach:</strong> <code>${esc(pObj.effective_reach_mm)} mm</code> &middot;
        <strong>Payload:</strong> <code>${esc(pObj.nominal_payload_kg)} kg</code>
      </p>
      <p class="small"><strong>Eligible Divisions:</strong> ${divisions.map((d) => `<code>${esc(d)}</code>`).join(" ")}</p>
      <p class="small muted">${esc(maskNote)}</p>
      <div class="callout callout-warn small"><strong>Open RFQs before PO:</strong> ${esc(bom.open_rfqs)}</div>
    `;
  }

  profBtns.forEach((b) => b.addEventListener("click", () => {
    state.profile = b.getAttribute("data-profile");
    if (state.profile === "P1") state.maskTactile = true;
    syncButtons();
  }));
  camBtns.forEach((b) => b.addEventListener("click", () => {
    state.camDelta = Number(b.getAttribute("data-cam"));
    syncButtons();
  }));
  tacBtns.forEach((b) => b.addEventListener("click", () => {
    state.maskTactile = b.getAttribute("data-mask") === "true";
    syncButtons();
  }));

  syncButtons();
}

init().catch((err) => {
  document.getElementById("a4-bench-card").innerHTML = `<div class="callout callout-fail">Error loading rig data: ${esc(err.message)}</div>`;
});
