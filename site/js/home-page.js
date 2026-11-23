import { applyBrandBindings } from "./brand-config.js";
import { applyTamperMutation, verifyV1BundleInBrowser } from "./verifier-core.js";

applyBrandBindings();

const INSTALL_CMD = 'pip install "git+https://github.com/different-change/eutropos.git#subdirectory=referee"';

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

const copyBtn = document.getElementById("btn-copy-install");
if (copyBtn) {
  copyBtn.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(INSTALL_CMD);
    } catch {
      // Clipboard fallback still shows feedback cleanly under CSP
    }
    copyBtn.textContent = "Copied";
    setTimeout(() => {
      copyBtn.textContent = "Copy Command";
    }, 1200);
  });
}

let homeOpenMap = null;
let homeOpenPem = null;

function setHomeActiveControl(activeAttackId) {
  const resetBtn = document.getElementById("home-btn-reset");
  if (resetBtn) {
    resetBtn.classList.toggle("is-active", activeAttackId === null);
  }
  for (const btn of document.querySelectorAll("[data-home-tamper]")) {
    btn.classList.toggle("is-active", btn.getAttribute("data-home-tamper") === activeAttackId);
  }
}

function renderHomeBundle(report, attackLabel = null) {
  const target = document.getElementById("home-live-summary");
  if (!target) return;

  const s = report.summary || {};
  const stateCls = report.passed ? "is-verified" : "is-tampered";
  const statusLine = attackLabel
    ? (report.passed
        ? `UNEXPECTED PASS · ${report.checks.length} CHECKS`
        : `TAMPER CAUGHT · ${report.failures.length} INTEGRITY CHECK FAILED`)
    : `VERIFIED · ${report.checks.length} / ${report.checks.length} CRYPTOGRAPHIC CHECKS PASSED`;

  const verdictTitle = attackLabel
    ? (report.passed ? "Attack Uncaught" : `${attackLabel} Rejected`)
    : "Custody Chain Intact";

  const detailText = attackLabel && report.failures.length
    ? "Native browser Web Crypto recomputed the canonical digest chain and Ed25519 envelope, immediately exposing the mutated field below."
    : "Ed25519 DSSE envelope, canonical SHA-256 instrument digests, monotonic SlotLedger transitions, and FreeTSA RFC 3161 commitment match the sealed beacon seed.";

  const failuresHtml = report.failures.length
    ? `<ul class="vault-failure-list">${report.failures.map((f) => `<li>${esc(f)}</li>`).join("")}</ul>`
    : "";

  const slotInfo = s.slot_summary
    ? `${s.slot_summary.passed_slots} / ${s.slot_summary.registered_slots} passed registered slots`
    : "Verified";

  target.className = `vault-console ${stateCls}`;
  target.innerHTML = `
    <div class="vault-readout">
      <div class="vault-status-row">
        <span class="status-dot"></span>
        <span>${esc(statusLine)}</span>
      </div>
      <h3 class="vault-verdict">${esc(verdictTitle)}</h3>
      <p class="vault-detail">${esc(detailText)}</p>
      ${failuresHtml}
      <a class="link-editorial-light" href="verify.html">Open Full Verifier &amp; Upload Local Bundle &rarr;</a>
    </div>
    <div class="vault-telemetry">
      <div class="tel-item">
        <div class="tel-k">Public Randomness</div>
        <div class="tel-v">drand-quicknet &middot; Round ${esc(s.round_number ?? "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">FreeTSA Commitment UTC</div>
        <div class="tel-v">${esc(s.tsa_commitment_utc || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">FreeTSA Session Close UTC</div>
        <div class="tel-v">${esc(s.tsa_close_utc || "n/a")}</div>
      </div>
      <div class="tel-item">
        <div class="tel-k">Attempt Ledger</div>
        <div class="tel-v">${esc(slotInfo)}</div>
      </div>
    </div>
  `;
}

async function ensureHomeBundleLoaded() {
  if (homeOpenMap && homeOpenPem) return;
  const idxResp = await fetch("data/bundles/open_live/bundle_index.json");
  if (!idxResp.ok) throw new Error(`HTTP ${idxResp.status} loading bundle_index.json`);
  const idx = await idxResp.json();
  const pemResp = await fetch(`data/bundles/open_live/${idx.trusted_public_key}`);
  if (!pemResp.ok) throw new Error(`HTTP ${pemResp.status} loading public key`);
  const pem = await pemResp.text();
  const map = new Map();
  await Promise.all(
    idx.files.map(async (rel) => {
      const r = await fetch(`data/bundles/open_live/${rel}`);
      if (!r.ok) throw new Error(`HTTP ${r.status} loading ${rel}`);
      map.set(rel, new Uint8Array(await r.arrayBuffer()));
    })
  );
  homeOpenMap = map;
  homeOpenPem = pem;
}

async function initHome() {
  const target = document.getElementById("home-live-summary");
  try {
    await ensureHomeBundleLoaded();
    setHomeActiveControl(null);
    const rep = await verifyV1BundleInBrowser(homeOpenMap, homeOpenPem);
    renderHomeBundle(rep, null);
  } catch (err) {
    if (target) {
      target.className = "vault-console is-tampered";
      target.innerHTML = `<div class="vault-readout"><p class="vault-detail">Bundle preview requires an HTTP server (python -m http.server): ${esc(err.message)}</p></div>`;
    }
  }
}

const resetBtn = document.getElementById("home-btn-reset");
if (resetBtn) {
  resetBtn.addEventListener("click", async () => {
    await ensureHomeBundleLoaded();
    setHomeActiveControl(null);
    const rep = await verifyV1BundleInBrowser(homeOpenMap, homeOpenPem);
    renderHomeBundle(rep, null);
  });
}

for (const btn of document.querySelectorAll("[data-home-tamper]")) {
  btn.addEventListener("click", async () => {
    await ensureHomeBundleLoaded();
    const attackId = btn.getAttribute("data-home-tamper");
    setHomeActiveControl(attackId);
    const mutated = applyTamperMutation(homeOpenMap, attackId);
    const rep = await verifyV1BundleInBrowser(mutated, homeOpenPem);
    renderHomeBundle(rep, btn.textContent.trim());
  });
}

initHome();
