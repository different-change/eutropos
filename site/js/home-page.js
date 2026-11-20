import { applyBrandBindings } from "./brand-config.js";
import { verifyV1BundleInBrowser } from "./verifier-core.js";

applyBrandBindings();

const copyBtn = document.getElementById("btn-copy-install");
if (copyBtn) {
  copyBtn.addEventListener("click", async () => {
    const cmd = 'pip install "git+https://github.com/different-change/eutropos.git#subdirectory=referee"';
    try {
      await navigator.clipboard.writeText(cmd);
    } catch {
      // Fallback still gives feedback without inline scripts
    }
    copyBtn.textContent = "Copied";
    setTimeout(() => {
      copyBtn.textContent = "Copy";
    }, 1200);
  });
}

async function initHome() {
  const target = document.getElementById("home-live-summary");
  try {
    const idxResp = await fetch("data/bundles/open_live/bundle_index.json");
    const idx = await idxResp.json();
    const pemResp = await fetch(`data/bundles/open_live/${idx.trusted_public_key}`);
    const pem = await pemResp.text();
    const map = new Map();
    await Promise.all(
      idx.files.map(async (rel) => {
        const r = await fetch(`data/bundles/open_live/${rel}`);
        map.set(rel, new Uint8Array(await r.arrayBuffer()));
      })
    );
    const rep = await verifyV1BundleInBrowser(map, pem);
    const cls = rep.passed ? "pass" : "fail";
    const statusTxt = rep.passed ? "VERIFIED PASS (CLIENT WEB CRYPTO)" : "VERIFICATION FAILED";
    target.innerHTML = `
      <div class="status-banner ${cls}">
        <span>${statusTxt} &middot; ${rep.checks.length} checks evaluated client-side</span>
        <span>OPEN_LIVE · ROUND ${rep.summary.round_number}</span>
      </div>
      <div class="grid-3">
        <div><div class="kpi-label">drand-quicknet Round</div><code>${rep.summary.round_number}</code></div>
        <div><div class="kpi-label">FreeTSA Commitment</div><code>${rep.summary.tsa_commitment_utc}</code></div>
        <div><div class="kpi-label">FreeTSA Session Close</div><code>${rep.summary.tsa_close_utc}</code></div>
      </div>
      <p class="mt-1"><a class="btn btn-primary" href="verify.html">Open Interactive Bundle &amp; Tamper Lab</a></p>
    `;
  } catch (err) {
    target.innerHTML = `<p class="badge badge-warn">Bundle preview requires HTTP server (<code>python -m http.server</code>): ${err.message}</p>`;
  }
}

initHome();
