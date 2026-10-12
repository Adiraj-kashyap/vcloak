#!/usr/bin/env python3
"""The job bridge between this GPU-less laptop and the free Colab/Kaggle runner (ai/GPU_RUNNER.md §4).

    python scripts/gpujob.py pack M07 [--quick] [--params k=v ...]   -> gpujobs/out/<job>/job.zip
    python scripts/gpujob.py verify gpujobs/inbox/results_<job>.zip  -> check only
    python scripts/gpujob.py ingest [--file <zip>]                   -> verify, copy runs/, index metrics

A job's commands come from `bench/jobs/<Mxx>.json`. `{quick}` in a command becomes `--quick` or nothing.

Integrity model. `bundle_sha256` is a content hash of every bundled file except job.json (a file
cannot contain its own hash). A result is accepted only if its job id, bundle hash and git sha equal
what was packed, the packed commit is an ancestor of HEAD, and the bundled code has not changed since.
This stops stale or mismatched evidence; it is not a signature and cannot stop deliberate forgery.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import re
import shutil
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
BUNDLE_DIRS = ("src", "kernels", "tests", "bench", "scripts")
BUNDLE_FILES = ("requirements-gpu.txt", "pyproject.toml")
ENTRY = "colab/gpu_entry.py"
# The G4 allow-list is not bundled and not part of the staleness check: pack itself adds the new
# bundle digest to it, which would otherwise change the bundle it has just hashed (ISSUE-5).
SECRETS_ALLOWLIST = "scripts/secrets_allowlist.json"
BUNDLE_PATHSPEC = (*BUNDLE_DIRS, *BUNDLE_FILES, ENTRY, f":(exclude){SECRETS_ALLOWLIST}")
SKIP_PARTS = {"__pycache__", ".pytest_cache", ".ruff_cache", ".git", ".venv", "runs", "node_modules"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".cubin", ".zip"}
MAX_BUNDLE_MB = 20
RESULT_TOP = {"result.json", "job.json", "runs", "logs"}
METRIC_COLS = 11


class JobError(Exception):
    """A pack or ingest precondition failed."""


def _git(root: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    return p.returncode, p.stdout.strip()


def _bundle_members(root: Path) -> list[tuple[str, Path]]:
    """(archive name, source path) for everything in a bundle except job.json, in sorted order."""
    members: list[tuple[str, Path]] = []
    for d in BUNDLE_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for p in base.rglob("*"):
            rel = p.relative_to(root)
            if p.is_file() and not (set(rel.parts) & SKIP_PARTS) and p.suffix not in SKIP_SUFFIXES \
                    and rel.as_posix() != SECRETS_ALLOWLIST \
                    and not any(part.endswith(".egg-info") for part in rel.parts):
                members.append((rel.as_posix(), p))
    for f in BUNDLE_FILES:
        if (root / f).is_file():
            members.append((f, root / f))
    if not (root / ENTRY).is_file():
        raise JobError(f"{ENTRY} is missing")
    members.append(("gpu_entry.py", root / ENTRY))
    return sorted(members)


def content_sha256(members: list[tuple[str, bytes]]) -> str:
    h = hashlib.sha256()
    for name, data in sorted(members):
        h.update(name.encode() + b"\0" + hashlib.sha256(data).digest())
    return h.hexdigest()


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ── pack ─────────────────────────────────────────────────────────────────────


def pack(module: str, *, quick: bool = False, params: dict[str, str] | None = None, root: Path = ROOT,
         allow_dirty: bool = False) -> Path:
    spec_path = root / "bench" / "jobs" / f"{module}.json"
    if not spec_path.exists():
        raise JobError(f"no job spec for {module}: create {spec_path.relative_to(root).as_posix()}")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))

    rc, sha = _git(root, "rev-parse", "HEAD")
    if rc != 0:
        raise JobError("not a git repository, or no commit yet: a job must be packed from a commit")
    _, dirty = _git(root, "status", "--porcelain", "--", *BUNDLE_PATHSPEC)
    if dirty and not allow_dirty:
        raise JobError("uncommitted changes in bundled paths - commit first, so the results can be tied "
                       "to a commit:\n" + dirty)

    commands = []
    for c in spec["commands"]:
        c = dict(c)
        c["cmd"] = " ".join(c["cmd"].replace("{quick}", "--quick" if quick else "").split())
        commands.append(c)

    files = [(name, p.read_bytes()) for name, p in _bundle_members(root)]
    job_id = _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + f"_{module}" + ("_quick" if quick else "")
    job = {
        "job_id": job_id, "module": module, "step": spec.get("step"), "title": spec.get("title", ""),
        "quick": quick, "params": params or {}, "seed": spec.get("seed", 0),
        "git_sha": sha, "dirty": bool(dirty),
        "packed_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "bundle_sha256": content_sha256(files), "n_files": len(files),
        "commands": commands,
    }
    out_dir = root / "gpujobs" / "out" / job_id
    out_dir.mkdir(parents=True, exist_ok=False)
    zip_path = out_dir / "job.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("job.json", json.dumps(job, indent=2))
        for name, data in files:
            z.writestr(name, data)
    size_mb = zip_path.stat().st_size / 1e6
    if size_mb > MAX_BUNDLE_MB:
        shutil.rmtree(out_dir)
        raise JobError(f"bundle is {size_mb:.1f} MB (> {MAX_BUNDLE_MB} MB): something large got packed")
    (out_dir / "job.json").write_text(json.dumps(job, indent=2) + "\n", encoding="utf-8")
    allowed = _allow_bundle_digest(root, job)
    print(f"packed  {zip_path.relative_to(root).as_posix()}  ({size_mb:.2f} MB, {len(files)} files)")
    print(f"job id          {job_id}")
    print(f"git sha         {sha}" + ("  (DIRTY)" if dirty else ""))
    print(f"bundle sha256   {job['bundle_sha256']}   (content hash, recorded in job.json)")
    print(f"zip sha256      {_file_sha256(zip_path)}")
    if allowed:
        print(f"allow-listed    the bundle sha256 in {SECRETS_ALLOWLIST} (G4); commit that file")
    return zip_path


def _allow_bundle_digest(root: Path, job: dict) -> bool:
    """Add the bundle digest that job.json now holds to the secrets scanner's allow-list, in the format
    `check_secrets.py --allow` writes (the SHA-256 of the hex run, never the run itself)."""
    path = root / SECRETS_ALLOWLIST
    if not path.is_file():
        return False
    doc = json.loads(path.read_text(encoding="utf-8"))
    token = hashlib.sha256(job["bundle_sha256"].encode()).hexdigest()
    rows = [e for e in doc.get("tokens", []) if e["sha256"] != token]
    rows.append({"sha256": token, "reason": f"bundle_sha256 of GPU job {job['job_id']} (a content hash, not a key)"})
    doc["tokens"] = sorted(rows, key=lambda e: (e.get("path", ""), e["sha256"]))
    doc.setdefault("files", [])
    path.write_text(json.dumps(doc, indent=1, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return True


# ── verify / ingest ──────────────────────────────────────────────────────────


def verify(zip_path: Path, *, root: Path = ROOT, allow_stale: bool = False) -> tuple[list[str], dict]:
    """Return (problems, result). An empty problem list means the bundle may be ingested."""
    if not zip_path.is_file():
        return [f"{zip_path}: no such file"], {}
    try:
        with zipfile.ZipFile(zip_path) as z:
            bad = z.testzip()
            if bad is not None:
                return [f"corrupt archive: CRC check failed on {bad}"], {}
            names = z.namelist()
            for n in names:
                pp = PurePosixPath(n.replace("\\", "/"))
                if pp.is_absolute() or ".." in pp.parts or ":" in n or pp.parts[0] not in RESULT_TOP:
                    return [f"unexpected or unsafe path in archive: {n}"], {}
            if "result.json" not in names or "job.json" not in names:
                return ["result.json or job.json missing: this is not a results bundle "
                        "(did you drop job.zip instead of results_<job>.zip?)"], {}
            result = json.loads(z.read("result.json"))
            job_in = json.loads(z.read("job.json"))
            run_manifests = {n: z.read(n) for n in names
                             if n.startswith("runs/") and n.count("/") == 2 and n.endswith("/manifest.json")}
    except (zipfile.BadZipFile, zlib.error, ValueError, OSError, KeyError, EOFError) as e:
        return [f"corrupt archive: {type(e).__name__}: {e}"], {}

    errs: list[str] = []
    job_id = str(result.get("job_id"))
    local_path = root / "gpujobs" / "out" / job_id / "job.json"
    if "/" in job_id or "\\" in job_id or not local_path.is_file():
        return [f"unknown job id {job_id!r}: no gpujobs/out/<job>/job.json was packed here"], result
    local = json.loads(local_path.read_text(encoding="utf-8"))
    if job_in != local:
        errs.append("job.json inside the results differs from the job that was packed")
    if result.get("bundle_sha256") != local["bundle_sha256"]:
        errs.append(f"bundle sha mismatch: result {result.get('bundle_sha256')} != packed {local['bundle_sha256']}")
    if result.get("packed_from_git_sha") != local["git_sha"]:
        errs.append(f"git sha mismatch: result {result.get('packed_from_git_sha')} != packed {local['git_sha']}")
    if errs:
        return errs, result

    sha = local["git_sha"]
    if _git(root, "cat-file", "-e", f"{sha}^{{commit}}")[0] != 0:
        errs.append(f"packed commit {sha[:12]} does not exist in this repository")
    elif _git(root, "merge-base", "--is-ancestor", sha, "HEAD")[0] != 0:
        errs.append(f"packed commit {sha[:12]} is not an ancestor of HEAD")
    elif not allow_stale:
        p = subprocess.run(["git", "diff", "--quiet", sha, "HEAD", "--", *BUNDLE_PATHSPEC], cwd=root)
        if p.returncode != 0:
            errs.append(f"stale evidence: bundled code changed since {sha[:12]}; re-pack and re-run the job")

    for name, raw in run_manifests.items():
        run_id = name.split("/")[1]
        try:
            m = json.loads(raw)
        except ValueError:
            errs.append(f"{name}: not valid JSON")
            continue
        if (m.get("gpu_job") or {}).get("job_id") != job_id:
            errs.append(f"{name}: run does not belong to job {job_id}")
        if m.get("run_id") != run_id:
            errs.append(f"{name}: run_id does not match its directory")
        if (root / "runs" / run_id).exists():
            errs.append(f"runs/{run_id} already exists locally (already ingested?)")
    return errs, result


def _summarise(result: dict) -> list[str]:
    env = result.get("env", {})
    lines = [f"job {result.get('job_id')}  module {result.get('module')}  quick {result.get('quick')}",
             f"runner {env.get('runner')}  gpu {env.get('gpu')}  driver {env.get('driver')}  "
             f"cupy {env.get('cupy')}  session {env.get('session_id')}"]
    for c in result.get("commands", []):
        flag = "ok" if c["exit_code"] == 0 else ("FAILED (optional)" if c.get("optional") else "FAILED")
        lines.append(f"  [{c['n']}] {c['name']}: exit {c['exit_code']} {flag}")
    lines.append(f"overall exit {result.get('overall_exit')}")
    return lines


def _cell(text: str) -> str:
    """A table cell cannot hold a pipe: `|t|` becomes `abs(t)`, any other pipe a slash."""
    return re.sub(r"\|([^|\s]+)\|", r"abs(\1)", text).replace("|", "/")


def _index_metrics(root: Path, run_dir: Path) -> int:
    """Append this run's summary.json metrics to state/METRICS_INDEX.md. Values are copied, never retyped."""
    summary = run_dir / "summary.json"
    index = root / "state" / "METRICS_INDEX.md"
    if not summary.exists() or not index.exists():
        return 0
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    rel = f"runs/{run_dir.name}"
    text = index.read_text(encoding="utf-8")
    rows = []
    for x in json.loads(summary.read_text(encoding="utf-8")).get("metrics", []):
        if f"| {x['id']} |" in text and f"| {rel} |" in text:
            continue
        cells = [_cell(c) for c in (
            x["id"], str(x["value"]), x.get("unit", "-"), x.get("stat", "-"), m["module"], rel, m["command"],
            m["run_id"][:8], "yes" if m["quick"] else "no", m["env"]["backend"], m["env"]["runner"])]
        assert len(cells) == METRIC_COLS
        rows.append("| " + " | ".join(cells) + " |")
    if rows:
        index.write_text(text.rstrip("\n") + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return len(rows)


def ingest(zip_path: Path | None = None, *, root: Path = ROOT, allow_stale: bool = False) -> dict:
    inbox = root / "gpujobs" / "inbox"
    if zip_path is None:
        found = sorted(inbox.glob("*.zip"), key=lambda p: p.stat().st_mtime)
        if not found:
            raise JobError(f"nothing to ingest: no .zip in {inbox.relative_to(root).as_posix()}/")
        zip_path = found[0]
    errs, result = verify(zip_path, root=root, allow_stale=allow_stale)
    if errs:
        raise JobError(f"REJECTED {zip_path.name}:\n  - " + "\n  - ".join(errs))

    job_id = result["job_id"]
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(root, [n for n in z.namelist() if n.startswith("runs/")])
        job_logs = root / "gpujobs" / "out" / job_id
        (job_logs / "result.json").write_bytes(z.read("result.json"))
        z.extractall(job_logs, [n for n in z.namelist() if n.startswith("logs/")])
        run_ids = sorted({n.split("/")[1] for n in z.namelist() if n.startswith("runs/") and n.count("/") >= 2})

    n_metrics = sum(_index_metrics(root, root / "runs" / r) for r in run_ids)
    done = root / "gpujobs" / "done"
    done.mkdir(parents=True, exist_ok=True)
    shutil.move(str(zip_path), str(done / zip_path.name))

    lines = _summarise(result)
    log = root / "state" / "SESSION_LOG.md"
    if log.exists():
        env = result.get("env", {})
        entry = (f"\n- GPU-JOB {job_id} ingested {_dt.datetime.now():%Y-%m-%d %H:%M}: "
                 f"runner {env.get('runner')}, gpu {env.get('gpu')}, session {env.get('session_id')}, "
                 f"overall exit {result.get('overall_exit')}, runs {', '.join(run_ids) or 'none'}, "
                 f"{n_metrics} metrics indexed.\n")
        with log.open("a", encoding="utf-8") as f:
            f.write(entry)
    print("\n".join(lines))
    print(f"ingested {len(run_ids)} run dir(s): {', '.join(run_ids) or 'none'}")
    print(f"indexed {n_metrics} metric(s); bundle moved to gpujobs/done/{zip_path.name}")
    if result.get("overall_exit") != 0:
        print(f"!! the job reported a failed required command - read gpujobs/out/{job_id}/logs/ "
              "before using any number")
    return result


# ── cli ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("pack")
    p.add_argument("module")
    p.add_argument("--quick", action="store_true")
    p.add_argument("--params", nargs="*", default=[], metavar="k=v")
    p.add_argument("--allow-dirty", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("zip")
    v.add_argument("--allow-stale", action="store_true")
    i = sub.add_parser("ingest")
    i.add_argument("--file", default=None)
    i.add_argument("--allow-stale", action="store_true")
    a = ap.parse_args(argv)
    try:
        if a.cmd == "pack":
            params = dict(kv.split("=", 1) for kv in a.params)
            pack(a.module, quick=a.quick, params=params, allow_dirty=a.allow_dirty)
        elif a.cmd == "verify":
            errs, result = verify(Path(a.zip), allow_stale=a.allow_stale)
            if errs:
                raise JobError(f"REJECTED {Path(a.zip).name}:\n  - " + "\n  - ".join(errs))
            print("\n".join(_summarise(result)))
            print("verify: OK (not ingested)")
        else:
            ingest(Path(a.file) if a.file else None, allow_stale=a.allow_stale)
    except JobError as e:
        print(f"gpujob: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
