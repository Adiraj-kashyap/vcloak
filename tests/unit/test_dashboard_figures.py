"""M18 S6b: every chart of dashboard.json that is not pending becomes a one-column PDF + 300 dpi PNG that holds at that size."""
from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD = ROOT / "web" / "data" / "dashboard.json"
pytest.importorskip("matplotlib")
pytestmark = pytest.mark.skipif(not DASHBOARD.exists(), reason="no generated dashboard.json in this tree")


def _module():
    spec = importlib.util.spec_from_file_location("dashboard_figures", ROOT / "scripts" / "dashboard_figures.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _dashboard() -> dict:
    return json.loads(DASHBOARD.read_text(encoding="utf-8"))


def test_every_chart_is_drawn_and_holds_at_one_column(tmp_path):
    figs = _module()
    dash = _dashboard()
    made = figs.render_all(dash, tmp_path)
    assert sorted(f["id"] for f in made) == sorted(c["id"] for c in dash["charts"] if not c.get("pending"))
    for f in made:
        checks = figs.check(f, tmp_path)
        assert all(checks.values()), {k: v for k, v in checks.items() if not v}


def test_a_pending_chart_is_not_drawn(tmp_path):
    figs = _module()
    dash = _dashboard()
    dash["charts"][0] = {"id": "later", "kind": "groupedBar", "title": "later", "pending": True, "metric_ids": ["X"]}
    made = figs.render_all(dash, tmp_path)
    assert "later" not in {f["id"] for f in made}
    assert not (tmp_path / "M18_dash_later.png").exists()


def test_the_values_drawn_are_those_of_the_spec(tmp_path):
    """The bars of a grouped bar chart are the spec's values, nothing else."""
    import matplotlib.pyplot as plt

    figs = _module()
    spec = copy.deepcopy(next(c for c in _dashboard()["charts"] if c["kind"] == "groupedBar"))
    with plt.rc_context(figs.style(figs.palette())):
        fig = figs.grouped_bar(spec, figs.palette())
        heights = sorted(round(p.get_height(), 6) for p in fig.axes[0].patches if p.get_height() == p.get_height())
        plt.close(fig)
    expected = sorted(round(v, 6) for s in spec["series"] for v in s["values"] if v is not None)
    assert heights == expected


def test_text_that_leaves_its_cell_fails_the_check(tmp_path):
    figs = _module()
    spec = copy.deepcopy(next(c for c in _dashboard()["charts"] if c["kind"] == "matrix"))
    spec["rows"][0]["observed"] = spec["rows"][0]["expected"] = "x" * 60  # one word that cannot wrap
    f = figs.render(spec, tmp_path, figs.palette())
    assert f["text_on_page"] is False
    assert figs.check(f, tmp_path)[f"{spec['id']}: every text on the page"] is False


def test_an_outcome_that_differs_shows_both(tmp_path):
    import matplotlib.pyplot as plt

    figs = _module()
    spec = copy.deepcopy(next(c for c in _dashboard()["charts"] if c["kind"] == "matrix"))
    spec["rows"][0].update(observed="500", ok=False)
    with plt.rc_context(figs.style(figs.palette())):
        fig = figs.matrix(spec, figs.palette())
        cells = fig.axes[0].tables[0].get_celld()
        outcome, verdict = cells[(1, 1)].get_text().get_text(), cells[(1, 2)].get_text().get_text()
        plt.close(fig)
    assert "expected" in outcome and "500" in outcome.replace("\n", " ")
    assert verdict == "NO"
