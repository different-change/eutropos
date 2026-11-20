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
      copyBtn.textContent = "Copy";
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
  const cls = report.passed ? "pass" : "fail";
  const statusTxt = attackLabel
    ? (report.passed ? "UNEXPECTED PASS" : `TAMPER CAUGHT (${report.failures.length} FAILED)`)
    : (report.passed ? "VERIFIED PASS (CLIENT WEB CRYPTO)" : `VERIFICATION FAILED (${report.failures.length})`);
  const rightTag = attackLabel
    ? `ATTACK: ${attackLabel}`
    : `OPEN_LIVE · DRAND ROUND ${s.round_number ?? "n/a"}`;

  target.innerHTML = `
    <div class="status-banner ${cls}">
      <span>${esc(statusTxt)} &middot; ${report.checks.length} checks evaluated client-side</span>
      <span>${esc(rightTag)}</span>
    </div>
    ${report.failures.length ? `<div class="callout callout-fail"><strong>Caught by browser Web Crypto:</strong><ul>${report.failures.map((f) => `<li><code>${esc(f)}</code></li>`).join("")}</ul></div>` : ""}
    <div class="grid-3 mt-1">
      <div><div class="kpi-label">drand-quicknet Round</div><code>${esc(s.round_number)}</code></div>
      <div><div class="kpi-label">FreeTSA Commitment UTC</div><code>${esc(s.tsa_commitment_utc)}</code></div>
      <div><div class="kpi-label">FreeTSA Session Close UTC</div><code>${esc(s.tsa_close_utc)}</code></div>
    </div>
    <div class="actions mt-1">
      <a class="btn btn-primary" href="verify.html">Open Full Verifier &amp; Upload Local Bundle</a>
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
      target.innerHTML = `<p class="badge badge-warn">Bundle preview requires an HTTP server (<code>python -m http.server</code>): ${esc(err.message)}</p>`;
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
