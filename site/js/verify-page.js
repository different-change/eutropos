import { applyBrandBindings } from "./brand-config.js";
import { applyTamperMutation, verifyV1BundleInBrowser } from "./verifier-core.js";

applyBrandBindings();

let activeMap = null;
let activePem = null;
let activeLabel = "";

function setPresetButtons(folder) {
  const openBtn = document.getElementById("btn-verify-open");
  const hazBtn = document.getElementById("btn-verify-hazard");
  if (openBtn) openBtn.classList.toggle("is-active", folder === "open_live");
  if (hazBtn) hazBtn.classList.toggle("is-active", folder === "hazard_live");
}

function renderReport(report, label, attackLabel = null) {
  const statusEl = document.getElementById("verify-status");
  const tbody = document.getElementById("verify-checks-body");

  const bannerCls = report.passed ? "pass" : "fail";
  const badgeText = report.passed
    ? (attackLabel ? "UNEXPECTED PASS" : "VERIFIED PASS")
    : `VERIFICATION FAILED (${report.failures.length})`;

  const s = report.summary || {};
  statusEl.innerHTML = `
    <div class="status-banner ${bannerCls}">
      <span>${badgeText} &middot; ${report.checks.length} Checks</span>
      <span>DATASET: ${label}${attackLabel ? ` &middot; TAMPER: ${attackLabel}` : ""}</span>
    </div>
    ${report.failures.length ? `<div class="callout callout-fail"><strong>Failures caught:</strong><ul>${report.failures.map((f) => `<li><code>${f}</code></li>`).join("")}</ul></div>` : ""}
    <div class="grid-4 mt-1">
      <div><div class="kpi-label">Disclosure Mode</div><code>${s.disclosure_mode || "n/a"}</code></div>
      <div><div class="kpi-label">Pareto Profile</div><code>${s.pareto_profile || "n/a"} (mask_tactile=${s.mask_tactile})</code></div>
      <div><div class="kpi-label">drand Round</div><code>${s.round_number ?? "n/a"} (${s.beacon_scheme || "n/a"})</code></div>
      <div><div class="kpi-label">Registered / Passed</div><code>${s.slot_summary ? `${s.slot_summary.passed_slots} / ${s.slot_summary.registered_slots}` : "n/a"}</code></div>
    </div>
  `;

  tbody.innerHTML = report.checks
    .map(
      (c) => `
      <tr>
        <td><code>${c.name}</code></td>
        <td><span class="badge ${c.passed ? "badge-pass" : "badge-fail"}">${c.passed ? "PASS" : "FAIL"}</span></td>
        <td><code>${c.detail}</code></td>
      </tr>`
    )
    .join("");
}

async function loadPreset(folder) {
  setPresetButtons(folder);
  const statusEl = document.getElementById("verify-status");
  statusEl.innerHTML = `<p class="mono">Fetching &amp; verifying <code>${folder}</code>...</p>`;
  try {
    const idxResp = await fetch(`data/bundles/${folder}/bundle_index.json`);
    const idx = await idxResp.json();
    const pemResp = await fetch(`data/bundles/${folder}/${idx.trusted_public_key}`);
    const pem = await pemResp.text();
    const map = new Map();
    await Promise.all(
      idx.files.map(async (rel) => {
        const res = await fetch(`data/bundles/${folder}/${rel}`);
        map.set(rel, new Uint8Array(await res.arrayBuffer()));
      })
    );
    activeMap = map;
    activePem = pem;
    activeLabel = folder;
    const rep = await verifyV1BundleInBrowser(map, pem);
    renderReport(rep, folder);
  } catch (err) {
    statusEl.innerHTML = `<div class="callout callout-fail">Failed to load preset: ${err.message}</div>`;
  }
}

document.getElementById("btn-verify-open").addEventListener("click", () => loadPreset("open_live"));
document.getElementById("btn-verify-hazard").addEventListener("click", () => loadPreset("hazard_live"));

for (const btn of document.querySelectorAll("[data-tamper]")) {
  btn.addEventListener("click", async () => {
    if (!activeMap || !activePem) {
      await loadPreset("open_live");
    }
    const attackId = btn.getAttribute("data-tamper");
    const mutated = applyTamperMutation(activeMap, attackId);
    const rep = await verifyV1BundleInBrowser(mutated, activePem);
    renderReport(rep, activeLabel, attackId);
  });
}

document.getElementById("input-folder").addEventListener("change", async (evt) => {
  setPresetButtons(null);
  const files = Array.from(evt.target.files || []);
  if (!files.length) return;
  const map = new Map();
  let pemText = null;
  for (const f of files) {
    const parts = (f.webkitRelativePath || f.name).split("/");
    const rel = parts.length > 1 ? parts.slice(1).join("/") : parts[0];
    const buf = new Uint8Array(await f.arrayBuffer());
    map.set(rel, buf);
    if (rel === "public_key.pem" || rel === "trusted_public_key.pem") {
      pemText = new TextDecoder().decode(buf);
    }
  }
  activeMap = map;
  activePem = pemText;
  activeLabel = "local-upload (using public_key.pem)";
  const rep = await verifyV1BundleInBrowser(map, pemText);
  renderReport(rep, activeLabel);
});

loadPreset("open_live");
