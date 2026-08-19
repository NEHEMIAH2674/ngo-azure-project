# Dashboard

Captured from `make dashboard` (`http://localhost:8501`), one shot per tab. No
separate KPI-overview shot: the KPI row (outbound calls, coding rate, paid
post call, value recovered, inbound calls) plus the window-closure banner
("Every disposition in the current selection has a closed 3-day payment
window...") sits at the top of every tab, so all three screenshots below
carry it already.

1. **`metric-1-coding-rate.png`** — coding rate by market, plus the full
   agent/campaign coaching table (day, market, campaign, agent, coding rate,
   conflicting-mapping flag).
2. **`metric-2-3-paid-post-call.png`** — paid-post-call rate by market, plus
   value recovered per market in local currency with the `*` estimated-FX
   marker on each USD figure.
3. **`metric-4-inbound-drivers.png`** — the level-1 → level-2 → level-3
   drill-down (captured mid-drill: Enquiry → Product Usage/Education).

The subtitle under the dashboard title (`built on dev_dlight_analytics_marts`)
confirms which environment it's reading from — dynamic, not hardcoded, so it
won't go stale the way a fixed string would if pointed at prod instead.
