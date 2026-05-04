"""Streamlit UI for the mortgage calculator.

Layout follows the wireframe mock: inputs on the left, "Plan your mortgage"
headline on top, a downpayment-vs-loan split bar, three KPI cards (Initial
monthly payment / Last monthly payment / Total paid), a monthly-payment-over-
time chart, and a tabs section for Fix / Market forecast / Simulation. The
Simulation tab also exposes editable Prime change and Inflation events.

Track behaviour:
  - Fixed : rate locked, balance not indexed; events ignored.
  - Prime : rate moves with prime-change events; balance not indexed.
  - Float : both prime-change events AND inflation events apply. The inflation
            outlook from the Market forecast tab is **auto-applied yearly**, so
            Float is naturally sensitive to inflation even with no manual
            events.
  - Mixed : split the loan across Fixed / Prime / Float in user-defined
            percentages (default 30/40/30). Each sub-mortgage runs with its
            own track rules, and the schedules are summed.
"""

from __future__ import annotations

from datetime import date

import altair as alt
import pandas as pd
import streamlit as st

from mortgage_calculator import MortgageCalculator


st.set_page_config(
    page_title="Plan your mortgage",
    page_icon="house",
    layout="wide",
    initial_sidebar_state="expanded",
)


CUSTOM_CSS = """
<style>
.block-container { padding-top: 2rem; padding-bottom: 2rem; }
.kpi-card {
    background: linear-gradient(180deg, #ffffff 0%, #f5f7fb 100%);
    border: 1px solid #e6e8ef;
    border-radius: 12px;
    padding: 1.1rem 1.3rem;
    box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04);
    height: 100%;
}
.kpi-label { color: #667085; font-size: 0.85rem; letter-spacing: 0.02em; }
.kpi-value { color: #101828; font-size: 1.7rem; font-weight: 700; margin-top: 0.25rem; }
.kpi-sub { color: #98a2b3; font-size: 0.8rem; margin-top: 0.15rem; }
.section-header { color: #344054; font-weight: 600; margin-top: 0.5rem; }
.tagline { color: #667085; margin-top: -0.5rem; }
hr.soft { border: none; border-top: 1px solid #eef0f4; margin: 1rem 0 0.5rem; }
</style>
"""

st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ---------------------------------------------------------------------------
# Track rules and styling
# ---------------------------------------------------------------------------
TRACK_RULES: dict[str, dict[str, bool]] = {
    "Fixed": {"prime": False, "inflation": False},
    "Prime": {"prime": True, "inflation": False},
    "Float": {"prime": True, "inflation": True},
}

TRACK_COLORS = {
    "Fixed": "#7F56D9",
    "Prime": "#2E90FA",
    "Float": "#F79009",
    "Total": "#101828",
    "Baseline": "#98a2b3",
}


# ---------------------------------------------------------------------------
# Session-state initialization (must happen BEFORE the calculation block so
# both the calc and the editors see the same values)
# ---------------------------------------------------------------------------
def _empty_prime_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[ns]"),
        "change_bp": pd.Series(dtype="float"),
    })


def _empty_inflation_df() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.Series(dtype="datetime64[ns]"),
        "inflation_pct": pd.Series(dtype="float"),
    })


def _coerce_event_df(df: pd.DataFrame, value_col: str) -> pd.DataFrame:
    """Streamlit's `st.data_editor` returns a DataFrame whose `date` column
    dtype can collapse to `object` once the user adds an empty row, which then
    makes the next render reject the DateColumn config. This coerces the
    dtypes back to `datetime64[ns]` / `float` so re-feeding the editor is
    safe."""
    if df is None:
        return _empty_prime_df() if value_col == "change_bp" else _empty_inflation_df()
    out = df.copy()
    if "date" not in out.columns:
        out["date"] = pd.Series(dtype="datetime64[ns]")
    if value_col not in out.columns:
        out[value_col] = pd.Series(dtype="float")
    out["date"] = pd.to_datetime(out["date"], errors="coerce")
    out[value_col] = pd.to_numeric(out[value_col], errors="coerce").astype("float64")
    return out[["date", value_col]]


if "prime_events" not in st.session_state:
    st.session_state.prime_events = _empty_prime_df()
if "inflation_events" not in st.session_state:
    st.session_state.inflation_events = _empty_inflation_df()
if "yield_curve" not in st.session_state:
    st.session_state.yield_curve = pd.DataFrame({
        "tenor_years": [1, 2, 5, 10, 20, 30],
        "rate_pct": [4.0, 4.1, 4.3, 4.5, 4.6, 4.7],
    })
if "inflation_curve" not in st.session_state:
    _this_year = date.today().year
    st.session_state.inflation_curve = pd.DataFrame({
        "year": list(range(_this_year, _this_year + 6)),
        "inflation_pct": [3.0, 2.8, 2.5, 2.3, 2.2, 2.0],
    })


# ---------------------------------------------------------------------------
# Sidebar inputs
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### Plan your mortgage")
    st.caption("We can help you buying your dream house")

    total_amount = st.number_input(
        "Total amount",
        min_value=50_000,
        max_value=20_000_000,
        value=1_000_000,
        step=10_000,
        format="%d",
    )

    downpayment = st.number_input(
        "Down payment",
        min_value=0,
        max_value=int(total_amount),
        value=min(int(total_amount * 0.30), int(total_amount)),
        step=10_000,
        format="%d",
    )

    loan_amount = max(int(total_amount) - int(downpayment), 0)
    st.metric("Loan amount", f"{loan_amount:,.0f}")

    years = st.slider("Years", min_value=5, max_value=30, value=25, step=1)

    track_type = st.radio(
        "Track type",
        options=["Fixed", "Prime", "Float", "Mixed"],
        horizontal=True,
        help=(
            "Fixed = rate locked for the term, balance not indexed. "
            "Prime = rate moves with prime-change events, balance not indexed. "
            "Float = variable rate AND balance auto-indexed to the inflation "
            "forecast. "
            "Mixed = split the loan across Fixed / Prime / Float."
        ),
    )

    TRACK_BLURBS = {
        "Fixed": "Rate locked for the term. Prime change and inflation events are ignored.",
        "Prime": "Prime-change events shift the rate. Inflation events are ignored.",
        "Float": "Prime-change events shift the rate. Balance is **auto-indexed** to the inflation outlook (Market forecast tab); manual inflation events compound on top.",
        "Mixed": "Split the loan across Fixed / Prime / Float. Each part is computed independently and the schedules are summed.",
    }
    st.caption(TRACK_BLURBS[track_type])

    # Mixed-mode percentage inputs
    components: dict[str, float] = {}
    mix_warning: str | None = None
    if track_type == "Mixed":
        st.markdown("**Allocation**")
        c1, c2, c3 = st.columns(3)
        pct_fixed = c1.number_input("% Fixed", min_value=0, max_value=100, value=30, step=5)
        pct_prime = c2.number_input("% Prime", min_value=0, max_value=100, value=40, step=5)
        pct_float = c3.number_input("% Float", min_value=0, max_value=100, value=30, step=5)
        total_pct = pct_fixed + pct_prime + pct_float
        if total_pct != 100:
            mix_warning = f"Percentages must sum to 100% (currently {total_pct}%)."
            st.error(mix_warning)
        components = {
            "Fixed": pct_fixed / 100.0,
            "Prime": pct_prime / 100.0,
            "Float": pct_float / 100.0,
        }
    else:
        components = {track_type: 1.0}

    interest_pct = st.slider(
        "Interest (%)",
        min_value=0.0,
        max_value=15.0,
        value=4.0,
        step=0.05,
    )

    start_date_value: date = st.date_input(
        "Start date",
        value=date.today().replace(day=1),
    )


# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
header_left, header_right = st.columns([0.7, 0.3])
with header_left:
    st.markdown("# Plan your mortgage")
    st.markdown(
        "<p class='tagline'>We can help you buying your dream house</p>",
        unsafe_allow_html=True,
    )
with header_right:
    if track_type == "Mixed":
        mix_summary = " / ".join(
            f"{int(round(v*100))}% {k}" for k, v in components.items() if v > 0
        )
        track_badge_html = f"Allocation: {mix_summary or '—'}"
    else:
        rules_for_header = TRACK_RULES[track_type]
        badges = []
        badges.append("rate \u2191\u2193 with prime" if rules_for_header["prime"] else "rate locked")
        badges.append("balance auto-indexed to CPI" if rules_for_header["inflation"] else "balance not indexed")
        track_badge_html = " &middot; ".join(badges)

    st.markdown(
        f"<div style='text-align:right;color:#667085;margin-top:1.2rem'>"
        f"Track: <b>{track_type}</b> &nbsp;|&nbsp; "
        f"Rate: <b>{interest_pct:.2f}%</b> &nbsp;|&nbsp; "
        f"Term: <b>{years}y</b><br/>"
        f"<span style='font-size:0.8rem'>{track_badge_html}</span></div>",
        unsafe_allow_html=True,
    )

st.markdown("<hr class='soft'/>", unsafe_allow_html=True)


# Guards
if loan_amount <= 0:
    st.warning("Down payment covers the entire amount; no loan to plan. "
               "Reduce the down payment to model a mortgage.")
    st.stop()
if mix_warning:
    st.stop()


# ---------------------------------------------------------------------------
# Event normalization and forecast helpers
# ---------------------------------------------------------------------------
def _normalize_events(df: pd.DataFrame, value_col: str) -> list[tuple[date, float]]:
    if df is None or df.empty:
        return []
    out: list[tuple[date, float]] = []
    for _, row in df.iterrows():
        d = row.get("date")
        v = row.get(value_col)
        if pd.isna(d) or pd.isna(v):
            continue
        d = pd.Timestamp(d).date()
        out.append((d, float(v)))
    out.sort(key=lambda t: t[0])
    return out


def _auto_inflation_events_from_forecast(
    start: date,
    years_n: int,
    forecast_df: pd.DataFrame,
) -> pd.DataFrame:
    """Generate one yearly inflation event per anniversary, looking up the
    expected % from the inflation outlook for that calendar year. Returns an
    empty DataFrame when no forecast is available."""
    if forecast_df is None or forecast_df.empty:
        return _empty_inflation_df()
    f = forecast_df.dropna()
    if f.empty:
        return _empty_inflation_df()
    yearly = dict(zip(f["year"].astype(int), f["inflation_pct"].astype(float)))
    rows = []
    # range(1, years_n) -> events at year 1, 2, ..., years_n - 1.
    # Year `years_n` would fall one period past the last scheduled payment.
    for i in range(1, years_n):
        ev_date = date(start.year + i, start.month, 1)
        infl = yearly.get(ev_date.year)
        if infl is None or infl <= 0:
            continue
        rows.append({"date": pd.Timestamp(ev_date), "inflation_pct": float(infl)})
    if not rows:
        return _empty_inflation_df()
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Calculation: single track and combined (mixed)
# ---------------------------------------------------------------------------
def build_calculator(
    rate_pct: float,
    years_n: int,
    loan: float,
    start: date,
    track: str,
    prime_df: pd.DataFrame,
    inflation_df: pd.DataFrame,
) -> tuple[MortgageCalculator, list[str]]:
    """Build & run a single-track calculator. Events not allowed by the track
    are silently dropped."""
    warnings: list[str] = []
    rules = TRACK_RULES[track]
    mc = MortgageCalculator(
        interest=rate_pct / 100.0,
        years=years_n,
        mortgage=loan,
        start_date=start,
    )
    mc.calc_mortgage_params()
    mc.calc_payments()

    prime_events = _normalize_events(prime_df, "change_bp") if rules["prime"] else []
    inflation_events = (
        _normalize_events(inflation_df, "inflation_pct") if rules["inflation"] else []
    )

    combined: list[tuple[date, str, float]] = (
        [(d, "prime", v) for d, v in prime_events]
        + [(d, "inflation", v) for d, v in inflation_events]
    )
    combined.sort(key=lambda t: t[0])

    payment_dates_set = set(mc.mortgage_df["payment date"].dt.date.tolist())

    for event_date, kind, value in combined:
        if event_date <= start:
            warnings.append(
                f"[{track}] Skipped {kind} event on {event_date}: not after start date."
            )
            continue
        if event_date not in payment_dates_set:
            warnings.append(
                f"[{track}] Skipped {kind} event on {event_date}: not on a "
                f"scheduled payment date (use the 1st of a month within the "
                f"loan term)."
            )
            continue
        try:
            if kind == "prime":
                mc.prime_change(
                    new_interest=value / 10_000.0,  # bp -> fraction
                    new_interest_period=event_date,
                )
            else:  # inflation
                mc.add_inflation(
                    inflation=value / 100.0,  # percent -> fraction
                    inflation_date=event_date,
                )
        except Exception as exc:  # pragma: no cover - defensive
            warnings.append(f"[{track}] Failed {kind} on {event_date}: {exc}")

    return mc, warnings


def build_components(
    components: dict[str, float],
    rate_pct: float,
    years_n: int,
    loan: float,
    start: date,
    prime_df: pd.DataFrame,
    inflation_df: pd.DataFrame,
    inflation_forecast_df: pd.DataFrame,
) -> tuple[pd.DataFrame, dict[str, dict], list[str], pd.DataFrame]:
    """Run a calculator per active track and return:
        (combined_df, per_track, warnings, auto_inflation_events_used)

    `combined_df` has the same schema as a single-track schedule, with all
    numeric columns summed across tracks (and `payment date` shared).
    `per_track[name]` -> {"share", "loan", "df"}.
    """
    warnings: list[str] = []
    per_track: dict[str, dict] = {}
    auto_events_for_float = _empty_inflation_df()

    active = {k: v for k, v in components.items() if v > 0}
    if not active:
        # Should be unreachable due to upstream guards
        raise ValueError("At least one component must have a positive share.")

    for track, share in active.items():
        sub_loan = loan * share

        # For Float, auto-apply inflation forecast. Manual events compound on
        # top by being concatenated with the auto-generated ones.
        if track == "Float":
            auto = _auto_inflation_events_from_forecast(start, years_n, inflation_forecast_df)
            auto_events_for_float = auto.copy()
            sub_inflation_df = pd.concat([auto, inflation_df], ignore_index=True)
        else:
            sub_inflation_df = inflation_df

        mc, w = build_calculator(
            rate_pct=rate_pct,
            years_n=years_n,
            loan=sub_loan,
            start=start,
            track=track,
            prime_df=prime_df,
            inflation_df=sub_inflation_df,
        )
        warnings.extend(w)
        per_track[track] = {
            "share": share,
            "loan": sub_loan,
            "df": mc.mortgage_df.copy(),
        }

    # Build combined schedule by summing numeric columns across tracks.
    first_df = next(iter(per_track.values()))["df"]
    combined = pd.DataFrame({"payment date": pd.to_datetime(first_df["payment date"])})
    numeric_cols = ["payment", "principal_paid", "interest_paid",
                    "start_balance", "ending_balance"]
    for col in numeric_cols:
        combined[col] = sum(t["df"][col].to_numpy() for t in per_track.values())

    return combined, per_track, warnings, auto_events_for_float


# Coerce the editor-backed event DataFrames before consuming them. Streamlit's
# data_editor can yield mixed dtypes once the user adds an empty row.
st.session_state.prime_events = _coerce_event_df(
    st.session_state.prime_events, "change_bp"
)
st.session_state.inflation_events = _coerce_event_df(
    st.session_state.inflation_events, "inflation_pct"
)

df, per_track, calc_warnings, auto_inflation_events = build_components(
    components=components,
    rate_pct=interest_pct,
    years_n=years,
    loan=loan_amount,
    start=start_date_value,
    prime_df=st.session_state.prime_events,
    inflation_df=st.session_state.inflation_events,
    inflation_forecast_df=st.session_state.inflation_curve,
)


# ---------------------------------------------------------------------------
# Down / Loan / Interest split bar
# ---------------------------------------------------------------------------
total_interest = float(df["interest_paid"].sum())
total_principal = float(df["principal_paid"].sum())
total_cost = float(downpayment) + total_principal + total_interest

split_df = pd.DataFrame(
    [
        {"segment": "Downpayment", "amount": float(downpayment), "order": 1},
        {"segment": "Loan principal", "amount": total_principal, "order": 2},
        {"segment": "Total interest", "amount": total_interest, "order": 3},
    ]
)
split_df["share"] = split_df["amount"] / max(total_cost, 1e-9)

split_chart = (
    alt.Chart(split_df)
    .mark_bar(size=36, cornerRadius=6)
    .encode(
        x=alt.X("amount:Q", stack="normalize",
                axis=alt.Axis(format="%", title=None, grid=False)),
        color=alt.Color(
            "segment:N",
            scale=alt.Scale(
                domain=["Downpayment", "Loan principal", "Total interest"],
                range=["#7F56D9", "#2E90FA", "#F79009"],
            ),
            legend=alt.Legend(orient="bottom", title=None),
        ),
        order=alt.Order("order:Q"),
        tooltip=[
            alt.Tooltip("segment:N", title="Segment"),
            alt.Tooltip("amount:Q", format=",.0f", title="Amount"),
            alt.Tooltip("share:Q", format=".1%", title="Share"),
        ],
    )
    .properties(height=110)
)

st.markdown("#### Downpayment / Loan / Interest")
st.altair_chart(split_chart, width="stretch")

split_cols = st.columns(3)
for col, (_, row) in zip(split_cols, split_df.iterrows()):
    with col:
        st.markdown(
            f"<div class='kpi-card'>"
            f"<div class='kpi-label'>{row['segment']}</div>"
            f"<div class='kpi-value'>{row['amount']:,.0f}</div>"
            f"<div class='kpi-sub'>{row['share']*100:.1f}% of total cost</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------
st.markdown("<br/>", unsafe_allow_html=True)

active_payments = df.loc[df["start_balance"] > 0, "payment"]
initial_payment = float(active_payments.iloc[0]) if not active_payments.empty else 0.0
last_payment = float(active_payments.iloc[-1]) if not active_payments.empty else 0.0
total_paid = float(df["payment"].sum())

kpi_cols = st.columns(3)
kpi_data = [
    ("Initial monthly payment", initial_payment, "first scheduled payment"),
    ("Last monthly payment", last_payment, "final scheduled payment"),
    ("Total paid", total_paid, "principal + interest over term"),
]
for col, (label, value, sub) in zip(kpi_cols, kpi_data):
    with col:
        st.markdown(
            f"<div class='kpi-card'>"
            f"<div class='kpi-label'>{label}</div>"
            f"<div class='kpi-value'>{value:,.0f}</div>"
            f"<div class='kpi-sub'>{sub}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )


# ---------------------------------------------------------------------------
# Monthly payment over time (prominent — shows prime spikes clearly)
# ---------------------------------------------------------------------------
st.markdown("<br/>", unsafe_allow_html=True)
st.markdown("#### Monthly payment over time")

if track_type == "Mixed" and len(per_track) > 1:
    # Stacked area: per-track payment + total line on top.
    rows = []
    for name, t in per_track.items():
        sub = t["df"][["payment date", "payment"]].copy()
        sub["payment date"] = pd.to_datetime(sub["payment date"])
        sub["track"] = name
        rows.append(sub)
    payments_long = pd.concat(rows, ignore_index=True)

    track_order = [k for k in ["Fixed", "Prime", "Float"] if k in per_track]
    stacked = (
        alt.Chart(payments_long)
        .mark_area(opacity=0.85)
        .encode(
            x=alt.X("payment date:T", title=None),
            y=alt.Y("payment:Q", title="Monthly payment", stack="zero"),
            color=alt.Color(
                "track:N",
                scale=alt.Scale(
                    domain=track_order,
                    range=[TRACK_COLORS[t] for t in track_order],
                ),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            order=alt.Order("track:N"),
            tooltip=[
                alt.Tooltip("payment date:T", title="Date"),
                alt.Tooltip("track:N", title="Track"),
                alt.Tooltip("payment:Q", format=",.2f", title="Payment"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(stacked, width="stretch")
else:
    # Single track: line chart.
    line_df = df[["payment date", "payment"]].copy()
    line_df["payment date"] = pd.to_datetime(line_df["payment date"])
    only = next(iter(per_track.keys()))
    color = TRACK_COLORS.get(only, "#2E90FA")
    line_chart = (
        alt.Chart(line_df)
        .mark_line(color=color, strokeWidth=2.5, interpolate="step-after")
        .encode(
            x=alt.X("payment date:T", title=None),
            y=alt.Y("payment:Q", title="Monthly payment"),
            tooltip=[
                alt.Tooltip("payment date:T", title="Date"),
                alt.Tooltip("payment:Q", format=",.2f", title="Payment"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(line_chart, width="stretch")


# ---------------------------------------------------------------------------
# Per-component breakdown (Mixed only)
# ---------------------------------------------------------------------------
if track_type == "Mixed":
    st.markdown("##### Per component")
    comp_cols = st.columns(len(per_track))
    for col, (name, t) in zip(comp_cols, per_track.items()):
        sub = t["df"]
        sub_initial = float(sub.loc[sub["start_balance"] > 0, "payment"].iloc[0]) if not sub.loc[sub["start_balance"] > 0].empty else 0.0
        sub_last = float(sub.loc[sub["start_balance"] > 0, "payment"].iloc[-1]) if not sub.loc[sub["start_balance"] > 0].empty else 0.0
        sub_total = float(sub["payment"].sum())
        with col:
            st.markdown(
                f"<div class='kpi-card'>"
                f"<div class='kpi-label'>{name} &middot; {int(round(t['share']*100))}% &middot; "
                f"{t['loan']:,.0f}</div>"
                f"<div class='kpi-value' style='color:{TRACK_COLORS[name]}'>{sub_total:,.0f}</div>"
                f"<div class='kpi-sub'>initial {sub_initial:,.0f} &nbsp;\u2192&nbsp; last {sub_last:,.0f}</div>"
                f"</div>",
                unsafe_allow_html=True,
            )


# ---------------------------------------------------------------------------
# Tabs: Fix / Market forecast / Simulation
# ---------------------------------------------------------------------------
st.markdown("<br/>", unsafe_allow_html=True)
tab_fix, tab_forecast, tab_sim = st.tabs(["Fix", "Market forecast", "Simulation"])


# ---- Fix ----
with tab_fix:
    st.markdown("##### Remaining balance")
    plot_df = df[["payment date", "payment", "principal_paid", "interest_paid",
                  "start_balance", "ending_balance"]].copy()
    plot_df["payment date"] = pd.to_datetime(plot_df["payment date"])

    if track_type == "Mixed" and len(per_track) > 1:
        # Per-track stacked balances.
        rows = []
        for name, t in per_track.items():
            sub = t["df"][["payment date", "ending_balance"]].copy()
            sub["payment date"] = pd.to_datetime(sub["payment date"])
            sub["track"] = name
            rows.append(sub)
        balances_long = pd.concat(rows, ignore_index=True)
        track_order = [k for k in ["Fixed", "Prime", "Float"] if k in per_track]
        balance_chart = (
            alt.Chart(balances_long)
            .mark_area(opacity=0.85)
            .encode(
                x=alt.X("payment date:T", title=None),
                y=alt.Y("ending_balance:Q", title="Remaining balance", stack="zero"),
                color=alt.Color(
                    "track:N",
                    scale=alt.Scale(
                        domain=track_order,
                        range=[TRACK_COLORS[t] for t in track_order],
                    ),
                    legend=alt.Legend(orient="bottom", title=None),
                ),
                order=alt.Order("track:N"),
                tooltip=[
                    alt.Tooltip("payment date:T", title="Date"),
                    alt.Tooltip("track:N", title="Track"),
                    alt.Tooltip("ending_balance:Q", format=",.0f", title="Balance"),
                ],
            )
            .properties(height=260)
        )
    else:
        balance_chart = (
            alt.Chart(plot_df)
            .mark_area(opacity=0.55, color="#2E90FA")
            .encode(
                x=alt.X("payment date:T", title=None),
                y=alt.Y("ending_balance:Q", title="Remaining balance"),
                tooltip=[
                    alt.Tooltip("payment date:T", title="Date"),
                    alt.Tooltip("ending_balance:Q", format=",.0f", title="Balance"),
                ],
            )
            .properties(height=260)
        )
    st.altair_chart(balance_chart, width="stretch")

    payment_breakdown = plot_df.melt(
        id_vars=["payment date"],
        value_vars=["principal_paid", "interest_paid"],
        var_name="component",
        value_name="amount",
    )
    payment_breakdown["component"] = payment_breakdown["component"].map({
        "principal_paid": "Principal",
        "interest_paid": "Interest",
    })
    breakdown_chart = (
        alt.Chart(payment_breakdown)
        .mark_area()
        .encode(
            x=alt.X("payment date:T", title=None),
            y=alt.Y("amount:Q", title="Monthly payment"),
            color=alt.Color(
                "component:N",
                scale=alt.Scale(
                    domain=["Principal", "Interest"],
                    range=["#2E90FA", "#F79009"],
                ),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                alt.Tooltip("payment date:T", title="Date"),
                alt.Tooltip("component:N", title="Component"),
                alt.Tooltip("amount:Q", format=",.2f", title="Amount"),
            ],
        )
        .properties(height=240)
    )
    st.markdown("##### Payment composition (combined)")
    st.altair_chart(breakdown_chart, width="stretch")

    with st.expander("Show full schedule (combined)"):
        display_df = plot_df.copy()
        display_df["payment date"] = display_df["payment date"].dt.strftime("%Y-%m-%d")
        for c in ["payment", "principal_paid", "interest_paid",
                  "start_balance", "ending_balance"]:
            display_df[c] = display_df[c].round(2)
        st.dataframe(display_df, width="stretch", hide_index=False)


# ---- Market forecast ----
with tab_forecast:
    st.markdown("##### Market forecast")
    st.caption(
        "Sketch a yield curve and inflation outlook here. The inflation "
        "outlook is **automatically applied yearly** to the Float component "
        "of your mortgage."
    )

    fc_left, fc_right = st.columns(2)

    with fc_left:
        st.markdown("**Yield curve (years \u2192 expected rate %)**")
        yc = st.data_editor(
            st.session_state.yield_curve,
            num_rows="dynamic",
            width="stretch",
            column_config={
                "tenor_years": st.column_config.NumberColumn("Tenor (years)", min_value=0, step=1),
                "rate_pct": st.column_config.NumberColumn("Rate (%)", min_value=0.0, max_value=20.0, step=0.05, format="%.2f"),
            },
            key="yield_curve_editor",
        )
        st.session_state.yield_curve = yc

        yc_clean = yc.dropna()
        if not yc_clean.empty:
            yc_chart = (
                alt.Chart(yc_clean)
                .mark_line(point=True, color="#7F56D9")
                .encode(
                    x=alt.X("tenor_years:Q", title="Tenor (years)"),
                    y=alt.Y("rate_pct:Q", title="Rate (%)"),
                    tooltip=[
                        alt.Tooltip("tenor_years:Q", title="Tenor"),
                        alt.Tooltip("rate_pct:Q", format=".2f", title="Rate %"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(yc_chart, width="stretch")

    with fc_right:
        st.markdown("**Inflation outlook (year \u2192 expected %)**")
        ic = st.data_editor(
            st.session_state.inflation_curve,
            num_rows="dynamic",
            width="stretch",
            column_config={
                "year": st.column_config.NumberColumn("Year", step=1),
                "inflation_pct": st.column_config.NumberColumn("Inflation (%)", step=0.1, format="%.2f"),
            },
            key="inflation_curve_editor",
        )
        st.session_state.inflation_curve = ic

        ic_clean = ic.dropna()
        if not ic_clean.empty:
            ic_chart = (
                alt.Chart(ic_clean)
                .mark_bar(color="#F79009")
                .encode(
                    x=alt.X("year:O", title="Year"),
                    y=alt.Y("inflation_pct:Q", title="Inflation (%)"),
                    tooltip=[
                        alt.Tooltip("year:O", title="Year"),
                        alt.Tooltip("inflation_pct:Q", format=".2f", title="%"),
                    ],
                )
                .properties(height=220)
            )
            st.altair_chart(ic_chart, width="stretch")

        if not auto_inflation_events.empty:
            with st.expander(
                f"Auto-applied inflation events on Float ({len(auto_inflation_events)})",
                expanded=False,
            ):
                show = auto_inflation_events.copy()
                show["date"] = pd.to_datetime(show["date"]).dt.strftime("%Y-%m-%d")
                st.dataframe(show, width="stretch", hide_index=True)
        elif "Float" in components and components["Float"] > 0:
            st.caption(
                "_No inflation events were auto-applied — fill in the outlook "
                "above to make Float grow with CPI._"
            )


# ---- Simulation ----
with tab_sim:
    st.markdown("##### Financial simulations")
    st.caption(
        "Add **Prime change** events (basis points added to the rate) and "
        "**Inflation** events (percent applied to the remaining balance). "
        "Events must fall on a scheduled payment date (the 1st of a month "
        "within the loan term)."
    )

    # Determine which event editors are active for the current track / mix.
    if track_type == "Mixed":
        prime_active = components.get("Prime", 0) > 0 or components.get("Float", 0) > 0
        inflation_active = components.get("Float", 0) > 0
        active_label = ", ".join(
            f"{int(round(v*100))}% {k}" for k, v in components.items() if v > 0
        )
        st.info(
            f"**Mixed allocation:** {active_label}. "
            f"Prime events affect: {[k for k,v in components.items() if v>0 and TRACK_RULES[k]['prime']] or '—'}. "
            f"Inflation events affect: {[k for k,v in components.items() if v>0 and TRACK_RULES[k]['inflation']] or '—'}."
        )
    else:
        rules = TRACK_RULES[track_type]
        prime_active = rules["prime"]
        inflation_active = rules["inflation"]
        st.info(
            f"**Track: {track_type}** \u2014 "
            + ("rate moves with prime-change events" if prime_active else "rate locked")
            + ", "
            + ("balance grows with inflation events" if inflation_active else "balance not indexed")
            + ". "
            + ("Disabled editors below have no effect on this track."
               if not (prime_active and inflation_active) else "")
        )

    sim_left, sim_right = st.columns(2)

    with sim_left:
        prime_label = "**Prime change events**" + (
            "" if prime_active
            else f"  &nbsp;<span style='color:#98a2b3'>(disabled for {track_type})</span>"
        )
        st.markdown(prime_label, unsafe_allow_html=True)
        prime_edit = st.data_editor(
            st.session_state.prime_events,
            num_rows="dynamic" if prime_active else "fixed",
            width="stretch",
            disabled=not prime_active,
            column_config={
                "date": st.column_config.DateColumn("Effective date"),
                "change_bp": st.column_config.NumberColumn(
                    "Change (bp)",
                    help="Basis points added to the current rate. e.g. 25 = +0.25%",
                    step=5.0,
                    format="%.0f",
                ),
            },
            key="prime_events_editor",
        )
        if prime_active:
            st.session_state.prime_events = _coerce_event_df(prime_edit, "change_bp")
            if st.button("Clear prime events", key="clear_prime"):
                st.session_state.prime_events = _empty_prime_df()
                st.rerun()
        else:
            st.caption(
                "Switch the Track type to **Prime**, **Float**, or a **Mixed** "
                "allocation that includes Prime/Float."
            )

    with sim_right:
        infl_label = "**Inflation events** (additional, on top of the auto-applied forecast)" + (
            "" if inflation_active
            else f"  &nbsp;<span style='color:#98a2b3'>(disabled for {track_type})</span>"
        )
        st.markdown(infl_label, unsafe_allow_html=True)
        inflation_edit = st.data_editor(
            st.session_state.inflation_events,
            num_rows="dynamic" if inflation_active else "fixed",
            width="stretch",
            disabled=not inflation_active,
            column_config={
                "date": st.column_config.DateColumn("Effective date"),
                "inflation_pct": st.column_config.NumberColumn(
                    "Inflation (%)",
                    help="Applied to the remaining balance. e.g. 5 = +5%",
                    step=0.5,
                    format="%.2f",
                ),
            },
            key="inflation_events_editor",
        )
        if inflation_active:
            st.session_state.inflation_events = _coerce_event_df(
                inflation_edit, "inflation_pct"
            )
            if st.button("Clear inflation events", key="clear_inflation"):
                st.session_state.inflation_events = _empty_inflation_df()
                st.rerun()
        else:
            st.caption(
                "Switch the Track type to **Float** or a **Mixed** allocation "
                "that includes Float."
            )

    if calc_warnings:
        with st.expander(f"Warnings ({len(calc_warnings)})", expanded=False):
            for w in calc_warnings:
                st.warning(w)

    # Baseline vs simulation: a single flat-rate mortgage on the full loan.
    st.markdown("###### Compare to a flat-rate baseline")
    baseline = MortgageCalculator(
        interest=interest_pct / 100.0,
        years=years,
        mortgage=loan_amount,
        start_date=start_date_value,
    )
    baseline.calc_mortgage_params()
    baseline.calc_payments()

    baseline_df = baseline.mortgage_df[["payment date", "ending_balance"]].copy()
    baseline_df["payment date"] = pd.to_datetime(baseline_df["payment date"])
    baseline_df["scenario"] = "Baseline"
    sim_df = df[["payment date", "ending_balance"]].copy()
    sim_df["payment date"] = pd.to_datetime(sim_df["payment date"])
    sim_df["scenario"] = "Simulation"

    compare = pd.concat([baseline_df, sim_df], ignore_index=True)

    compare_chart = (
        alt.Chart(compare)
        .mark_line()
        .encode(
            x=alt.X("payment date:T", title=None),
            y=alt.Y("ending_balance:Q", title="Remaining balance"),
            color=alt.Color(
                "scenario:N",
                scale=alt.Scale(
                    domain=["Baseline", "Simulation"],
                    range=["#98a2b3", "#2E90FA"],
                ),
                legend=alt.Legend(orient="bottom", title=None),
            ),
            tooltip=[
                alt.Tooltip("payment date:T", title="Date"),
                alt.Tooltip("scenario:N", title="Scenario"),
                alt.Tooltip("ending_balance:Q", format=",.0f", title="Balance"),
            ],
        )
        .properties(height=260)
    )
    st.altair_chart(compare_chart, width="stretch")

    base_total = float(baseline.mortgage_df["payment"].sum())
    delta = total_paid - base_total
    sim_summary_cols = st.columns(3)
    sim_summary_cols[0].metric("Total paid (sim)", f"{total_paid:,.0f}")
    sim_summary_cols[1].metric("Total paid (baseline)", f"{base_total:,.0f}")
    sim_summary_cols[2].metric(
        "Delta vs baseline",
        f"{delta:,.0f}",
        delta=f"{delta:,.0f}",
        delta_color="inverse",
    )
