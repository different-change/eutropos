// Client-side Web Crypto API verifier for eutropos-referee-v1.0 evidence bundles (Browser + Node ESM).
import { DEMO_SIGNER_KEYS } from "./brand-config.js";

export const DRAND_QUICKNET_CHAIN_HASH =
  "52db9ba70e0cc0f6eaf7803dd07447a1f5477735fd3f661792ba94600c84e971";
export const DRAND_QUICKNET_PUBKEY_HEX =
  "83cf0f2896adee7eb8b5f01fcad3912212c437e0073e911fb90022d3e760183c" +
  "8c4b450b6a0a6c3ac6a5776a2d1064510d1fec758c921cc22b0e17e63aaf4bcb" +
  "5ed66304de9cf809bd274ca73bab4af5a6e9c76a4bc09e76eae8991ef5ece45a";
export const DRAND_QUICKNET_GENESIS = 1692803367;
export const DRAND_QUICKNET_PERIOD = 3;

const PAYLOAD_TYPE = "application/vnd.eutropos.referee-certificate+json";
const MAX_RETRIES_PER_SLOT = 2;
const SLOT_STATUSES = new Set(["completed", "start_failure", "aborted", "hardware_fault", "retry"]);
const NON_RETRYABLE = new Set(["completed", "aborted"]);
const ALLOWED_DISCLOSURE_MODES = new Set(["general-open", "hazard-escrowed"]);
const ID_CT_TST_INFO_OID_HEX = "2a864886f70d0109100104";
const ID_SHA256_OID_HEX = "608648016503040201";

const te = new TextEncoder();
const td = new TextDecoder("utf-8", { fatal: true });

function getSubtle() {
  if (globalThis.crypto && globalThis.crypto.subtle) {
    return globalThis.crypto.subtle;
  }
  throw new Error("Web Crypto SubtleCrypto unavailable");
}

export function hexFromBytes(bytes) {
  let s = "";
  for (let i = 0; i < bytes.length; i += 1) {
    s += bytes[i].toString(16).padStart(2, "0");
  }
  return s;
}

export function bytesFromHex(hex) {
  if (typeof hex !== "string" || hex.length % 2 !== 0 || !/^[0-9a-f]*$/i.test(hex)) {
    throw new Error("Invalid hex string");
  }
  const out = new Uint8Array(hex.length / 2);
  for (let i = 0; i < out.length; i += 1) {
    out[i] = parseInt(hex.slice(i * 2, i * 2 + 2), 16);
  }
  return out;
}

export async function sha256Bytes(bytes) {
  const buf = await getSubtle().digest("SHA-256", bytes);
  return new Uint8Array(buf);
}

export async function sha256Hex(bytes) {
  return hexFromBytes(await sha256Bytes(bytes));
}

export function decodeBase64(b64, urlsafe = false) {
  if (typeof b64 !== "string" || b64.length % 4 !== 0) {
    throw new Error("Invalid base64 length");
  }
  const std = urlsafe ? b64.replace(/-/g, "+").replace(/_/g, "/") : b64;
  if (!/^[A-Za-z0-9+/]*={0,2}$/.test(std)) {
    throw new Error("Invalid base64 characters");
  }
  const bin = atob(std);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i += 1) {
    out[i] = bin.charCodeAt(i);
  }
  let reEnc = "";
  for (let i = 0; i < out.length; i += 1) reEnc += String.fromCharCode(out[i]);
  const b64Check = urlsafe
    ? btoa(reEnc).replace(/\+/g, "-").replace(/\//g, "_")
    : btoa(reEnc);
  if (b64Check !== b64) {
    throw new Error("Non-canonical base64 padding or encoding");
  }
  return out;
}

export function dssePAE(payloadType, payloadBytes) {
  const typeBytes = te.encode(payloadType);
  const head = te.encode(`DSSEv1 ${typeBytes.length} `);
  const mid = te.encode(` ${payloadBytes.length} `);
  const out = new Uint8Array(head.length + typeBytes.length + mid.length + payloadBytes.length);
  let pos = 0;
  out.set(head, pos); pos += head.length;
  out.set(typeBytes, pos); pos += typeBytes.length;
  out.set(mid, pos); pos += mid.length;
  out.set(payloadBytes, pos);
  return out;
}

export async function importEd25519Pem(pemText) {
  const cleaned = pemText
    .replace(/-----BEGIN PUBLIC KEY-----/g, "")
    .replace(/-----END PUBLIC KEY-----/g, "")
    .replace(/\s+/g, "");
  const der = decodeBase64(cleaned, false);
  const subtle = getSubtle();
  let key;
  try {
    key = await subtle.importKey("spki", der, { name: "Ed25519" }, true, ["verify"]);
  } catch (err) {
    const msg = String(err?.message || err);
    if (err?.name === "NotSupportedError" || /ed25519|unrecognized|not supported/i.test(msg)) {
      const e = new Error("This browser environment lacks native Web Crypto Ed25519 verification");
      e.code = "UNSUPPORTED_BROWSER";
      throw e;
    }
    throw err;
  }
  const rawSpki = new Uint8Array(await subtle.exportKey("spki", key));
  const raw32 = rawSpki.slice(rawSpki.length - 32);
  const fpHex = await sha256Hex(raw32);
  const kid = fpHex.slice(0, 16);
  return { key, kid, fpHex, raw32Hex: hexFromBytes(raw32) };
}

// Strict minimal-length ASN.1 DER parser for RFC 3161 TimeStampResp -> PKIStatusInfo + ContentInfo -> SignedData -> TSTInfo
function readDerNode(bytes, offset, end = bytes.length) {
  if (offset >= end) throw new Error("Truncated DER element");
  const tag = bytes[offset];
  let pos = offset + 1;
  if (pos >= end) throw new Error("Truncated DER length");
  const lenByte = bytes[pos];
  pos += 1;
  let len = 0;
  if ((lenByte & 0x80) === 0) {
    len = lenByte;
  } else {
    const numOctets = lenByte & 0x7f;
    if (numOctets === 0 || numOctets > 4 || pos + numOctets > end) {
      throw new Error("Unsupported or truncated DER length");
    }
    if (bytes[pos] === 0) {
      throw new Error("Leading zero in DER length");
    }
    for (let i = 0; i < numOctets; i += 1) {
      len = (len * 256) + bytes[pos + i];
    }
    if (len < 128) {
      throw new Error("Non-minimal DER length");
    }
    pos += numOctets;
  }
  const valEnd = pos + len;
  if (valEnd > end) throw new Error("DER length exceeds bounds");
  return {
    tag,
    constructed: (tag & 0x20) !== 0,
    valStart: pos,
    valEnd,
    next: valEnd,
    value: bytes.subarray(pos, valEnd),
  };
}

function readDerChildren(bytes, start, end) {
  const children = [];
  let cursor = start;
  while (cursor < end) {
    const node = readDerNode(bytes, cursor, end);
    children.push(node);
    cursor = node.next;
  }
  return children;
}

function parseDerGeneralizedTime(ascii) {
  const m = /^(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})(?:\.(\d+))?Z$/.exec(ascii);
  if (!m) throw new Error(`Invalid ASN.1 GeneralizedTime: ${ascii}`);
  const yr = Number(m[1]);
  const mo = Number(m[2]);
  const dy = Number(m[3]);
  const hr = Number(m[4]);
  const mn = Number(m[5]);
  const sc = Number(m[6]);
  const ms = m[7] ? Number(m[7].slice(0, 3).padEnd(3, "0")) : 0;
  const epochMs = Date.UTC(yr, mo - 1, dy, hr, mn, sc, ms);
  const iso = new Date(epochMs).toISOString().replace(".000Z", "Z");
  return { iso, epochSec: Math.floor(epochMs / 1000), epochMs };
}

function findEncapTstInfoNode(bytes, node) {
  if (!node.constructed) return null;
  const kids = readDerChildren(bytes, node.valStart, node.valEnd);
  if (
    node.tag === 0x30 &&
    kids.length >= 2 &&
    kids[0].tag === 0x06 &&
    hexFromBytes(kids[0].value) === ID_CT_TST_INFO_OID_HEX &&
    kids[1].tag === 0xa0
  ) {
    const inner = readDerChildren(bytes, kids[1].valStart, kids[1].valEnd);
    if (inner.length === 1 && inner[0].tag === 0x04) {
      return inner[0].value;
    }
  }
  for (const child of kids) {
    const found = findEncapTstInfoNode(bytes, child);
    if (found) return found;
  }
  return null;
}

export function parseTstInfoFromTsr(tsrBytes) {
  if (!(tsrBytes instanceof Uint8Array) || tsrBytes.length < 16) {
    throw new Error("Invalid TSR byte buffer");
  }
  const root = readDerNode(tsrBytes, 0, tsrBytes.length);
  if (root.tag !== 0x30) throw new Error("TimeStampResp outer element must be SEQUENCE");
  const respKids = readDerChildren(tsrBytes, root.valStart, root.valEnd);
  if (respKids.length < 2) throw new Error("TimeStampResp missing token");
  const statusInfo = respKids[0];
  if (statusInfo.tag !== 0x30) throw new Error("PKIStatusInfo must be SEQUENCE");
  const statusKids = readDerChildren(tsrBytes, statusInfo.valStart, statusInfo.valEnd);
  if (statusKids.length < 1 || statusKids[0].tag !== 0x02 || statusKids[0].value.length !== 1) {
    throw new Error("PKIStatus integer missing");
  }
  const pkiStatus = statusKids[0].value[0];
  if (pkiStatus !== 0 && pkiStatus !== 1) {
    throw new Error(`Unsupported TSA PKIStatus: ${pkiStatus}`);
  }
  const tstOctets = findEncapTstInfoNode(tsrBytes, respKids[1]);
  if (!tstOctets) throw new Error("id-ct-TSTInfo payload absent in TSR");

  const tstSeq = readDerNode(tstOctets, 0, tstOctets.length);
  if (tstSeq.tag !== 0x30) throw new Error("TSTInfo outer element must be SEQUENCE");
  const fields = readDerChildren(tstOctets, tstSeq.valStart, tstSeq.valEnd);
  if (fields.length < 5) throw new Error("Incomplete TSTInfo structure");

  const msgImp = fields[2];
  if (msgImp.tag !== 0x30) throw new Error("TSTInfo messageImprint malformed");
  const impKids = readDerChildren(tstOctets, msgImp.valStart, msgImp.valEnd);
  if (impKids.length !== 2 || impKids[0].tag !== 0x30 || impKids[1].tag !== 0x04) {
    throw new Error("TSTInfo messageImprint structure malformed");
  }
  const algKids = readDerChildren(tstOctets, impKids[0].valStart, impKids[0].valEnd);
  if (algKids.length < 1 || algKids[0].tag !== 0x06 || hexFromBytes(algKids[0].value) !== ID_SHA256_OID_HEX) {
    throw new Error("TSTInfo hashAlgorithm must be SHA-256 OID");
  }
  if (impKids[1].value.length !== 32) {
    throw new Error("TSTInfo hashedMessage must be 32 bytes for SHA-256");
  }
  const imprintHex = hexFromBytes(impKids[1].value);

  const genNode = fields[4];
  if (genNode.tag !== 0x18) throw new Error("TSTInfo genTime GeneralizedTime missing");
  const genAscii = td.decode(genNode.value);
  const parsedTime = parseDerGeneralizedTime(genAscii);

  return {
    pkiStatus,
    imprintHex,
    genTimeAscii: genAscii,
    genTimeUtc: parsedTime.iso,
    genTimeEpochSec: parsedTime.epochSec,
    genTimeEpochMs: parsedTime.epochMs,
  };
}

// Strict canonical JSON parser: enforces UTF-8, zero extra whitespace, sorted unique object keys, rejecting -0/NaN.
export function parseCanonicalJsonBytes(rawBytes) {
  const src = td.decode(rawBytes);
  let i = 0;

  function expectChar(ch) {
    if (src[i] !== ch) throw new Error(`Expected '${ch}' at offset ${i}`);
    i += 1;
  }

  function parseString() {
    expectChar('"');
    const start = i - 1;
    while (i < src.length) {
      const c = src.charCodeAt(i);
      if (c === 0x22) {
        i += 1;
        return JSON.parse(src.slice(start, i));
      }
      if (c === 0x5c) {
        i += 2;
      } else if (c < 0x20) {
        throw new Error(`Unescaped control char in string at ${i}`);
      } else {
        i += 1;
      }
    }
    throw new Error("Unterminated string");
  }

  function parseNumber() {
    const start = i;
    if (src[i] === "-") i += 1;
    if (src[i] === "0") {
      i += 1;
    } else if (src[i] >= "1" && src[i] <= "9") {
      while (i < src.length && src[i] >= "0" && src[i] <= "9") i += 1;
    } else {
      throw new Error(`Invalid number at ${start}`);
    }
    if (src[i] === ".") {
      i += 1;
      if (!(src[i] >= "0" && src[i] <= "9")) throw new Error(`Invalid fraction at ${i}`);
      while (i < src.length && src[i] >= "0" && src[i] <= "9") i += 1;
    }
    if (src[i] === "e" || src[i] === "E") {
      i += 1;
      if (src[i] === "+" || src[i] === "-") i += 1;
      if (!(src[i] >= "0" && src[i] <= "9")) throw new Error(`Invalid exponent at ${i}`);
      while (i < src.length && src[i] >= "0" && src[i] <= "9") i += 1;
    }
    const token = src.slice(start, i);
    const val = Number(token);
    if (!Number.isFinite(val)) throw new Error("Non-finite number");
    if (Object.is(val, -0)) throw new Error("Negative zero rejected");
    return val;
  }

  function parseValue() {
    if (i >= src.length) throw new Error("Unexpected EOF");
    const ch = src[i];
    if (ch === '"') return parseString();
    if (ch === "{") {
      i += 1;
      const obj = {};
      if (src[i] === "}") {
        i += 1;
        return obj;
      }
      let prevKey = null;
      while (true) {
        const k = parseString();
        if (Object.prototype.hasOwnProperty.call(obj, k)) {
          throw new Error(`Duplicate JSON key: ${k}`);
        }
        if (prevKey !== null && prevKey >= k) {
          throw new Error(`Unsorted JSON key: ${k} after ${prevKey}`);
        }
        prevKey = k;
        expectChar(":");
        obj[k] = parseValue();
        if (src[i] === "}") {
          i += 1;
          return obj;
        }
        expectChar(",");
      }
    }
    if (ch === "[") {
      i += 1;
      const arr = [];
      if (src[i] === "]") {
        i += 1;
        return arr;
      }
      while (true) {
        arr.push(parseValue());
        if (src[i] === "]") {
          i += 1;
          return arr;
        }
        expectChar(",");
      }
    }
    if (src.startsWith("true", i)) { i += 4; return true; }
    if (src.startsWith("false", i)) { i += 5; return false; }
    if (src.startsWith("null", i)) { i += 4; return null; }
    if (ch === "-" || (ch >= "0" && ch <= "9")) return parseNumber();
    throw new Error(`Unexpected token at offset ${i}: '${ch}'`);
  }

  const res = parseValue();
  if (i !== src.length) {
    throw new Error(`Trailing garbage or whitespace at byte ${i}`);
  }
  return res;
}

function u64be(n) {
  const b = new Uint8Array(8);
  let v = BigInt(n);
  for (let i = 7; i >= 0; i -= 1) {
    b[i] = Number(v & 0xffn);
    v >>= 8n;
  }
  return b;
}

function concatBytes(...chunks) {
  let len = 0;
  for (const c of chunks) len += c.length;
  const out = new Uint8Array(len);
  let pos = 0;
  for (const c of chunks) {
    out.set(c, pos);
    pos += c.length;
  }
  return out;
}

function lp(bytes) {
  return concatBytes(u64be(bytes.length), bytes);
}

function deepEqual(a, b) {
  if (Object.is(a, b)) return true;
  if (typeof a !== typeof b || a === null || b === null) return false;
  if (Array.isArray(a)) {
    if (!Array.isArray(b) || a.length !== b.length) return false;
    return a.every((v, idx) => deepEqual(v, b[idx]));
  }
  if (typeof a === "object") {
    if (Array.isArray(b)) return false;
    const ka = Object.keys(a);
    const kb = Object.keys(b);
    if (ka.length !== kb.length) return false;
    return ka.every((k) => Object.prototype.hasOwnProperty.call(b, k) && deepEqual(a[k], b[k]));
  }
  return false;
}

function drandRoundEpochSec(roundNum) {
  return DRAND_QUICKNET_GENESIS + (Number(roundNum) - 1) * DRAND_QUICKNET_PERIOD;
}

function epochToIsoUtc(epochSec) {
  return new Date(epochSec * 1000).toISOString().replace(".000Z", "Z");
}

function wilson95(k, n) {
  if (n <= 0) return null;
  const z = 1.959963984540054;
  const p = k / n;
  const den = 1 + (z * z) / n;
  const cen = p + (z * z) / (2 * n);
  const half = z * Math.sqrt((p * (1 - p)) / n + (z * z) / (4 * n * n));
  return [
    Math.max(0, Number(((cen - half) / den).toFixed(6))),
    Math.min(1, Number(((cen + half) / den).toFixed(6))),
  ];
}

export async function verifyV1BundleInBrowser(fileMap, publicKeyPem, options = {}) {
  const checks = [];
  const failures = [];
  const add = (name, passed, detail) => {
    const ok = Boolean(passed);
    checks.push({ name, passed: ok, detail });
    if (!ok) failures.push(`${name}: ${detail}`);
    return ok;
  };

  const pinnedRegistry = options.pinnedKeys || DEMO_SIGNER_KEYS;
  const keySource = options.keySource || "bundled";

  if (!publicKeyPem) {
    add("trusted_public_key", false, "Public key PEM required");
    return { passed: false, status: "failed", trustStatus: "missing-key", checks, failures, summary: null };
  }

  let keyInfo;
  try {
    keyInfo = await importEd25519Pem(publicKeyPem);
  } catch (err) {
    const unsupported = err?.code === "UNSUPPORTED_BROWSER";
    add("dsse_signature", false, String(err.message || err));
    return {
      passed: false,
      status: unsupported ? "unsupported-browser" : "failed",
      trustStatus: "invalid-key",
      checks,
      failures,
      summary: null,
    };
  }

  const pinnedEntry = Object.prototype.hasOwnProperty.call(pinnedRegistry, keyInfo.kid) &&
    pinnedRegistry[keyInfo.kid].sha256 === keyInfo.fpHex
    ? pinnedRegistry[keyInfo.kid]
    : null;

  let trustStatus = "self-signed-untrusted";
  let trustLabel = "Bundle-Supplied Key Only (Signer Unverified)";
  if (keySource === "external-file") {
    trustStatus = "external-trusted-key";
    trustLabel = `External Auditor Key (keyid=${keyInfo.kid})`;
  } else if (pinnedEntry) {
    trustStatus = "pinned-demo-key";
    trustLabel = pinnedEntry.label;
  }

  const getBytes = (rel) => fileMap.get(rel) || null;
  const certBytes = getBytes("certificate.json");
  if (!certBytes) {
    add("dsse_signature", false, "Missing certificate.json");
    return { passed: false, status: "failed", trustStatus, checks, failures, summary: null };
  }

  let payload;
  try {
    const env = parseCanonicalJsonBytes(certBytes);
    if (env.payloadType !== PAYLOAD_TYPE || !Array.isArray(env.signatures) || env.signatures.length !== 1) {
      throw new Error("Invalid DSSE envelope header");
    }
    const rawPayloadBytes = decodeBase64(env.payload, false);
    const pae = dssePAE(env.payloadType, rawPayloadBytes);
    const subtle = getSubtle();
    const entry = env.signatures[0];
    if (!entry || entry.keyid !== keyInfo.kid) {
      throw new Error("DSSE key ID differs from supplied public key");
    }
    const sigBytes = decodeBase64(entry.sig, false);
    const verified = await subtle.verify({ name: "Ed25519" }, keyInfo.key, sigBytes, pae);
    if (!verified) throw new Error("Ed25519 DSSE signature verification failed");
    payload = parseCanonicalJsonBytes(rawPayloadBytes);
    add("dsse_signature", true, `Web Crypto Ed25519 DSSEv1 PAE verified; keyid=${keyInfo.kid}`);
  } catch (err) {
    add("dsse_signature", false, String(err.message || err));
    return { passed: false, status: "failed", trustStatus, checks, failures, summary: null };
  }

  const reqJson = (rel) => {
    const raw = getBytes(rel);
    if (!raw) throw new Error(`Missing required file: ${rel}`);
    return { raw, doc: parseCanonicalJsonBytes(raw) };
  };

  let taskSpec, bodyCfg, pre, post, close, ledgerRows, reveal = null;
  const dMode = payload.disclosure_mode;
  try {
    if (!ALLOWED_DISCLOSURE_MODES.has(dMode)) {
      throw new Error(`Unsupported disclosure_mode: ${dMode}`);
    }
    taskSpec = reqJson("task_spec.json");
    bodyCfg = reqJson("body_configuration.json");
    pre = reqJson("pre_beacon_registration.json");
    post = reqJson("post_beacon_inputs.json");
    close = reqJson("manifests/session_close.json");
    const ledBytes = getBytes("manifests/slot_ledger.jsonl");
    if (!ledBytes) throw new Error("Missing manifests/slot_ledger.jsonl");
    const ledLines = td.decode(ledBytes).split("\n").filter((l) => l.length > 0);
    ledgerRows = ledLines.map((l) => parseCanonicalJsonBytes(te.encode(l)));
    if (dMode === "general-open") {
      reveal = reqJson("seed_reveal.json").doc;
    }
    add("v1_structure", true, `Loaded v1.0 artifacts (${dMode})`);
  } catch (err) {
    add("v1_structure", false, String(err.message || err));
    return { passed: false, status: "failed", trustStatus, checks, failures, summary: null };
  }

  try {
    const taskSha = await sha256Hex(taskSpec.raw);
    const bodySha = await sha256Hex(bodyCfg.raw);
    const preSha = await sha256Hex(pre.raw);
    const postSha = await sha256Hex(post.raw);
    const closeSha = await sha256Hex(close.raw);
    const ledgerSha = await sha256Hex(getBytes("manifests/slot_ledger.jsonl"));

    add(
      "cert_prereg_consistency",
      deepEqual(payload.subject, pre.doc.subject) &&
        payload.pareto_profile === pre.doc.pareto_profile &&
        payload.pareto_profile === taskSpec.doc.pareto_profile &&
        payload.pareto_profile === bodyCfg.doc.pareto_profile &&
        payload.mask_tactile === pre.doc.mask_tactile &&
        payload.mask_tactile === taskSpec.doc.mask_tactile &&
        payload.mask_tactile === bodyCfg.doc.mask_tactile &&
        payload.disclosure_mode === pre.doc.disclosure_mode &&
        deepEqual(payload.hashes, pre.doc.hashes) &&
        pre.doc.hashes?.task_spec === taskSha &&
        pre.doc.hashes?.body_configuration === bodySha,
      "Certificate, preregistration, task_spec, and body_configuration match"
    );

    add(
      "pre_post_binding",
      preSha === payload.pre_beacon_registration_sha256 &&
        preSha === post.doc.pre_beacon_registration_sha256 &&
        preSha === close.doc.pre_beacon_registration_sha256 &&
        postSha === close.doc.post_beacon_inputs_sha256,
      "pre_beacon_registration and post_beacon_inputs SHA-256 bindings"
    );

    const bcfg = pre.doc.beacon_config || {};
    const bdict = post.doc.beacon || {};
    const seedPub = payload.seed || {};
    add(
      "submitter_commitment",
      Boolean(pre.doc.submitter_N_hex) &&
        pre.doc.submitter_N_hex === post.doc.submitter_N_hex &&
        pre.doc.submitter_N_hex === seedPub.submitter_N_hex,
      "submitter_N_hex pre-committed prior to beacon release"
    );
    add(
      "post_beacon_match",
      deepEqual(bdict, seedPub.beacon) && bdict.round_number === bcfg.target_round,
      `round=${bdict.round_number} matches target_round=${bcfg.target_round}`
    );
    if (bcfg.scheme === "drand-quicknet") {
      const pinnedOk =
        bcfg.network === "drand-quicknet" &&
        bcfg.chain_hash === DRAND_QUICKNET_CHAIN_HASH &&
        bcfg.public_key_hex === DRAND_QUICKNET_PUBKEY_HEX &&
        bdict.chain_hash === DRAND_QUICKNET_CHAIN_HASH &&
        bdict.cryptographically_verified === true;
      let sigDigestOk = false;
      try {
        const sigBytes = bytesFromHex(bdict.signature_hex);
        const valHash = await sha256Hex(sigBytes);
        sigDigestOk = valHash === bdict.value_hex;
      } catch {
        sigDigestOk = false;
      }
      add(
        "drand_pinned_network",
        pinnedOk && sigDigestOk,
        "Pinned drand-quicknet chain_hash, G2 pubkey, and SHA256(sig)==randomness (BLS pairing runs in Python CLI)"
      );
    } else {
      add("drand_beacon", bdict.round_number === bcfg.target_round, "Local stub beacon");
    }

    if (dMode === "hazard-escrowed") {
      const leakedFields = ["S_hex", "nonce_hex", "derived_R_hex"].filter((k) =>
        Object.prototype.hasOwnProperty.call(seedPub, k)
      );
      add(
        "hazard_public_seed_redacted",
        leakedFields.length === 0 &&
          seedPub.seed_reveal_escrowed === true &&
          seedPub.commitment_C === pre.doc.commitment_C &&
          !fileMap.has("seed_reveal.json") &&
          !fileMap.has("referee_targets.json"),
        "Private seed_reveal and referee_targets omitted from public artifact directory"
      );
    } else if (reveal) {
      const sec = bytesFromHex(reveal.S_hex);
      const non = bytesFromHex(reveal.nonce_hex);
      const sub = bytesFromHex(reveal.submitter_N_hex);
      const bval = bytesFromHex(reveal.beacon?.value_hex);
      const cCalc = await sha256Hex(concatBytes(te.encode("eutropos-seed-commit-v1.0"), lp(sec), lp(non)));
      const rCalc = await sha256Bytes(concatBytes(te.encode("eutropos-run-seed-v1.0"), lp(sec), lp(sub), lp(bval)));
      const evalCalc = ((rCalc[0] << 24) | (rCalc[1] << 16) | (rCalc[2] << 8) | rCalc[3]) & 0x7fffffff;
      add(
        "commitment_C",
        cCalc === reveal.commitment_C &&
          cCalc === pre.doc.commitment_C &&
          cCalc === seedPub.commitment_C &&
          reveal.submitter_N_hex === pre.doc.submitter_N_hex &&
          deepEqual(reveal.beacon, post.doc.beacon),
        "v1.0 SHA-256 seed commitment and reveal bindings verified"
      );
      add(
        "derived_R_v1",
        hexFromBytes(rCalc) === reveal.derived_R_hex &&
          evalCalc === reveal.eval_seed &&
          reveal.derived_R_hex === seedPub.derived_R_hex &&
          reveal.eval_seed === seedPub.eval_seed,
        "v1.0 SHA-256 run seed & 31-bit eval_seed verified against certificate"
      );
    }

    // Slot Ledger State Machine & Independent Summary Recomputation
    const planned = pre.doc.planned_slots || [];
    const bySlotSpec = new Map(planned.map((s) => [s.slot_id, s]));
    const history = new Map(planned.map((s) => [s.slot_id, []]));
    const seenAtt = new Set();
    const completedEvents = [];
    let retriesCount = 0;
    let startFailureEvents = 0;
    let hardwareFaults = 0;
    let ledgerOk = planned.length > 0 && bySlotSpec.size === planned.length;

    for (let idx = 0; idx < ledgerRows.length && ledgerOk; idx += 1) {
      const ev = ledgerRows[idx];
      const spec = bySlotSpec.get(ev.slot_id);
      if (
        ev.seq !== idx ||
        !spec ||
        ev.logical_instance_id !== spec.logical_instance_id ||
        !SLOT_STATUSES.has(ev.status) ||
        !ev.execution_attempt_id ||
        seenAtt.has(ev.execution_attempt_id)
      ) {
        ledgerOk = false;
        break;
      }
      const prevList = history.get(ev.slot_id);
      if (prevList.length === 0) {
        if (ev.retry_of_attempt_id !== null) ledgerOk = false;
      } else {
        const prev = prevList[prevList.length - 1];
        retriesCount += 1;
        if (
          NON_RETRYABLE.has(prev.status) ||
          ev.retry_of_attempt_id !== prev.execution_attempt_id ||
          prevList.length > MAX_RETRIES_PER_SLOT
        ) {
          ledgerOk = false;
        }
      }
      if (ev.status === "completed") completedEvents.push(ev);
      if (ev.status === "start_failure") startFailureEvents += 1;
      if (ev.status === "hardware_fault") hardwareFaults += 1;
      seenAtt.add(ev.execution_attempt_id);
      prevList.push(ev);
    }

    let terminalCompleted = 0;
    let terminalPassed = 0;
    let terminalFailed = 0;
    let terminalAborted = 0;
    let terminalStartFail = 0;
    let allAccounted = ledgerOk;

    for (const s of planned) {
      const evs = history.get(s.slot_id) || [];
      if (evs.length === 0) {
        allAccounted = false;
        continue;
      }
      const lastEv = evs[evs.length - 1];
      if (lastEv.status === "completed") {
        terminalCompleted += 1;
        if (lastEv.trial_passed === true) terminalPassed += 1;
        else terminalFailed += 1;
      } else if (lastEv.status === "aborted") {
        terminalAborted += 1;
      } else if (lastEv.status === "start_failure") {
        terminalStartFail += 1;
      } else {
        allAccounted = false;
      }
    }

    add(
      "slot_ledger_machine",
      ledgerOk && allAccounted,
      `${ledgerRows.length} ledger events across ${planned.length} registered slots (${ledgerOk && allAccounted ? "all terminal" : "incomplete ledger"})`
    );

    const effPassRate = planned.length ? Number((terminalPassed / planned.length).toFixed(6)) : 0;
    const effCi = wilson95(terminalPassed, planned.length);
    const recomputedSlotSummary = {
      registered_slots: planned.length,
      completed_slots: terminalCompleted,
      passed_slots: terminalPassed,
      failed_slots: terminalFailed,
      aborted_slots: terminalAborted,
      terminal_start_failures: terminalStartFail,
      hardware_faults: hardwareFaults,
      start_failure_events: startFailureEvents,
      retries: retriesCount,
      all_slots_accounted: allAccounted,
      effective_pass_rate: effPassRate,
      effective_pass_ci95: effCi,
    };
    add(
      "slot_summary_recomputed",
      deepEqual(recomputedSlotSummary, payload.slot_summary),
      `Recomputed ${terminalPassed} passed / ${planned.length} registered slots match signed summary`
    );

    // Walk trial manifest chain
    const referenced = [];
    for (const e of pre.doc.files || []) referenced.push(e);
    let prevHash = preSha;
    const trials = [];
    const trialShas = [];
    let chainOk = close.doc.trial_manifest_count === completedEvents.length;
    for (let i = 0; i < close.doc.trial_manifest_count; i += 1) {
      const rel = `manifests/trial_${String(i).padStart(4, "0")}.json`;
      try {
        const tm = reqJson(rel);
        const ev = completedEvents[i];
        const expPass = tm.doc.scores?.["eutropos-mass"] === 1 && tm.doc.scores?.["eutropos-geometry"] === 1;
        if (
          tm.doc.prev_manifest_hash !== prevHash ||
          !ev ||
          tm.doc.slot_id !== ev.slot_id ||
          tm.doc.execution_attempt_id !== ev.execution_attempt_id ||
          !deepEqual(tm.doc.scores, ev.scores) ||
          tm.doc.trial_passed !== ev.trial_passed ||
          tm.doc.trial_passed !== expPass
        ) {
          chainOk = false;
        }
        prevHash = await sha256Hex(tm.raw);
        trialShas.push(prevHash);
        trials.push(tm.doc);
        for (const e of tm.doc.files || []) referenced.push(e);
      } catch {
        chainOk = false;
        trialShas.push(null);
      }
    }
    add(
      "ledger_manifest_chain",
      chainOk &&
        close.doc.prev_manifest_hash === prevHash &&
        close.doc.slot_ledger_sha256 === ledgerSha &&
        closeSha === payload.evidence?.chain_root_hash,
      `Chained ${trials.length} trial manifests to chain_root_hash=${closeSha.slice(0, 16)}...`
    );

    for (const e of close.doc.files || []) referenced.push(e);

    // ASN.1 DER RFC 3161 TSTInfo imprint & genTime extraction + full protocol ordering
    const tsaRec = payload.evidence?.tsa_receipts || {};
    const derTimes = {};
    const checkTsaBlock = async (label, blk, expectedDigestHex, recordCheck = true) => {
      if (!blk) {
        if (recordCheck) add(`tsa_${label}_der`, false, "Missing TSA receipt record");
        return false;
      }
      const raw = getBytes(blk.path);
      const actualSha = raw ? await sha256Hex(raw) : null;
      let tst = null;
      try {
        if (raw) tst = parseTstInfoFromTsr(raw);
      } catch {
        tst = null;
      }
      if (tst) derTimes[label] = tst;
      const digestOk =
        Boolean(raw) &&
        blk.digest_sha256 === expectedDigestHex &&
        actualSha === blk.tsr_sha256 &&
        Boolean(tst) &&
        tst.imprintHex === expectedDigestHex;
      if (recordCheck) {
        add(
          `tsa_${label}_der`,
          digestOk,
          tst
            ? `${blk.provider} DER genTime=${tst.genTimeUtc} (CMS X.509 signature runs in CLI)`
            : `${blk.provider} TSR ASN.1 DER parse failed`
        );
      }
      return digestOk;
    };
    await checkTsaBlock("commitment", tsaRec.commitment, preSha, true);
    await checkTsaBlock("post_beacon", tsaRec.post_beacon, postSha, true);
    await checkTsaBlock("session_close", tsaRec.session_close, closeSha, true);

    const checkpointLabels = [];
    let checkpointsOk = true;
    const rawCheckpoints = Array.isArray(tsaRec.checkpoints) ? tsaRec.checkpoints : [];
    for (let i = 0; i < rawCheckpoints.length; i += 1) {
      const chk = rawCheckpoints[i];
      const lbl = `checkpoint_${i}`;
      checkpointLabels.push(lbl);
      const midx = chk?.manifest_index;
      const expectedTrialSha =
        Number.isInteger(midx) && midx >= 0 && midx < trialShas.length ? trialShas[midx] : null;
      const ok = Boolean(expectedTrialSha) && (await checkTsaBlock(lbl, chk, expectedTrialSha, false));
      if (!ok) checkpointsOk = false;
    }

    const tCommMs = derTimes.commitment?.genTimeEpochMs;
    const tPostMs = derTimes.post_beacon?.genTimeEpochMs;
    const tCloseMs = derTimes.session_close?.genTimeEpochMs;
    const baseChronoOk =
      Number.isFinite(tCommMs) &&
      Number.isFinite(tPostMs) &&
      Number.isFinite(tCloseMs) &&
      tCommMs <= tPostMs &&
      tPostMs <= tCloseMs;
    const checkpointsChronoOk = checkpointLabels.every((lbl) => {
      const tChk = derTimes[lbl]?.genTimeEpochMs;
      return Number.isFinite(tChk) && tPostMs <= tChk && tChk <= tCloseMs;
    });
    add(
      "tsa_chronology",
      baseChronoOk && checkpointsOk && checkpointsChronoOk,
      Number.isFinite(tCommMs) && Number.isFinite(tCloseMs)
        ? `DER TSTInfo genTime: ${derTimes.commitment.genTimeUtc} <= ${derTimes.post_beacon?.genTimeUtc} <= ${derTimes.session_close.genTimeUtc}${checkpointLabels.length ? ` (+ ${checkpointLabels.length} checkpoints)` : ""}`
        : "Unavailable DER TSA timestamps"
    );

    let beaconRoundEpoch = null;
    if (bcfg.scheme === "drand-quicknet" && Number.isFinite(bdict.round_number)) {
      beaconRoundEpoch = drandRoundEpochSec(bdict.round_number);
      const beaconRoundMs = beaconRoundEpoch * 1000;
      add(
        "commitment_before_beacon_round",
        Number.isFinite(tCommMs) && tCommMs < beaconRoundMs,
        Number.isFinite(tCommMs)
          ? `Commitment DER ${derTimes.commitment.genTimeUtc} precedes quicknet round ${bdict.round_number} (${epochToIsoUtc(beaconRoundEpoch)}) by ${Math.floor((beaconRoundMs - tCommMs) / 1000)} s`
          : "Cannot compare commitment timestamp to drand round"
      );
      add(
        "post_beacon_after_round",
        Number.isFinite(tPostMs) && tPostMs >= beaconRoundMs,
        Number.isFinite(tPostMs)
          ? `Post-beacon DER ${derTimes.post_beacon.genTimeUtc} >= quicknet round ${bdict.round_number} (${epochToIsoUtc(beaconRoundEpoch)})`
          : "Cannot compare post-beacon timestamp to drand round"
      );
    }

    // Referenced file SHA-256 + byte-size verification
    let fileOkCount = 0;
    for (const entry of referenced) {
      const raw = getBytes(entry.path);
      if (!raw || raw.length !== entry.size_bytes) {
        add("file_sha256", false, `${entry.path} (size or existence mismatch)`);
        continue;
      }
      const h = await sha256Hex(raw);
      if (h !== entry.sha256) {
        add("file_sha256", false, entry.path);
      } else {
        fileOkCount += 1;
      }
    }
    if (fileOkCount === referenced.length) {
      add("all_files_sha256", true, `Verified SHA-256 + size across all ${fileOkCount} artifacts`);
    }

    const bundledPem = getBytes("public_key.pem");
    if (bundledPem) {
      try {
        const bKey = await importEd25519Pem(td.decode(bundledPem));
        add("public_key_copy", bKey.kid === keyInfo.kid, `Bundled keyid=${bKey.kid} matches active key`);
      } catch {
        add("public_key_copy", false, "Invalid bundled public_key.pem");
      }
    }

    const deviations = Array.isArray(pre.doc.deviations_and_incidents) ? pre.doc.deviations_and_incidents : [];
    const isSoftwareDemo =
      pinnedEntry?.evidenceClass === "software-demo" ||
      pre.doc.subject?.name === "v1-compliant-bench" ||
      deviations.some((d) => /simulat/i.test(String(d)));

    return {
      passed: failures.length === 0,
      status: failures.length === 0 ? "passed" : "failed",
      trustStatus,
      trustLabel,
      keyId: keyInfo.kid,
      keyFingerprint: keyInfo.fpHex,
      isSoftwareDemo,
      deferredCliChecks: [
        "BLS12-381 G1/G2 pairing signature against drand-quicknet public key",
        "X.509 / CMS SignedData TSA certificate chain verification",
      ],
      checks,
      failures,
      summary: {
        certificate_version: payload.certificate_version,
        pareto_profile: payload.pareto_profile,
        disclosure_mode: dMode,
        mask_tactile: payload.mask_tactile,
        beacon_scheme: bcfg.scheme,
        round_number: bdict.round_number,
        beacon_round_utc: beaconRoundEpoch !== null ? epochToIsoUtc(beaconRoundEpoch) : null,
        chain_root_hash: closeSha,
        tsa_commitment_der_utc: derTimes.commitment?.genTimeUtc || null,
        tsa_close_der_utc: derTimes.session_close?.genTimeUtc || null,
        tsa_commitment_utc: derTimes.commitment?.genTimeUtc || tsaRec.commitment?.gen_time_utc || null,
        tsa_close_utc: derTimes.session_close?.genTimeUtc || tsaRec.session_close?.gen_time_utc || null,
        slot_summary: recomputedSlotSummary,
        signed_slot_summary: payload.slot_summary,
        results: payload.results,
      },
    };
  } catch (err) {
    add("bundle_validation_error", false, String(err?.message || err));
    return {
      passed: false,
      status: "failed",
      trustStatus,
      trustLabel,
      keyId: keyInfo.kid,
      keyFingerprint: keyInfo.fpHex,
      isSoftwareDemo: false,
      checks,
      failures,
      summary: null,
    };
  }
}

export function applyTamperMutation(originalMap, attackId) {
  const cloned = new Map();
  for (const [k, v] of originalMap.entries()) {
    cloned.set(k, new Uint8Array(v));
  }
  if (attackId === "scale_byte_flip") {
    const scaleKey = [...cloned.keys()].find((k) => k.endsWith("_scale.txt"));
    if (scaleKey) {
      const arr = cloned.get(scaleKey);
      arr[0] = arr[0] ^ 0x01;
    }
  } else if (attackId === "hide_start_failure") {
    const raw = td.decode(cloned.get("manifests/slot_ledger.jsonl"));
    const rows = raw.split("\n").filter(Boolean).map((l) => JSON.parse(l));
    const kept = rows.filter((r) => r.status !== "start_failure");
    kept.forEach((r, idx) => { r.seq = idx; });
    const outText = kept.map((r) => JSON.stringify(r)).join("\n") + "\n";
    cloned.set("manifests/slot_ledger.jsonl", te.encode(outText));
  } else if (attackId === "forge_ledger_pass") {
    const raw = td.decode(cloned.get("manifests/slot_ledger.jsonl"));
    const rows = raw.split("\n").filter(Boolean).map((l) => JSON.parse(l));
    let promoted = false;
    for (const r of rows) {
      if (r.status === "start_failure") {
        r.status = "completed";
        r.trial_passed = true;
        r.scores = { "eutropos-geometry": 1.0, "eutropos-mass": 1.0 };
        r.reason = "forged pass";
        promoted = true;
        break;
      }
    }
    if (!promoted && rows.length > 0) {
      rows[0].status = "completed";
      rows[0].trial_passed = true;
      rows[0].scores = { "eutropos-geometry": 1.0, "eutropos-mass": 1.0 };
      rows[0].reason = "forged pass";
    }
    const sorted = rows.map((r) => {
      const obj = {};
      for (const k of Object.keys(r).sort()) obj[k] = r[k];
      return JSON.stringify(obj);
    });
    cloned.set("manifests/slot_ledger.jsonl", te.encode(sorted.join("\n") + "\n"));
  } else if (attackId === "swap_cert_bytes") {
    const doc = JSON.parse(td.decode(cloned.get("certificate.json")));
    const origSig = doc.signatures[0].sig;
    doc.signatures[0].sig = (origSig[0] === "A" ? "B" : "A") + origSig.slice(1);
    const out = {};
    for (const k of Object.keys(doc).sort()) out[k] = doc[k];
    cloned.set("certificate.json", te.encode(JSON.stringify(out)));
  }
  return cloned;
}
