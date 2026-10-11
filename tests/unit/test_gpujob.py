"""pack -> (simulated runner) -> verify -> ingest, in a throwaway git repository under tmp_path.

The "results" here are test fixtures built inside tmp_path. They never touch the real runs/ or
METRICS_INDEX.md, and their GPU is named TEST-FIXTURE so they cannot be mistaken for evidence.
"""
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

import check_metrics
import gpujob

REPO = Path(__file__).resolve().parents[2]
# in the repo the entry point is colab/gpu_entry.py; inside a job bundle it sits at the root
ENTRY = next(p for p in (REPO / "colab/gpu_entry.py", REPO / "gpu_entry.py") if p.exists())
pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not available")


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=test", "-c", "user.email=test@example.invalid",
                    "-c", "core.autocrlf=false", *args], cwd=root, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for d in ("src/pkg", "bench/jobs", "colab", "state", "gpujobs/inbox", "gpujobs/out", "tests"):
        (root / d).mkdir(parents=True)
    (root / "src/pkg/a.py").write_text("X = 1\n", encoding="utf-8")
    (root / "tests/test_a.py").write_text("def test_a():\n    assert True\n", encoding="utf-8")
    (root / "requirements-gpu.txt").write_text("cupy-cuda12x\n", encoding="utf-8")
    shutil.copy(ENTRY, root / "colab/gpu_entry.py")
    (root / "bench/jobs/M99.json").write_text(json.dumps({
        "step": "S1", "seed": 1,
        "commands": [{"name": "bench", "cmd": "python bench/run.py {quick} --out runs"}]}), encoding="utf-8")
    (root / "state/METRICS_INDEX.md").write_text(
        "| " + " | ".join(check_metrics.COLUMNS) + " |\n|" + "---|" * 11 + "\n", encoding="utf-8")
    (root / "state/SESSION_LOG.md").write_text("# log\n", encoding="utf-8")
    _git(root, "init", "-q", "-b", "main")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "init")
    return root


def _fake_results(root: Path, job_zip: Path, **override) -> Path:
    """Stand in for the runner: build results_<job>.zip the way colab/gpu_entry.py lays it out."""
    with zipfile.ZipFile(job_zip) as z:
        job = json.loads(z.read("job.json"))
    job_id = job["job_id"]
    run_id = f"{job_id[:15]}_M99_fixture"
    env = {"os": "linux", "python": "3", "backend": "cupy", "runner": "colab", "session_id": "s1",
           "gpu": "TEST-FIXTURE", "cc": "0.0", "cuda": "0", "cupy": "0", "driver": "0"}
    manifest = {"run_id": run_id, "module": "M99", "step": "S1", "owner": "test", "git_sha": job["git_sha"],
                "dirty": False, "command": "python bench/run.py --out runs", "seed": 1, "quick": False,
                "params": {}, "env": env, "telemetry_start": {}, "telemetry_end": {},
                "outputs": ["summary.json"], "status": "OK", "notes": "test fixture",
                "gpu_job": {"job_id": job_id, "bundle_sha256": job["bundle_sha256"],
                            "packed_from_git_sha": job["git_sha"]}}
    result = {"job_id": job_id, "module": "M99", "step": "S1", "quick": False,
              "packed_from_git_sha": job["git_sha"], "bundle_sha256": job["bundle_sha256"], "env": env,
              "commands": [{"n": 1, "name": "bench", "cmd": "x", "exit_code": 0, "log": "logs/01_bench.txt",
                            "optional": False}], "overall_exit": 0}
    result.update(override)
    out = root / "gpujobs" / "inbox" / f"results_{job_id}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("result.json", json.dumps(result))
        z.writestr("job.json", json.dumps(job))
        z.writestr(f"runs/{run_id}/manifest.json", json.dumps(manifest))
        z.writestr(f"runs/{run_id}/summary.json",
                   json.dumps({"metrics": [{"id": "K-FIXTURE-MS", "value": 1.25, "unit": "ms", "stat": "median"}]}))
        z.writestr("logs/01_bench.txt", "fixture log\n")
    return out


def test_pack_produces_a_runnable_bundle(repo, tmp_path, capsys):
    zip_path = gpujob.pack("M99", quick=True, params={"k": "v"}, root=repo)
    assert "bundle sha256" in capsys.readouterr().out
    job = json.loads((zip_path.parent / "job.json").read_text(encoding="utf-8"))
    assert job["quick"] and job["params"] == {"k": "v"} and job["job_id"].endswith("_M99_quick")
    assert job["commands"][0]["cmd"] == "python bench/run.py --quick --out runs"
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        z.extractall(tmp_path / "unz")
    assert {"job.json", "gpu_entry.py", "requirements-gpu.txt", "src/pkg/a.py", "tests/test_a.py",
            "bench/jobs/M99.json"} <= names
    assert not any(n.startswith(("runs/", ".git/", ".venv/", "gpujobs/", "state/")) for n in names)
    p = subprocess.run([sys.executable, "gpu_entry.py", "--job", "job.json", "--dry-run"],
                       cwd=tmp_path / "unz", capture_output=True, text=True)
    assert p.returncode == 0 and "[1] python bench/run.py --quick --out runs" in p.stdout


def test_pack_refuses_uncommitted_code(repo):
    (repo / "src/pkg/a.py").write_text("X = 2\n", encoding="utf-8")
    with pytest.raises(gpujob.JobError, match="uncommitted changes"):
        gpujob.pack("M99", root=repo)


def test_pack_needs_a_job_spec(repo):
    with pytest.raises(gpujob.JobError, match="no job spec"):
        gpujob.pack("M98", root=repo)


def test_roundtrip_ingest(repo, capsys):
    res = _fake_results(repo, gpujob.pack("M99", root=repo))
    job_id = res.stem[len("results_"):]
    errs, _ = gpujob.verify(res, root=repo)
    assert errs == []
    gpujob.ingest(root=repo)
    out = capsys.readouterr().out
    assert "ingested 1 run dir(s)" in out and "indexed 1 metric(s)" in out
    (run_dir,) = (repo / "runs").iterdir()
    assert (run_dir / "manifest.json").exists()
    assert not res.exists() and (repo / "gpujobs/done" / res.name).exists()
    assert (repo / "gpujobs/out" / job_id / "result.json").exists()
    assert (repo / "gpujobs/out" / job_id / "logs/01_bench.txt").exists()
    index = (repo / "state/METRICS_INDEX.md").read_text(encoding="utf-8")
    assert f"| K-FIXTURE-MS | 1.25 | ms | median | M99 | runs/{run_dir.name} |" in index
    assert index.rstrip().endswith("| no | cupy | colab |")
    assert f"GPU-JOB {job_id} ingested" in (repo / "state/SESSION_LOG.md").read_text(encoding="utf-8")
    # the indexed row satisfies the metrics checker
    assert check_metrics.check(repo / "state/METRICS_INDEX.md", repo) == []
    # the same results cannot be ingested twice
    again = _fake_results(repo, repo / "gpujobs/out" / job_id / "job.zip")
    with pytest.raises(gpujob.JobError, match="already exists locally"):
        gpujob.ingest(root=repo)
    assert again.exists()


def test_corrupted_zip_is_rejected(repo):
    res = _fake_results(repo, gpujob.pack("M99", root=repo))
    with zipfile.ZipFile(res) as z:
        info = z.getinfo("result.json")
    data = bytearray(res.read_bytes())
    at = info.header_offset + 30 + len(info.filename) + info.compress_size // 2
    data[at] ^= 0xFF
    res.write_bytes(bytes(data))
    with pytest.raises(gpujob.JobError, match="(?s)REJECTED.*corrupt archive"):
        gpujob.ingest(root=repo)
    assert res.exists() and not (repo / "runs").exists()


@pytest.mark.parametrize("override, message", [
    ({"bundle_sha256": "0" * 64}, "bundle sha mismatch"),
    ({"packed_from_git_sha": "f" * 40}, "git sha mismatch"),
    ({"job_id": "20000101-000000_M99"}, "unknown job id"),
    ({"job_id": "../../etc"}, "unknown job id"),
])
def test_mismatched_results_are_rejected(repo, override, message):
    res = _fake_results(repo, gpujob.pack("M99", root=repo), **override)
    with pytest.raises(gpujob.JobError, match=message):
        gpujob.ingest(root=repo)
    assert res.exists() and not (repo / "runs").exists()


def test_stale_results_are_rejected(repo):
    res = _fake_results(repo, gpujob.pack("M99", root=repo))
    (repo / "src/pkg/a.py").write_text("X = 2\n", encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "change bundled code after packing")
    errs, _ = gpujob.verify(res, root=repo)
    assert any("stale evidence" in e for e in errs)
    assert gpujob.verify(res, root=repo, allow_stale=True)[0] == []


def test_job_zip_dropped_by_mistake_is_rejected(repo):
    job_zip = gpujob.pack("M99", root=repo)
    errs, _ = gpujob.verify(job_zip, root=repo)
    assert len(errs) == 1 and ("unexpected or unsafe path" in errs[0] or "not a results bundle" in errs[0])


def test_path_traversal_is_rejected(repo):
    res = _fake_results(repo, gpujob.pack("M99", root=repo))
    with zipfile.ZipFile(res, "a") as z:
        z.writestr("runs/../../evil.txt", "x")
    errs, _ = gpujob.verify(res, root=repo)
    assert errs and "unsafe path" in errs[0]


def test_pack_allow_lists_its_bundle_digest_without_going_stale(repo):
    """ISSUE-5: pack records the new digest for G4; that write neither changes the bundle nor makes it stale."""
    import hashlib

    allow = repo / "scripts" / "secrets_allowlist.json"
    allow.parent.mkdir()
    allow.write_text(json.dumps({"files": [], "tokens": []}), encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "add the allow-list")
    job_zip = gpujob.pack("M99", root=repo)
    with zipfile.ZipFile(job_zip) as z:
        job = json.loads(z.read("job.json"))
        assert "scripts/secrets_allowlist.json" not in z.namelist()
    (entry,) = json.loads(allow.read_text(encoding="utf-8"))["tokens"]
    assert entry["sha256"] == hashlib.sha256(job["bundle_sha256"].encode()).hexdigest()
    assert job["job_id"] in entry["reason"] and job["bundle_sha256"] not in allow.read_text(encoding="utf-8")
    _git(repo, "commit", "-q", "-am", "allow-list the bundle digest")
    assert gpujob.verify(_fake_results(repo, job_zip), root=repo)[0] == []
