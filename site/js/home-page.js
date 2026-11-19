import { applyBrandBindings } from "./brand-config.js";
import { verifyV1BundleInBrowser } from "./verifier-core.js";

applyBrandBindings();

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
    const badgeCls = rep.passed ? "badge-pass" : "badge-fail";
    const statusTxt = rep.passed ? "VERIFIED PASS (CLIENT WEB CRYPTO)" : "VERIFICATION FAILED";
    target.innerHTML = `
      <p><span class="badge ${badgeCls}">${statusTxt}</span> &nbsp; <code>${rep.checks.length}</code> checks evaluated client-side</p>
      <div class="grid-3">
        <div><strong>drand-quicknet Round</strong><br/><code>${rep.summary.round_number}</code></div>
        <div><strong>FreeTSA Commitment</strong><br/><code>${rep.summary.tsa_commitment_utc}</code></div>
        <div><strong>FreeTSA Session Close</strong><br/><code>${rep.summary.tsa_close_utc}</code></div>
      </div>
      <p class="mt-1"><a class="btn btn-primary" href="verify.html">Open Full Interactive Bundle &amp; Tamper Lab</a></p>
    `;
  } catch (err) {
    target.innerHTML = `<p class="badge badge-warn">Bundle preview requires HTTP server (<code>python -m http.server</code>): ${err.message}</p>`;
  }
}

initHome();
