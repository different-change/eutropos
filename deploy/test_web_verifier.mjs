import { readFileSync } from "node:fs";
import path from "node:path";
import assert from "node:assert/strict";
import { generateKeyPairSync, sign } from "node:crypto";
import {
  applyTamperMutation,
  parseTstInfoFromTsr,
  verifyV1BundleInBrowser,
} from "../site/js/verifier-core.js";
import { formatVaultState, renderVaultConsole } from "../site/js/vault-render.js";

function loadBundleFromDisk(bundleDir) {
  const baseDir = path.dirname(bundleDir);
  const name = path.basename(bundleDir);
  const idx = JSON.parse(readFileSync(path.join(baseDir, `${name}.index.json`), "utf-8"));
  const pubPem = readFileSync(path.join(baseDir, idx.trusted_public_key), "utf-8");
  const fileMap = new Map();
  for (const rel of idx.files) {
    fileMap.set(rel, new Uint8Array(readFileSync(path.join(bundleDir, rel))));
  }
  return { fileMap, pubPem };
}

function canonSort(obj) {
  if (Array.isArray(obj)) return obj.map(canonSort);
  if (obj && typeof obj === "object") {
    const out = {};
    for (const k of Object.keys(obj).sort()) out[k] = canonSort(obj[k]);
    return out;
  }
  return obj;
}

const openDir = path.resolve("site/data/bundles/open_live");
const hazDir = path.resolve("site/data/bundles/hazard_live");

const openBundle = loadBundleFromDisk(openDir);
const repOpen = await verifyV1BundleInBrowser(openBundle.fileMap, openBundle.pubPem, { keySource: "bundled" });
assert.equal(repOpen.passed, true, `open_live failed: ${repOpen.failures.join("; ")}`);
assert.equal(repOpen.checks.length, 22, `Expected 22 open checks, got ${repOpen.checks.length}`);
assert.equal(repOpen.checks.some((c) => c.name === "certificate_version" && c.passed), true);
assert.equal(repOpen.checks.some((c) => c.name === "disclosure_receipt" && c.passed), true);
assert.equal(repOpen.checks.some((c) => c.name === "post_beacon_after_round" && c.passed), true);
assert.equal(repOpen.trustStatus, "pinned-demo-key");
assert.equal(repOpen.isSoftwareDemo, true);
assert.equal(repOpen.summary.tsa_commitment_der_utc, "2026-11-19T23:50:32Z");
assert.equal(repOpen.summary.slot_summary.passed_slots, 3);
assert.equal(repOpen.summary.slot_summary.registered_slots, 3);
assert.equal(repOpen.summary.slot_attempts, 4);
const tstComm = parseTstInfoFromTsr(openBundle.fileMap.get("tsa/commitment.tsr"));
assert.equal(tstComm.genTimeUtc, "2026-11-19T23:50:32Z");
assert.equal(typeof tstComm.genTimeEpochNs, "bigint");
console.log("OPEN_LIVE_WEB_CRYPTO_OK:", repOpen.checks.length, "checks, round", repOpen.summary.round_number, "DER UTC", repOpen.summary.tsa_commitment_der_utc);

const hazBundle = loadBundleFromDisk(hazDir);
const repHaz = await verifyV1BundleInBrowser(hazBundle.fileMap, hazBundle.pubPem, { keySource: "bundled" });
assert.equal(repHaz.passed, true, `hazard_live failed: ${repHaz.failures.join("; ")}`);
assert.equal(repHaz.checks.length, 21, `Expected 21 hazard checks, got ${repHaz.checks.length}`);
assert.equal(repHaz.checks.some((c) => c.name === "certificate_version" && c.passed), true);
assert.equal(repHaz.checks.some((c) => c.name === "disclosure_receipt" && c.passed), true);
assert.equal(repHaz.checks.some((c) => c.name === "post_beacon_after_round" && c.passed), true);
assert.equal(repHaz.trustStatus, "pinned-demo-key");
console.log("HAZARD_LIVE_WEB_CRYPTO_OK:", repHaz.checks.length, "checks, round", repHaz.summary.round_number);

// Missing or forged disclosure/escrow receipts must fail disclosure_receipt
const missingEscrow = new Map(hazBundle.fileMap);
missingEscrow.delete("escrow_receipt.json");
const badEsc = await verifyV1BundleInBrowser(missingEscrow, hazBundle.pubPem, { keySource: "bundled" });
assert.equal(badEsc.passed, false);
assert.equal(badEsc.failures.some((f) => f.startsWith("disclosure_receipt:")), true);

const forgedTargets = new Map(openBundle.fileMap);
forgedTargets.set("referee_targets.json", new TextEncoder().encode('{"schema":"eutropos-targets-v1.0","trials":[]}'));
const badTgt = await verifyV1BundleInBrowser(forgedTargets, openBundle.pubPem, { keySource: "bundled" });
assert.equal(badTgt.passed, false);
assert.equal(badTgt.failures.some((f) => f.startsWith("disclosure_receipt:")), true);

// Tamper mutations including genuine start_failure -> completed promotion on forge_ledger_pass
for (const attack of ["scale_byte_flip", "hide_start_failure", "forge_ledger_pass", "swap_cert_bytes"]) {
  const mutRes = applyTamperMutation(openBundle.fileMap, attack);
  assert.equal(mutRes.mutated, true, `Attack ${attack} did not mutate open_live`);
  const bad = await verifyV1BundleInBrowser(mutRes.map, openBundle.pubPem, { keySource: "bundled" });
  assert.equal(bad.passed, false, `Attack ${attack} unexpectedly passed!`);
  const uiCleanBranch = formatVaultState(bad, { attackLabel: null, sourceLabel: "Test" });
  assert.equal(uiCleanBranch.stateCls, "is-tampered");
  assert.equal(uiCleanBranch.statusLine.includes("VERIFIED"), false, "Failing clean check unexpectedly printed VERIFIED");
  assert.equal(uiCleanBranch.verdictTitle.includes("Intact"), false, "Failing clean check unexpectedly printed Intact");
  console.log(`TAMPER_CAUGHT_${attack}:`, bad.failures[0]);
}

// Inapplicable tamper simulation returns mutated:false and clean inapplicable formatting (never UNEXPECTED PASS)
const noScaleMap = new Map(openBundle.fileMap);
for (const k of [...noScaleMap.keys()]) {
  if (k.endsWith("_scale.txt")) noScaleMap.delete(k);
}
const inappRes = applyTamperMutation(noScaleMap, "scale_byte_flip");
assert.equal(inappRes.mutated, false);
const uiInapp = formatVaultState(repOpen, { attackLabel: "Flip 1 Scale Byte", inapplicableReason: inappRes.reason, sourceLabel: "Local" });
assert.equal(uiInapp.stateCls, "is-pending");
assert.equal(uiInapp.statusLine.includes("INAPPLICABLE"), true);
assert.equal(uiInapp.statusLine.includes("UNEXPECTED PASS"), false);

// Strict ASN.1 DER CMS path, trailing-byte rejection, non-minimal DER, and calendar date checks
function derTlv(tag, ...chunks) {
  const body = Buffer.concat(chunks);
  assert.ok(body.length < 128);
  return Buffer.concat([Buffer.from([tag, body.length]), body]);
}
const sha1Oid = Buffer.from([0x06, 0x05, 0x2b, 0x0e, 0x03, 0x02, 0x1a]);
const sha256Oid = Buffer.from([0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01]);
const signedDataOid = Buffer.from([0x06, 0x09, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x07, 0x02]);
const tstIdOid = Buffer.from([0x06, 0x0b, 0x2a, 0x86, 0x48, 0x86, 0xf7, 0x0d, 0x01, 0x09, 0x10, 0x01, 0x04]);
const makeTsrWith = (algOid, digestLen, genStr) => {
  const tst = derTlv(
    0x30,
    Buffer.from([0x02, 0x01, 0x01]),
    Buffer.from([0x06, 0x01, 0x01]),
    derTlv(0x30, derTlv(0x30, algOid), Buffer.concat([Buffer.from([0x04, digestLen]), Buffer.alloc(digestLen)])),
    Buffer.from([0x02, 0x01, 0x01]),
    Buffer.concat([Buffer.from([0x18, genStr.length]), Buffer.from(genStr, "ascii")])
  );
  const encap = derTlv(0x30, tstIdOid, derTlv(0xa0, derTlv(0x04, tst)));
  const signedData = derTlv(0x30, Buffer.from([0x02, 0x01, 0x03]), derTlv(0x31), encap);
  return new Uint8Array(
    derTlv(0x30, derTlv(0x30, Buffer.from([0x02, 0x01, 0x00])), derTlv(0x30, signedDataOid, derTlv(0xa0, signedData)))
  );
};

assert.throws(
  () => parseTstInfoFromTsr(new Uint8Array([0x30, 0x81, 0x10, ...new Array(16).fill(0)])),
  /Non-minimal DER length/
);
assert.throws(() => parseTstInfoFromTsr(makeTsrWith(sha1Oid, 20, "20261119235032Z")), /SHA-256 OID/);
assert.throws(() => parseTstInfoFromTsr(makeTsrWith(sha256Oid, 32, "20260230235032Z")), /calendar date/);
const withTrailing = new Uint8Array([...openBundle.fileMap.get("tsa/commitment.tsr"), 0x00]);
assert.throws(() => parseTstInfoFromTsr(withTrailing), /Trailing bytes/);

// Unexpected pass attack state + missing slot accountability + retries pluralization + stub beacon checks
const uiUnexpected = formatVaultState(repOpen, { attackLabel: "Mock Attack", sourceLabel: "Test" });
assert.equal(uiUnexpected.stateCls, "is-error");
assert.equal(uiUnexpected.statusLine.includes("UNEXPECTED PASS"), true);

const uiStub = formatVaultState({ ...repOpen, summary: { ...repOpen.summary, isStubBeacon: true } }, { sourceLabel: "Local" });
assert.equal(uiStub.stateCls, "is-self-signed");
assert.equal(uiStub.statusLine.includes("LOCAL STUB BUNDLE"), true);

const incompleteMock = {
  passed: true,
  trustStatus: "pinned-demo-key",
  checks: [{ passed: true }],
  summary: {
    pareto_profile: "P2",
    slot_attempts: 4,
    slot_summary: { passed_slots: 2, registered_slots: 3, retries: 2, all_slots_accounted: false },
  },
};
const fakeEl = { className: "", innerHTML: "" };
renderVaultConsole(fakeEl, incompleteMock, { compactTelemetry: true, showCliHandoff: false });
assert.equal(fakeEl.innerHTML.includes("INCOMPLETE LEDGER"), true);
assert.equal(fakeEl.innerHTML.includes("4 attempts (2 retries)"), true);
assert.equal(fakeEl.innerHTML.includes("vault-cli-handoff"), false);
incompleteMock.summary.slot_summary.retries = 0;
incompleteMock.summary.slot_summary.all_slots_accounted = true;
renderVaultConsole(fakeEl, incompleteMock, { compactTelemetry: true });
assert.equal(fakeEl.innerHTML.includes("0 retries"), true);
assert.equal(fakeEl.innerHTML.includes("all terminal"), true);

// Verify DER TSR mutation fails even when JSON stays untouched
const tsrTampered = new Map(openBundle.fileMap);
const origTsr = new Uint8Array(tsrTampered.get("tsa/commitment.tsr"));
origTsr[origTsr.length - 10] ^= 0xff;
tsrTampered.set("tsa/commitment.tsr", origTsr);
const badTsr = await verifyV1BundleInBrowser(tsrTampered, openBundle.pubPem, { keySource: "bundled" });
assert.equal(badTsr.passed, false, "Corrupted .tsr DER bytes unexpectedly passed!");

// Verify self-signed key classification vs external trusted key classification
const { publicKey, privateKey } = generateKeyPairSync("ed25519");
const roguePem = publicKey.export({ format: "pem", type: "spki" }).toString();
const rogueRaw32 = publicKey.export({ format: "der", type: "spki" }).subarray(-32);
const { createHash } = await import("node:crypto");
const rogueKid = createHash("sha256").update(rogueRaw32).digest("hex").slice(0, 16);

const rogueEnv = JSON.parse(new TextDecoder().decode(openBundle.fileMap.get("certificate.json")));
const rawPayloadBytes = Buffer.from(rogueEnv.payload, "base64");
const pae = Buffer.concat([
  Buffer.from(`DSSEv1 ${rogueEnv.payloadType.length} `),
  Buffer.from(rogueEnv.payloadType),
  Buffer.from(` ${rawPayloadBytes.length} `),
  rawPayloadBytes,
]);
const sigB64 = sign(null, pae, privateKey).toString("base64");
rogueEnv.signatures = [{ keyid: rogueKid, sig: sigB64 }];

const selfSignedMap = new Map(openBundle.fileMap);
selfSignedMap.set("certificate.json", new TextEncoder().encode(JSON.stringify(canonSort(rogueEnv))));
selfSignedMap.set("public_key.pem", new TextEncoder().encode(roguePem));

const repSelfSigned = await verifyV1BundleInBrowser(selfSignedMap, roguePem, { keySource: "bundled" });
assert.equal(repSelfSigned.passed, true);
assert.equal(repSelfSigned.trustStatus, "self-signed-untrusted");
const uiSelfSigned = formatVaultState(repSelfSigned, { sourceLabel: "Upload" });
assert.equal(uiSelfSigned.stateCls, "is-self-signed");
assert.equal(uiSelfSigned.statusLine.includes("SIGNER UNVERIFIED"), true);

const repExtKey = await verifyV1BundleInBrowser(selfSignedMap, roguePem, { keySource: "external-file" });
assert.equal(repExtKey.passed, true);
assert.equal(repExtKey.trustStatus, "external-trusted-key");

console.log("WEB_VERIFIER_TESTS_PASSED");
