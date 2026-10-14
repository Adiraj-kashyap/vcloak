"""ISSUE-49: how many rows the schedule of each cell can put into one bucket-window, for the rates considered.

    python runs/20261014-062714_M15_s2_checks/bucket_bound.py > runs/20261014-062714_M15_s2_checks/bucket_bound.txt

Arithmetic on the seed (15), the default layout (64 buckets, W = 60 s, CAND_K 128) and the public development key:
`bench/run_e2e_cells.bucket_bound`, an upper bound over every alignment of the wall-clock window. The last block
counts, for the 200-user schedule at 0.2, the alignments (0.25 s steps) in which a bucket-window is above CAND_K.
Not a measurement, no metric.
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "bench"))

import run_e2e_cells as cells  # noqa: E402

from vcloak.bench import e2e  # noqa: E402
from vcloak.crypto import chacha_ref  # noqa: E402
from vcloak.service.app import dev_master  # noqa: E402
from vcloak.service.models import conv_id_of  # noqa: E402

TOTAL_S = 140.0  # warm-up 20 s + 120 s
print("rate  buckets  users  conversations  fullest_bucket_convs  max_rows_one_window  cand_k  buckets_over  convs_in_them")
for rate, buckets in ((0.2, 64), (0.15, 64), (0.1, 64), (0.2, 128)):
    for users in cells.USERS:
        a = cells.build_parser().parse_args(["--rate", str(rate), "--buckets", str(buckets)])
        b = cells.bucket_bound(users, a, TOTAL_S)
        print(f"{rate:<5} {buckets:<8} {users:<6} {b['conversations']:<14} {b['conversations_in_fullest_bucket']:<21} "
              f"{b['max_sends_in_one_window_span']:<20} {b['cand_k']:<7} {b['buckets_that_can_exceed_cand_k']:<13} "
              f"{b['conversations_in_those_buckets']}")

seed, users, window_s, cand_k = 15, 200, 60.0, 128
tokens = e2e.conv_tokens(np.random.default_rng([seed, 0xE2E]), users // 2)
ids = np.array([conv_id_of(t) for t in tokens], dtype=np.uint64)
bucket = chacha_ref.bucket_prf(chacha_ref.derive_subkeys(bytes(dev_master()))[2], ids, 64)
for rate in (0.2, 0.15):
    sends = e2e.schedule(users, rate, TOTAL_S, seed)
    t = np.array([s.t for s in sends])
    b = np.array([int(bucket[s.conv]) for s in sends])
    phis = np.arange(0.0, window_s, 0.25)
    over, worst = 0, 0
    for phi in phis:
        key = np.floor((t + phi) / window_s).astype(np.int64) * 64 + b
        m = int(np.unique(key, return_counts=True)[1].max())
        worst, over = max(worst, m), over + (m > cand_k)
    print(f"users {users} rate {rate}: {len(sends)} sends; alignments with a bucket-window above {cand_k}: "
          f"{over} of {len(phis)}; fullest bucket-window over all alignments: {worst}")
