"""Streamlit dashboard on top of the dbt marts (dlight_analytics_marts.*).

Reads only from the marts -- never raw or staging -- the same layering rule
the rest of this repo follows. Run via `make dashboard` or:

    streamlit run dashboard/streamlit_app.py

Color/chart choices follow the project's data-viz design system: markets get
a fixed categorical color (same market = same color on every chart, in every
tab -- color follows the entity, never the sort order), single-metric
magnitude comparisons (Metric 4) use one sequential hue rather than a
categorical rainbow, and every chart's identity is also carried by a direct
text label so nothing depends on color alone.
"""

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "ingestion"))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from common import get_analytics_dataset, get_bigquery_client, get_project_id

# --------------------------------------------------------------------------
# Palette -- fixed categorical order (validated adjacent-pair CVD-safe), one
# sequential hue for magnitude-only comparisons, and the two status colors.
# See the dataviz skill this was built against for the validation method.
# --------------------------------------------------------------------------
MARKET_ORDER = ["Kenya", "Uganda", "Tanzania", "Nigeria"]
MARKET_COLORS = {
    "Kenya": "#2a78d6",     # categorical slot 1 -- blue
    "Uganda": "#eb6834",    # categorical slot 2 -- orange
    "Tanzania": "#1baf7a",  # categorical slot 3 -- aqua
    "Nigeria": "#eda100",   # categorical slot 4 -- yellow
}
SEQUENTIAL_BLUE = "#2a78d6"
INK_PRIMARY = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
SURFACE = "#fcfcfb"
FONT_FAMILY = "system-ui, -apple-system, 'Segoe UI', sans-serif"

st.set_page_config(page_title="d.light Call-Centre Effectiveness", page_icon="\U0001f4de", layout="wide")


# --------------------------------------------------------------------------
# Data access -- cached; reads only dlight_analytics_marts.*
# --------------------------------------------------------------------------
@st.cache_resource
def _client():
    return get_bigquery_client()


@st.cache_data(ttl=600)
def load_mart(table: str) -> pd.DataFrame:
    project = get_project_id()
    dataset = f"{get_analytics_dataset()}_marts"
    return _client().query(f"SELECT * FROM `{project}.{dataset}.{table}`").to_dataframe()


def _chart_layout(fig: go.Figure, title: str, y_title: str = "", show_legend: bool = False) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, font=dict(size=16, color=INK_PRIMARY)),
        yaxis_title=y_title,
        showlegend=show_legend,
        plot_bgcolor=SURFACE,
        paper_bgcolor=SURFACE,
        font=dict(family=FONT_FAMILY, color=INK_PRIMARY, size=13),
        yaxis=dict(gridcolor=GRIDLINE, gridwidth=1, zeroline=False, tickfont=dict(color=INK_MUTED)),
        xaxis=dict(tickfont=dict(color=INK_SECONDARY), showgrid=False),
        margin=dict(t=50, b=10, l=10, r=10),
        bargap=0.4,
        height=380,
    )
    return fig


def market_bar(df: pd.DataFrame, value_col: str, title: str, y_title: str, as_pct: bool) -> go.Figure:
    """One bar per market, in fixed market order, market's own fixed color.

    x-axis already names each category directly, so a color legend would
    just restate it -- identity here comes from the label, not color alone.
    """
    ordered = df.set_index("market").reindex(MARKET_ORDER).dropna(subset=[value_col]).reset_index()
    colors = [MARKET_COLORS[m] for m in ordered["market"]]
    text = [f"{v:.1%}" if as_pct else f"{v:,.0f}" for v in ordered[value_col]]
    fig = go.Figure(
        go.Bar(
            x=ordered["market"],
            y=ordered[value_col],
            marker=dict(color=colors, line_width=0),
            text=text,
            textposition="outside",
            textfont=dict(color=INK_PRIMARY),
            width=0.5,
            hovertemplate="<b>%{x}</b><br>" + ("%{y:.1%}" if as_pct else "%{y:,.0f}") + "<extra></extra>",
        )
    )
    if as_pct:
        fig.update_yaxes(tickformat=".0%")
    return _chart_layout(fig, title, y_title)


def magnitude_bar(df: pd.DataFrame, x_col: str, value_col: str, title: str, y_title: str) -> go.Figure:
    """Single-hue bar for comparing magnitude across non-market categories
    (e.g. inbound disposition reasons) -- not an identity/categorical job,
    so one sequential hue rather than a multi-color palette.
    """
    ordered = df.sort_values(value_col, ascending=False)
    total = ordered[value_col].sum()
    text = [f"{v:,.0f} ({v / total:.0%})" for v in ordered[value_col]]
    fig = go.Figure(
        go.Bar(
            x=ordered[x_col],
            y=ordered[value_col],
            marker=dict(color=SEQUENTIAL_BLUE, line_width=0),
            text=text,
            textposition="outside",
            textfont=dict(color=INK_PRIMARY),
            width=0.5,
            hovertemplate="<b>%{x}</b><br>%{y:,.0f} calls<extra></extra>",
        )
    )
    return _chart_layout(fig, title, y_title)


# --------------------------------------------------------------------------
# Load marts
# --------------------------------------------------------------------------
try:
    daily = load_mart("agg_daily_summary")
    coding = load_mart("fct_coding_rate")
    paid = load_mart("fct_paid_post_call")
    inbound = load_mart("fct_inbound_call_drivers")
except Exception as exc:  # noqa: BLE001 -- surface any auth/connectivity issue plainly to the viewer
    st.error(
        "Could not reach BigQuery. Confirm `.env` is configured and the marts have been built "
        f"(`make transform`). Details: {exc}"
    )
    st.stop()

# --------------------------------------------------------------------------
# Sidebar filters
# --------------------------------------------------------------------------
st.sidebar.header("Filters")
markets_present = [m for m in MARKET_ORDER if m in set(daily["market"]).union(coding["market"])]
selected_markets = st.sidebar.multiselect("Market", markets_present, default=markets_present)

days_present = sorted(set(daily["day"].dropna()))
selected_days = st.sidebar.multiselect("Day", days_present, default=days_present, format_func=str)

if st.sidebar.button("Refresh data"):
    st.cache_data.clear()
    st.rerun()

st.sidebar.caption(
    "Data covers Aug 4-7, 2026 (a 3-4 day sample extract). "
    "See WRITEUP.md in the repo for data gaps, assumptions, and recommendations."
)


def _filter(df: pd.DataFrame, market_col: str = "market", day_col: str | None = "day") -> pd.DataFrame:
    out = df[df[market_col].isin(selected_markets)]
    if day_col and day_col in out.columns and selected_days:
        out = out[out[day_col].isin(selected_days)]
    return out


daily_f = _filter(daily)
coding_f = _filter(coding, day_col="call_date_local")
paid_f = _filter(paid, market_col="country_name", day_col=None)
if selected_days:
    paid_f = paid_f[pd.to_datetime(paid_f["disposed_at_utc"]).dt.date.isin(selected_days)]

# --------------------------------------------------------------------------
# Header + KPI row
# --------------------------------------------------------------------------
st.title("d.light Call-Centre Effectiveness")
st.caption("Kenya · Uganda · Tanzania · Nigeria — built on `dlight_analytics_marts`")

total_outbound = int(daily_f["total_outbound_calls"].sum())
coded_calls = int(daily_f["coded_calls"].sum())
coding_rate = coded_calls / total_outbound if total_outbound else None

total_dispositions = int(daily_f["total_dispositions"].sum())
paid_count = int(daily_f["paid_post_call_count"].sum())
paid_rate = paid_count / total_dispositions if total_dispositions else None

value_usd = daily_f["value_recovered_usd"].sum(min_count=1)
value_usd_estimated = bool(daily_f["value_recovered_usd_is_estimated"].fillna(False).any())
inbound_total = int(daily_f["inbound_call_count"].sum())
still_in_window = int(daily_f["still_in_window_count"].sum())

k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("Outbound calls", f"{total_outbound:,}")
k2.metric("Coding rate", f"{coding_rate:.1%}" if coding_rate is not None else "—")
k3.metric("Paid post call", f"{paid_rate:.1%}" if paid_rate is not None else "—")
if pd.notna(value_usd):
    k4.metric(
        "Value recovered (USD)",
        f"${value_usd:,.0f}" + (" *" if value_usd_estimated else ""),
        help=(
            "* Converted using the latest available rate, not the historical rate for each "
            "payment's actual date — the configured exchangerate-api.com plan doesn't include "
            "historical lookups. See WRITEUP.md Metric 3."
            if value_usd_estimated
            else "Converted using each payment's own historical-date exchange rate."
        ),
    )
else:
    k4.metric(
        "Value recovered (USD)",
        "Unavailable",
        help="Requires a live exchangerate-api.com key (EXCHANGE_RATE_API_KEY). "
        "Shows local-currency figures per market in the Metric 2 & 3 tab instead.",
    )
k5.metric("Inbound calls", f"{inbound_total:,}")

if still_in_window > 0:
    st.warning(
        f"⚠ {still_in_window:,} disposed calls are still inside their 3-day payment window "
        "— paid-post-call status for those is provisional and will change on the next daily run."
    )
else:
    st.success(
        "✓ Every disposition in the current selection has a closed 3-day payment window "
        "— these figures are final, not provisional."
    )

st.divider()

tab1, tab2, tab3 = st.tabs(["Metric 1 · Coding rate", "Metrics 2 & 3 · Paid post call", "Metric 4 · Inbound drivers"])

# --------------------------------------------------------------------------
# Tab 1 -- Coding rate
# --------------------------------------------------------------------------
with tab1:
    by_market = (
        coding_f.groupby("market", as_index=False)[["total_outbound_calls", "coded_calls"]].sum()
    )
    by_market["coding_rate"] = by_market["coded_calls"] / by_market["total_outbound_calls"]

    left, right = st.columns([2, 3])
    with left:
        st.plotly_chart(
            market_bar(by_market, "coding_rate", "Coding rate by market", "% of outbound calls coded", as_pct=True),
            use_container_width=True,
        )
    with right:
        st.caption(
            "Tanzania's coding rate is far below the other three markets in this sample — "
            "see WRITEUP.md §1 for why that's the single most actionable number here."
        )
        st.dataframe(
            by_market.sort_values("coding_rate"),
            column_config={
                "market": "Market",
                "total_outbound_calls": st.column_config.NumberColumn("Outbound calls", format="%d"),
                "coded_calls": st.column_config.NumberColumn("Coded", format="%d"),
                "coding_rate": st.column_config.ProgressColumn(
                    "Coding rate", format="%.1f%%", min_value=0, max_value=1
                ),
            },
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("By agent and campaign")
    st.caption(
        "Coaching detail — sort any column; this is the (day, market, campaign, agent) grain the brief asked for."
    )
    detail_cols = [
        "call_date_local", "market", "campaign_name", "agent_ameyo_user_id", "agent_name",
        "agent_team", "total_outbound_calls", "coded_calls", "coding_rate", "agent_has_conflicting_mapping",
    ]
    st.dataframe(
        coding_f[detail_cols].sort_values("coding_rate"),
        column_config={
            "call_date_local": "Day",
            "market": "Market",
            "campaign_name": "Campaign",
            "agent_ameyo_user_id": "Agent (Ameyo id)",
            "agent_name": "Agent name",
            "agent_team": "Team",
            "total_outbound_calls": st.column_config.NumberColumn("Outbound calls", format="%d"),
            "coded_calls": st.column_config.NumberColumn("Coded", format="%d"),
            "coding_rate": st.column_config.ProgressColumn("Coding rate", format="%.1f%%", min_value=0, max_value=1),
            "agent_has_conflicting_mapping": st.column_config.CheckboxColumn(
                "Conflicting mapping?",
                help="This agent has 2+ rows in Atlas Ameyo Mapping.csv with no way to tell "
                "which is current — see WRITEUP.md gap #4.",
            ),
        },
        hide_index=True,
        use_container_width=True,
        height=350,
    )

# --------------------------------------------------------------------------
# Tab 2 -- Paid post call + value recovered
# --------------------------------------------------------------------------
with tab2:
    by_market_paid = (
        paid_f.groupby("country_name", as_index=False)
        .agg(
            total_dispositions=("call_log_id", "count"),
            # pandas 'count' skips NaN -- this is exactly the attributable population
            with_contract=("contract_id", "count"),
            paid_post_call=("is_paid_post_call", "sum"),
            value_recovered_local=("attributed_payment_amount_local", "sum"),
            value_recovered_usd=("attributed_payment_amount_usd", "sum"),
            value_recovered_usd_is_estimated=("used_estimated_fx_rate", "any"),
            currency_code=("currency_code", "first"),
        )
        .rename(columns={"country_name": "market"})
    )
    # Denominator is dispositions WITH a contract_id, not all dispositions:
    # ~12% have no contract_id and can never be attributed to a payment, so
    # including them would understate the rate against a population that was
    # never reachable in the first place. Matches WRITEUP.md §1's headline
    # table exactly -- the full-population cut is still visible via the
    # "Dispositions" column for anyone who wants that denominator instead.
    by_market_paid["paid_post_call_rate"] = by_market_paid["paid_post_call"] / by_market_paid["with_contract"]

    left, right = st.columns([2, 3])
    with left:
        st.plotly_chart(
            market_bar(
                by_market_paid, "paid_post_call_rate", "Paid post call by market",
                "% of dispositions-with-a-contract paid within 3 days", as_pct=True,
            ),
            use_container_width=True,
        )
    with right:
        st.caption(
            "Rate is over dispositions **with a contract_id** (the only ones a payment could possibly "
            "attribute to) — 12.1% of all dispositions have none; see WRITEUP.md gap #2. Attribution rule: "
            "each payment credits its single nearest-preceding disposed call on the same contract, within "
            "3 days — see WRITEUP.md §3 for why."
        )
        paid_display_cols = ["market", "total_dispositions", "with_contract", "paid_post_call", "paid_post_call_rate"]
        st.dataframe(
            by_market_paid[paid_display_cols].sort_values("market"),
            column_config={
                "market": "Market",
                "total_dispositions": st.column_config.NumberColumn("All dispositions", format="%d"),
                "with_contract": st.column_config.NumberColumn("With a contract", format="%d"),
                "paid_post_call": st.column_config.NumberColumn("Paid post call", format="%d"),
                "paid_post_call_rate": st.column_config.ProgressColumn(
                    "Rate (of with-contract)", format="%.1f%%", min_value=0, max_value=1
                ),
            },
            hide_index=True,
            use_container_width=True,
        )

    st.subheader("Value recovered, by market")
    any_estimated = bool(by_market_paid["value_recovered_usd_is_estimated"].fillna(False).any())
    st.caption(
        "Local-currency figure shown first — summing KES/UGX/TZS/NGN on one axis would imply "
        "comparability that doesn't exist. USD alongside it for cross-market comparison"
        + (
            " — marked * where converted at the latest available rate rather than each payment's own "
            "historical-date rate (the configured exchangerate-api.com plan has no historical lookup); "
            "see WRITEUP.md §3."
            if any_estimated
            else "."
        )
    )
    money_cols = st.columns(len(by_market_paid)) if len(by_market_paid) else []
    for col, (_, row) in zip(money_cols, by_market_paid.sort_values("market").iterrows()):
        star = " *" if row["value_recovered_usd_is_estimated"] else ""
        usd_line = (
            f"${row['value_recovered_usd']:,.0f}{star}" if pd.notna(row["value_recovered_usd"]) else "USD unavailable"
        )
        col.metric(f"{row['market']} ({row['currency_code']})", f"{row['value_recovered_local']:,.0f}")
        col.caption(usd_line)

# --------------------------------------------------------------------------
# Tab 3 -- Inbound drivers (drill-down)
# --------------------------------------------------------------------------
with tab3:
    inbound_f = inbound[inbound["market"].isin(selected_markets)]
    if selected_days:
        inbound_f = inbound_f[inbound_f["disposition_date_utc"].isin(selected_days)]

    level_one_agg = inbound_f.groupby("level_one", as_index=False)["call_count"].sum()

    st.plotly_chart(
        magnitude_bar(
            level_one_agg, "level_one", "call_count",
            "What are customers calling about? (level 1)", "Inbound calls",
        ),
        use_container_width=True,
    )

    if not level_one_agg.empty:
        l1_options = level_one_agg.sort_values("call_count", ascending=False)["level_one"]
        chosen_l1 = st.selectbox("Drill into level 1:", l1_options, index=0)

        l2_df = (
            inbound_f[inbound_f["level_one"] == chosen_l1]
            .groupby("level_two", as_index=False)["call_count"]
            .sum()
        )
        if not l2_df.empty:
            st.plotly_chart(
                magnitude_bar(l2_df, "level_two", "call_count", f'"{chosen_l1}" → level 2', "Inbound calls"),
                use_container_width=True,
            )

            l2_options = l2_df.sort_values("call_count", ascending=False)["level_two"]
            chosen_l2 = st.selectbox("Drill into level 2:", l2_options, index=0)
            l3_df = (
                inbound_f[(inbound_f["level_one"] == chosen_l1) & (inbound_f["level_two"] == chosen_l2)]
                .groupby("level_three", as_index=False)["call_count"]
                .sum()
            )
            if not l3_df.empty:
                l3_title = f'"{chosen_l1}" → "{chosen_l2}" → level 3'
                st.plotly_chart(
                    magnitude_bar(l3_df, "level_three", "call_count", l3_title, "Inbound calls"),
                    use_container_width=True,
                )
