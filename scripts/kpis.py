"""Reference implementation of the report's main measures in pandas.

Same definitions as the DAX measures (see docs/measures.md). Used to check the numbers shown
in Power BI and to write the KPI snapshot in the README.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def load(folder: Path) -> pd.DataFrame:
    contacts = pd.concat(pd.read_parquet(f) for f in sorted((folder / "contacts").glob("*.parquet")))
    sa = pd.read_parquet(folder / "dimensions" / "service_agreement.parquet")
    partners = pd.read_parquet(folder / "dimensions" / "partner.parquet")
    channels = pd.read_parquet(folder / "dimensions" / "channel.parquet")
    df = contacts.merge(sa, on="Service Key").merge(partners, on="Partner Key").merge(channels, on="Channel Key")
    df["Month"] = df["Contact Start"].dt.to_period("M").astype(str)
    return df


def kpis(df: pd.DataFrame) -> pd.Series:
    answered = df["Outcome"] == "Answered"
    abandoned = ~answered
    short = abandoned & (df["Wait Seconds"] <= df["Short Abandon Seconds"])
    within = answered & (df["Wait Seconds"] <= df["SLA Threshold Seconds"])
    offered = len(df)
    return pd.Series(
        {
            "Contacts Offered": offered,
            "Service Level %": within.sum() / (offered - short.sum()),
            "SLA Target %": df["SLA Target"].mean(),  # volume-weighted (one row per contact)
            "Abandon Rate": (abandoned.sum() - short.sum()) / (offered - short.sum()),
            "ASA (s)": df.loc[answered, "Wait Seconds"].mean(),
            "AHT (s)": df.loc[answered, "Handle Seconds"].mean(),
        }
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default="data")
    parser.add_argument("--by", nargs="*", default=[])
    args = parser.parse_args()
    df = load(Path(args.data))
    result = kpis(df) if not args.by else df.groupby(args.by).apply(kpis, include_groups=False)
    with pd.option_context("display.width", 200, "display.max_rows", 200, "display.float_format", "{:,.3f}".format):
        print(result)


if __name__ == "__main__":
    main()
