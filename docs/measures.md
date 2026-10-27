# Measure dictionary

Every measure lives in the `Contacts` table, in a display folder, with a description and a format
string (enforced by the CI quality gate). The pandas reference implementation of the main measures is
in [`scripts/kpis.py`](../scripts/kpis.py).

## 1. Volume

| Measure | Definition |
|---|---|
| Contacts Offered | Contacts that reached a partner queue (answered + abandoned) |
| Contacts Answered | Offered contacts answered by an agent |
| Contacts Abandoned | Customers who gave up before being answered |
| Short Abandons | Abandoned within the contract's short-abandon limit (voice 5 s, WhatsApp 30 s): wrong number, changed mind. Not counted against the partner |
| Abandon Rate | (Abandoned − Short Abandons) / (Offered − Short Abandons) |

## 2. Service level

| Measure | Definition |
|---|---|
| Answered Within SLA | Answered with a wait ≤ the **contract's own limit** (20, 30, 120, 180 or 300 s depending on partner and channel). Evaluated contract by contract (`SUMX` over `Service Agreement`) |
| Service Level % | Answered Within SLA / (Offered − Short Abandons) — the industry formula used in BPO contracts |
| SLA Target % | Contract target; for selections with several contracts, weighted by each contract's volume |
| SLA Gap | Service Level % − SLA Target %, in percentage points |
| SLA Status | "Met" or "Missed" |
| Intervals Meeting SLA % | Share of half-hour intervals (day × interval) whose service level met the target — catches partners that hit the monthly average while failing every peak |
| Contracts Below Target | Number of partner/channel contracts below target in the selection |

## 3. Speed & handling

| Measure | Definition |
|---|---|
| ASA (s) | Average speed of answer: average wait of answered contacts |
| AHT (s) | Average handle time of answered contacts |
| Workload Hours | Handle time in hours (staffing and partner billing) |
| Longest Wait (s) | Longest wait before an answer |

## Time intelligence (calculation group)

`Time Intelligence[Period]` applies to **any** measure: `Current`, `MTD`, `YTD`, `PY` (same period last
year), `YoY Δ` (difference, in the measure's own format) and `YoY %` (relative change). One calculation
group replaces six copies of every measure.

## Row-level security

| Role | Sees |
|---|---|
| Contact Center Management | Every partner |
| Partner Manager | Only the partner mapped to the signed-in user in `Partner Access` (`USERPRINCIPALNAME()`); the filter on `Partner` flows to contracts and contacts |

## Incremental refresh

`Contacts` keeps a rolling **24 months** and refreshes only the **last 3 days** on each scheduled refresh.
The source query opens only the monthly Parquet files that overlap each partition's `RangeStart`–`RangeEnd`
window, then filters the rows.
