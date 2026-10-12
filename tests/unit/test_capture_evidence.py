"""scripts/capture_evidence.py: the index handling and the file rules, without a browser.

The capture itself needs Chrome and a running service; it is exercised by running the script (M13 S5b, A6).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import capture_evidence as ce

HEAD = "# EVIDENCE INDEX\n\n" + ce.INDEX_HEAD + "\n|---|---|---|---|---|---|---|\n"
OLD = "| TERM-M00-PYTEST | terminal/M00_pytest.txt — summary | M00 | 2026-10-11 | runs/x (git abc1) | measured | — |\n"


def row(id: str = "SCR-M13-DASHBOARD-LIGHT", file: str = "screens/M13_dashboard_light_20261012.png",
        **kw: str) -> dict[str, str]:
    return {"id": id, "file": file, "what": "the dashboard", "module": "M13", "date": "2026-10-12",
            "source": "runs/20261012-000000_M13_x (git abc1234, dirty)", "state": "seed", **kw}


def test_a_new_row_goes_to_the_end_and_the_rest_is_untouched() -> None:
    text, replaced = ce.upsert_rows(HEAD + OLD, [row()])
    assert text.startswith(HEAD + OLD) and replaced == []
    last = ce.row_cells(text.rstrip("\n").split("\n")[-1])
    assert last[0] == "SCR-M13-DASHBOARD-LIGHT" and last[4].startswith("runs/") and last[5] == "seed" and len(last) == 7


def test_a_second_run_replaces_its_rows_and_adds_none() -> None:
    once, _ = ce.upsert_rows(HEAD + OLD, [row(), row(id="SCR-M13-DASHBOARD-DARK", file="screens/d.png")])
    twice, replaced = ce.upsert_rows(once, [row(what="the dashboard again"),
                                            row(id="SCR-M13-DASHBOARD-DARK", file="screens/d.png")])
    assert replaced == [] and twice.count("\n") == once.count("\n")
    assert "the dashboard again" in twice and twice.count("SCR-M13-DASHBOARD-LIGHT") == 1


def test_a_row_whose_file_changed_reports_the_old_file_and_keeps_used_in() -> None:
    once, _ = ce.upsert_rows(HEAD, [row(used="report Fig. 4.2")])
    later, replaced = ce.upsert_rows(once, [row(file="screens/M13_dashboard_light_20261013.png")])
    assert replaced == [("SCR-M13-DASHBOARD-LIGHT", "screens/M13_dashboard_light_20261012.png",
                         "M13_dashboard_light_20261012.png")]
    cells = ce.row_cells(later.rstrip("\n").split("\n")[-1])
    assert cells[6] == "report Fig. 4.2" and "supersedes screens/M13_dashboard_light_20261012.png" in cells[1]


def test_a_row_needs_a_run_dir_and_a_known_data_state() -> None:
    with pytest.raises(ValueError, match="no run dir"):
        ce.index_row(**row(source="by hand"))
    with pytest.raises(ValueError, match="data state"):
        ce.index_row(**row(state="estimated"))
    with pytest.raises(ValueError, match="no table head"):
        ce.upsert_rows("# nothing\n", [row()])


def test_a_cell_cannot_break_the_table() -> None:
    line = ce.index_row(**row(what="a | b\nc"))
    assert len(ce.row_cells(line)) == 7 and "a / b c" in line


def test_ids_and_png_size(tmp_path: Path) -> None:
    assert ce.shot_id("M13", "chat_vcloak_reveal", "light") == "SCR-M13-CHAT-VCLOAK-REVEAL-LIGHT"
    png = tmp_path / "a.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\rIHDR" + (1440).to_bytes(4, "big") + (900).to_bytes(4, "big"))
    assert ce.png_size(png) == (1440, 900)
    png.write_bytes(b"not a picture, twenty-four bytes long")
    with pytest.raises(ValueError, match="not a PNG"):
        ce.png_size(png)


def test_a_terminal_copy_must_come_from_a_run_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ce, "ROOT", tmp_path)
    run = tmp_path / "runs" / "20261012-000000_M13_x"
    run.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"git_sha": "abc1234def", "dirty": True}), encoding="utf-8")
    (run / "pytest_all.txt").write_text("1 passed\n", encoding="utf-8")
    (tmp_path / "loose.txt").write_text("typed by hand\n", encoding="utf-8")
    [(src, r)] = ce.terminal_rows([f"runs/{run.name}/pytest_all.txt=summary of the suite"], module="M13", tag="S5b",
                                  date="2026-10-12")
    assert src == run / "pytest_all.txt" and r["id"] == "TERM-M13-S5B-PYTEST-ALL"
    assert r["file"] == "terminal/M13_S5b_pytest_all.txt" and r["source"] == f"runs/{run.name} (git abc1234, dirty)"
    for bad in ("loose.txt=typed", f"runs/{run.name}/pytest_all.txt", f"runs/{run.name}/missing.txt=x"):
        with pytest.raises(ValueError, match="--terminal"):
            ce.terminal_rows([bad], module="M13", tag="", date="2026-10-12")


def test_views_and_modes_are_the_ones_the_page_has() -> None:
    html = (ce.ROOT / "web" / "index.html").read_text(encoding="utf-8")
    for view in ce.VIEWS:
        assert f'data-view="{view}"' in html and f'id="view-{view}"' in html
    assert len(ce.THEMES) * (len(ce.CHAT_MODES) + len(ce.PLAIN_VIEWS)) >= 8  # the S5b check


def test_the_strip_of_a_picture_must_agree_with_the_server() -> None:
    gpu = {"backend": "numpy", "runner": "local", "device": "a cpu", "util": None}
    strip = {"epoch": "1000", "backend": "numpy · local", "slots": "64", "fill_hidden": False,
             "no_epoch_hidden": True, "server_epoch": 1002, "server_gpu": gpu, "server_slots": 64}
    assert ce.strip_agrees(strip)
    assert not ce.strip_agrees({**strip, "epoch": "—"})  # nothing shown
    assert not ce.strip_agrees({**strip, "server_epoch": 1010})  # a clock of its own
    assert not ce.strip_agrees({**strip, "backend": "cupy · kaggle"})  # a backend the server did not name
    assert not ce.strip_agrees({**strip, "server_gpu": None})
    assert not ce.strip_agrees({**strip, "slots": "—"})


def test_another_run_on_the_same_day_keeps_the_picture_of_the_earlier_run() -> None:
    """The file name carries the day only: a later run of that day would overwrite the picture of an
    earlier one, and with it what the record of that run points at."""
    once, _ = ce.upsert_rows(HEAD, [row()])
    later_run = "runs/20261012-111111_M13_y (git def5678)"
    later, replaced = ce.upsert_rows(once, [row(source=later_run)])
    kept = "M13_dashboard_light_20261012.20261012-000000.png"
    assert replaced == [("SCR-M13-DASHBOARD-LIGHT", "screens/M13_dashboard_light_20261012.png", kept)]
    note = f"; the earlier picture (runs/20261012-000000_M13_x) is kept as superseded/{kept}"
    assert note in later and later.count("SCR-M13-DASHBOARD-LIGHT") == 1
    # the same run again overwrites its own picture, and the row still says what the earlier run left
    again, replaced = ce.upsert_rows(later, [row(source=later_run, what="the dashboard again")])
    assert replaced == [] and note in again and again.count("is kept as") == 1
    # a third run keeps the second, and both notes stay
    third, replaced = ce.upsert_rows(again, [row(source="runs/20261012-222222_M13_z (git 0000000)")])
    assert [r[2] for r in replaced] == ["M13_dashboard_light_20261012.20261012-111111.png"]
    assert third.count("is kept as") == 2 and note in third
