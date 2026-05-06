"""
CO₂ Sensor Dashboard — Streamlit
=================================
Updated with all latest improvements:
  - Zero / invalid readings filtered out automatically
  - Dynamic Y-axis min floored at 300 ppm (not hard-coded)
  - Distinct zone colours: Good (green) · Moderate (yellow) · Elevated (burnt-orange) · High (deep crimson)
  - Per-day sections when data spans multiple days
  - Office-hours pie chart (10 AM – 10 PM) + Non-office-hours pie chart per day
  - Sidebar controls: configurable office hours start/end

Install:
    pip install streamlit boto3 pandas plotly

Run:
    streamlit run app.py
"""

import io
import time
import boto3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
import streamlit as st
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key

# ── Config ────────────────────────────────────────────────────────────────────
REGION    = "eu-north-1"
TABLE     = "CO2Readings"
DEVICE_ID = "S88GH_CO2_Sensor"

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday"]

ZONES = [
    (0,    800,  "Good",     "#27ae60", "rgba(46,204,113,0.15)"),
    (800,  1000, "Moderate", "#d4ac0d", "rgba(241,196,15,0.22)"),
    (1000, 1200, "Elevated", "#d35400", "rgba(211,84,0,0.15)"),
    (1200, 99999,"High",     "#7b0020", "rgba(100,0,20,0.18)"),
]

CARD_META = [
    ("Good",     "< 800 ppm",       "#edfaf3", "#27ae60"),
    ("Moderate", "800 – 1000 ppm",  "#fefce8", "#d4ac0d"),
    ("Elevated", "1000 – 1200 ppm", "#fff3e8", "#d35400"),
    ("High",     "≥ 1200 ppm",      "#fdf0f0", "#7b0020"),
]

PIE_COLORS = ["#27ae60", "#d4ac0d", "#d35400", "#7b0020"]
PIE_LABELS = ["Good <800", "Moderate 800–1000", "Elevated 1000–1200", "High ≥1200"]

# ── Helpers ───────────────────────────────────────────────────────────────────
def classify(ppm: int) -> str:
    for lo, hi, label, *_ in ZONES:
        if lo <= ppm < hi:
            return label
    return "High"

def dot_color(ppm: int) -> str:
    for lo, hi, _, color, *_ in ZONES:
        if lo <= ppm < hi:
            return color
    return "#7b0020"

def level_counts(df: pd.DataFrame) -> dict:
    return {
        "Good":     int((df["co2_ppm"] < 800).sum()),
        "Moderate": int(((df["co2_ppm"] >= 800)  & (df["co2_ppm"] < 1000)).sum()),
        "Elevated": int(((df["co2_ppm"] >= 1000) & (df["co2_ppm"] < 1200)).sum()),
        "High":     int((df["co2_ppm"] >= 1200).sum()),
    }

# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=0)
def fetch_dynamodb() -> pd.DataFrame:
    ddb   = boto3.resource(
        "dynamodb",
        region_name=REGION,
        aws_access_key_id=st.secrets["aws"]["access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
    )
    table  = ddb.Table(TABLE)
    items  = []
    kwargs = {"KeyConditionExpression": Key("device_id").eq(DEVICE_ID)}
    while True:
        resp = table.query(**kwargs)
        items.extend(resp["Items"])
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
    rows = [
        {"timestamp_utc": datetime.fromtimestamp(int(r["ts"]) / 1000, tz=timezone.utc),
         "co2_ppm":       int(r.get("co2_ppm", 0))}
        for r in items
    ]
    return pd.DataFrame(rows).sort_values("timestamp_utc").reset_index(drop=True)

def load_csv(file) -> pd.DataFrame:
    df = pd.read_csv(file)
    df["timestamp_utc"] = pd.to_datetime(df["timestamp_utc"], utc=True)
    return df.sort_values("timestamp_utc").reset_index(drop=True)

def filter_invalid(df: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    before = len(df)
    df = df[df["co2_ppm"] > 0].reset_index(drop=True)
    return df, before - len(df)

# ── Charts ────────────────────────────────────────────────────────────────────
def line_chart(day_df: pd.DataFrame, tz_offset: int) -> go.Figure:
    loc   = day_df["timestamp_utc"] + pd.Timedelta(hours=tz_offset)
    y_min = max(300, (day_df["co2_ppm"].min() // 50) * 50 - 50)
    y_max = (day_df["co2_ppm"].max() // 50) * 50 + 100

    fig = go.Figure()

    # Coloured background zones
    for lo, hi, label, color, fill in ZONES:
        y0 = max(lo, y_min)
        y1 = min(hi, y_max)
        if y0 >= y1:
            continue
        fig.add_hrect(
            y0=y0, y1=y1,
            fillcolor=fill, line_width=0,
            annotation_text=label,
            annotation_position="right",
            annotation=dict(font_size=10, font_color=color),
        )

    # Dashed zone boundary lines
    for boundary in [800, 1000, 1200]:
        if y_min < boundary < y_max:
            fig.add_hline(
                y=boundary,
                line=dict(color="rgba(0,0,0,0.15)", width=1, dash="dot"),
            )

    # Data line
    fig.add_trace(go.Scatter(
        x=loc,
        y=day_df["co2_ppm"],
        mode="lines+markers",
        line=dict(color="#2c3e50", width=2),
        marker=dict(
            color=[dot_color(v) for v in day_df["co2_ppm"]],
            size=5,
            line=dict(color="white", width=1),
        ),
        hovertemplate="%{x|%H:%M}<br><b>%{y} ppm</b><extra></extra>",
    ))

    fig.update_layout(
        height=320,
        margin=dict(l=0, r=80, t=10, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(
            showgrid=True,
            gridcolor="#f0f0f0",
            ticksuffix=" ppm",
            range=[y_min, y_max],
        ),
    )
    return fig

def bar_chart(counts: dict) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=["Good<br><800", "Moderate<br>800–1000",
           "Elevated<br>1000–1200", "High<br>≥1200"],
        y=[counts["Good"], counts["Moderate"], counts["Elevated"], counts["High"]],
        marker_color=["#27ae60", "#d4ac0d", "#d35400", "#7b0020"],
        marker_line_width=0,
        hovertemplate="%{y} readings<extra></extra>",
    ))
    fig.update_layout(
        height=260,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
    )
    return fig

def pie_chart(counts: dict, title: str) -> go.Figure:
    values = [counts["Good"], counts["Moderate"], counts["Elevated"], counts["High"]]
    total  = sum(values)

    if total == 0:
        fig = go.Figure(go.Pie(
            labels=["No data"],
            values=[1],
            marker_colors=["#e0e0e0"],
            textinfo="label",
            hoverinfo="skip",
        ))
    else:
        fig = go.Figure(go.Pie(
            labels=PIE_LABELS,
            values=values,
            marker=dict(colors=PIE_COLORS, line=dict(color="white", width=2)),
            textinfo="percent",
            hovertemplate="%{label}<br><b>%{value} readings</b> (%{percent})<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=12), x=0, xanchor="left"),
        height=280,
        margin=dict(l=0, r=0, t=36, b=0),
        paper_bgcolor="white",
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="bottom", y=-0.35,
            xanchor="center", x=0.5,
            font=dict(size=10),
        ),
    )
    return fig

def level_card_html(name, rng, count, pct, bg, border) -> str:
    return f"""
<div style="border-left:4px solid {border};border-radius:8px;
            padding:12px 14px;background:{bg};margin-bottom:8px">
  <div style="font-size:12px;font-weight:600;color:#444">{name}</div>
  <div style="font-size:11px;color:#888;margin-bottom:6px">{rng}</div>
  <div style="font-size:1.5rem;font-weight:700;color:{border}">{count}</div>
  <div style="font-size:11px;color:#aaa">{pct}% of readings</div>
</div>"""

# ── Page setup ────────────────────────────────────────────────────────────────
st.set_page_config(page_title="CO₂ Monitor", page_icon="🌿", layout="wide")
st.markdown("""<style>
  [data-testid="metric-container"] {
    background:#fff; border:1px solid #e8ecf0;
    border-radius:10px; padding:1rem;
  }
  [data-testid="stMetricLabel"]  { font-size:.75rem!important; text-transform:uppercase;
                                   letter-spacing:.05em; color:#888; }
  [data-testid="stMetricValue"]  { font-size:1.55rem!important; }
  [data-testid="stMetricDelta"]  { font-size:.78rem!important; }
  .day-divider {
    border-left: 4px solid #378ADD;
    padding-left: 0.75rem;
    margin: 1.5rem 0 0.25rem;
  }
</style>""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️  Settings")
    source = st.radio("Data source", ["🔴  Live (DynamoDB)", "📁  CSV file"])

    tz_offset = st.number_input("UTC offset (hours)", value=5,
                                min_value=-12, max_value=14, step=1)
    tz_label  = f"UTC+{tz_offset}" if tz_offset >= 0 else f"UTC{tz_offset}"

    st.divider()
    st.markdown("**Office hours**")
    office_start = st.slider("Start hour", 0, 23, 10)
    office_end   = st.slider("End hour",   0, 23, 22)
    st.caption(f"Office hours: {office_start:02d}:00 – {office_end:02d}:00")

    uploaded     = None
    auto_refresh = False
    refresh_min  = 2

    if "Live" in source:
        st.divider()
        auto_refresh = st.toggle("Auto-refresh", value=False)
        if auto_refresh:
            refresh_min = st.slider("Refresh every (minutes)", 1, 30, 2)
    else:
        st.divider()
        uploaded = st.file_uploader("Upload CSV", type=["csv"])

# ── Load data ─────────────────────────────────────────────────────────────────
df = pd.DataFrame()

if "Live" in source:
    with st.spinner("Fetching from DynamoDB…"):
        try:
            df = fetch_dynamodb()
            st.sidebar.caption(f"Last fetched: {datetime.now().strftime('%H:%M:%S')}")
        except Exception as exc:
            st.error(f"DynamoDB error: {exc}")
            st.stop()
else:
    if uploaded is None:
        st.info("📁  Upload a CSV file in the sidebar to view the dashboard.")
        st.stop()
    df = load_csv(uploaded)

if df.empty:
    st.warning("No data found.")
    st.stop()

# Filter zeros/invalid
df, removed = filter_invalid(df)
if df.empty:
    st.warning("All readings were zero or invalid.")
    st.stop()

# Localise timestamps and split by day
df["ts_local"]   = df["timestamp_utc"] + pd.Timedelta(hours=tz_offset)
df["date_local"] = df["ts_local"].dt.date
days             = sorted(df["date_local"].unique())
total_all        = len(df)

# ── Page header ───────────────────────────────────────────────────────────────
st.title("CO₂ Office Air Quality Dashboard")

date_range = (
    df["ts_local"].iloc[0].strftime("%B %d, %Y")
    if len(days) == 1
    else f"{df['ts_local'].iloc[0].strftime('%B %d, %Y')} – "
         f"{df['ts_local'].iloc[-1].strftime('%B %d, %Y')}"
)
st.caption(
    f"{date_range}  ·  {tz_label}  ·  "
    f"{total_all} readings across {len(days)} day(s)"
    + (f"  ·  {removed} zero readings excluded" if removed else "")
)

# ── Per-day sections ──────────────────────────────────────────────────────────
for day_date in days:
    day_df   = df[df["date_local"] == day_date].copy()
    day_name = DAYS[pd.Timestamp(day_date).weekday()]
    total    = len(day_df)

    mean_ppm  = round(day_df["co2_ppm"].mean())
    max_idx   = day_df["co2_ppm"].idxmax()
    min_idx   = day_df["co2_ppm"].idxmin()
    latest    = day_df.iloc[-1]
    duration  = (day_df["ts_local"].iloc[-1] - day_df["ts_local"].iloc[0]).total_seconds() / 3600
    counts    = level_counts(day_df)
    pcts      = {k: round(v / total * 100) if total else 0 for k, v in counts.items()}

    # Office / non-office split
    hour          = day_df["ts_local"].dt.hour
    office_df     = day_df[(hour >= office_start) & (hour < office_end)]
    non_office_df = day_df[(hour < office_start)  | (hour >= office_end)]
    oc            = level_counts(office_df)
    noc           = level_counts(non_office_df)
    oc_total      = sum(oc.values())
    noc_total     = sum(noc.values())

    # ── Day heading ──────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="day-divider">'
        f'<h2 style="margin:0;font-size:1.15rem;font-weight:700;">'
        f'{day_name} · {day_date.strftime("%B %d, %Y")}</h2>'
        f'<p style="margin:2px 0 0;font-size:0.8rem;color:#888;">'
        f'{day_df["ts_local"].iloc[0].strftime("%I:%M %p").lstrip("0")} – '
        f'{day_df["ts_local"].iloc[-1].strftime("%I:%M %p").lstrip("0")} {tz_label}'
        f' · {total} readings over {duration:.1f} h</p>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Metrics ──────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Average CO₂",   f"{mean_ppm} ppm")
    c2.metric("Peak CO₂",
              f"{day_df.loc[max_idx, 'co2_ppm']} ppm",
              f"at {day_df.loc[max_idx, 'ts_local'].strftime('%I:%M %p').lstrip('0')}")
    c3.metric("Minimum CO₂",
              f"{day_df.loc[min_idx, 'co2_ppm']} ppm",
              f"at {day_df.loc[min_idx, 'ts_local'].strftime('%I:%M %p').lstrip('0')}")
    c4.metric("Latest Reading",
              f"{int(latest['co2_ppm'])} ppm",
              classify(int(latest["co2_ppm"])))

    st.write("")

    # ── Line chart ────────────────────────────────────────────────────────────
    st.subheader("CO₂ Trend Over Time")
    st.plotly_chart(line_chart(day_df, tz_offset), use_container_width=True,
                    key=f"line_{day_date}")

    # ── Level cards + bar chart ───────────────────────────────────────────────
    col_l, col_r = st.columns(2)
    with col_l:
        st.subheader("Air Quality Level Breakdown")
        for name, rng, bg, border in CARD_META:
            st.markdown(
                level_card_html(name, rng, counts[name], pcts[name], bg, border),
                unsafe_allow_html=True,
            )
    with col_r:
        st.subheader("Readings per Level")
        st.plotly_chart(bar_chart(counts), use_container_width=True,
                        key=f"bar_{day_date}")

    # ── Pie charts ────────────────────────────────────────────────────────────
    pie_l, pie_r = st.columns(2)
    with pie_l:
        st.plotly_chart(
            pie_chart(oc,  f"☀️ Office Hours  ({office_start:02d}:00–{office_end:02d}:00)  ·  {oc_total} readings"),
            use_container_width=True,
            key=f"pie_office_{day_date}",
        )
    with pie_r:
        st.plotly_chart(
            pie_chart(noc, f"🌙 Non-Office Hours  ·  {noc_total} readings"),
            use_container_width=True,
            key=f"pie_non_{day_date}",
        )

    # ── Raw data expander ─────────────────────────────────────────────────────
    with st.expander("Show raw data for this day"):
        st.dataframe(
            day_df[["ts_local", "co2_ppm"]].rename(
                columns={"ts_local": f"Timestamp ({tz_label})", "co2_ppm": "CO₂ (ppm)"}
            ),
            use_container_width=True,
        )

    st.divider()

# ── Download (all data) ───────────────────────────────────────────────────────
buf = io.StringIO()
df[["ts_local", "co2_ppm"]].rename(
    columns={"ts_local": "timestamp_local", "co2_ppm": "co2_ppm"}
).to_csv(buf, index=False)

st.download_button(
    "⬇️  Download full CSV",
    data=buf.getvalue(),
    file_name=f"co2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_min * 60)
    fetch_dynamodb.clear()
    st.rerun()
