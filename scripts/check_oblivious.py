#!/usr/bin/env python3
"""Audit check G3: no data-dependent branch or address in the CUDA kernels (ai/CONVENTIONS.md §2).

    python scripts/check_oblivious.py [kernels/ | file.cu ...]   # exit 1 if anything is flagged
    python scripts/check_oblivious.py --self-test                # prove that planted leaks are flagged

A static, per-function, flow-insensitive check of kernels/*.cu and *.cuh. Every identifier is put in
one of three classes:

  data     pointer and reference parameters, parameters and variables with a data name (hi, lo, slot,
           pay, key, ks, tag, ...), every parameter of a helper that is not a known public name, and
           anything assigned from an expression that mentions data (also through a helper's
           reference or pointer parameter).
  public   thread/block ids, the public kernel parameters (n, k, j, T, npairs, ...), ALL_CAPS
           constants, and variables assigned only from public expressions (t, i, l, base, loop counters).
  unknown  everything else.

Flagged: `if`/`while`/`for`/`switch` conditions, `?:` and `&&`/`||` that mention a data or unknown
identifier; array subscripts built from anything but public identifiers; `goto`; function-like macros
(they are not analysed - use an inline function).

Limits. This reads source text, not the compiler's output: it cannot see a branch that nvcc
introduces, and it does not check data-dependent instruction latency (division). The SASS and Nsight
checks of M08 cover the generated code. Unconditional writes are a convention it does not verify.
"""
from __future__ import annotations

import argparse
import bisect
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KERNEL_DIR = ROOT / "kernels"
SUFFIXES = (".cu", ".cuh")

DATA_NAME = re.compile(
    r"^(?:[a-z]_)?(?:hi|lo|slot|pay|key|keys|ks|tag|tags|nonce|ct|pt|mac|msg|state|perm|bucket|dummy|secret|data)"
    r"(?:_[a-z0-9]+)*$")
PUBLIC_PARAMS = frozenset({"n", "k", "j", "t", "i", "l", "T", "S", "K", "B", "npairs", "j_start", "base", "nblocks",
                           "counter0", "epoch", "win"})
BUILTINS = frozenset({"threadIdx", "blockIdx", "blockDim", "gridDim"})
NOT_VARIABLES = frozenset("""
    u8 u16 u32 u64 i32 i64 unsigned signed int long short char bool float double void const volatile static
    auto size_t uint8_t uint16_t uint32_t uint64_t int32_t int64_t true false sizeof return if else for while
    do switch case default break continue goto struct typedef inline extern __shared__ __device__ __global__
    __forceinline__ __restrict__ NULL nullptr
""".split())
CONTROL = ("if", "while", "for", "switch")
IDENT = re.compile(r"(?<![\w.])[A-Za-z_]\w*")
ASSIGN = re.compile(r"<<=|>>=|[-+*/%&|^]=|(?<![=!<>])=(?!=)")
TARGET = re.compile(r"([A-Za-z_]\w*)\s*(?:\[.*\])?\s*$", re.S)
FUNC = re.compile(r"\b([A-Za-z_]\w*)\s*\(([^()]*)\)\s*\{")
CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    message: str
    source: str

    def __str__(self) -> str:
        return f"{self.path}:{self.line}: {self.rule}: {self.message}\n    {self.source}"


@dataclass(frozen=True)
class Signature:
    """A function's parameters as (name, is_pointer_or_reference), in order."""

    params: tuple[tuple[str, bool], ...]
    is_kernel: bool


def strip_code(src: str) -> tuple[str, list[tuple[int, str]]]:
    """Blank out comments, literals and preprocessor lines, keeping every newline (so offsets map to
    lines). Returns the code and the function-like macros found, as (offset, text)."""
    out = re.sub(r"//[^\n]*|/\*.*?\*/|\"(?:\\.|[^\"\\\n])*\"|'(?:\\.|[^'\\\n])*'",
                 lambda m: re.sub(r"[^\n]", " ", m.group()), src, flags=re.S)
    macros = []

    def directive(m: re.Match[str]) -> str:
        if re.match(r"[ \t]*#[ \t]*define[ \t]+\w+\(", m.group()):
            macros.append((m.start(), m.group().strip()))
        return re.sub(r"[^\n]", " ", m.group())

    return re.sub(r"^[ \t]*#(?:[^\n\\]|\\\n|\\.)*", directive, out, flags=re.M), macros


def _match(code: str, start: int, open_ch: str, close_ch: str) -> int:
    """Offset of the bracket closing the one at `start`."""
    depth = 0
    for p in range(start, len(code)):
        if code[p] == open_ch:
            depth += 1
        elif code[p] == close_ch:
            depth -= 1
            if depth == 0:
                return p
    raise ValueError(f"unbalanced {open_ch!r} at offset {start}")


def idents(expr: str) -> set[str]:
    """Variable names in an expression: no member names, call names, types, keywords or literals."""
    out = set()
    for m in IDENT.finditer(expr):
        name = m.group()
        if name in NOT_VARIABLES or expr[: m.start()].rstrip().endswith("->"):
            continue
        if expr[m.end():].lstrip().startswith("("):
            continue  # a call or a function-style cast; its arguments are still scanned
        out.add(name)
    return out


def _split_args(text: str) -> list[str]:
    args, depth, cur = [], 0, ""
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth -= 1
        if ch == "," and depth == 0:
            args.append(cur)
            cur = ""
        else:
            cur += ch
    return [a.strip() for a in [*args, cur] if a.strip()]


def functions(code: str) -> list[tuple[str, Signature, int, int]]:
    """(name, signature, body start, body end) for every function defined at the top level."""
    found = []
    pos = prev_end = 0
    while True:
        m = FUNC.search(code, pos)
        if m is None:
            return found
        if m.group(1) in CONTROL:
            pos = m.end()
            continue
        params = []
        for p in _split_args(m.group(2)):
            names = IDENT.findall(p)
            if names and names[-1] not in NOT_VARIABLES:
                params.append((names[-1], "*" in p or "&" in p))
        end = _match(code, m.end() - 1, "{", "}")
        sig = Signature(tuple(params), "__global__" in code[prev_end:m.start()])
        found.append((m.group(1), sig, m.end(), end))
        pos = prev_end = end + 1


def classify(body: str, sig: Signature, sigs: dict[str, Signature]) -> tuple[set[str], set[str]]:
    """(data, public) identifier sets of one function body."""
    data = {name for name, is_ptr in sig.params
            if is_ptr or DATA_NAME.match(name) or (not sig.is_kernel and name not in PUBLIC_PARAMS)}
    roots = {name for name, _ in sig.params if name in PUBLIC_PARAMS and name not in data} | set(BUILTINS)

    assigns: dict[str, list[set[str]]] = {}
    for piece in re.split(r"[;{}]", body):
        m = ASSIGN.search(piece)
        t = TARGET.search(piece[: m.start()]) if m else None
        if m and t and t.group(1) not in NOT_VARIABLES:
            assigns.setdefault(t.group(1), []).append(idents(piece[m.end():]) | idents(t.group()) - {t.group(1)})
    out_args: list[tuple[set[str], set[str]]] = []  # (arguments a call may write, every identifier it reads)
    for m in CALL.finditer(body):
        if m.group(1) in CONTROL or m.group(1) in NOT_VARIABLES:
            continue
        args = _split_args(body[m.end(): _match(body, m.end() - 1, "(", ")")])
        callee = sigs.get(m.group(1))
        writable = {a for n, a in enumerate(args) if re.fullmatch(r"[A-Za-z_]\w*", a)
                    and (callee is None or n >= len(callee.params) or callee.params[n][1])}
        out_args.append((writable, set().union(*map(idents, args)) if args else set()))

    names = set(assigns) | data | {n for n in idents(body) if DATA_NAME.match(n)}
    data |= {n for n in names if DATA_NAME.match(n)}
    changed = True
    while changed:
        changed = False
        for name, rhs_list in assigns.items():
            if name not in data and any(rhs & data for rhs in rhs_list):
                data.add(name)
                changed = True
        for writable, read in out_args:
            if read & data and not writable <= data:
                data |= writable
                changed = True

    public = set(roots)
    changed = True
    while changed:
        changed = False
        for name, rhs_list in assigns.items():
            if name in data or name in public:
                continue
            if all(_all_public(rhs - {name}, public) for rhs in rhs_list):
                public.add(name)
                changed = True
    return data, public - data


def _all_public(names: set[str], public: set[str]) -> bool:
    return all(n in public or re.fullmatch(r"[A-Z][A-Z0-9_]*", n) for n in names)


def _offending(expr: str, data: set[str], public: set[str]) -> tuple[list[str], list[str]]:
    used = idents(expr)
    return sorted(used & data), sorted(n for n in used - data if not _all_public({n}, public))


def check_source(src: str, path: str, sigs: dict[str, Signature] | None = None) -> list[Finding]:
    code, macros = strip_code(src)
    lines = src.splitlines()
    starts = [0] + [m.end() for m in re.finditer("\n", code)]

    def finding(offset: int, rule: str, message: str) -> Finding:
        line = bisect.bisect_right(starts, offset)
        return Finding(path, line, rule, message, lines[line - 1].strip())

    out = [finding(off, "MACRO", "function-like macro is not analysed; use an inline function") for off, _ in macros]
    funcs = functions(code)
    sigs = {**(sigs or {}), **{name: sig for name, sig, _, _ in funcs}}
    for fname, sig, b0, b1 in funcs:
        body = code[b0:b1]
        data, public = classify(body, sig, sigs)

        def report(offset: int, rule: str, what: str, expr: str, fname: str = fname,
                   data: set[str] = data, public: set[str] = public) -> None:
            bad, unknown = _offending(expr, data, public)
            if bad:
                out.append(finding(offset, rule, f"{what} depends on data ({', '.join(bad)}) in {fname}()"))
            elif unknown:
                out.append(finding(offset, rule,
                                   f"{what} uses {', '.join(unknown)}, not proven public, in {fname}()"))

        for m in re.finditer(r"\b(if|while|for|switch)\s*\(", body):
            end = _match(body, m.end() - 1, "(", ")")
            report(b0 + m.start(), "BRANCH", f"`{m.group(1)}` condition", body[m.end():end])
        for m in re.finditer(r"\?|&&|\|\|", body):
            lo = max(body.rfind(c, 0, m.start()) for c in ";{}") + 1
            hi = min((p for p in (body.find(c, m.end()) for c in ";{}") if p >= 0), default=len(body))
            rule, what = ("TERNARY", "`?:` selection") if m.group() == "?" else ("SHORT_CIRCUIT", f"`{m.group()}`")
            report(b0 + m.start(), rule, what, body[lo:hi])
        for m in re.finditer(r"\[", body):
            end = _match(body, m.start(), "[", "]")
            report(b0 + m.start(), "INDEX", "array subscript", body[m.end():end])
        for m in re.finditer(r"\bgoto\b", body):
            out.append(finding(b0 + m.start(), "GOTO", f"goto in {fname}()"))
    return sorted(set(out), key=lambda f: (f.path, f.line, f.rule))


def collect(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for p in paths:
        if p.is_dir():
            files += sorted(q for q in p.rglob("*") if q.suffix in SUFFIXES)
        elif p.is_file():
            files.append(p)
        else:
            raise FileNotFoundError(p)
    return files


def check_paths(paths: list[Path], root: Path | None = None) -> tuple[list[Finding], list[Path]]:
    files = collect(paths)
    sources = {f: f.read_text(encoding="utf-8") for f in files}
    sigs: dict[str, Signature] = {}
    for src in sources.values():  # helpers in a header are called from other files
        sigs.update({name: sig for name, sig, _, _ in functions(strip_code(src)[0])})
    findings: list[Finding] = []
    for f, src in sources.items():
        try:
            rel = f.resolve().relative_to((root or ROOT).resolve()).as_posix()
        except ValueError:
            rel = f.as_posix()
        findings += check_source(src, rel, sigs)
    return findings, files


# Each plant is inserted after the anchor line of bitonic_pairs_global and must raise `rule` on its line.
ANCHOR = "    u32 l = i + j;\n"
PLANTS = (
    ("data_branch", "    if (hi[i] > hi[l]) { return; }\n", "BRANCH"),
    ("data_loop_bound", "    for (u32 q = 0; q < slot[i]; q++) { pay[i] = 0; }\n", "BRANCH"),
    ("data_while", "    while (lo[i] != 0) { lo[i] >>= 1; }\n", "BRANCH"),
    ("data_ternary", "    u64 big = (hi[i] > hi[l]) ? hi[i] : hi[l];\n", "TERNARY"),
    ("data_short_circuit", "    u64 both = (u64)((hi[i] > hi[l]) && (lo[i] > lo[l]));\n", "SHORT_CIRCUIT"),
    ("data_index", "    pay[slot[i] & (npairs - 1)] = 0;\n", "INDEX"),
    ("derived_data_index", "    u32 d = slot[i];\n    u32 e = d & 1;\n    pay[e] = 0;\n", "INDEX"),
    ("data_through_reference",
     "    u32 z = 0;\n    u32 w = 1;\n    xor_swap32(z, w, hi[i]);\n    pay[z] = 0;\n", "INDEX"),
    ("unknown_index", "    pay[some_global] = 0;\n", "INDEX"),
    ("goto", "    goto done;\n", "GOTO"),
)


def self_test(kernel_dir: Path = KERNEL_DIR) -> int:
    """Copy the kernels to a temp dir and check that each planted leak is flagged at its own line."""
    original = (kernel_dir / "bitonic.cu").read_text(encoding="utf-8")
    assert original.count(ANCHOR) >= 1, "anchor line not found in bitonic.cu"
    failed = 0
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        for f in collect([kernel_dir]):
            (tmp / f.name).write_text(f.read_text(encoding="utf-8"), encoding="utf-8")
        clean, _ = check_paths([tmp], root=tmp)
        print(f"{'PASS' if not clean else 'FAIL'}  clean copy: {len(clean)} finding(s)")
        failed += bool(clean)
        for name, plant, rule in PLANTS:
            at = original.index(ANCHOR) + len(ANCHOR)
            (tmp / "bitonic.cu").write_text(original[:at] + plant + original[at:], encoding="utf-8")
            first = original[:at].count("\n") + 1
            want = range(first, first + plant.count("\n"))
            found = check_paths([tmp], root=tmp)[0]
            got = [f for f in found if f.rule == rule and f.line in want]
            others = [f for f in found if f.line not in want]
            ok = bool(got) and not others
            failed += not ok
            print(f"{'PASS' if ok else 'FAIL'}  planted {name}: expected {rule} -> "
                  + (f"{got[0].path}:{got[0].line}: {got[0].message}" if got else "NOT FLAGGED")
                  + (f"  (+{len(others)} finding(s) on unplanted lines)" if others else ""))
    print(f"self-test: {'OK' if not failed else 'FAILED'} ({len(PLANTS) + 1 - failed}/{len(PLANTS) + 1})")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="*", help="kernel files or directories (default: kernels/)")
    ap.add_argument("--self-test", action="store_true")
    a = ap.parse_args(argv)
    if a.self_test:
        return self_test()
    try:
        findings, files = check_paths([Path(p) for p in a.paths] or [KERNEL_DIR])
    except FileNotFoundError as e:
        print(f"check_oblivious: no such file or directory: {e}", file=sys.stderr)
        return 2
    for f in findings:
        print(f)
    print(f"check_oblivious: {len(files)} file(s), {len(findings)} finding(s) - {'FAIL' if findings else 'PASS'}")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
