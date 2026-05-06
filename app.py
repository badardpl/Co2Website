"""
CO₂ Sensor Dashboard — Streamlit
=================================
Mirrors the HTML dashboard design (color zones, level cards, metrics,
line chart, bar chart) with live DynamoDB data or a local CSV file.

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
import streamlit as st
from datetime import datetime, timezone
from boto3.dynamodb.conditions import Key

# ── Config ────────────────────────────────────────────────────────────────────
REGION    = "eu-north-1"
TABLE     = "CO2Readings"
DEVICE_ID = "S88GH_CO2_Sensor"

ZONES = [
    (0,    800,  "Good",     "#27ae60", "rgba(46,204,113,0.15)"),
    (800,  1000, "Moderate", "#d4ac0d", "rgba(241,196,15,0.20)"),
    (1000, 1200, "Elevated", "#d35400", "rgba(211,84,0,0.15)"),
    (1200, 99999,"High",     "#7b0020", "rgba(120,0,30,0.20)"),
]

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

# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=0)
def fetch_dynamodb() -> pd.DataFrame:
    ddb   = boto3.resource(
        "dynamodb",
        region_name=REGION,
        aws_access_key_id=st.secrets["aws"]["access_key_id"],
        aws_secret_access_key=st.secrets["aws"]["secret_access_key"],
    )
    table = ddb.Table(TABLE)
    items, kwargs = [], {"KeyConditionExpression": Key("device_id").eq(DEVICE_ID)}
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

# ── Charts ────────────────────────────────────────────────────────────────────
def line_chart(df: pd.DataFrame, tz_offset: int) -> go.Figure:
    loc = df["timestamp_utc"] + pd.Timedelta(hours=tz_offset)
    y_min = max(400, df["co2_ppm"].min() - 60)
    y_max = df["co2_ppm"].max() + 100

    fig = go.Figure()
    for lo, hi, label, color, fill in ZONES:
        fig.add_hrect(
            y0=max(lo, y_min), y1=min(hi, y_max),
            fillcolor=fill, line_width=0,
            annotation_text=label,
            annotation_position="right",
            annotation=dict(font_size=10, font_color=color),
        )
    fig.add_trace(go.Scatter(
        x=loc, y=df["co2_ppm"],
        mode="lines+markers",
        line=dict(color="#2c3e50", width=2),
        marker=dict(color=[dot_color(v) for v in df["co2_ppm"]],
                    size=5, line=dict(color="white", width=1)),
        hovertemplate="%{x|%H:%M}<br><b>%{y} ppm</b><extra></extra>",
    ))
    fig.update_layout(
        height=300, margin=dict(l=0, r=70, t=10, b=0),
        paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                   ticksuffix=" ppm", range=[y_min, y_max]),
    )
    return fig

def bar_chart(counts: dict) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=["Good<br><400–800", "Moderate<br>800–1000",
           "Elevated<br>1000–1200", "High<br>≥1200"],
        y=[counts["Good"], counts["Moderate"], counts["Elevated"], counts["High"]],
        marker_color=["#27ae60", "#d4ac0d", "#d35400", "#7b0020"],
        hovertemplate="%{y} readings<extra></extra>",
    ))
    fig.update_layout(
        height=240, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="white", plot_bgcolor="white", showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
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
</style>""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
    st.title("⚙️  Settings")
    source = st.radio("Data source", ["🔴  Live (DynamoDB)", "📁  CSV file"])

    tz_offset = st.number_input("UTC offset (hours)", value=5,
                                min_value=-12, max_value=14, step=1)
    tz_label = f"UTC+{tz_offset}" if tz_offset >= 0 else f"UTC{tz_offset}"

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

# ── Compute stats ─────────────────────────────────────────────────────────────
df["ts_local"] = df["timestamp_utc"] + pd.Timedelta(hours=tz_offset)

total    = len(df)
mean_ppm = round(df["co2_ppm"].mean())
max_idx  = df["co2_ppm"].idxmax()
min_idx  = df["co2_ppm"].idxmin()
latest   = df.iloc[-1]
duration = (df["ts_local"].iloc[-1] - df["ts_local"].iloc[0]).total_seconds() / 3600

counts = {
    "Good":     int((df["co2_ppm"] < 800).sum()),
    "Moderate": int(((df["co2_ppm"] >= 800)  & (df["co2_ppm"] < 1000)).sum()),
    "Elevated": int(((df["co2_ppm"] >= 1000) & (df["co2_ppm"] < 1200)).sum()),
    "High":     int((df["co2_ppm"] >= 1200).sum()),
}
pcts = {k: round(v / total * 100) for k, v in counts.items()}

# ── Header ────────────────────────────────────────────────────────────────────
st.title("CO₂ Office Air Quality Dashboard")
st.caption(
    f"{df['ts_local'].iloc[0].strftime('%B %d, %Y')}  ·  "
    f"{df['ts_local'].iloc[0].strftime('%H:%M')} – "
    f"{df['ts_local'].iloc[-1].strftime('%H:%M')} {tz_label}  ·  "
    f"{total} readings over {duration:.1f} h"
)

# ── Metrics ───────────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("Average CO₂",   f"{mean_ppm} ppm")
c2.metric("Peak CO₂",      f"{df.loc[max_idx, 'co2_ppm']} ppm",
          f"at {df.loc[max_idx, 'ts_local'].strftime('%H:%M')}")
c3.metric("Minimum CO₂",   f"{df.loc[min_idx, 'co2_ppm']} ppm",
          f"at {df.loc[min_idx, 'ts_local'].strftime('%H:%M')}")
c4.metric("Latest Reading", f"{int(latest['co2_ppm'])} ppm",
          classify(int(latest["co2_ppm"])))

st.write("")

# ── Line chart ────────────────────────────────────────────────────────────────
st.subheader("CO₂ Trend Over Time")
st.plotly_chart(line_chart(df, tz_offset), use_container_width=True)

# ── Level cards + bar chart ───────────────────────────────────────────────────
col_l, col_r = st.columns(2)

with col_l:
    st.subheader("Air Quality Level Breakdown")
    CARD_META = [
        ("Good",     "< 800 ppm",       "#f0faf4", "#27ae60"),
        ("Moderate", "800 – 1000 ppm",  "#fffbf0", "#d4ac0d"),
        ("Elevated", "1000 – 1200 ppm", "#fff6f0", "#d35400"),
        ("High",     "≥ 1200 ppm",      "#fff0f0", "#7b0020"),
    ]
    for name, rng, bg, border in CARD_META:
        st.markdown(
            level_card_html(name, rng, counts[name], pcts[name], bg, border),
            unsafe_allow_html=True,
        )

with col_r:
    st.subheader("Readings per Level")
    st.plotly_chart(bar_chart(counts), use_container_width=True)

    # Raw data expander
    with st.expander("Show raw data"):
        st.dataframe(
            df[["ts_local", "co2_ppm"]].rename(
                columns={"ts_local": f"timestamp ({tz_label})", "co2_ppm": "co2_ppm"}
            ),
            use_container_width=True,
        )

# ── Download ──────────────────────────────────────────────────────────────────
st.divider()
buf = io.StringIO()
df[["ts_local", "co2_ppm"]].rename(
    columns={"ts_local": "timestamp_local", "co2_ppm": "co2_ppm"}
).to_csv(buf, index=False)

st.download_button(
    "⬇️  Download CSV",
    data=buf.getvalue(),
    file_name=f"co2_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
    mime="text/csv",
)

# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_min * 60)
    fetch_dynamodb.clear()
    st.rerun()
