#!/usr/bin/env python3
"""
V-cloak reference oracle (Phase P1: NumPy correctness oracle).

Implements the complete V-cloak write path and read path on CPU with the same
branch-free bitonic network the CUDA kernel uses, then runs the interim
experiments reported in the paper:

  E0  end-to-end restoration correctness
  E1  order-recovery attack on a database dump (Kendall tau), with window ablation
  E2  permutation uniformity (chi-square, TVD) and Kendall-tau band at n = 2^16
  E3  access-trace invariance (bitonic vs data-dependent merge sort)
  E4  CPU reference throughput of the bitonic network
  E5  session-security test matrix (DPoP-style proof-of-possession + refresh rotation)

Every number the paper prints is written to results/ by this script.
Run:  python3 vcloak_oracle.py            (full, ~3-6 min on a laptop)
      python3 vcloak_oracle.py --quick    (smoke test)
"""
from __future__ import annotations

import argparse, base64, hashlib, hmac, json, os, time, uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy import stats
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, x25519
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature, encode_dss_signature
from cryptography.exceptions import InvalidSignature

OUT = Path(__file__).resolve().parent.parent / "results"
OUT.mkdir(exist_ok=True)
BLOCK = 256          # padded plaintext block (4 KiB in the deployment; 256 B keeps the oracle fast)
EPOCH_S = 0.2        # 200 ms epoch


def hkdf(key: bytes, info: bytes, n: int = 32) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=n, salt=None, info=info).derive(key)


# --------------------------------------------------------------------------------------
# 1. Branch-free bitonic network (identical schedule to kernels/bitonic.cu)
# --------------------------------------------------------------------------------------
_SCHED_CACHE: dict[int, list] = {}


def bitonic_schedule(n: int):
    """Comparator schedule. Depends on n only -> the access pattern is data-independent."""
    assert n & (n - 1) == 0, "n must be a power of two"
    if n in _SCHED_CACHE:
        return _SCHED_CACHE[n]
    idx = np.arange(n, dtype=np.int64)
    sched = []
    k = 2
    while k <= n:
        j = k // 2
        while j >= 1:
            part = idx ^ j
            m = part > idx
            lo, hi = idx[m], part[m]
            asc = (lo & k) == 0
            sched.append((lo, hi, asc))
            j //= 2
        k *= 2
    _SCHED_CACHE[n] = sched
    return sched


def bitonic_sort(keys: list[np.ndarray], payload: list[np.ndarray] | None = None, trace: list | None = None):
    """Sort lexicographically by keys[0], keys[1], ... (uint64 limbs). The last limb must make
    keys unique (we always append the slot index). Swaps are arithmetic selects (np.where),
    the CPU analogue of the masked compare-exchange in the CUDA kernel."""
    n = keys[0].shape[0]
    cols = [k.copy() for k in keys] + [p.copy() for p in (payload or [])]
    nk = len(keys)
    for lo, hi, asc in bitonic_schedule(n):
        if trace is not None:
            trace.append(hashlib.sha256(lo.tobytes() + hi.tobytes()).digest())
        gt = np.zeros(lo.shape[0], dtype=bool)
        eq = np.ones(lo.shape[0], dtype=bool)
        for c in cols[:nk]:
            a, b = c[lo], c[hi]
            gt |= eq & (a > b)
            eq &= (a == b)
        swap = np.where(asc, gt, ~gt)            # select, no branch on data
        for c in cols:
            a, b = c[lo], c[hi]
            c[lo] = np.where(swap, b, a)
            c[hi] = np.where(swap, a, b)
    return cols[:nk], cols[nk:]


def merge_sort_trace(vals: list[int]) -> bytes:
    """A conventional data-dependent sort; its comparison trace is recorded for contrast in E3."""
    h = hashlib.sha256()

    def ms(a, off):
        if len(a) <= 1:
            return a
        m = len(a) // 2
        L, R = ms(a[:m], off), ms(a[m:], off + m)
        out, i, j = [], 0, 0
        while i < len(L) and j < len(R):
            h.update(f"{off+i},{off+m+j};".encode())
            if L[i] <= R[j]:
                out.append(L[i]); i += 1
            else:
                out.append(R[j]); j += 1
        return out + L[i:] + R[j:]

    ms(list(vals), 0)
    return h.digest()


# --------------------------------------------------------------------------------------
# 2. Cryptographic layer
# --------------------------------------------------------------------------------------
def chacha_tags(key: bytes, epoch: int, n: int) -> tuple[np.ndarray, np.ndarray]:
    """128-bit blind tags (two uint64 limbs) from a ChaCha20 keystream keyed per epoch."""
    k = hkdf(key, b"vcloak-tag|" + epoch.to_bytes(8, "big"))
    enc = Cipher(algorithms.ChaCha20(k, b"\x00" * 16), mode=None).encryptor()
    ks = np.frombuffer(enc.update(b"\x00" * (16 * n)), dtype=np.uint64).reshape(n, 2)
    return ks[:, 0].copy(), ks[:, 1].copy()


@dataclass
class Keys:
    k_order: bytes = field(default_factory=lambda: os.urandom(32))   # GPU-resident only
    k_tag: bytes = field(default_factory=lambda: os.urandom(32))

    def bucket(self, conv_id: int, n_buckets: int) -> int:
        d = hmac.new(hkdf(self.k_order, b"bucket"), conv_id.to_bytes(8, "big"), hashlib.sha256).digest()
        return int.from_bytes(d[:4], "big") % n_buckets

    def seq_enc(self, conv_id: int, seq: int) -> bytes:
        nonce = os.urandom(12)
        return nonce + AESGCM(hkdf(self.k_order, b"seq")).encrypt(nonce, conv_id.to_bytes(8, "big") + seq.to_bytes(8, "big"), b"seq")

    def seq_dec(self, blob: bytes) -> tuple[int, int]:
        pt = AESGCM(hkdf(self.k_order, b"seq")).decrypt(blob[:12], blob[12:], b"seq")
        return int.from_bytes(pt[:8], "big"), int.from_bytes(pt[8:], "big")


def client_encrypt(k_content: bytes, text: bytes) -> bytes:
    padded = text + b"\x80" + b"\x00" * (BLOCK - len(text) - 1)          # fixed-length block
    nonce = os.urandom(12)
    return nonce + AESGCM(k_content).encrypt(nonce, padded, None)


def client_decrypt(k_content: bytes, blob: bytes) -> bytes:
    pt = AESGCM(k_content).decrypt(blob[:12], blob[12:], None)
    return pt[: pt.rstrip(b"\x00").rfind(b"\x80")]


# --------------------------------------------------------------------------------------
# 3. Write path, storage model, read path
# --------------------------------------------------------------------------------------
@dataclass
class Msg:
    conv: int
    seq: int
    arrival: int          # ground-truth global arrival rank
    t: float
    payload: bytes


def oblivious_compact(is_dummy: np.ndarray, order_idx: np.ndarray) -> np.ndarray:
    """Sort-based oblivious compaction: real slots first, preserving the (already random) order.
    Replaces the prefix-scan scatter whose write addresses depend on which slots are real."""
    n = is_dummy.shape[0]
    _, (perm,) = bitonic_sort([is_dummy.astype(np.uint64), np.arange(n, dtype=np.uint64)], [order_idx])
    return perm


def write_epoch(keys: Keys, epoch: int, batch: list[Msg], slots: int) -> list[Msg]:
    assert len(batch) <= slots
    n_real = len(batch)
    hi, lo = chacha_tags(keys.k_tag, epoch, slots)
    slot_idx = np.arange(slots, dtype=np.uint64)
    (_, _, _), (perm,) = bitonic_sort([hi, lo, slot_idx], [slot_idx])        # permute padded batch
    is_dummy = (perm >= n_real)
    out = oblivious_compact(is_dummy, perm)[:n_real]                        # strip dummies
    return [batch[int(i)] for i in out]


@dataclass
class Row:
    row_uuid: str
    bucket: int
    round_visible: int
    seq_enc: bytes
    payload: bytes
    truth: int            # evaluation only; never visible to the attacker


def simulate_traffic(rng: np.random.Generator, n_conv: int, duration_s: float, rate: float, k_content: dict) -> list[Msg]:
    events = []
    for c in range(n_conv):
        t = rng.exponential(1 / rate)
        while t < duration_s:
            events.append((t, c))
            # conversational burst: replies arrive quickly, then a pause
            t += rng.exponential(2.0) if rng.random() < 0.7 else rng.exponential(1 / rate)
    events.sort()
    seqs = [0] * n_conv
    msgs = []
    for r, (t, c) in enumerate(events):
        msgs.append(Msg(c, seqs[c], r, t, client_encrypt(k_content[c], f"m{seqs[c]} conv{c}".encode())))
        seqs[c] += 1
    return msgs


def build_database(keys: Keys, msgs: list[Msg], mode: str, window_s: float, slots: int, n_buckets: int, rng) -> list[Row]:
    """mode = conventional | epoch (Review-1 design) | window (refined: coarse round + window reshuffle)."""
    if mode == "conventional":
        return [Row(str(m.arrival + 1), keys.bucket(m.conv, n_buckets), int(m.t), keys.seq_enc(m.conv, m.seq), m.payload, m.arrival) for m in msgs]
    by_epoch: dict[int, list[Msg]] = {}
    for m in msgs:
        by_epoch.setdefault(int(m.t // EPOCH_S), []).append(m)
    heap: list[Row] = []
    for e in sorted(by_epoch):
        for m in write_epoch(keys, e, by_epoch[e], slots):
            rnd = e if mode == "epoch" else int((e * EPOCH_S) // window_s)
            heap.append(Row(str(uuid.uuid4()), keys.bucket(m.conv, n_buckets), rnd, keys.seq_enc(m.conv, m.seq), m.payload, m.arrival))
    if mode == "window":
        # periodic re-shuffle compaction: each closed window is rewritten in a fresh GPU permutation
        out, cur = [], []
        for r in heap + [None]:
            if r is None or (cur and r.round_visible != cur[0].round_visible):
                n = 1 << max(1, (len(cur) - 1).bit_length())
                hi, lo = chacha_tags(keys.k_tag, 10**9 + cur[0].round_visible, n)
                si = np.arange(n, dtype=np.uint64)
                _, (perm,) = bitonic_sort([hi, lo, si], [si])
                out += [cur[int(i)] for i in perm if i < len(cur)]
                cur = []
            if r is not None:
                cur.append(r)
        heap = out
    return heap


def order_recovery_attack(rows: list[Row], conv_of: dict | None = None) -> dict:
    """Attacker's best order: sort by visible round, then physical heap position."""
    guess = sorted(range(len(rows)), key=lambda p: (rows[p].round_visible, p))
    truth = np.array([rows[p].truth for p in guess])
    rank_guess = np.arange(len(guess))
    res = {"tau_global": float(stats.kendalltau(rank_guess, truth).statistic)}
    # within the visible round (the granularity the design claims to protect)
    taus, w = [], []
    groups: dict[int, list[int]] = {}
    for g, p in enumerate(guess):
        groups.setdefault(rows[p].round_visible, []).append(g)
    for gs in groups.values():
        if len(gs) >= 3:
            t = stats.kendalltau(np.arange(len(gs)), truth[gs]).statistic
            if not np.isnan(t):
                taus.append(t); w.append(len(gs))
    res["tau_within_round"] = float(np.average(taus, weights=w)) if taus else float("nan")
    res["rounds_with_3plus"] = len(taus)
    # which of two consecutive messages came first (turn order) -- per conversation proxy via buckets
    correct = sum(1 for a, b in zip(truth[:-1], truth[1:]) if a < b)
    res["adjacent_pair_accuracy"] = correct / max(1, len(truth) - 1)
    if conv_of is not None:
        # Conversation turn order, attacker given the conversation membership of every row (worst case):
        # for consecutive messages i -> i+1 of the same conversation, does the dump order them correctly?
        pos = {rows[p].truth: g for g, p in enumerate(guess)}
        rnd = {rows[p].truth: rows[p].round_visible for p in guess}
        by_conv: dict = {}
        for t in sorted(pos):
            by_conv.setdefault(conv_of[t], []).append(t)
        ok = tot = same = ok_same = 0
        for seq in by_conv.values():
            for a, b in zip(seq[:-1], seq[1:]):
                tot += 1
                hit = pos[a] < pos[b]
                ok += hit
                if rnd[a] == rnd[b]:
                    same += 1
                    ok_same += hit
        res["turn_order_accuracy"] = ok / max(1, tot)
        res["turns_same_round_frac"] = same / max(1, tot)
        res["turn_accuracy_same_round"] = ok_same / max(1, same) if same else float("nan")
    return res


def read_conversation(keys: Keys, rows: list[Row], conv: int, rnd: int, cand: int, n_buckets: int, rng) -> list[bytes]:
    """Fixed-size candidate fetch from (bucket, round); GPU decrypts seq_enc and bitonic-sorts."""
    b = keys.bucket(conv, n_buckets)
    pool = [r for r in rows if r.bucket == b and r.round_visible == rnd]
    assert len(pool) <= cand, "candidate set too small for this bucket/round"
    dummies = [None] * (cand - len(pool))
    cset = pool + dummies
    n = 1 << (cand - 1).bit_length()
    cset += [None] * (n - len(cset))
    miss = np.ones(n, dtype=np.uint64)
    seqk = np.zeros(n, dtype=np.uint64)
    for i, r in enumerate(cset):
        if r is not None:
            c, s = keys.seq_dec(r.seq_enc)
            miss[i] = np.uint64(0 if c == conv else 1)
            seqk[i] = np.uint64(s)
    _, (perm,) = bitonic_sort([miss, seqk, np.arange(n, dtype=np.uint64)], [np.arange(n, dtype=np.uint64)])
    hits = int((miss == 0).sum())
    return [cset[int(i)].payload for i in perm[:hits]]


# --------------------------------------------------------------------------------------
# 4. Session security (response to Review-2 feedback)
# --------------------------------------------------------------------------------------
def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def ub64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def jwk_thumb(pub: ec.EllipticCurvePublicKey) -> str:
    n = pub.public_numbers()
    jwk = {"crv": "P-256", "kty": "EC", "x": b64u(n.x.to_bytes(32, "big")), "y": b64u(n.y.to_bytes(32, "big"))}
    return b64u(hashlib.sha256(json.dumps(jwk, separators=(",", ":"), sort_keys=True).encode()).digest()), jwk


def make_dpop(priv, htm, htu, token, iat=None, jti=None):
    _, jwk = jwk_thumb(priv.public_key())
    hdr = {"typ": "dpop+jwt", "alg": "ES256", "jwk": jwk}
    body = {"htm": htm, "htu": htu, "iat": int(iat if iat is not None else time.time()),
            "jti": jti or b64u(os.urandom(16)), "ath": b64u(hashlib.sha256(token.encode()).digest())}
    si = f"{b64u(json.dumps(hdr).encode())}.{b64u(json.dumps(body).encode())}"
    r, s = decode_dss_signature(priv.sign(si.encode(), ec.ECDSA(hashes.SHA256())))
    return si + "." + b64u(r.to_bytes(32, "big") + s.to_bytes(32, "big"))


class SessionServer:
    ACCESS_TTL, SKEW, JTI_TTL = 600, 60, 300

    def __init__(self):
        self.mac = os.urandom(32)
        self.seen_jti: dict[str, float] = {}
        self.refresh: dict[str, dict] = {}

    def issue(self, user, jkt, now=None, family=None):
        now = now or time.time()
        body = {"sub": user, "cnf": {"jkt": jkt}, "exp": int(now + self.ACCESS_TTL)}
        p = b64u(json.dumps(body).encode())
        at = p + "." + b64u(hmac.new(self.mac, p.encode(), hashlib.sha256).digest())
        rt = b64u(os.urandom(32))
        fam = family or b64u(os.urandom(8))
        self.refresh[rt] = {"user": user, "jkt": jkt, "family": fam, "used": False}
        return at, rt

    def verify(self, method, url, at, proof, now=None) -> tuple[int, str]:
        now = now or time.time()
        try:
            p, tag = at.split(".")
            ok_mac = hmac.compare_digest(ub64(tag), hmac.new(self.mac, p.encode(), hashlib.sha256).digest())
            claims = json.loads(ub64(p))
            h, b, sig = proof.split(".")
            hdr, body = json.loads(ub64(h)), json.loads(ub64(b))
            x, y = int.from_bytes(ub64(hdr["jwk"]["x"]), "big"), int.from_bytes(ub64(hdr["jwk"]["y"]), "big")
            pub = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
            raw = ub64(sig)
            pub.verify(encode_dss_signature(int.from_bytes(raw[:32], "big"), int.from_bytes(raw[32:], "big")),
                       f"{h}.{b}".encode(), ec.ECDSA(hashes.SHA256()))
        except (InvalidSignature, ValueError, KeyError):
            return 401, "bad signature/format"
        # every check is evaluated before deciding, so failures take the same path
        jkt, _ = jwk_thumb(pub)
        checks = {
            "token_mac": ok_mac,
            "token_exp": claims["exp"] > now,
            "key_binding": hmac.compare_digest(jkt, claims["cnf"]["jkt"]),
            "htm": body["htm"] == method,
            "htu": body["htu"] == url,
            "iat_window": abs(now - body["iat"]) <= self.SKEW,
            "ath": hmac.compare_digest(body["ath"], b64u(hashlib.sha256(at.encode()).digest())),
            "jti_fresh": body["jti"] not in self.seen_jti,
        }
        self.seen_jti = {k: v for k, v in self.seen_jti.items() if v > now - self.JTI_TTL}
        if all(checks.values()):
            self.seen_jti[body["jti"]] = now
            return 200, "ok"
        return 401, ",".join(k for k, v in checks.items() if not v)

    def rotate(self, rt, jkt):
        rec = self.refresh.get(rt)
        if rec is None:
            return None, "unknown"
        if rec["used"]:                                      # reuse => revoke entire family
            for v in self.refresh.values():
                if v["family"] == rec["family"]:
                    v["used"] = True
            return None, "reuse-detected: family revoked"
        if rec["jkt"] != jkt:
            return None, "key mismatch"
        rec["used"] = True
        return self.issue(rec["user"], jkt, family=rec["family"]), "rotated"


def e2e_session_key():
    """Client-to-client content key: X25519 agreement -> HKDF over the transcript (hybrid ML-KEM planned)."""
    a, b = x25519.X25519PrivateKey.generate(), x25519.X25519PrivateKey.generate()
    pa = a.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    pb = b.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    tr = hashlib.sha256(pa + pb).digest()
    ka = hkdf(a.exchange(b.public_key()) + tr, b"vcloak-content")
    kb = hkdf(b.exchange(a.public_key()) + tr, b"vcloak-content")
    return ka == kb, ka


def session_tests() -> list[tuple[str, str, str]]:
    srv = SessionServer()
    dev = ec.generate_private_key(ec.SECP256R1())
    atk = ec.generate_private_key(ec.SECP256R1())
    jkt, _ = jwk_thumb(dev.public_key())
    at, rt = srv.issue("userA", jkt)
    U = "https://vcloak.local/api/conversations/read"
    rows = []

    def run(name, expect, code_reason):
        code, why = code_reason
        rows.append((name, f"{expect}", f"{code} ({why})" if code != 200 else "200"))

    run("Valid token + fresh DPoP proof", 200, srv.verify("POST", U, at, make_dpop(dev, "POST", U, at)))
    fixed = make_dpop(dev, "POST", U, at, jti="replay-1")
    srv.verify("POST", U, at, fixed)
    run("Replayed proof (same jti)", 401, srv.verify("POST", U, at, fixed))
    run("Stolen token, attacker's own key", 401, srv.verify("POST", U, at, make_dpop(atk, "POST", U, at)))
    run("Proof for different URL (htu)", 401, srv.verify("POST", U, at, make_dpop(dev, "POST", U + "x", at)))
    run("Proof for different method (htm)", 401, srv.verify("POST", U, at, make_dpop(dev, "GET", U, at)))
    run("Stale proof (iat -5 min)", 401, srv.verify("POST", U, at, make_dpop(dev, "POST", U, at, iat=time.time() - 300)))
    exp_at, _ = srv.issue("userA", jkt, now=time.time() - 3600)
    run("Expired access token", 401, srv.verify("POST", U, exp_at, make_dpop(dev, "POST", U, exp_at)))
    tampered = at[:-2] + ("AA" if at[-2:] != "AA" else "BB")
    run("Tampered access token", 401, srv.verify("POST", U, tampered, make_dpop(dev, "POST", U, tampered)))
    (at2, rt2), why = srv.rotate(rt, jkt)
    rows.append(("Refresh-token rotation", "rotated", why))
    _, why = srv.rotate(rt, jkt)
    rows.append(("Old refresh token reused", "family revoked", why))
    _, why = srv.rotate(rt2, jkt)
    rows.append(("Rotated token after reuse detected", "family revoked", why))
    same, _ = e2e_session_key()
    rows.append(("X25519+HKDF content key agreement", "keys equal", "keys equal" if same else "MISMATCH"))
    return rows


# --------------------------------------------------------------------------------------
# 5. Experiments
# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--seed", type=int, default=20260915)
    ap.add_argument("--tex-only", action="store_true", help="regenerate LaTeX from results/results.json")
    ap.add_argument("--e1-only", action="store_true", help="recompute only the order-recovery attack")
    args = ap.parse_args()
    if args.tex_only:
        write_tex(json.loads((OUT / "results.json").read_text()))
        return
    if args.e1_only:                      # recompute E1 with the same traffic parameters, keep other results
        prev = json.loads((OUT / "results.json").read_text())
        rng = np.random.default_rng(args.seed)
        n_conv, dur, rate, slots, n_buckets = (200, 900, 0.05, 64, 64)
        k_content = {c: os.urandom(32) for c in range(n_conv)}
        keys = Keys()
        msgs = simulate_traffic(rng, n_conv, dur, rate, k_content)
        conv_of = {m.arrival: m.conv for m in msgs}
        att = {"conventional": order_recovery_attack(build_database(keys, msgs, "conventional", 0, slots, n_buckets, rng), conv_of),
               "epoch_200ms": order_recovery_attack(build_database(keys, msgs, "epoch", 0, slots, n_buckets, rng), conv_of)}
        for w in [1, 10, 60, 300]:
            att[f"window_{w}s"] = order_recovery_attack(build_database(keys, msgs, "window", w, slots, n_buckets, rng), conv_of)
        prev["E1_attack"] = att
        (OUT / "results.json").write_text(json.dumps(prev, indent=2, default=str))
        write_tex(prev)
        print(json.dumps(att, indent=1))
        return
    rng = np.random.default_rng(args.seed)
    Q = args.quick
    R: dict = {"seed": args.seed, "quick": Q}

    # ---- E0 + E1: traffic, DB construction, attack, read-back correctness -------------
    n_conv, dur, rate, slots, n_buckets = (40, 120, 0.05, 64, 16) if Q else (200, 900, 0.05, 64, 64)
    k_content = {c: os.urandom(32) for c in range(n_conv)}
    keys = Keys()
    msgs = simulate_traffic(rng, n_conv, dur, rate, k_content)
    R["traffic"] = {"conversations": n_conv, "duration_s": dur, "messages": len(msgs), "slots_per_epoch": slots,
                    "epochs": int(dur / EPOCH_S), "max_real_per_epoch": 0, "buckets": n_buckets}
    per_epoch = {}
    for m in msgs:
        per_epoch[int(m.t // EPOCH_S)] = per_epoch.get(int(m.t // EPOCH_S), 0) + 1
    R["traffic"]["max_real_per_epoch"] = max(per_epoch.values())
    R["traffic"]["mean_real_per_epoch"] = len(msgs) / R["traffic"]["epochs"]

    attack = {}
    t0 = time.perf_counter()
    rows_conv = build_database(keys, msgs, "conventional", 0, slots, n_buckets, rng)
    conv_of = {m.arrival: m.conv for m in msgs}
    attack["conventional"] = order_recovery_attack(rows_conv, conv_of)
    rows_ep = build_database(keys, msgs, "epoch", 0, slots, n_buckets, rng)
    attack["epoch_200ms"] = order_recovery_attack(rows_ep, conv_of)
    windows = [1, 10, 60, 300] if not Q else [10, 60]
    for w in windows:
        rows_w = build_database(keys, msgs, "window", w, slots, n_buckets, rng)
        attack[f"window_{w}s"] = order_recovery_attack(rows_w, conv_of)
    R["E1_attack"] = attack
    R["E1_time_s"] = time.perf_counter() - t0

    # read-back correctness on the refined (60 s window) layout
    rows_w = build_database(keys, msgs, "window", 60, slots, n_buckets, rng)
    occ: dict = {}
    for r in rows_w:
        occ[(r.bucket, r.round_visible)] = occ.get((r.bucket, r.round_visible), 0) + 1
    cand_k = 1 << (max(occ.values()) - 1).bit_length()          # public K: next pow2 over max occupancy
    R["E0_candidate_K"] = {"K": cand_k, "max_occupancy": max(occ.values()), "mean_occupancy": float(np.mean(list(occ.values())))}
    print("E1 done", flush=True)
    trials, ok = 0, 0
    convs = rng.choice(n_conv, size=min(n_conv, 60 if not Q else 15), replace=False)
    for c in convs:
        truth = sorted([m for m in msgs if m.conv == c], key=lambda m: m.seq)
        rounds = sorted({int(m.t // 60) for m in truth})
        got = []
        for rnd in rounds:
            got += [client_decrypt(k_content[c], p) for p in read_conversation(keys, rows_w, int(c), rnd, cand_k, n_buckets, rng)]
        trials += 1
        ok += int(got == [client_decrypt(k_content[c], m.payload) for m in truth])
    R["E0_restoration"] = {"conversations_checked": trials, "exact_order": ok}
    print("E0 done", flush=True)

    # ---- E2: permutation uniformity + Kendall tau band -------------------------------
    n_small, reps = 64, (2000 if Q else 20000)
    counts = np.zeros((n_small, n_small), dtype=np.int64)
    base = os.urandom(32)
    si = np.arange(n_small, dtype=np.uint64)
    for r in range(reps):
        hi, lo = chacha_tags(base, r, n_small)
        _, (perm,) = bitonic_sort([hi, lo, si], [si])
        counts[perm.astype(np.int64), np.arange(n_small)] += 1      # input slot -> output position
    exp = reps / n_small
    dof = (n_small - 1) ** 2
    corr = (n_small - 1) / n_small          # permutation-count tables: E[X^2] = n(n-1), rescale to chi2((n-1)^2)

    def chi_stat(cnt):
        return float(corr * ((cnt - exp) ** 2 / exp).sum())

    chi2 = chi_stat(counts)
    p_chi = float(stats.chi2.sf(chi2, dof))
    tvd = float(0.5 * np.abs(counts / reps - 1 / n_small).sum(axis=1).mean())
    ideal = np.zeros_like(counts)
    for r in range(reps):                    # calibration: numpy's ideal permutation sampler, same test
        ideal[rng.permutation(n_small), np.arange(n_small)] += 1
    chi2_ideal = chi_stat(ideal)
    R["E2_uniformity"] = {"n": n_small, "epochs": reps, "chi2": chi2, "dof": dof, "p_value": p_chi,
                          "chi2_ideal_sampler": chi2_ideal, "p_ideal_sampler": float(stats.chi2.sf(chi2_ideal, dof)),
                          "mean_tvd": tvd, "tvd_of_ideal_sampler": float(0.5 * np.abs(ideal / reps - 1 / n_small).sum(axis=1).mean())}

    n_big, ep_big = (1 << 12, 100) if Q else (1 << 16, 1000)
    sib = np.arange(n_big, dtype=np.uint64)
    taus = []
    for e in range(ep_big):
        hi, lo = chacha_tags(base, 10**6 + e, n_big)
        _, (perm,) = bitonic_sort([hi, lo, sib], [sib])
        taus.append(stats.kendalltau(np.arange(n_big), perm).statistic)
    taus = np.array(taus)
    sigma = float(np.sqrt(2 * (2 * n_big + 5) / (9 * n_big * (n_big - 1))))
    R["E2_tau_band"] = {"n": n_big, "epochs": ep_big, "sigma_theory": sigma, "band_3sigma": 3 * sigma,
                        "mean_tau": float(taus.mean()), "std_tau": float(taus.std(ddof=1)),
                        "max_abs_tau": float(np.abs(taus).max()), "frac_in_band": float((np.abs(taus) < 3 * sigma).mean())}
    cnt, edges = np.histogram(taus / sigma, bins=24, range=(-4, 4))
    np.savetxt(OUT / "tau_hist.dat", np.column_stack([(edges[:-1] + edges[1:]) / 2, cnt]),
               header="z count", comments="", fmt=["%.4f", "%d"])

    print("E2 done", flush=True)
    # ---- E3: access-trace invariance --------------------------------------------------
    n3 = 1024
    inputs = {
        "all-identical": np.zeros(n3, dtype=np.uint64),
        "sorted": np.arange(n3, dtype=np.uint64),
        "reverse-sorted": np.arange(n3, dtype=np.uint64)[::-1].copy(),
        "random": rng.integers(0, 2**63, n3, dtype=np.uint64),
        "two-value skew": (rng.random(n3) < 0.95).astype(np.uint64),
    }
    trace_rows = []
    for name, v in inputs.items():
        tr = []
        bitonic_sort([v, np.arange(n3, dtype=np.uint64)], trace=tr)
        trace_rows.append((name, hashlib.sha256(b"".join(tr)).hexdigest()[:12], merge_sort_trace(v.tolist()).hex()[:12], len(tr)))
    R["E3_trace"] = {"n": n3, "rows": trace_rows,
                     "bitonic_distinct_traces": len({r[1] for r in trace_rows}),
                     "mergesort_distinct_traces": len({r[2] for r in trace_rows})}

    # ---- E4: CPU reference throughput ------------------------------------------------
    thr = []
    for lg in ([10, 12, 14] if Q else [10, 12, 14, 16, 18, 20]):
        n = 1 << lg
        s = np.arange(n, dtype=np.uint64)
        hi, lo = chacha_tags(base, 7, n)
        bitonic_schedule(n)
        times = []
        for _ in range(3 if lg >= 18 else 7):
            t = time.perf_counter()
            bitonic_sort([hi, lo, s], [s])
            times.append(time.perf_counter() - t)
        med = float(np.median(times))
        thr.append({"log2n": lg, "rounds": lg * (lg + 1) // 2, "median_ms": med * 1e3, "keys_per_s": n / med})
    R["E4_cpu_throughput"] = thr

    # AES-GCM block cost (client side, per padded block)
    k = os.urandom(32)
    t = time.perf_counter()
    for _ in range(20000):
        client_encrypt(k, b"hello")
    R["E4_aesgcm_us_per_block"] = (time.perf_counter() - t) / 20000 * 1e6

    # ---- E5: session security ---------------------------------------------------------
    R["E5_session"] = session_tests()

    # ---- analytic tables ---------------------------------------------------------------
    R["analytic_bitonic"] = [{"log2n": k_, "rounds": k_ * (k_ + 1) // 2, "cmp_exch": (1 << k_) // 2 * k_ * (k_ + 1) // 2} for k_ in (10, 12, 14, 16, 18, 20)]
    R["analytic_collision"] = {b: float(np.log2((2**16) ** 2 / 2 ** (b + 1))) for b in (64, 96, 128)}

    (OUT / "results.json").write_text(json.dumps(R, indent=2, default=str))
    write_tex(R)
    print(json.dumps({k_: v for k_, v in R.items() if k_ not in ("E3_trace", "E5_session")}, indent=1, default=str)[:4000])


def write_tex(R):
    """Emit LaTeX macros and pgfplots data consumed by the paper (results/ is \\input by main.tex)."""
    f = lambda x, d=3: f"{x:.{d}f}"
    a = R["E1_attack"]
    m = {
        "resMsgs": R["traffic"]["messages"], "resConvs": R["traffic"]["conversations"],
        "resDuration": R["traffic"]["duration_s"], "resMeanPerEpoch": f(R["traffic"]["mean_real_per_epoch"], 2),
        "resTauConvGlobal": f(a["conventional"]["tau_global"]), "resTauConvWithin": f(a["conventional"]["tau_within_round"]),
        "resTauEpochGlobal": f(a["epoch_200ms"]["tau_global"]), "resTauEpochWithin": f(a["epoch_200ms"]["tau_within_round"]),
        "resRestoreOK": R["E0_restoration"]["exact_order"], "resRestoreN": R["E0_restoration"]["conversations_checked"],
        "resChiSq": f(R["E2_uniformity"]["chi2"], 1), "resChiDof": R["E2_uniformity"]["dof"], "resChiP": f(R["E2_uniformity"]["p_value"], 3),
        "resTVD": f(R["E2_uniformity"]["mean_tvd"], 4), "resChiIdeal": f(R["E2_uniformity"]["chi2_ideal_sampler"], 1), "resChiPIdeal": f(R["E2_uniformity"]["p_ideal_sampler"], 3), "resTVDIdeal": f(R["E2_uniformity"]["tvd_of_ideal_sampler"], 4),
        "resUnifEpochs": R["E2_uniformity"]["epochs"],
        "resTauN": R["E2_tau_band"]["n"], "resTauEpochs": R["E2_tau_band"]["epochs"],
        "resTauSigma": f(R["E2_tau_band"]["sigma_theory"], 5), "resTauBand": f(R["E2_tau_band"]["band_3sigma"], 4),
        "resTauMean": f"{R['E2_tau_band']['mean_tau']:.2e}", "resTauStd": f(R["E2_tau_band"]["std_tau"], 5),
        "resTauMaxAbs": f(R["E2_tau_band"]["max_abs_tau"], 4), "resTauInBand": f(100 * R["E2_tau_band"]["frac_in_band"], 1),
        "resAESus": f(R["E4_aesgcm_us_per_block"], 1), "resCandK": R["E0_candidate_K"]["K"], "resMaxOcc": R["E0_candidate_K"]["max_occupancy"], "resMeanOcc": f(R["E0_candidate_K"]["mean_occupancy"], 1), "resBuckets": R["traffic"].get("buckets", 0),
        "resBitonicTraces": R["E3_trace"]["bitonic_distinct_traces"], "resMergeTraces": R["E3_trace"]["mergesort_distinct_traces"],
    }
    for key, mac in [("conventional", "Conv"), ("epoch_200ms", "Epoch"), ("window_10s", "WTen"), ("window_60s", "WSixty"), ("window_300s", "WThreeHundred")]:
        if key in a:
            m[f"resTurn{mac}"] = f(100 * a[key].get("turn_order_accuracy", float("nan")), 1)
            m[f"resSame{mac}"] = f(100 * a[key].get("turns_same_round_frac", float("nan")), 1)
            m[f"resTauG{mac}"] = f(a[key]["tau_global"])
    lines = ["% auto-generated by oracle/vcloak_oracle.py -- do not edit by hand"]
    lines += [f"\\newcommand{{\\{k}}}{{{v}}}" for k, v in m.items()]
    (OUT / "macros.tex").write_text("\n".join(lines) + "\n")

    name = {"conventional": "Conventional (AUTO\\_INCREMENT)", "epoch_200ms": "V-cloak R1 (200\\,ms round visible)"}
    t = []
    for k, v in a.items():
        label = name[k] if k in name else "V-cloak refined, $W=" + k.split("_")[1][:-1] + "$\\,s"
        t.append(f"{label} & {f(v['tau_global'])} & {f(v['tau_within_round'])} & {f(v.get('turn_order_accuracy', float('nan')))} & {('--' if k == 'conventional' else f"{100*v.get('turns_same_round_frac', float('nan')):.1f}\\%")} \\\\")
    (OUT / "attack_table.tex").write_text("\\newcommand{\\attackrows}{%\n" + "\n".join(t) + "\n}\n")

    wins = [(int(k.split("_")[1][:-1]), v) for k, v in a.items() if k.startswith("window")]
    (OUT / "window_ablation.dat").write_text("W tauglobal tauwithin turnacc samefrac\n" + "\n".join(f"{w} {v['tau_global']:.4f} {v['tau_within_round']:.4f} {v.get('turn_order_accuracy', 0):.4f} {v.get('turns_same_round_frac', 0):.4f}" for w, v in wins) + "\n")

    (OUT / "throughput.dat").write_text("log2n rounds ms kps\n" + "\n".join(f"{r['log2n']} {r['rounds']} {r['median_ms']:.3f} {r['keys_per_s']:.1f}" for r in R["E4_cpu_throughput"]) + "\n")
    (OUT / "throughput_table.tex").write_text("\\newcommand{\\throughputrows}{%\n" + "\n".join(f"$2^{{{r['log2n']}}}$ & {r['rounds']} & {r['median_ms']:.2f} & {r['keys_per_s']/1e3:.1f} & \\pending \\\\" for r in R["E4_cpu_throughput"]) + "\n}\n")

    (OUT / "trace_table.tex").write_text("\\newcommand{\\tracerows}{%\n" + "\n".join(f"{n} & \\texttt{{{b}}} & \\texttt{{{ms}}} \\\\" for n, b, ms, _ in R["E3_trace"]["rows"]) + "\n}\n")
    (OUT / "session_table.tex").write_text("\\newcommand{\\sessionrows}{%\n" + "\n".join(f"{n} & {e} & {g.replace('_', chr(92)+'_')} \\\\" for n, e, g in R["E5_session"]) + "\n}\n")


if __name__ == "__main__":
    main()
