# Write-up

This covers the five things the brief asked for: my answers to the four metrics, the data gaps I found, the assumptions I had to make, how I handled each gap, and my recommendations. All figures are the pipeline's actual output against the sample extract (Aug 4–7, 2026) — nothing here is estimated by hand.

## At a glance

| Metric | Result |
|---|---|
| **1. Coding rate** | 44.68% overall — ranging from Kenya's 64.9% down to **Tanzania's 5.0%** |
| **2. Paid post call** | 12.88% of dispositions with a contract are paid within 3 days |
| **3. Value recovered** | **$14,013 USD** across all four markets (flagged as an estimate — see below) |
| **4. Inbound drivers** | Enquiry (50%), Service Request (21%), Complaints (17%), Customer Feedback (12%) |

The single most useful thing in this dataset is Tanzania's coding rate: three of every four outbound calls there never even get a disposition logged, against roughly one in three for Kenya, Uganda, and Nigeria. That's worth a conversation before anything else in this write-up.

## 1. Answers

### Metric 1 — Coding rate

**44.68%** of outbound calls (4,695 of 10,508) end up disposed of in Atlas.

| Market | Outbound calls | Coded | Rate |
|---|---|---|---|
| Kenya | 5,163 | 3,353 | **64.9%** |
| Nigeria | 1,874 | 604 | 32.2% |
| Uganda | 2,119 | 671 | 31.7% |
| Tanzania | 1,352 | 67 | **5.0%** |

`fct_coding_rate` carries this at (day, market, campaign, agent) grain — 340 rows across 285 distinct agents and 32 campaigns — exactly the breakdown the brief asked for, since it's meant for coaching individual agents.

Tanzania's number is the one I'd act on first. Three of four outbound calls there aren't coded at anywhere near the rate they are in Kenya, and that gap is too large to be an agent-performance story on its own — it reads like a training gap, a process gap, or an Ameyo/Atlas access issue specific to that market. I'd want that answered before drawing any conclusion about individual agents.

### Metric 2 — Paid post call

**11.32%** of all 52,132 Atlas dispositions are followed by a payment on that contract within 3 days. Restricted to the 45,814 dispositions that actually carry a `contract_id` — the only ones a payment *could* attribute to — the rate is **12.88%**.

| Market | Dispositions with a contract | Paid post call | Rate |
|---|---|---|---|
| Kenya | 34,611 | 3,509 | 10.1% |
| Nigeria | 4,113 | 560 | 13.6% |
| Uganda | 3,052 | 736 | 24.1% |
| Tanzania | 4,038 | 1,096 | **27.1%** |

There's an interesting inversion here: Tanzania has by far the worst coding rate but the best paid-post-call rate among the calls that do get coded. The volumes are small (67 coded outbound calls total), so I'd treat that as a hypothesis worth testing with more data rather than a finding on its own.

**Attribution rule** (the brief left this open deliberately): each payment is attributed to the single nearest-preceding disposed call on the same contract, within the 3-day window. See Assumptions below for why.

Every row in `fct_paid_post_call` currently shows `is_window_closed = true`, because the sample dates are already in the past relative to when I actually ran the pipeline. On a live daily run, the most recent 3 days would show `is_window_closed = false` and should be read as provisional — this is the moving-window problem the brief specifically asked how I'd handle, and it's a real column in the mart, not just a note in this document.

### Metric 3 — Value recovered from call-centre intervention

**$14,013 USD** across all four markets, once I configured a live exchange-rate key. Before that, the pipeline correctly returned `NULL` for every `attributed_payment_amount_usd` rather than fabricating a number — that's by design, not a bug.

One caveat that actually matters: this figure is an *estimate*, and the pipeline says so rather than hiding it. The free tier of exchangerate-api.com doesn't include historical rate lookups, so every conversion here uses the *latest available* rate rather than the rate that actually applied on each payment's date. Every affected row carries `rate_is_estimated = true` in `raw.fx_rates`, and that flag is threaded all the way through `fct_paid_post_call` and `agg_daily_summary` to the dashboard, where it shows as a visible `*` next to the number rather than a footnote nobody reads. Over a 4-day sample the drift this introduces is small; it would compound over a real production window and should be revisited — a paid plan, or a provider with historical support — before this number is used for anything with money attached to it.

| Market | Currency | Paid dispositions | Value recovered (local) | Value recovered (USD, estimated) |
|---|---|---|---|---|
| Kenya | KES | 3,509 | 962,312 | $6,575.58 |
| Uganda | UGX | 736 | 5,435,466 | $1,541.47 |
| Tanzania | TZS | 1,096 | 7,767,360 | $2,969.64 |
| Nigeria | NGN | 560 | 3,960,567 | $2,920.35 |

### Metric 4 — Top drivers of inbound calls

Every one of the 7,679 calls disposed as `Inbound Team` falls under exactly four `level_one` categories — a clean, tight result:

| level_one | Calls | Share |
|---|---|---|
| Enquiry | 3,851 | 50.1% |
| Service Request | 1,616 | 21.0% |
| Complaints | 1,296 | 16.9% |
| Customer Feedback | 916 | 11.9% |

`level_two` and `level_three` are populated inconsistently (see Data gaps), so I built `fct_inbound_call_drivers` to carry all three levels alongside market and day, letting a BI tool start at level one and drill down live instead of needing a second query for every level.

## 2. Data gaps

Everything below is quantified from the actual extracts, not asserted:

| # | Gap | Quantified |
|---|---|---|
| 1 | **The coding link is unreliable free text.** The only thread from an Ameyo call to its Atlas outcome is an agent manually pasting a call_log_id into a notes field. | Only 4,933 of 10,508 outbound calls (47%) have *any* note at all; of those, 4,695 (95% of notes, 45% of all calls) resolve to a real Atlas call_log_id. The rest is prose, phone numbers, or junk (`"silence"`, `"hung up"`, `"254757421943 254757421943"`). |
| 2 | **Missing `contract_id` on Atlas dispositions.** A disposition with no contract can never be attributed to a payment. | 6,318 of 52,132 (12.1%). |
| 3 | **Missing `customer_id` on Atlas dispositions.** | 1,847 of 52,132 (3.5%). |
| 4 | **Conflicting duplicate agent records with no way to arbitrate.** 29 agents in `Atlas Ameyo Mapping.csv` have two rows differing in `team` and/or `atlas_user_name` — e.g. Kenya's `Joseph.Ojungu` appears once under `Attrition` and separately under `Upsell` — and the file has no timestamp or effective-date column to say which is current. | 29 of 1,589 distinct agents (1.8%). |
| 5 | **Exact-duplicate payment transactions.** Byte-identical rows — same timestamp to the millisecond, contract, provider, amount — almost certainly the same event ingested twice upstream, not two coincidentally identical payments. | 31 rows collapse out of 849,306 (849,306 → 849,275 distinct payments). |
| 6 | **Non-monetary "payments."** Two rows are `provider = MANUAL`, `amount = 0.0` (Nigeria) — these read as ledger adjustments, not real payments. | 2 rows. |
| 7 | **Two coding schemes for the same four markets, never reconciled in the source data.** Ameyo uses `ch_contact_center_id` 1–4; Atlas uses `tenant_id` 1001–1004, and nothing in either file states the mapping. | Every row in both files; bridged here via a hand-built seed, which is itself an assumption. |
| 8 | **Two timezone conventions in one Ameyo field, silently.** `ch_date_added` is local time; every other timestamp in the dataset is UTC, and nothing in the column name signals this. | All 10,508 Ameyo rows. |
| 9 | **A CSV quoting artifact that looks like duplicate rows if you don't parse it correctly.** A lone `"` character sits alone on 8 physical lines in `Atlas Ameyo Mapping.csv`; a spec-correct CSV parser absorbs it as an embedded newline in the *previous* row's last field. A naive line-by-line scan misreads this as a duplicate key. | 8 rows in the agent mapping file; the same pattern likely explains an apparent duplicate `ch_call_id` in the Ameyo extract too. |
| 10 | **`level_two`/`level_three` disposition detail is optional and inconsistently populated** — not a defect by itself, but it limits how far Metric 4 can be drilled for any given call. | Visible directly in `fct_inbound_call_drivers`; not separately quantified here. |
| 11 | **The sample window is narrow and right-censored.** Calls span Aug 4–6; payments span Aug 4–7. Most calls' 3-day payment window hadn't closed *within the extract itself* — though by the time I actually ran the pipeline, all of it had settled (see Metric 2). | 3–4 calendar days of data. |

## 3. Assumptions

Everywhere the brief left a decision open, here's what I chose and why:

- **Coding match rule**: a call is "coded" if *any* digit-run extracted from its notes field exists as a real `call_log_id` in Atlas — checked by existence, not by guessing a digit-length pattern to tell a call_log_id apart from a phone number. If a note contained multiple candidates that all matched real ids (not observed in this extract), I take the smallest one, deterministically.
- **Payment attribution rule (Metrics 2 & 3)**: each payment attributes to its single **nearest-preceding** disposed call on the same contract, within the 3-day window. I chose this specifically because Metric 3 sums money — crediting every call in a multi-call window would double- or triple-count the same shilling of recovered value. The trade-off is real: an earlier call in a sequence that actually prompted the payment gets no credit. I'd rather state that limitation than hide it.
- **"Day" for Metric 1 is the agent's local operational day** (from Ameyo's local timestamp), not a UTC calendar day — a coaching report should group by the day the agent experienced their shift, not by a UTC boundary that can fall mid-shift.
- **Zero-amount `MANUAL` payments are excluded** from Metric 2/3's money and "paid" logic, but kept visible — not deleted — in the staging layer behind an `is_zero_amount` flag.
- **Exact-duplicate payments collapse to one**, keeping whichever copy was ingested first. Since they're byte-identical, which physical copy survives doesn't change any downstream number.
- **Conflicting duplicate agent-mapping rows are resolved deterministically** — preferring a non-blank name, then an alphabetically-last team, purely for reproducibility — **and flagged** via `has_conflicting_source_rows`. There's no timestamp to say which row is actually current, so this is a coin-flip I made visible rather than a silent fix.
- **Country-code bridging** (Ameyo 1–4 ↔ Atlas 1001–1004 ↔ timezone ↔ currency) lives in one seed file, not inferred arithmetically — explicit and testable rather than assumed stable.
- **Timezone conversion assumes fixed, no-DST offsets** (EAT = UTC+3 for Kenya/Uganda/Tanzania, WAT = UTC+1 for Nigeria) — true for all four current markets, so a static offset is safe. It would need revisiting if d.light expands into a market that observes DST.
- **Raw is never transformed, deduplicated, or type-cast at ingestion** — every business column lands as the literal string from the CSV. This was an explicit correction I made mid-build: an earlier version of the loader upserted at ingestion, which both silently collapsed the conflicting-agent evidence in gap #4 and turned out to be a genuine correctness bug — BigQuery's `MERGE` allows duplicate-keyed rows to insert cleanly on a first load but hard-crashes the moment a second file touches the same key. All cleaning, typing, and deduplication now happens explicitly and testably in dbt staging instead.

## 4. How I handled each gap

| Gap | Excluded / Defaulted / Flagged / Modelled around |
|---|---|
| Unreliable coding link (#1) | **Modelled around** — an existence-check against real Atlas ids rather than a fragile pattern match. |
| Missing `contract_id` (#2) | **Excluded** from payment attribution (it's structurally impossible to attribute), but **not deleted** — it stays in `fct_paid_post_call`'s denominator with `is_paid_post_call = false`, so Metric 2's population is the full, honest set of disposed calls. Both cuts, with and without a contract, are computable from the same mart. |
| Missing `customer_id` (#3) | **Flagged** — kept as `NULL` rather than defaulted to a sentinel value that could masquerade as a real id. |
| Conflicting agent duplicates (#4) | **Flagged and defaulted** — one row kept deterministically per agent, with `has_conflicting_source_rows = true` surfaced on every mart that joins to agent identity. |
| Duplicate payments (#5) | **Excluded** — collapsed to one row per exact duplicate in staging, and tested (`unique` on `payment_row_key`) so a regression would fail loudly rather than silently reintroduce the duplication. |
| Zero-amount payments (#6) | **Flagged** (`is_zero_amount`) and **excluded** from money/paid-call logic only — never deleted. |
| Country-code mismatch (#7) | **Modelled around** via a seed table, tested for uniqueness and not-null on both key columns. |
| Timezone mismatch (#8) | **Modelled around** with an explicit UTC conversion in staging, not left as an implicit "everything's roughly UTC" assumption. |
| CSV quoting artifact (#9) | **Modelled around** by using a spec-correct CSV parser instead of naive line-splitting — this resolves it entirely, and no rows were actually lost. |
| Sparse `level_two`/`level_three` (#10) | **Defaulted** to `'Not specified'` rather than left `NULL`, so a `GROUP BY` in a BI tool doesn't silently drop rows. |
| Narrow, right-censored sample window (#11) | **Flagged structurally** — `is_window_closed` is a real column on every row of `fct_paid_post_call`, not just a caveat in this document. |

## 5. Recommendations

**For the call-centre team:**
- **Look at Tanzania's coding rate (5% against Kenya's 65%) before anything else.** It's the largest, most actionable signal in this data, and it reads like a process or access question, not an agent-performance one.
- **Treat Metric 2 and 3 figures for the most recent 3 days as provisional on any daily dashboard.** They will keep moving until the window closes — don't let a Monday number look final on Tuesday.
- **Decide deliberately on the attribution rule.** Nearest-preceding-call under-credits an agent who makes the first of several calls that eventually leads to payment. If the team would rather reward "started the conversation" over "closed it," that's an equally defensible rule — worth an explicit conversation, not a rule I pick silently on your behalf.

**For d.light's engineering team:**
- **Fix the manual copy-paste link between Ameyo and Atlas.** This is the single biggest lever available: 53% of outbound calls have no note in Ameyo at all, meaning the agent never even attempted to paste the id — that alone accounts for most of the 55.3% of calls that end up uncoded. An API-level link — Atlas writing the call_log_id back into Ameyo automatically on disposition, or a shared identifier generated once and used by both systems — would fix Metric 1 at the source, instead of every downstream report needing an ever-cleverer text match.
- **Add a timestamp or effective-date column to the Atlas Ameyo Mapping export.** Without one, the 29 conflicting agent records are fundamentally unresolvable from the data alone — someone has to go ask.
- **Add a real payment identifier to the Payments extract.** A synthetic hash of business columns, which is what this pipeline uses, can't reliably tell a true duplicate transmission apart from two genuinely independent payments that happen to match.
- **Standardize country coding across systems**, or at minimum publish the Ameyo–Atlas mapping as a shared reference table both systems read from, rather than leaving two independent numbering schemes for every future report to bridge on its own.

## What I'd do next with more time

- Move off the free exchangerate-api.com tier (or switch provider) so Metric 3 uses each payment's actual historical rate instead of a flagged estimate.
- Add a couple more Dagster asset checks as real production volume arrives — the ones here (row-count, null-rate, FX freshness) are a reasonable starting set, not a complete one.
- Wire Dagster's asset-check failures into Slack or email so a broken daily run is visible without someone opening the UI.
- Publish `dbt docs generate` somewhere the wider team can browse without needing repo access.
- Confirm with the call-centre team which Metric 2 denominator — all dispositions, or only those with a contract — they actually want as the headline number on a live dashboard, rather than presenting both.
