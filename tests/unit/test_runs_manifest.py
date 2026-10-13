import importlib.util
import json
import os
from pathlib import Path

from vcloak import runs
from vcloak.gpu.runtime import get_backend

REPO = Path(__file__).resolve().parents[2]
JOB = {"job_id": "20000101-000000_M00", "bundle_sha256": "ab" * 32, "git_sha": "c" * 40, "dirty": False}


def _fake_bundle_root(tmp_path: Path) -> Path:
    """A directory that looks like an unpacked job bundle: no git, but a job.json."""
    (tmp_path / "job.json").write_text(json.dumps(JOB), encoding="utf-8")
    return tmp_path


def test_new_run_validates(tmp_path):
    d = runs.new_run("M00", "dummy", step="S4", owner="test", command="true", seed=3,
                     root=_fake_bundle_root(tmp_path), backend=get_backend("numpy"))
    (d / "out.txt").write_text("x", encoding="utf-8")
    m = runs.finish_run(d, status="OK")
    assert runs.validate_manifest(d) == []
    assert m["outputs"] == ["out.txt"]
    # On the remote runner VCLOAK_RUNNER is colab/kaggle even for a numpy-backend run.
    assert m["env"]["backend"] == "numpy" and m["env"]["session_id"]
    assert m["env"]["runner"] == os.environ.get("VCLOAK_RUNNER", "local")
    assert m["git_sha"] == JOB["git_sha"] and m["gpu_job"]["job_id"] == JOB["job_id"]
    assert m["telemetry_start"]["available"] in (True, False)


def test_quick_run_is_tagged(tmp_path):
    d = runs.new_run("M00", "dummy", step="S4", owner="test", command="true", quick=True,
                     root=_fake_bundle_root(tmp_path), backend=get_backend("numpy"))
    assert d.name.endswith("_quick")
    runs.finish_run(d, status="OK")
    assert runs.validate_manifest(d) == []


def test_validation_catches_problems(tmp_path):
    d = runs.new_run("M00", "dummy", step="S4", owner="test", command="true",
                     root=_fake_bundle_root(tmp_path), backend=get_backend("numpy"))
    runs.finish_run(d, status="OK")
    m = runs.read_manifest(d)

    def errs(**change):
        bad = json.loads(json.dumps(m))
        for k, v in change.items():
            if k.startswith("env_"):
                bad["env"][k[4:]] = v
            else:
                bad[k] = v
        runs.write_manifest(d, bad)
        return " ".join(runs.validate_manifest(d))

    assert "status" in errs(status="GREAT")
    assert "listed output missing" in errs(outputs=["nope.csv"])
    assert "git_sha unknown" in errs(git_sha="unknown")
    assert "does not match directory" in errs(run_id="20000101-000000_M00_other")
    # a run claiming the GPU backend must identify the GPU
    assert "backend cupy but env.gpu missing" in errs(env_backend="cupy")
    assert "manifest.json missing" in runs.validate_manifest(tmp_path)[0]


def test_probe_runs_on_numpy_and_measures_nothing(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location("probe_gpu", REPO / "bench" / "probe_gpu.py")
    probe = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(probe)
    monkeypatch.setenv("VCLOAK_BACKEND", "numpy")
    monkeypatch.chdir(_fake_bundle_root(tmp_path))
    assert probe.main(["--seed", "7", "--quick", "--out", str(tmp_path / "runs")]) == 0
    (d,) = (tmp_path / "runs").iterdir()
    assert runs.validate_manifest(d) == []
    assert runs.read_manifest(d)["status"] == "NOT_MEASURED"
    summary = json.loads((d / "summary.json").read_text(encoding="utf-8"))
    assert summary["vector_add"]["correct"] is True
    assert {m["id"]: m["value"] for m in summary["metrics"]} == dict.fromkeys(
        ("ENV-PEAK-BW", "ENV-D2D-BW", "ENV-MAX-LOG2N", "ENV-VRAM-FREE"), "NOT_MEASURED")


def test_runner_vcpu_comes_from_the_manifest_or_the_ingested_bundle_never_a_guess(tmp_path):
    import zipfile

    man = {"env": {"session_id": "S1"}, "gpu_job": {"job_id": "J1"}}
    assert runs.runner_vcpu(man, tmp_path) is None
    done = tmp_path / "gpujobs" / "done"
    done.mkdir(parents=True)
    with zipfile.ZipFile(done / "results_J1.zip", "w") as z:
        z.writestr("result.json", json.dumps({"env": {"session_id": "S1", "cpu_count": "4"}}))
    assert runs.runner_vcpu(man, tmp_path) == 4
    assert runs.runner_vcpu({"env": {"session_id": "S2"}, "gpu_job": {"job_id": "J1"}}, tmp_path) is None
    assert runs.runner_vcpu({"env": {"session_id": "S1", "cpu_count": 2}, "gpu_job": {"job_id": "J1"}}, tmp_path) == 2
