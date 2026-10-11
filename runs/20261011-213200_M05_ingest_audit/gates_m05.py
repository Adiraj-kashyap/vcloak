"""M05 ingest gates, computed from the ingested files of GPU job 20261011-193547_M05."""
import json, re, subprocess, sys
from pathlib import Path

job = Path(sys.argv[1]); out = Path(sys.argv[2])
res = json.loads((job / "result.json").read_text())
jobj = json.loads((job / "job.json").read_text())
logs = {c["name"]: (job / c["log"]).read_text(encoding="utf-8", errors="replace") for c in res["commands"]}
lines, ok_all = [], True

# Labels use spaces: check_secrets reads a long underscore-joined name as a key-like run.
def gate(name, ok, detail=""):
    global ok_all
    ok_all &= bool(ok)
    lines.append(f"    {'PASS' if ok else 'FAIL'} {name}" + (f" - {detail}" if detail else ""))

def passed(log, test, param_re=r"[^\]]*cupy[^\]]*"):
    return len(re.findall(rf"::{test}\[{param_re}\] PASSED", logs[log]))

def summary(log):
    return [l for l in logs[log].splitlines() if re.search(r"\d+ passed", l)][-1].strip(" =")

def bad(log):
    return len(re.findall(r"\b(FAILED|ERROR|SKIPPED|XFAIL|XPASS)\b", logs[log]))

e = res["env"]
lines.append(f"job {res['job_id']} session {e['session_id']} runner {e['runner']} gpu {e['gpu']} driver {e['driver']} "
             f"cupy {e['cupy']} cuda_runtime {e['cuda_runtime']} nvcc {e['nvcc']}")
gate("all_commands_exit_0", all(c["exit_code"] == 0 for c in res["commands"]) and res["overall_exit"] == 0,
     f"{len(res['commands'])} commands")
gate("git_sha_matches_pack", res["packed_from_git_sha"] == jobj["git_sha"], jobj["git_sha"][:7])
gate("bundle_sha_matches_pack", res["bundle_sha256"] == jobj["bundle_sha256"])
gate("backend_cupy", e["backend"] == "cupy")
for lg in ("pytest_aead", "pytest_restore", "pytest_regression", "pytest_max_log2n"):
    gate("no fail/error/skip: " + lg, bad(lg) == 0, summary(lg))
gate("A1 RFC 8439 2.5.2 Poly1305 on the GPU", passed("pytest_aead", "test_rfc8439_2_5_2_poly1305", "cupy") == 1)
gate("A1 RFC 8439 2.8.2 AEAD on the GPU", passed("pytest_aead", "test_rfc8439_2_8_2_aead", "cupy") == 1)
for t in ("test_seal_equals_reference", "test_open_equals_reference_on_valid_tampered_and_dummy_rows",
          "test_every_single_bit_flip_is_a_miss", "test_poly1305_equals_reference_at_every_alignment",
          "test_aead_tag_equals_reference", "test_seal_adversarial_columns",
          "test_open_under_the_wrong_key_misses_everything", "test_poly1305_final_reduction_edges"):
    n = passed("pytest_aead", t); gate("A2 cupy: " + t.replace("_", " "), n > 0, f"{n} cupy cases passed")
for t in ("test_read_window_equals_oracle", "test_restore_sort_equals_lexicographic_order",
          "test_compact_equals_oracle", "test_write_path_order_equals_oracle"):
    n = passed("pytest_restore", t); gate("A4 cupy: " + t.replace("_", " "), n > 0, f"{n} cupy cases passed")
for lg in ("pytest_aead", "pytest_restore"):
    ps = sorted(set(re.findall(r"::test_gpu_equals_simulator\[([^\]]+)\] PASSED", logs[lg])))
    sizes = sorted({int(p.split("-")[0]) for p in ps}); seeds = sorted({p.split("-")[1] for p in ps})
    gate("G5 gpu equals simulator: " + lg, len(ps) == 9 and len(sizes) >= 3 and len(seeds) >= 3,
         f"sizes {sizes} x seeds {seeds}")
ml = re.findall(r"(tests/gpu/\S+::test_max_log2n\[[^\]]+\]) PASSED", logs["pytest_max_log2n"])
gate("G5_max_log2n", len(ml) == 6, f"{len(ml)} passed: {summary('pytest_max_log2n')}")
gate("regression_chacha_bitonic", bad("pytest_regression") == 0, summary("pytest_regression"))
gate("check_oblivious_on_runner", "0 finding(s) - PASS" in logs["check_oblivious"], logs["check_oblivious"].strip())
lines.append(f"    NOTE cupy-parametrised PASSED lines: aead {len(re.findall(r'cupy[^\]]*\] PASSED', logs['pytest_aead']))}, "
             f"restore {len(re.findall(r'cupy[^\]]*\] PASSED', logs['pytest_restore']))}")
lines.append("    NOTE no timing, telemetry or metric in this job (tests only); nothing is added to METRICS_INDEX")
lines.append(f"gates: {'PASS' if ok_all else 'FAIL'}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines)); sys.exit(0 if ok_all else 1)
