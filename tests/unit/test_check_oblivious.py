"""M03 S5: the static obliviousness checker (audit check G3)."""
from __future__ import annotations

from pathlib import Path

import check_oblivious as co

KERNELS = Path(__file__).resolve().parents[2] / "kernels"

CLEAN = """
extern "C" __global__
void demo(unsigned long long* hi, unsigned int* pay, unsigned int k, unsigned int n)
{
    unsigned int t = blockIdx.x * blockDim.x + threadIdx.x;
    if (t >= n || k == 0) { return; }          // public guard, public short-circuit
    unsigned int i = (t & k) ? t : t ^ 1;      // public selection
    for (unsigned int q = 0; q < k; q++) { pay[i] ^= (unsigned int)hi[t]; }
}
"""


def rules(src: str) -> list[tuple[int, str]]:
    return [(f.line, f.rule) for f in co.check_source(src, "x.cu")]


def test_repository_kernels_are_clean() -> None:
    findings, files = co.check_paths([KERNELS])
    assert findings == [] and {f.name for f in files} >= {"bitonic.cu", "common.cuh", "vector_add.cu"}


def test_self_test_flags_every_planted_leak(capsys) -> None:
    assert co.self_test() == 0
    out = capsys.readouterr().out
    assert out.count("PASS") == len(co.PLANTS) + 1 and "FAIL" not in out


def test_public_control_flow_is_allowed() -> None:
    assert rules(CLEAN) == []


def test_data_dependent_constructs_are_flagged() -> None:
    body = "    unsigned int t = threadIdx.x;\n"
    cases = {
        "    if (hi[t] > 5) { pay[t] = 0; }\n": "BRANCH",
        "    pay[t] = hi[t] > 5 ? 1 : 0;\n": "TERNARY",
        "    pay[t] = (hi[t] > 5) || (k > 2);\n": "SHORT_CIRCUIT",
        "    pay[hi[t] & 3] = 0;\n": "INDEX",
        "    unsigned int v = (unsigned int)hi[t];\n    pay[v] = 0;\n": "INDEX",
        "    while (n > 0) { n -= pay[t]; }\n": "BRANCH",  # n becomes data once it is assigned from pay
    }
    for stmt, rule in cases.items():
        src = CLEAN.replace("    unsigned int t = blockIdx.x * blockDim.x + threadIdx.x;\n", body + stmt)
        assert rule in [r for _, r in rules(src)], stmt


def test_comments_strings_and_macros() -> None:
    assert rules(CLEAN.replace("// public guard", "// if (hi[t] > 0) pay[hi[t]] = 0 ? 1 : 2")) == []
    assert rules("#define PICK(a, b) ((a) > (b) ? (a) : (b))\n" + CLEAN) == [(1, "MACRO")]
    assert rules("#define MAX_T 256\n" + CLEAN) == []


def test_helper_parameters_are_data_unless_public() -> None:
    helper = "__device__ unsigned int pick(unsigned int a, unsigned int i) { unsigned int tab[2]; return tab[%s]; }\n"
    assert rules(helper % "i") == []
    assert rules(helper % "a") == [(1, "INDEX")]


def test_cli_exit_codes(tmp_path, capsys) -> None:
    (tmp_path / "ok.cu").write_text(CLEAN, encoding="utf-8")
    assert co.main([str(tmp_path)]) == 0
    (tmp_path / "bad.cu").write_text(CLEAN.replace("q < k", "q < pay[t]"), encoding="utf-8")
    assert co.main([str(tmp_path)]) == 1
    assert "bad.cu:8: BRANCH" in capsys.readouterr().out
    assert co.main([str(tmp_path / "missing")]) == 2
