"""Synthetic contact center data for the Power BI report (24 months, ~1.7 million contacts).

A bank outsources customer service to six BPO partners, on two channels (voice and WhatsApp).
Each partner/channel has its own contract: the wait limit that counts as "answered on time",
the service level target and the short-abandon limit. All names are fictitious.

Behaviour built into the data, so the report has real stories to show:
* daily and intraday seasonality (peaks at 10:00 and 14:00), WhatsApp growing every month
* waiting time grows with the load of the interval and depends on each partner's capacity
* customers give up when the wait exceeds their patience (abandoned contacts)
* one partner (Delta CX) loses capacity from March 2026 and starts missing its voice SLA

Output (Parquet, read by the Power BI model through the DataFolder parameter):
    <out>/contacts/contacts_YYYY-MM.parquet   one file per month (incremental refresh friendly)
    <out>/dimensions/*.parquet                partners, channels, service agreements, queues
    <out>/security/partner_access.parquet     user -> partner (row-level security)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

START, END = "2024-10-01", "2026-09-30"

PARTNERS = pd.DataFrame(
    {
        "Partner Key": [1, 2, 3, 4, 5, 6],
        "Partner": ["Atlas BPO", "Boreal Contact", "Cobalt Services", "Delta CX", "Equinox Atende", "Fenix Relacionamento"],
        "Site": ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Recife", "Salvador"],
        "Volume Share": [0.24, 0.20, 0.18, 0.16, 0.12, 0.10],
    }
)
CAPACITY = {1: 1.10, 2: 1.00, 3: 0.97, 4: 1.02, 5: 0.93, 6: 1.05}  # >1 = shorter waits
CHANNELS = pd.DataFrame({"Channel Key": [1, 2], "Channel": ["Voice", "WhatsApp"]})
QUEUES = pd.DataFrame(
    {
        "Queue Key": [1, 2, 3, 4, 5],
        "Queue": ["Cards", "Accounts", "Loans", "Fraud & Security", "Collections"],
        "Priority": ["Normal", "Normal", "Normal", "High", "Low"],
        "Volume Share": [0.34, 0.26, 0.17, 0.08, 0.15],
        "Handle Factor": [1.0, 0.9, 1.25, 1.45, 1.1],
    }
)
# Contract per partner and channel: answer within N seconds, target %, short-abandon limit
VOICE_TERMS = {1: (20, 0.80), 2: (30, 0.80), 3: (30, 0.85), 4: (20, 0.80), 5: (30, 0.80), 6: (20, 0.85)}
WHATSAPP_TERMS = {1: (120, 0.85), 2: (180, 0.85), 3: (180, 0.90), 4: (120, 0.85), 5: (300, 0.85), 6: (120, 0.90)}


def service_agreements() -> pd.DataFrame:
    rows = []
    for p in PARTNERS["Partner Key"]:
        for ch, terms, short in ((1, VOICE_TERMS, 5), (2, WHATSAPP_TERMS, 30)):
            limit, target = terms[p]
            rows.append(
                {
                    "Service Key": p * 10 + ch,
                    "Partner Key": p,
                    "Channel Key": ch,
                    "SLA Threshold Seconds": limit,
                    "SLA Target": target,
                    "Short Abandon Seconds": short,
                }
            )
    return pd.DataFrame(rows)


# Share of the day's contacts in each half-hour interval (0 = 00:00, 20 = 10:00, 28 = 14:00)
def intraday(channel: int) -> np.ndarray:
    k = np.arange(48)
    open_from, open_to = (16, 40) if channel == 1 else (14, 46)  # voice 08-20h, WhatsApp 07-23h
    curve = np.exp(-((k - 20.5) ** 2) / 10) + 0.85 * np.exp(-((k - 28.5) ** 2) / 14) + 0.25
    curve[(k < open_from) | (k >= open_to)] = 0
    return curve / curve.sum()


WEEKDAY = np.array([1.22, 1.08, 1.03, 1.0, 1.06, 0.55, 0.28])  # Monday .. Sunday


def generate(scale: float, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    days = pd.date_range(START, END, freq="D")
    curves = {1: intraday(1), 2: intraday(2)}
    frames = []
    next_id = 1
    for i, day in enumerate(days):
        months = i / 30.4
        base = 2_000 * scale * (1 + 0.012 * months) * WEEKDAY[day.weekday()] * (1.12 if day.month in (1, 12) else 1.0)
        whatsapp_share = 0.25 + 0.30 * min(months / 24, 1)
        for ch, share in ((1, 1 - whatsapp_share), (2, whatsapp_share)):
            n_channel = rng.poisson(base * share)
            if n_channel == 0:
                continue
            interval = rng.choice(48, size=n_channel, p=curves[ch])
            partner = rng.choice(PARTNERS["Partner Key"], size=n_channel, p=PARTNERS["Volume Share"])
            queue = rng.choice(QUEUES["Queue Key"], size=n_channel, p=QUEUES["Volume Share"])
            # load of the interval relative to the average open interval -> longer waits at peaks
            load = curves[ch][interval] / curves[ch][curves[ch] > 0].mean()
            capacity = np.vectorize(CAPACITY.get)(partner).astype(float)
            if day >= pd.Timestamp("2026-03-01"):
                capacity = np.where((partner == 4) & (ch == 1), capacity * 0.86, capacity)  # Delta CX staffing gap
            mean_wait = (7 if ch == 1 else 34) * load**1.6 / capacity**3
            wait = rng.gamma(shape=1.3, scale=mean_wait / 1.3)
            patience = rng.exponential(110 if ch == 1 else 900, size=n_channel)
            abandoned = wait > patience
            wait = np.where(abandoned, patience, wait)
            handle_factor = QUEUES.set_index("Queue Key")["Handle Factor"].to_numpy()[queue - 1]
            handle = rng.lognormal(np.log(300 if ch == 1 else 480), 0.45, size=n_channel) * handle_factor
            minute = interval * 30 + rng.integers(0, 30, size=n_channel)
            start = day + pd.to_timedelta(minute, unit="min") + pd.to_timedelta(rng.integers(0, 60, size=n_channel), unit="s")
            frames.append(
                pd.DataFrame(
                    {
                        "Contact Start": start,
                        "Contact Date": day.date(),
                        "Interval Key": interval.astype("int64"),
                        "Service Key": (partner * 10 + ch).astype("int64"),
                        "Queue Key": queue.astype("int64"),
                        "Outcome": np.where(abandoned, "Abandoned", "Answered"),
                        "Wait Seconds": np.round(wait).astype("int64"),
                        "Handle Seconds": np.where(abandoned, 0, np.round(handle)).astype("int64"),
                    }
                )
            )
    contacts = pd.concat(frames, ignore_index=True).sort_values("Contact Start", kind="stable").reset_index(drop=True)
    contacts.insert(0, "Contact ID", np.arange(next_id, next_id + len(contacts), dtype="int64"))
    return contacts


def write(contacts: pd.DataFrame, out: Path) -> None:
    for folder in ("contacts", "dimensions", "security"):
        (out / folder).mkdir(parents=True, exist_ok=True)
    for old in (out / "contacts").glob("*.parquet"):
        old.unlink()
    month = contacts["Contact Start"].dt.strftime("%Y-%m")
    for value, part in contacts.groupby(month):
        part.to_parquet(out / "contacts" / f"contacts_{value}.parquet", index=False)
    PARTNERS.drop(columns="Volume Share").to_parquet(out / "dimensions" / "partner.parquet", index=False)
    CHANNELS.to_parquet(out / "dimensions" / "channel.parquet", index=False)
    QUEUES.drop(columns=["Volume Share", "Handle Factor"]).to_parquet(out / "dimensions" / "queue.parquet", index=False)
    service_agreements().to_parquet(out / "dimensions" / "service_agreement.parquet", index=False)
    # Row-level security: each partner manager sees only their own partner (fictitious users)
    access = pd.DataFrame(
        {
            "User Email": [f"manager.{p.split()[0].lower()}@example.com" for p in PARTNERS["Partner"]],
            "Partner Key": PARTNERS["Partner Key"],
        }
    )
    access.to_parquet(out / "security" / "partner_access.parquet", index=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default="data", help="output folder (DataFolder parameter in Power BI)")
    parser.add_argument("--scale", type=float, default=1.0, help="1.0 = ~1.7 million contacts")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()
    contacts = generate(args.scale, args.seed)
    write(contacts, Path(args.out))
    print(
        json.dumps(
            {
                "contacts": len(contacts),
                "first": str(contacts["Contact Start"].min()),
                "last": str(contacts["Contact Start"].max()),
            }
        )
    )


if __name__ == "__main__":
    main()
