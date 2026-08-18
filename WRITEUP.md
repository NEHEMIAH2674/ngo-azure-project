# Write-up

## 1. Answers

All figures below are from the pipeline's actual output against the sample extract (Aug 4–7, 2026), queried directly from the marts in `dlight_analytics_marts`.

### Metric 1 — Coding rate

**44.68%** of outbound calls (4,695 of 10,508) end up disposed of in Atlas.

| Market | Outbound calls | Coded | Rate |
|---|---|---|---|
| Kenya | 5,163 | 3,353 | **64.9%** |
| Nigeria | 1,874 | 604 | 32.2% |
| Uganda | 2,119 | 671 | 31.7% |
| Tanzania | 1,352 | 67 | **5.0%** |

`fct_coding_rate` carries this at (day, market, campaign, agent) grain — 340 rows across 285 distinct agents and 32 campaigns — exactly the breakdown the brief asked for, for agent coaching.

**Tanzania's 5% coding rate is the single most actionable number in this dataset** — three of four outbound calls there aren't even attempted at coding at anywhere near the same rate as Kenya's 65%. That gap alone justifies checking whether it's a training issue, a process issue, or an Ameyo/Atlas access issue specific to that market before assuming it's an agent-performance problem.

### Metric 2 — Paid post call

**11.32%** of all 52,132 Atlas dispositions are followed by a payment on that contract within 3 days. Restricted to the 45,814 dispositions that actually have a `contract_id` (the only ones that *can* be attributed), the rate is **12.88%**.

| Market | Dispositions (w/ contract) | Paid post call | Rate |
|---|---|---|---|
| Kenya | 34,611 | 3,509 | 10.1% |
| Nigeria | 4,113 | 560 | 13.6% |
| Uganda | 3,052 | 736 | 24.1% |
| Tanzania | 4,038 | 1,096 | **27.1%** |

Interesting inversion from Metric 1: Tanzania has by far the worst coding rate but the best paid-post-call rate among coded calls — small numbers (only 67 coded outbound calls total), so treat this as a hypothesis to check with more data, not a conclusion.

**Attribution rule** (this was left open by the brief; see Assumptions below): each payment is attributed to its single nearest-preceding disposed call on the same contract, within the 3-day window.

**Every row in `fct_paid_post_call` currently shows `is_window_closed = true`** — because the sample dates are already in the past relative to when this pipeline actually ran. On a live daily run, the most recent 3 days would show `is_window_closed = false` and should be read as provisional, not final — see the moving-window discussion below.

### Metric 3 — Value recovered from call-centre intervention

**$14,007.04 USD total** across all four markets, once a live `EXCHANGE_RATE_API_KEY` was configured (`ingestion/api/fx/`) — before that, the pipeline correctly returned `NULL` for every `attributed_payment_amount_usd` rather than fabricating a number, by design, not a bug.

**Caveat that matters**: this figure is an *estimate*, not an exact conversion, and the pipeline says so explicitly rather than hiding it. The free tier of exchangerate-api.com doesn't include historical rate lookups, so every conversion here uses the *latest* available rate (as of the fetch), not the rate that actually applied on each payment's own date. Every affected row carries `rate_is_estimated = true` / `rate_source = 'latest_fallback'` in `raw.fx_rates`, and that flag is threaded all the way through to `fct_paid_post_call.used_estimated_fx_rate` and `agg_daily_summary.value_recovered_usd_is_estimated` — the dashboard surfaces it as a visible `*` next to the number, not a footnote. Over a 4-day window the drift this introduces is small, but it would compound on a real production window and should be revisited (a paid plan, or a different provider with historical support) before this number is used for anything with money attached to it.

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

`level_two`/`level_three` are populated inconsistently (see Data gaps) — `fct_inbound_call_drivers` carries all three levels plus market and day so a BI tool can drill down live rather than needing a second query.

## 2. Data gaps

Everything below is quantified, not asserted, from the actual extracts:

| # | Gap | Quantified |
|---|---|---|
| 1 | **Coding link is unreliable free text.** The only thread from an Ameyo call to its Atlas outcome is an agent manually pasting a call_log_id into a notes field. | Only 4,933 of 10,508 outbound calls (47%) have *any* note at all; of those, 4,695 (95% of notes, 45% of all calls) resolve to a real Atlas call_log_id. The rest is prose, phone numbers, or junk (`"silence"`, `"hung up"`, `"254757421943 254757421943"`). |
| 2 | **Missing contract_id on Atlas dispositions.** A disposition with no contract can never be attributed to a payment. | 6,318 of 52,132 (12.1%). |
| 3 | **Missing customer_id on Atlas dispositions.** | 1,847 of 52,132 (3.5%). |
| 4 | **Conflicting duplicate agent records with no way to arbitrate.** 29 agents in `Atlas Ameyo Mapping.csv` have two rows differing in `team` and/or `atlas_user_name` (e.g. Kenya/`Joseph.Ojungu` is `Attrition` in one row, `Upsell` in the other), and the file carries no timestamp or effective-date column to say which is current. | 29 of 1,589 distinct agents (1.8%). |
| 5 | **Exact-duplicate payment transactions.** Byte-identical rows (same timestamp to the millisecond, contract, provider, amount) — almost certainly the same event ingested twice upstream, not two coincidentally identical payments. | 31 rows collapse out of 849,306 (849,306 → 849,275 distinct payments). |
| 6 | **Non-monetary "payments."** Two rows are `provider = MANUAL`, `amount = 0.0` (Nigeria) — read as ledger adjustments, not real payments. | 2 rows. |
| 7 | **Two coding schemes for the same four markets, never reconciled in the source data.** Ameyo uses `ch_contact_center_id` 1–4; Atlas uses `tenant_id` 1001–1004. Nothing in either file states the mapping. | All rows in both files; bridged via a hand-built seed (`country_code_mapping.csv`), an assumption in itself. |
| 8 | **Two timezone conventions in one Ameyo field, silently.** `ch_date_added` is local time; every other timestamp in the dataset is UTC, and nothing in the column name signals this. | All 10,508 Ameyo rows. |
| 9 | **A CSV quoting artifact that looks like duplicate rows if you don't parse it correctly.** A lone `"` character sits alone on 8 physical lines in `Atlas Ameyo Mapping.csv`; a spec-correct CSV parser absorbs it as an embedded newline in the *previous* row's last field. A naive line-by-line scan misreads this as a duplicate key. | 8 rows in agent mapping; the same artifact pattern likely explains an apparent duplicate `ch_call_id` in the Ameyo extract too. |
| 10 | **`level_two`/`level_three` disposition detail is optional and inconsistently populated**, by design per the brief — not itself a defect, but it limits how far Metric 4 can be drilled for any given call. | Not separately quantified here; visible directly in `fct_inbound_call_drivers`. |
| 11 | **The sample window is narrow and right-censored.** Calls span Aug 4–6; payments span Aug 4–7. Most calls' 3-day payment window hadn't closed *within the extract itself* — though by the time this pipeline actually runs, all of it has settled (see Metric 2). | 3–4 calendar days of data. |

## 3. Assumptions

Every place the brief left a decision open, and what was chosen:

- **Coding match rule**: a call is "coded" if *any* digit-run extracted from its notes field exists as a real `call_log_id` in Atlas — checked by existence, not by guessing a digit-length pattern to distinguish a call_log_id from a phone number. If multiple candidates in one note match real ids (not observed in this extract), the smallest is taken, deterministically.
- **Payment attribution rule (Metric 2/3)**: each payment attributes to its single **nearest-preceding** disposed call on the same contract, within {payment window} = 3 days. Chosen specifically because Metric 3 sums money — crediting every call in a multi-call window would double- or triple-count the same shilling of recovered value. Trade-off: an earlier call in a sequence that actually prompted the payment gets no credit; this is a real limitation, not hidden.
- **"Day" for Metric 1 is the agent's local operational day** (from Ameyo's local timestamp), not a UTC calendar day — a coaching report should group by the day the agent experienced their shift, not a UTC boundary that can fall mid-shift.
- **Zero-amount `MANUAL` payments are excluded** from Metric 2/3's money and "paid" logic, but kept visible (not deleted) in the staging layer with an `is_zero_amount` flag.
- **Exact-duplicate payments are collapsed to one**, keeping whichever copy was ingested first — since they're byte-identical, which copy survives doesn't change any number.
- **Conflicting duplicate agent-mapping rows are resolved deterministically** (prefer a non-blank name, then an alphabetically-last team, purely for reproducibility) **and flagged** via `has_conflicting_source_rows` — since there is no timestamp to say which row is actually current, this is a coin-flip made visible, not a hidden fix.
- **Country-code bridging** (Ameyo 1–4 ↔ Atlas 1001–1004 ↔ timezone ↔ currency) lives in one seed file (`country_code_mapping.csv`), not inferred arithmetically — explicit and testable rather than assumed stable.
- **Timezone conversion assumes fixed, no-DST offsets** (EAT = UTC+3 for KE/UG/TZ, WAT = UTC+1 for NG) — true for all four markets, so a static offset is safe; this would need revisiting if d.light ever expands into a market that observes DST.
- **Raw is never transformed, deduplicated, or type-cast at ingestion** — every business column lands as the literal string from the CSV. This was an explicit correction mid-build (an earlier version MERGE-upserted at ingestion, which both silently collapsed the conflicting agent-duplicate evidence in gap #4 *and* was a genuine correctness bug — BigQuery's MERGE permits duplicate-keyed rows to insert cleanly on a first load but hard-crashes on a second file touching the same key). All cleaning/typing/deduplication now happens explicitly and testably in dbt staging.

## 4. How each gap was handled

| Gap | Excluded / Defaulted / Flagged / Modelled around |
|---|---|
| Unreliable coding link (#1) | **Modelled around**: existence-check against real Atlas ids rather than a fragile pattern match. |
| Missing contract_id (#2) | **Excluded** from payment attribution (structurally impossible to attribute), but **not deleted** — stays in `fct_paid_post_call`'s denominator with `is_paid_post_call = false`, so Metric 2's population is the full, honest set of disposed calls. Both cuts (with/without a contract) are computable from the same mart. |
| Missing customer_id (#3) | **Flagged** — kept as `NULL`, not defaulted to a sentinel value that could masquerade as a real id. |
| Conflicting agent duplicates (#4) | **Flagged and defaulted** — one row kept deterministically per agent, `has_conflicting_source_rows = true` surfaced on every mart that joins to agent identity. |
| Duplicate payments (#5) | **Excluded** (collapsed to one row per exact duplicate) in `stg_atlas__payments`, tested (`unique` on `payment_row_key`) so a regression would fail loudly. |
| Zero-amount payments (#6) | **Flagged** (`is_zero_amount`), **excluded** from money/paid-call logic only. |
| Country-code mismatch (#7) | **Modelled around** via the `country_code_mapping` seed, tested for uniqueness/not-null on both key columns. |
| Timezone mismatch (#8) | **Modelled around** — explicit `TIMESTAMP_SUB(..., INTERVAL offset HOUR)` conversion in staging, not left as an implicit "everything's roughly UTC" assumption. |
| CSV quoting artifact (#9) | **Modelled around** — using a spec-correct CSV parser (Python's `csv` module) instead of naive line-splitting resolves it entirely; no rows were actually lost. |
| Sparse level_two/three (#10) | **Defaulted** to `'Not specified'` in `fct_inbound_call_drivers` rather than left `NULL`, so `GROUP BY` in a BI tool doesn't silently drop rows. |
| Narrow/right-censored sample window (#11) | **Flagged structurally**: `is_window_closed` on every row of `fct_paid_post_call`, not just a caveat in this document. |

## 5. Recommendations

**To the call-centre team:**
- **Investigate Tanzania's coding rate (5% vs. Kenya's 65%) before anything else** — this is the largest, most actionable signal in the data, and it's a process/access question, not a modelling one.
- Treat Metric 2/3 figures for the most recent 3 days as provisional on any daily dashboard — they will keep moving. Don't let a Monday number look "final" on Tuesday.
- The nearest-preceding-call attribution rule under-credits agents who make the first of several calls that eventually leads to payment. If the team wants to reward "first contact that started the conversation" rather than "last contact before payment," that's a different, equally defensible rule — worth a explicit conversation, not a silent pick.

**To d.light (upstream, engineering):**
- **Fix the manual copy-paste link between Ameyo and Atlas.** It's the single biggest lever here: 53% of outbound calls currently have no coded outcome at all, purely because of a manual step agents have to remember. An API-level link (Atlas writes the call_log_id back into Ameyo automatically on disposition, or a shared call identifier is generated once and used by both systems) would fix Metric 1 at the source rather than requiring ever-cleverer text matching downstream.
- **Add a timestamp/effective-date column to the Atlas Ameyo Mapping export.** Without one, 29 conflicting agent records are fundamentally unresolvable from data alone — someone has to go ask.
- **Add a real payment identifier** to the Payments extract. A synthetic hash of business columns (what this pipeline uses) can't reliably distinguish a true duplicate transmission from two genuinely independent, coincidentally identical payments.
- **Standardize country coding across systems**, or at minimum publish the Ameyo↔Atlas mapping as a shared reference table both systems read from, instead of leaving two independent numbering schemes to be bridged downstream by whoever builds the next report.
