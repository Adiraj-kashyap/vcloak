#!/usr/bin/env python3
"""M08 S3 - list every branch in the machine code (SASS) of the kernels, with where its predicate comes from.

    python scripts/sass_check.py --compile [--arch sm_75] [--out runs]   # on the runner: nvcc, cuobjdump, analyse
    python scripts/sass_check.py --listing sass_bitonic.txt [...]        # anywhere: analyse saved listings again

--compile builds kernels/bitonic.cu, aead_open.cu and chacha_tags.cu with
`nvcc -cubin -arch=sm_<cc> -std=c++17`, disassembles each with `cuobjdump -sass`, saves the raw listings
(sass_<file>.txt) in a new run dir and analyses them. The planted-leak kernel of the dudect harness is
compiled as well, as a positive control: its data-dependent branch must be classified DATA. When CuPy
exposes its nvrtc compiler, the kernels are also built the way the service builds them and listed as
sass_nvrtc_<file>.txt, because nvcc and nvrtc need not emit the same code.

The analysis is static, per function and flow-insensitive, like scripts/check_oblivious.py. For each
control-flow instruction it follows the predicate back through every instruction of the function
that writes one of the registers involved, down to the leaves:
    param        a kernel parameter or launch constant, c[0x0][...]   (public)
    id           S2R of SR_TID / SR_CTAID / ...                      (public)
    imm          an immediate                                           (public)
    const        a load from a constant bank, LDC                       (public)
    global, shared, local   a load from memory: LDG / LDS / LDL         (data, possibly secret)
    unknown      a register that nothing in the function writes
A branch is `public` when every leaf is public, `DATA` when a memory load is among them, else
`unknown`. Because all writers of a register are followed (not only the one that reaches the branch),
a register that is reused for data elsewhere makes a public branch look like DATA: every DATA or
unknown line has to be explained by reading the listing, never waved through (ai/modules/M08 A3).
Unconditional jumps and the final EXIT/RET are listed as `unconditional`.

Exit status: 0 when the listings were produced and analysed (whatever they say), 1 when the tools
failed or the positive control was not classified DATA.
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

KERNEL_DIR = ROOT / "kernels"
KERNEL_FILES = ("bitonic.cu", "aead_open.cu", "chacha_tags.cu")
CONTROL_FILE = ROOT / "bench" / "planted" / "planted_leak.cu"
NM = "NOT_MEASURED"

INSTR_RE = re.compile(r"/\*([0-9a-fA-F]{4,8})\*/\s+(.*?)\s*;")
FUNC_RES = (re.compile(r"^\s*\.text\.([A-Za-z_$][\w$.]*):"), re.compile(r"^\s*Function\s*:\s*([A-Za-z_$][\w$.]*)"))
LABEL_RE = re.compile(r"^\s*(\.L_[\w.]+):")
GUARD_RE = re.compile(r"^@(!?P\d+)\s+")
REG_RE = re.compile(r"\b(R\d+|P\d+|UR\d+|UP\d+)\b")
PARAM_RE = re.compile(r"c\[0x[0-9a-fA-F]+\]\s*\[[^\]]*\]")
SR_RE = re.compile(r"\bSR_[\w.]+")
IMM_RE = re.compile(r"(?<![\w\]])-?0x[0-9a-fA-F]+\b|(?<![\w.\]])-?\d+(?:\.\d+)?\b")

JUMPS = {"BRA", "BRX", "JMP", "JMX", "CALL", "CAL", "JCAL", "BRK", "BREAK", "CONT", "KILL"}
ENDS = {"EXIT", "RET"}
SYNC = {"SSY", "SYNC", "BSSY", "BSYNC", "PBK", "PCNT", "WARPSYNC", "PRET"}
LOADS = {"LDG": "global", "LD": "global", "ATOM": "global", "ATOMG": "global", "LDS": "shared", "ATOMS": "shared",
         "LDL": "local", "LDC": "const", "ULDC": "const"}
NO_DEST = {"STG", "ST", "STS", "STL", "NOP", "MEMBAR", "ERRBAR"} | JUMPS | ENDS | SYNC
PUBLIC = {"param", "id", "imm", "const"}
DATA_LEAVES = {"global", "shared", "local"}
ZERO_REGS = {"RZ", "URZ", "PT", "UPT"}


@dataclass
class Instr:
    addr: int
    text: str
    guard: str | None
    opcode: str
    base: str
    dests: list[str]
    srcs: list[str]
    leaves: set[str]


@dataclass
class Function:
    name: str
    instrs: list[Instr] = field(default_factory=list)
    labels: dict[str, int] = field(default_factory=dict)


def _operands(rest: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in rest:
        if ch in "[(":
            depth += 1
        elif ch in "])":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_instr(addr: int, text: str) -> Instr:
    body, guard = text, None
    m = GUARD_RE.match(body)
    if m:
        guard, body = m.group(1), body[m.end():]
    opcode, _, rest = body.partition(" ")
    base = opcode.split(".")[0]
    ops = _operands(rest)
    dests: list[str] = []
    src_ops = ops
    if base not in NO_DEST and ops:
        # the first operand is written; compare instructions write a second predicate as well
        n_dest = 2 if len(ops) > 1 and re.fullmatch(r"U?P\d+|U?PT", ops[1]) and re.fullmatch(r"U?P\d+|U?PT", ops[0]) \
            else 1
        dests = [r for op in ops[:n_dest] for r in REG_RE.findall(op) if "[" not in op]
        src_ops = ops[n_dest:]
        if "[" in ops[0]:  # a memory operand first: nothing is written to a register
            src_ops = ops
    srcs = [r for op in src_ops for r in REG_RE.findall(op)]
    leaves: set[str] = set()
    joined = ", ".join(src_ops)
    if base in LOADS:
        leaves.add(LOADS[base])
        if LOADS[base] != "const":
            srcs = []  # the address is public by rule 2; what matters is that the value comes from memory
    if PARAM_RE.search(joined):
        leaves.add("param")
    if base == "S2R" or SR_RE.search(joined):
        leaves.add("id")
    if IMM_RE.search(PARAM_RE.sub("", joined)):
        leaves.add("imm")
    return Instr(addr, text, guard, opcode, base, dests, srcs, leaves)


def parse_listing(text: str) -> list[Function]:
    funcs: list[Function] = []
    cur: Function | None = None
    for line in text.splitlines():
        name = next((m.group(1) for rx in FUNC_RES if (m := rx.match(line))), None)
        if name is not None:
            if cur is None or cur.name != name or cur.instrs:
                cur = Function(name)
                funcs.append(cur)
            continue
        if cur is None:
            continue
        m = LABEL_RE.match(line)
        if m:
            cur.labels[m.group(1)] = len(cur.instrs)
            continue
        m = INSTR_RE.search(line)
        if m:
            cur.instrs.append(parse_instr(int(m.group(1), 16), m.group(2).strip()))
    return [f for f in funcs if f.instrs]


def trace(fn: Function, reg: str) -> set[str]:
    """Leaves that can reach `reg` through any instruction of the function that writes it."""
    writers: dict[str, list[Instr]] = {}
    for ins in fn.instrs:
        for d in ins.dests:
            writers.setdefault(d, []).append(ins)
    seen: set[str] = set()
    leaves: set[str] = set()
    todo = [reg.lstrip("!")]
    while todo:
        r = todo.pop()
        if r in seen or r in ZERO_REGS:
            continue
        seen.add(r)
        if r not in writers:
            leaves.add("unknown")
            continue
        for ins in writers[r]:
            leaves |= ins.leaves
            todo += ins.srcs
            if ins.guard:
                todo.append(ins.guard)
    return leaves


def classify(leaves: set[str]) -> str:
    if leaves & DATA_LEAVES:
        return "DATA"
    if "unknown" in leaves or not leaves:
        return "unknown"
    return "public"


def analyse_function(fn: Function) -> dict[str, Any]:
    rows = []
    for ins in fn.instrs:
        if ins.base not in JUMPS | ENDS | SYNC:
            continue
        preds = ([ins.guard] if ins.guard else []) + [p for p in ins.srcs if re.fullmatch(r"U?P\d+", p)]
        regs = [r for r in ins.srcs if re.fullmatch(r"U?R\d+", r)] if ins.base in ("BRX", "JMX") else []
        if ins.base in SYNC:
            kind, leaves = "sync", set()
        elif not preds and not regs:
            kind, leaves = "unconditional", set()
        else:
            leaves = set().union(*(trace(fn, x) for x in preds + regs))
            kind = classify(leaves)
        rows.append({"addr": f"{ins.addr:04x}", "instr": ins.text, "class": kind, "predicate": preds + regs,
                     "leaves": sorted(leaves)})
    counted = [r for r in rows if r["class"] in ("public", "DATA", "unknown")
               or (r["class"] == "unconditional" and r["instr"].split(" ")[0].split(".")[0] in JUMPS)]
    return {"function": fn.name, "instructions": len(fn.instrs), "branches": len(counted),
            "conditional": sum(r["class"] in ("public", "DATA", "unknown") for r in rows),
            "public": sum(r["class"] == "public" for r in rows), "data": sum(r["class"] == "DATA" for r in rows),
            "unknown": sum(r["class"] == "unknown" for r in rows), "sync": sum(r["class"] == "sync" for r in rows),
            "rows": rows}


def analyse_listing(text: str) -> list[dict[str, Any]]:
    return [analyse_function(f) for f in parse_listing(text)]


def render(source: str, funcs: list[dict[str, Any]]) -> str:
    out = [f"# SASS branches of {source}", "# class: public | DATA | unknown | unconditional | sync "
           "(see scripts/sass_check.py; DATA and unknown must be explained by reading the listing)", ""]
    if not funcs:
        out.append("no function found: the listing is empty or its format is not the one this parser reads")
    for f in funcs:
        out.append(f"{f['function']}: {f['instructions']} instructions, {f['branches']} branches "
                   f"({f['conditional']} conditional: {f['public']} public, {f['data']} DATA, {f['unknown']} unknown), "
                   f"{f['sync']} divergence-control")
        for r in f["rows"]:
            src = f"  <- {', '.join(r['predicate'])}: {', '.join(r['leaves']) or '-'}" if r["predicate"] else ""
            out.append(f"  {r['addr']}  {r['class']:<13} {r['instr']}{src}")
        out.append("")
    return "\n".join(out) + "\n"


def metric_id(function: str) -> str:
    return "T-SASS-BRA-" + function.upper().replace("_", "-")


def metrics_of(per_file: dict[str, list[dict[str, Any]]], reason: str | None) -> list[dict[str, Any]]:
    out = []
    if reason:
        for name in KERNEL_FILES:
            out.append({"id": "T-SASS-BRA-" + Path(name).stem.upper().replace("_", "-"), "value": NM,
                        "unit": "branches", "stat": "count", "note": reason})
        return out
    for name, funcs in per_file.items():
        for f in funcs:
            out.append({"id": metric_id(f["function"]), "value": f["branches"], "unit": "branches", "stat": "count",
                        "note": f"{name}: {f['conditional']} conditional ({f['public']} public, {f['data']} DATA, "
                                f"{f['unknown']} unknown by the static trace), {f['sync']} divergence-control, "
                                f"{f['instructions']} instructions"})
    return out


# ── --compile: nvcc and cuobjdump on the runner ──────────────────────────────


def _run(cmd: list[str], timeout: int = 600) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired) as e:
        return 127, f"{type(e).__name__}: {e}"


def detect_arch() -> tuple[str | None, str]:
    try:
        import cupy as cp  # type: ignore[import-not-found]

        props = cp.cuda.runtime.getDeviceProperties(cp.cuda.Device().id)
        return f"sm_{props['major']}{props['minor']}", "cupy device properties"
    except Exception as e:  # noqa: BLE001
        why = f"cupy: {type(e).__name__}"
    rc, out = _run(["nvidia-smi", "--query-gpu=compute_cap", "--format=csv,noheader"], timeout=60)
    if rc == 0 and out.strip():
        return "sm_" + out.strip().splitlines()[0].replace(".", ""), "nvidia-smi"
    return None, why + "; nvidia-smi gave no compute capability"


def disassemble(cubin: Path) -> tuple[str | None, str]:
    for tool in (["cuobjdump", "-sass", str(cubin)], ["nvdisasm", str(cubin)]):
        if shutil.which(tool[0]) is None:
            continue
        rc, out = _run(tool)
        if rc == 0 and INSTR_RE.search(out):
            return out, " ".join(tool[:-1])
    return None, "neither cuobjdump nor nvdisasm produced a listing"


def compile_nvcc(src: Path, arch: str, work: Path) -> tuple[str | None, str, str]:
    cubin = work / (src.stem + ".cubin")
    cmd = ["nvcc", "-cubin", f"-arch={arch}", "-std=c++17", "-I", str(KERNEL_DIR), "-o", str(cubin), str(src)]
    rc, out = _run(cmd)
    if rc != 0 or not cubin.exists():
        return None, " ".join(cmd), f"nvcc exit {rc}: {out[-800:]}"
    listing, how = disassemble(cubin)
    return listing, " ".join(cmd), how


def compile_nvrtc(src: Path, work: Path) -> tuple[str | None, str]:
    """The cubin that CuPy's nvrtc path builds for the service, when this CuPy exposes it."""
    try:
        from cupy.cuda import compiler  # type: ignore[import-not-found]

        blob, _ = compiler.compile_using_nvrtc(src.read_text(encoding="utf-8"),
                                               options=("-std=c++17", "-I" + str(KERNEL_DIR)))
        if not isinstance(blob, bytes) or not blob.startswith(b"\x7fELF"):
            return None, "cupy's nvrtc path returned PTX, not a cubin"
        cubin = work / (src.stem + "_nvrtc.cubin")
        cubin.write_bytes(blob)
        return disassemble(cubin)
    except Exception as e:  # noqa: BLE001 - an internal CuPy interface: its absence is recorded, not fatal
        return None, f"{type(e).__name__}: {e}"[:300]


def main_compile(a: argparse.Namespace, command: str) -> int:
    from vcloak import runs
    from vcloak.gpu.runtime import get_backend

    backend = get_backend()
    run_dir = runs.new_run("M08", "sass", step="S3", owner="Aditya", command=command, root=Path.cwd(),
                           runs_dir=a.out, backend=backend, params={"files": list(KERNEL_FILES), "arch": a.arch})
    arch, arch_from = (a.arch, "--arch") if a.arch else detect_arch()
    per_file: dict[str, list[dict[str, Any]]] = {}
    log: dict[str, Any] = {"arch": arch, "arch_from": arch_from, "files": {}, "nvrtc": {}}
    reason = None
    if shutil.which("nvcc") is None:
        reason = "nvcc is not installed on this machine"
    elif arch is None:
        reason = f"the compute capability is unknown ({arch_from})"
    control: dict[str, Any] = {"file": CONTROL_FILE.relative_to(ROOT).as_posix(), "detected": None}
    if reason is None:
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            for name in KERNEL_FILES:
                stem = Path(name).stem
                listing, cmd, how = compile_nvcc(KERNEL_DIR / name, arch, work)  # type: ignore[arg-type]
                log["files"][name] = {"command": cmd, "disassembler": how, "ok": listing is not None}
                if listing is None:
                    continue
                (run_dir / f"sass_{stem}.txt").write_text(listing, encoding="utf-8")
                per_file[name] = analyse_listing(listing)
                (run_dir / f"sass_{stem}_branches.txt").write_text(render(name, per_file[name]), encoding="utf-8")
                rt, rt_how = compile_nvrtc(KERNEL_DIR / name, work)
                log["nvrtc"][name] = {"ok": rt is not None, "how": rt_how}
                if rt is not None:
                    (run_dir / f"sass_nvrtc_{stem}.txt").write_text(rt, encoding="utf-8")
                    funcs = analyse_listing(rt)
                    (run_dir / f"sass_nvrtc_{stem}_branches.txt").write_text(render(name + " (nvrtc)", funcs),
                                                                             encoding="utf-8")
                    log["nvrtc"][name]["functions"] = [{k: v for k, v in f.items() if k != "rows"} for f in funcs]
            listing, cmd, how = compile_nvcc(CONTROL_FILE, arch, work)  # type: ignore[arg-type]
            control.update({"command": cmd, "disassembler": how})
            if listing is not None:
                (run_dir / "sass_control_planted_leak.txt").write_text(listing, encoding="utf-8")
                funcs = analyse_listing(listing)
                (run_dir / "sass_control_planted_leak_branches.txt").write_text(render(control["file"], funcs),
                                                                               encoding="utf-8")
                control["detected"] = any(f["data"] > 0 for f in funcs)
        missing = [n for n in KERNEL_FILES if n not in per_file]
        empty = [n for n, funcs in per_file.items() if not funcs]
        if missing and not per_file:
            reason = "no listing was produced: " + "; ".join(f"{n}: {log['files'][n]['disassembler']}" for n in missing)
    else:
        missing, empty = list(KERNEL_FILES), []

    metrics = metrics_of(per_file, reason)
    (run_dir / "summary.json").write_text(json.dumps({
        "metrics": metrics, "reason": reason, "log": log, "control": control,
        "analysis": "static, per function, flow-insensitive; DATA and unknown need a reading of the listing",
        "functions": {n: [{k: v for k, v in f.items() if k != "rows"} for f in funcs]
                      for n, funcs in per_file.items()},
        "to_explain": {n: [{"function": f["function"], **r} for f in funcs for r in f["rows"]
                           if r["class"] in ("DATA", "unknown")] for n, funcs in per_file.items()}},
        indent=2) + "\n", encoding="utf-8")
    notes = []
    if reason:
        status = NM
        notes.append(reason)
    elif missing or empty or control["detected"] is not True:
        status = "FAIL"
        if missing:
            notes.append("no listing for: " + ", ".join(missing))
        if empty:
            notes.append("listing not understood by the parser (raw listing saved): " + ", ".join(empty))
        if control["detected"] is not True:
            notes.append("the planted data-dependent branch was not classified DATA: the checker has no power here")
    else:
        status = "OK"
    flagged = sum(f["data"] + f["unknown"] for funcs in per_file.values() for f in funcs)
    if flagged:
        notes.append(f"{flagged} branch(es) classified DATA or unknown by the static trace: explain each from "
                     "the listing")
    runs.finish_run(run_dir, status=status, notes="; ".join(notes))
    print(f"run dir     {run_dir}")
    print(f"arch        {arch} ({arch_from})")
    for n, funcs in per_file.items():
        for f in funcs:
            print(f"  {n:<16} {f['function']:<24} branches {f['branches']:>3}  conditional {f['conditional']:>3}  "
                  f"DATA {f['data']}  unknown {f['unknown']}  sync {f['sync']}")
    print(f"control     planted leak classified DATA: {control['detected']}")
    print(f"status      {status}   {'; '.join(notes)}")
    return 1 if status == "FAIL" else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("--compile", action="store_true", help="build and disassemble the kernels (needs nvcc)")
    ap.add_argument("--listing", nargs="*", default=[], help="saved cuobjdump -sass listings to analyse")
    ap.add_argument("--arch", default="", help="e.g. sm_75; default: the device's compute capability")
    ap.add_argument("--out", default="runs")
    a = ap.parse_args(argv)
    if a.compile:
        command = "python scripts/sass_check.py " + " ".join(shlex.quote(x) for x in (argv if argv is not None
                                                                                   else sys.argv[1:]))
        return main_compile(a, command)
    if not a.listing:
        ap.error("give --compile or --listing FILE ...")
    for path in a.listing:
        sys.stdout.write(render(path, analyse_listing(Path(path).read_text(encoding="utf-8", errors="replace"))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
