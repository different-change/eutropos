import { applyBrandBindings } from "../site/js/brand-config.js";

const SITE_ROOT = "../site/";
applyBrandBindings();

const slides = Array.from(document.querySelectorAll(".slide"));
const jumpStrip = document.getElementById("jump-strip");
const counterEl = document.getElementById("slide-counter");
const prevBtn = document.getElementById("btn-prev");
const nextBtn = document.getElementById("btn-next");

let activeIdx = 0;

function esc(v) {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function goToSlide(idx) {
  activeIdx = Math.max(0, Math.min(slides.length - 1, idx));
  slides.forEach((s, i) => s.classList.toggle("active", i === activeIdx));
  const dots = Array.from(jumpStrip.querySelectorAll(".jump-dot"));
  dots.forEach((d, i) => d.classList.toggle("active", i === activeIdx));
  counterEl.textContent = `${activeIdx + 1} / ${slides.length}`;
}

slides.forEach((_, i) => {
  const dot = document.createElement("button");
  dot.className = "jump-dot";
  dot.type = "button";
  dot.textContent = String(i + 1);
  dot.setAttribute("aria-label", `Go to slide ${i + 1}`);
  dot.addEventListener("click", () => goToSlide(i));
  jumpStrip.appendChild(dot);
});

prevBtn.addEventListener("click", () => goToSlide(activeIdx - 1));
nextBtn.addEventListener("click", () => goToSlide(activeIdx + 1));

const printBtn = document.getElementById("btn-print");
if (printBtn) {
  printBtn.addEventListener("click", () => window.print());
}

document.addEventListener("keydown", (evt) => {
  if (evt.target && ["INPUT", "SELECT", "TEXTAREA"].includes(evt.target.tagName)) return;
  if (evt.key === "ArrowRight" || evt.key === "PageDown" || evt.key === " ") {
    evt.preventDefault();
    goToSlide(activeIdx + 1);
  } else if (evt.key === "ArrowLeft" || evt.key === "PageUp") {
    evt.preventDefault();
    goToSlide(activeIdx - 1);
  } else if (evt.key === "Home") {
    evt.preventDefault();
    goToSlide(0);
  } else if (evt.key === "End") {
    evt.preventDefault();
    goToSlide(slides.length - 1);
  }
});

// Interactive 4-track audience selector on Slide 12
const TRACKS = {
  partner: {
    title: "Track 1 — Frontier Lab / Robotics Partner (Zero Capital Ask)",
    badge: "Integration & Pilot Track",
    ask: "$0 Capital Ask · Immediate Plugin Integration",
    summary: "Run eutropos-referee==1.0.0 alongside existing inspect-robots pipelines or via standalone isolated execution to attach hardware-truth seals to model evaluations.",
    allocation: [
      "15-minute entry-point registration in existing inspect-robots CI / eval workflows",
      "Joint specification of 1 private hazard-escrowed surrogate family (e.g. I2 or H2)",
      "Cross-lab blinded bundle exchange verifiable offline in browser Web Crypto",
    ],
    milestones: [
      "Day 1: Prove open + hazard-escrowed live cryptographic custody chains on your tasks",
      "Day 30: Evaluate blinded checkpoint runs on Stage-1 physical fixture",
      "Day 90: Co-publish third-party certified safety / capability appendix",
    ],
  },
  lean: {
    title: "Track 2 — Lean Physical Proof Pilot ($250k – $500k)",
    badge: "Capital-Efficient Physical Proof",
    ask: "$250,000 – $500,000 · 12-Month Lean Runway",
    summary: "Fund physical metrology hardware and confirmatory physical trials sequentially: verify the $1,291 A4 sensor bench first, then build one P2 dual-division rig.",
    allocation: [
      "$1,291 Stage-1 A4 Sensor Bench (Radwag WTC 2000 + Basler ace 2) before arm capex",
      "~$41k Single P2 UFACTORY 850 + ORCA v2.1 Touch rig + ~$15k interchangeable fixtures/spares",
      "Founder metrology engineering, physical 240-trial A4 publication, and Season-0 open launch",
    ],
    milestones: [
      "Month 2: Publish 240-trial physical A4 study closing synthetic-to-real referee proof",
      "Month 6: Complete P2 dual-division cell + human teleop ceilings across 15 families",
      "Month 12: First external robotics policies certified under Track B + initial pilot revenue",
    ],
  },
  preseed: {
    title: "Track 3 — Pre-Seed Operating Round ($1.5M – $3M)",
    badge: "Full Dual-Track Startup",
    ask: "$1.5M – $3.0M · 18-Month Operating Runway",
    summary: "Stand up twin matched P1 + P2 physical referee cells, continuous Season-1 public submissions, and paid confidential Track C audits for labs and OEMs.",
    allocation: [
      "Dual matched physical referee cells (P1 open-commercial + P2 tactile/blind-stereo)",
      "Engineering hires: robotics metrology, fixtures/CAD, and isolated runner infrastructure",
      "Enterprise compliance prep, escrow custody operations, and direct lab/insurer GTM",
    ],
    milestones: [
      "Month 4: Dual P1 + P2 cells operational with cross-cell human teleop baselines",
      "Month 9: Season-1 public leaderboard open to metered external policy submissions",
      "Month 18: 3+ paid Track C closed-bank audits delivered; ISO-traceable calibration active",
    ],
  },
  seed: {
    title: "Track 4 — Institutional Seed ($5M+)",
    badge: "Standards Bureau Scale",
    ask: "$5.0M+ Institutional Lead · 24-Month Runway",
    summary: "Scale standardized multi-region physical certification infrastructure spanning public Season leaderboards and insurer/regulatory-grade hazard escrow bureaus.",
    allocation: [
      "Multi-cell automated referee labs (US + EU) supporting rapid throughput across divisions",
      "HSM-backed escrow key ceremony infrastructure and full continuous telemetry archives",
      "Insurer underwriting & OEM procurement partnerships translating scores to deployment limits",
    ],
    milestones: [
      "Month 6: Regional twin physical referee cells + accredited metrology calibration",
      "Month 12: Standing Season-1 & Season-2 capability index referenced by labs and buyers",
      "Month 24: Multi-enterprise Track C recurring audit contracts + insurer underwriting adoption",
    ],
  },
};

function renderTrack(trackKey) {
  const t = TRACKS[trackKey] || TRACKS.lean;
  document.querySelectorAll(".track-btn").forEach((b) => {
    b.classList.toggle("active", b.getAttribute("data-track") === trackKey);
  });
  const host = document.getElementById("track-detail");
  host.innerHTML = `
    <div class="grid-2">
      <div class="panel panel-white">
        <span class="badge badge-pass">${esc(t.badge)}</span>
        <h3>${esc(t.title)}</h3>
        <div class="big-num">${esc(t.ask)}</div>
        <p class="small muted">${esc(t.summary)}</p>
      </div>
      <div class="panel panel-white">
        <h3>Capital / Effort Allocation</h3>
        <ul class="small">${t.allocation.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
        <h3 class="mt-1">Concrete Execution Milestones</h3>
        <ul class="small">${t.milestones.map((x) => `<li>${esc(x)}</li>`).join("")}</ul>
      </div>
    </div>
  `;
}

document.querySelectorAll(".track-btn").forEach((btn) => {
  btn.addEventListener("click", () => renderTrack(btn.getAttribute("data-track")));
});

// Hydrate Slide 3 SVG chart & Slide 4 showcase crops from real exported dataset
async function hydrateEvidence() {
  try {
    const resp = await fetch(`${SITE_ROOT}data/a4_study.json`);
    if (!resp.ok) return;
    const data = await resp.json();

    // Slide 3 chart
    const chartHost = document.getElementById("deck-a4-chart");
    const jList = [
      { key: "robodojo_astra", label: "OpenAI Astra" },
      { key: "claude_opus_5_5", label: "Anthropic Opus" },
      { key: "datacenterbench_dual", label: "Dual Judge" },
      { key: "gemini_4_neon", label: "Google Neon" },
      { key: null, label: "Hidden Instruments" },
    ];
    const w = 780;
    const h = 215;
    const pL = 46;
    const pR = 16;
    const pT = 22;
    const pB = 38;
    const cw = w - pL - pR;
    const ch = h - pT - pB;
    const yF = (v) => pT + ch - (Math.min(v, 50) / 50) * ch;
    const parts = [`<svg class="deck-chart-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="Deck A4 VLM FPR vs Instruments">`];
    [0, 10, 20, 30, 40, 50].forEach((tk) => {
      const yy = yF(tk);
      parts.push(`<line x1="${pL}" y1="${yy}" x2="${w - pR}" y2="${yy}" stroke="#D5D0C5" stroke-width="1"/>`);
      parts.push(`<text x="${pL - 6}" y="${yy + 3}" text-anchor="end" font-size="10" fill="#525B66" font-family="ui-monospace, monospace">${tk}%</text>`);
    });
    const yt = yF(5);
    parts.push(`<line x1="${pL}" y1="${yt}" x2="${w - pR}" y2="${yt}" stroke="#1F5E4B" stroke-width="1.5" stroke-dasharray="5,4"/>`);
    parts.push(`<text x="${w - pR}" y="${yt - 11}" text-anchor="end" font-size="10" font-weight="700" fill="#1F5E4B">5% Stop-Use Max FPR</text>`);

    const gw = cw / jList.length;
    const bw = 24;
    jList.forEach((item, idx) => {
      const cx = pL + idx * gw + gw / 2;
      if (!item.key) {
        const y0 = yF(0);
        parts.push(`<rect x="${cx - 32}" y="${y0 - 3}" width="64" height="3" fill="#1F5E4B"/>`);
        parts.push(`<text x="${cx}" y="${y0 - 15}" text-anchor="middle" font-size="10" font-weight="700" fill="#1F5E4B">0.0% / 0.0%</text>`);
      } else {
        const st = data.statistics.judges[item.key];
        const bars = [
          { v: st.overall_fpr * 100, c: "#B43B28" },
          { v: st.per_stratum.S4.fpr * 100, c: "#9C7A3C" },
          { v: st.overall_ffr * 100, c: "#1B365D" },
        ];
        const xs = cx - (3 * bw + 12) / 2;
        bars.forEach((b, bi) => {
          const bx = xs + bi * (bw + 6);
          const by = yF(b.v);
          parts.push(`<rect x="${bx}" y="${by}" width="${bw}" height="${Math.max(2, yF(0) - by)}" rx="0" fill="${b.c}"/>`);
          parts.push(`<text x="${bx + bw / 2}" y="${by - 4}" text-anchor="middle" font-size="9.5" font-weight="700" fill="#151A21">${b.v.toFixed(1)}%</text>`);
        });
      }
      parts.push(`<text x="${cx}" y="${h - 12}" text-anchor="middle" font-size="11" font-weight="600" fill="#151A21">${esc(item.label)}</text>`);
    });
    parts.push("</svg>");
    chartHost.innerHTML = parts.join("");

    // Slide 4 showcase crops (top 3 deceptive/borderline fails)
    const showIds = ["tr_57_962127", "tr_40_574742", "tr_23_604214"];
    const picked = showIds.map((id) => data.showcase.find((s) => s.opaque_id === id)).filter(Boolean);
    document.getElementById("deck-showcase").innerHTML = picked
      .map((tr) => `
        <div class="panel panel-white">
          <div class="mono small"><code>${esc(tr.family_id)}</code> &middot; <code>${esc(tr.stratum)}</code> &middot; <span class="badge badge-fail">GT FAIL</span></div>
          <div class="mini-stereo">
            <img src="${esc(SITE_ROOT + tr.left_img)}" alt="${esc(tr.opaque_id)} left"/>
            <img src="${esc(SITE_ROOT + tr.right_img)}" alt="${esc(tr.opaque_id)} right"/>
          </div>
          <p class="small"><strong>Physics:</strong> ${esc(tr.gt_reason)}</p>
        </div>
      `)
      .join("");
  } catch {
    // Offline fallback stays graceful if opened without HTTP server
  }
}

const params = new URLSearchParams(window.location.search);
const requestedTrack = (params.get("track") || "").trim().toLowerCase();
const hasLockedTrack = Object.prototype.hasOwnProperty.call(TRACKS, requestedTrack);

goToSlide(0);
renderTrack(hasLockedTrack ? requestedTrack : "lean");
if (hasLockedTrack) {
  const bar = document.querySelector(".track-bar");
  if (bar) bar.classList.add("is-hidden");
  const ey = document.querySelector('section[data-slide="12"] .slide-eyebrow');
  if (ey) ey.textContent = "Slide 12 · Proposed Path Forward & Collaboration Scope";
  const h2 = document.querySelector('section[data-slide="12"] h2');
  if (h2) h2.textContent = TRACKS[requestedTrack].title;
}
hydrateEvidence();
