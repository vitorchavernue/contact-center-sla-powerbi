"""The synthetic data has the shape the Power BI model expects and the stories the report tells."""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import generate_data  # noqa: E402
import kpis  # noqa: E402


@pytest.fixture(scope="module")
def folder(tmp_path_factory):
    out = tmp_path_factory.mktemp("data")
    generate_data.write(generate_data.generate(scale=0.08, seed=2026), out)
    return out


def test_one_file_per_month_for_24_months(folder):
    names = sorted(p.name for p in (folder / "contacts").glob("*.parquet"))
    assert len(names) == 24
    assert names[0] == "contacts_2024-10.parquet" and names[-1] == "contacts_2026-09.parquet"


def test_contacts_schema_matches_the_power_query_schema(folder):
    df = pd.read_parquet(folder / "contacts" / "contacts_2025-06.parquet")
    assert list(df.columns) == [
        "Contact ID",
        "Contact Start",
        "Contact Date",
        "Interval Key",
        "Service Key",
        "Queue Key",
        "Outcome",
        "Wait Seconds",
        "Handle Seconds",
    ]
    assert set(df["Outcome"]) == {"Answered", "Abandoned"}
    assert (df["Wait Seconds"] >= 0).all()
    assert (df.loc[df["Outcome"] == "Abandoned", "Handle Seconds"] == 0).all()
    assert df["Interval Key"].between(0, 47).all()


def test_every_key_exists_in_its_dimension(folder):
    df = kpis.load(folder)  # inner joins: rows would disappear if a key were missing
    total = sum(len(pd.read_parquet(p)) for p in (folder / "contacts").glob("*.parquet"))
    assert len(df) == total
    assert df["Contact ID"].is_unique


def test_row_level_security_maps_one_manager_per_partner(folder):
    access = pd.read_parquet(folder / "security" / "partner_access.parquet")
    partners = pd.read_parquet(folder / "dimensions" / "partner.parquet")
    assert access["User Email"].is_unique
    assert set(access["Partner Key"]) == set(partners["Partner Key"])


def test_delta_cx_voice_falls_below_target_after_march_2026(folder):
    df = kpis.load(folder)
    voice = df[(df["Partner"] == "Delta CX") & (df["Channel"] == "Voice")]
    before = kpis.kpis(voice[voice["Contact Start"] < "2026-03-01"])
    after = kpis.kpis(voice[voice["Contact Start"] >= "2026-03-01"])
    assert before["Service Level %"] >= before["SLA Target %"]
    assert after["Service Level %"] < after["SLA Target %"] - 0.03


def test_whatsapp_share_grows(folder):
    df = kpis.load(folder)
    share = df.groupby(df["Contact Start"].dt.year)["Channel"].apply(lambda s: (s == "WhatsApp").mean())
    assert share.iloc[-1] > share.iloc[0]
