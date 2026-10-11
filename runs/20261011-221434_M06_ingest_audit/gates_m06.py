"""M06 ingest gates, computed from the ingested files of GPU job 20261011-215111_M06."""
import csv, json, re, statistics, sys
from pathlib import Path

job = Path(sys.argv[1]); run = Path(sys.argv[2]); out = Path(sys.argv[3])
res = json.loads((job / "result.json").read_text())
jobj = json.loads((job / "job.json").read_text())
logs = {c["name"]: (job / c["log"]).read_text(encoding="utf-8", errors="replace") for c in res["commands"]}
man = json.loads((run / "manifest.json").read_text())
summ = json.loads((run / "summary.json").read_text())
rows = list(csv.DictReader((run / "raw.csv").open(encoding="utf-8")))
lines, ok_all = [], True
STAGES = ("h2d", "tags", "sort", "compact", "d2h", "seal", "bucket", "open", "host")

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
gate("all commands exit 0", all(c["exit_code"] == 0 for c in res["commands"]) and res["overall_exit"] == 0,
     f"{len(res['commands'])} commands")
gate("git sha matches pack", res["packed_from_git_sha"] == jobj["git_sha"], jobj["git_sha"][:7])
gate("bundle sha matches pack", res["bundle_sha256"] == jobj["bundle_sha256"])
gate("backend cupy", e["backend"] == "cupy")
for lg in ("pytest_engine", "pytest_engine_vs_oracle", "pytest_regression", "pytest_max_log2n"):
    gate("no fail/error/skip: " + lg, bad(lg) == 0, summary(lg))

for t in ("test_write_epoch_equals_the_oracle", "test_write_epoch_equals_the_oracle_for_any_epoch",
          "test_write_epoch_equals_the_oracle_for_any_public_parameters",
          "test_write_epoch_equals_the_oracle_on_adversarial_batches", "test_reshuffle_equals_the_oracle",
          "test_read_window_equals_the_oracle_for_50_windows", "test_read_window_pads_to_k_with_misses",
          "test_bucket_of_equals_the_reference", "test_write_reshuffle_read_round_trip",
          "test_the_stored_order_does_not_depend_on_slots"):
    n = passed("pytest_engine_vs_oracle", t); gate("A1 cupy: " + t.replace("_", " "), n > 0, f"{n} cupy cases passed")
gate("A1 smoke bench: 0 oracle mismatches", summ["mismatches"] == 0 and all(c["mismatches"] == 0 for c in summ["configs"]),
     f"{len(summ['configs'])} configs")
for t in ("test_load_master_zeroizes_the_host_buffer_and_derives_the_m02_subkeys",
          "test_zeroize_clears_the_device_buffer_and_empties_the_store",
          "test_reload_replaces_the_keys_and_clears_the_old_buffer"):
    n = passed("pytest_engine", t); gate("A2 cupy: " + t.replace("_", " "), n == 1, f"{n} cupy case passed")
gate("A2 host buffer zeroized when derivation fails",
     "::test_the_host_buffer_is_zeroized_even_when_derivation_fails PASSED" in logs["pytest_engine"])
for t in ("test_a3_the_key_store_has_no_device_to_host_path",
          "test_a3_the_engine_downloads_only_through_d2h_and_never_a_key_buffer"):
    gate("A3 on the runner: " + t.replace("_", " "), f"::{t} PASSED" in logs["pytest_engine"])
for t in ("test_last_timings_of_every_call", "test_an_empty_epoch_runs_the_permutation_and_returns_no_row"):
    n = passed("pytest_engine", t); gate("A4 cupy: " + t.replace("_", " "), n == 1, f"{n} cupy case passed")
gate("A4 timer is CUDA events", summ["timer"] == "cupy.cuda.Event", str(summ["timer"]))
worst = max(abs(sum(float(r[s + "_ms"]) for s in STAGES) - float(r["total_ms"])) / float(r["total_ms"]) for r in rows)
gate("A4 raw.csv: stages add up to total in every timed call", worst < 1e-3,
     f"{len(rows)} calls, worst relative gap {worst:.2e}")
gate("A4 raw.csv: every stage a call uses is positive, the others are 0",
     all((float(r[s + "_ms"]) > 0) == (s not in (("open",) if r["kind"] == "write_epoch"
                                                 else ("tags", "compact", "seal", "bucket")))
         for r in rows for s in STAGES))

ps = sorted(set(re.findall(r"::test_gpu_engine_equals_the_simulator_engine\[([^\]]+)\] PASSED",
                           logs["pytest_engine_vs_oracle"])))
sizes = sorted({int(p.split("-")[0]) for p in ps}); seeds = sorted({p.split("-")[1] for p in ps})
gate("G5 gpu engine equals simulator engine", len(ps) == 9 and len(sizes) >= 3 and len(seeds) >= 3,
     f"sizes {sizes} x seeds {seeds}")
ml = re.findall(r"(tests/\S+::test_max_log2n\[[^\]]+\]) PASSED", logs["pytest_max_log2n"])
gate("G5 max log2n", len(ml) == 3, f"{len(ml)} passed: {summary('pytest_max_log2n')}")
gate("regression M03-M05", bad("pytest_regression") == 0, summary("pytest_regression"))
gate("check oblivious on runner", "0 finding(s) - PASS" in logs["check_oblivious"], logs["check_oblivious"].strip())

gate("G2b smoke manifest: backend cupy with a gpu_job block of this job",
     man["env"]["backend"] == "cupy" and man["gpu_job"]["job_id"] == res["job_id"]
     and man["gpu_job"]["bundle_sha256"] == res["bundle_sha256"] and man["quick"] is True)
lim = summ["cv_limit"]
for c in summ["configs"]:
    a = c["attempts"][-1]
    last = [float(r["total_ms"]) for r in rows if r["kind"] == c["kind"] and int(r["size"]) == c["size"]
            and int(r["attempt"]) == a["attempt"]]
    med = statistics.median(last)
    idx = next(m["value"] for m in summ["metrics"] if m["id"] == c["metric"])
    gate("metric equals the median of raw.csv: " + c["metric"], len(last) == a["runs"] and abs(med - idx) < 5e-5,
         f"{idx} ms, {len(last)} runs, attempt {a['attempt']} of {len(c['attempts'])}")
    st = a["stage_median_ms"]; top = max(st, key=st.get)
    lines.append(f"    {'NOTE' if a['cv'] <= lim else 'WARN'} {c['metric']}: CV {a['cv']:.3f} (limit {lim}), clock "
                 f"{a['clock']['status']} {a['clock']['before_mhz']}->{a['clock']['after_mhz']} MHz, largest stage "
                 f"{top} {st[top]:.3f} ms = {100 * st[top] / a['median_ms']:.0f}% of the median total")
lines.append(f"    NOTE smoke run status in its manifest: {man['status']} ({man['notes']})")
lines.append(f"    NOTE telemetry rows: {summ['telemetry_samples']}; runs per config: {man['params']['runs']} (quick)")
lines.append(f"gates: {'PASS' if ok_all else 'FAIL'}")
out.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("\n".join(lines)); sys.exit(0 if ok_all else 1)
