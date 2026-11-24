import { applyBrandBindings } from "./brand-config.js";

applyBrandBindings();

const SOURCE_LINKS = {
  "radwagusa.com": "https://radwagusa.com",
  "baslerweb.com": "https://www.baslerweb.com",
  "edmundoptics.com": "https://www.edmundoptics.com",
};

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

function usdDelta(delta) {
  const n = Number(delta);
  if (n < 0) return `\u2212${usd(Math.abs(n))}`;
  if (n > 0) return `+${usd(n)}`;
  return "$0";
}

function renderSourceText(src) {
  return String(src ?? "")
    .split(" + ")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const href = SOURCE_LINKS[part];
      return href
        ? `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(part)}</a>`
        : `<span class="mono-inline">${esc(part)}</span>`;
    })
    .join(" + ");
}

async function init() {
  const resp = await fetch("data/rig_frontier.json");
  if (!resp.ok) throw new Error(`Failed loading rig_frontier.json (${resp.status})`);
  const data = await resp.json();

  const bench = data.a4_sensor_bench;
  document.getElementById("a4-bench-card").innerHTML = `
    <div class="grid-2 grid-align-start">
      <div>
        <span class="badge badge-editorial">Stage 1 · Core Sensor Subtotal Before Arms &amp; Hands</span>
        <h3>${esc(bench.name)}</h3>
        <div class="bom-total">${usd(bench.total_usd)} <span class="small muted">(2-item core subtotal)</span></div>
        <p class="small muted">${esc(bench.note)}</p>
      </div>
      <div>
        <ul>
          ${bench.items.map((it) => `<li><strong>${usd(it.price_usd)}</strong> &mdash; ${esc(it.item)} (${renderSourceText(it.source)})</li>`).join("")}
          <li><strong>Budgeted Separately</strong> &mdash; Head stereo camera (ZED 2i <span class="mono-inline">$529</span> or OAK-D LR <span class="mono-inline">$809</span>), <span class="mono-inline">H1</span> seating collar switch, and <span class="mono-inline">H4</span> catch-box fixtures; human technicians execute the pre-arm <span class="mono-inline">n = 240</span> physical manipulations.</li>
        </ul>
      </div>
    </div>
  `;

  const camGroup = document.getElementById("cfg-cam-group");
  data.camera_options.forEach((opt) => {
    const btn = document.createElement("button");
    btn.className = "pill-btn";
    btn.type = "button";
    btn.setAttribute("data-cam", String(opt.delta_vs_baseline_usd));
    btn.setAttribute("aria-pressed", "false");
    const shortName = opt.model
      .replace("Stereolabs ", "")
      .replace("Luxonis ", "")
      .replace(" (2 mm IP66)", "")
      .replace("Long Range ", "LR ");
    btn.textContent = `${shortName} (${usd(opt.price_usd)}, ${usdDelta(opt.delta_vs_baseline_usd)})`;
    camGroup.appendChild(btn);
  });

  document.getElementById("profiles-table-body").innerHTML = data.profiles
    .map((p) => {
      const dofNote = p.profile_id === "P0" ? "26 (2x7 sim arm + 2x6 hand)" : `${esc(p.total_dof)} (2x6 arm + 2x17 finger)`;
      return `
      <tr>
        <td><span class="mono-inline">${esc(p.profile_id)}</span></td>
        <td><span class="mono-inline">${esc(p.title)}</span></td>
        <td>${esc(p.arms)}</td>
        <td>${esc(p.hands)}</td>
        <td class="num">${dofNote}</td>
        <td class="num">${esc(p.effective_reach_mm)} mm</td>
        <td class="num">${p.has_tactile ? `<span class="badge badge-pass">Yes</span>` : `<span class="badge">None</span>`}</td>
        <td class="num">${p.listed_subtotal_usd === 0 ? "$0 (Sim)" : usd(p.listed_subtotal_usd)}</td>
        <td class="small">${p.divisions.map((d) => `<code>${esc(d)}</code>`).join(" ")}</td>
        <td class="small">${esc(p.licence_summary)}</td>
      </tr>
    `;
    })
    .join("");

  document.getElementById("excluded-table-body").innerHTML = data.excluded_candidates
    .map((c) => `<tr><td><strong>${esc(c.candidate)}</strong></td><td>${esc(c.reason)}</td></tr>`)
    .join("");

  document.getElementById("families-table-body").innerHTML = data.families
    .map((f) => `<tr><td><span class="mono-inline">${esc(f.family_id)}</span></td><td><strong>${esc(f.name)}</strong></td><td>${esc(f.predicates)}</td></tr>`)
    .join("");

  const state = { profile: "P2", camDelta: 0, maskTactile: false };
  const profBtns = Array.from(document.querySelectorAll("#cfg-profile-group .pill-btn"));
  const camBtns = Array.from(document.querySelectorAll("#cfg-cam-group .pill-btn"));
  const tacBtns = Array.from(document.querySelectorAll("#cfg-tactile-group .pill-btn"));
  const summaryEl = document.getElementById("cfg-summary-card");

  function syncButtons() {
    if (state.profile === "P1") state.maskTactile = true;

    profBtns.forEach((b) => {
      const active = b.getAttribute("data-profile") === state.profile;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    camBtns.forEach((b) => {
      const active = Number(b.getAttribute("data-cam")) === state.camDelta;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });
    tacBtns.forEach((b) => {
      const isTactileEnabledBtn = b.getAttribute("data-mask") === "false";
      const disabled = state.profile === "P1" && isTactileEnabledBtn;
      b.disabled = disabled;
      b.setAttribute("aria-disabled", String(disabled));
      const active = (b.getAttribute("data-mask") === "true") === state.maskTactile && !disabled;
      b.classList.toggle("active", active);
      b.setAttribute("aria-pressed", String(active));
    });

    const pObj = data.profiles.find((p) => p.profile_id === state.profile);
    const bom = data.bom_basis.find((b) => b.id === `BOM-C-${state.profile}`);
    const total = bom.total_est_usd + state.camDelta;

    const divisions = state.profile === "P1"
      ? ["blind-stereo-nontactile (native non-tactile hardware)"]
      : state.maskTactile
        ? ["blind-stereo-nontactile (via mask_tactile=True parity)"]
        : ["blind-stereo-tactile (primary P2)", "blind-stereo-nontactile (available via mask_tactile=True)"];

    const maskNote = state.profile === "P1"
      ? "P1 omits tactile sensor hardware and competes natively in blind-stereo-nontactile (tactile mode disabled)."
      : state.maskTactile
        ? "mask_tactile_observation() and validate_dexterous_semantics() reject any tactile key at load time for non-tactile parity."
        : "P2 competes in blind-stereo-tactile directly, and switches into non-tactile parity via mask_tactile=True.";

    summaryEl.innerHTML = `
      <div class="stamp stamp-dark">Selected Configuration &middot; ${esc(bom.label)}</div>
      <div class="bom-total">~${usd(total)}</div>
      <div class="dossier-grid">
        <div class="dossier-row">
          <span class="dossier-k">Arms &amp; Hands</span>
          <span class="dossier-v">${usd(bom.arms_usd)} arms &middot; ${usd(bom.hands_usd)} hands</span>
        </div>
        <div class="dossier-row">
          <span class="dossier-k">Peripherals &amp; Optics Adj.</span>
          <span class="dossier-v">${usd(bom.peripherals_est_usd + state.camDelta)}</span>
        </div>
        <div class="dossier-row">
          <span class="dossier-k">Degrees of Freedom</span>
          <span class="dossier-v">${esc(pObj.total_dof)} bimanual (2x ${esc(pObj.arm_dof)} arm + 2x ${esc(pObj.finger_dof_per_hand)} finger)</span>
        </div>
        <div class="dossier-row">
          <span class="dossier-k">Reach &amp; Nominal Payload</span>
          <span class="dossier-v">${esc(pObj.effective_reach_mm)} mm eff. &middot; ${esc(pObj.nominal_payload_kg)} kg</span>
        </div>
        <div class="dossier-row">
          <span class="dossier-k">Eligible Divisions</span>
          <span class="dossier-v">${divisions.map((d) => esc(d)).join(" · ")}</span>
        </div>
      </div>
      <p class="dossier-note">${esc(maskNote)}</p>
      <div class="dossier-rfq"><strong>Open RFQs pending prior to purchase order:</strong> ${esc(bom.open_rfqs)}</div>
    `;
  }

  profBtns.forEach((b) => b.addEventListener("click", () => {
    const nextProf = b.getAttribute("data-profile");
    if (nextProf === state.profile) return;
    state.profile = nextProf;
    state.maskTactile = nextProf === "P1";
    syncButtons();
  }));
  camBtns.forEach((b) => b.addEventListener("click", () => {
    state.camDelta = Number(b.getAttribute("data-cam"));
    syncButtons();
  }));
  tacBtns.forEach((b) => b.addEventListener("click", () => {
    if (b.disabled) return;
    state.maskTactile = b.getAttribute("data-mask") === "true";
    syncButtons();
  }));

  syncButtons();
}

init().catch((err) => {
  document.getElementById("a4-bench-card").innerHTML = `<div class="callout callout-fail">Error loading rig data: ${esc(err.message)}</div>`;
});
