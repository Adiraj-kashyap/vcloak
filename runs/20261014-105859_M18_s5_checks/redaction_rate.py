"""M18 S5 check: how often the base64 rule of vcloak.service.logsapi misses a random client token, and what it
changes in the real state/ files. A property of the redaction heuristic, not a result of V-cloak (no metric)."""
import base64
import random
import sys

from vcloak.service.logsapi import KINDS, STATE_DIR, redact_line

rng = random.Random(2026)
N = 20000
print("token form | tokens | served unredacted")
for label, nb, enc in (("browser conv_token, 24 bytes base64url", 24, base64.urlsafe_b64encode),
                       ("16 bytes base64url", 16, base64.urlsafe_b64encode),
                       ("32 bytes base64", 32, base64.b64encode),
                       ("hex, 16 bytes", 16, None)):
    miss = 0
    for _ in range(N):
        b = rng.randbytes(nb)
        t = b.hex() if enc is None else enc(b).decode().rstrip("=")
        miss += t in redact_line(f"x {t} y")[0]
    print(f"{label} | {N} | {miss}")
print()
print("state file | lines | lines changed | lines with <b64> | lines with <hex>")
for kind, name in KINDS.items():
    lines = (STATE_DIR / name).read_text(encoding="utf-8", errors="replace").splitlines()
    out = [redact_line(x) for x in lines]
    print(f"{kind} | {len(lines)} | {sum(c for _, c in out)} | {sum('<b64>' in s for s, _ in out)} | "
          f"{sum('<hex>' in s for s, _ in out)}")
sys.exit(0)
