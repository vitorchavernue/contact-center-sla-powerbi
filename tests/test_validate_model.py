"""The quality gate passes on the project and catches the mistakes it is meant to catch."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest

if importlib.util.find_spec("pythonnet") is None or importlib.util.find_spec("sempy") is None:
    pytest.skip("needs pythonnet and the TOM assemblies (semantic-link-sempy)", allow_module_level=True)

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import validate_model  # noqa: E402


@pytest.fixture(scope="module")
def model():
    return validate_model.load_model()


def test_project_passes_every_rule(model):
    failed = [r.rule for r in validate_model.model_rules(model) + validate_model.report_rules(model) if not r.passed]
    assert failed == []


def test_measure_without_description_and_with_division_is_caught(model):
    contacts = model.Tables.Find("Contacts")
    measure = contacts.Measures.Find("Abandon Rate")
    original = (measure.Description, measure.Expression)
    measure.Description = ""
    measure.Expression = "[Contacts Abandoned] / [Contacts Offered]"
    try:
        failed = {r.rule for r in validate_model.model_rules(model) if not r.passed}
    finally:
        measure.Description, measure.Expression = original
    assert "Every measure has a description" in failed
    assert "Measures divide with DIVIDE (no division by zero errors)" in failed


def test_visual_using_a_deleted_measure_is_caught(model, tmp_path, monkeypatch):
    report = tmp_path / "ContactCenterSLA.Report"
    shutil.copytree(validate_model.REPORT, report)
    visual = next((report / "definition" / "pages" / "Overview" / "visuals").glob("k_sl/visual.json"))
    data = json.loads(visual.read_text(encoding="utf-8"))
    data["visual"]["query"]["queryState"]["Values"]["projections"][0]["field"]["Measure"]["Property"] = "Old Measure"
    visual.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(validate_model, "REPORT", report)
    results = {r.rule: r for r in validate_model.report_rules(model)}
    broken = next(r for name, r in results.items() if name.startswith("Every field used"))
    assert not broken.passed and "Old Measure" in broken.detail
