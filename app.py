"""
CO₂ Sensor Dashboard — Streamlit  (Streamlit Cloud / deployed version)
=======================================================================
Credentials come from st.secrets (configured in Streamlit Cloud settings).

Install:
    pip install streamlit boto3 pandas plotly

Run locally (requires .streamlit/secrets.toml with [aws] section):
    streamlit run app_cloud.py

Deploy:
    Push to GitHub, connect repo in Streamlit Cloud,
    set secrets under App settings → Secrets.
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

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday",
        "Saturday", "Sunday"]

ZONES = [
    (0,    800,  "Good",     "#27ae60", "rgba(46,204,113,0.15)"),
    (800,  1000, "Moderate", "#d4ac0d", "rgba(241,196,15,0.22)"),
    (1000, 1200, "Elevated", "#d35400", "rgba(211,84,0,0.15)"),
    (1200, 99999,"High",     "#7b0020", "rgba(100,0,20,0.18)"),
]

PIE_COLORS = ["#27ae60", "#d4ac0d", "#d35400", "#7b0020"]
PIE_LABELS = ["Good <800", "Moderate 800–1000", "Elevated 1000–1200", "High ≥1200"]

MIN_DATE = pd.Timestamp("2026-05-05", tz="UTC")

# ── Helpers ───────────────────────────────────────────────────────────────────
def classify(ppm: int) -> str:
    for lo, hi, label, *_ in ZONES:
        if lo <= ppm < hi:
            return label
    return "High"

def zone_color(ppm: int) -> str:
    for lo, hi, _, color, *_ in ZONES:
        if lo <= ppm < hi:
            return color
    return "#7b0020"

def dot_color(ppm: int) -> str:
    return zone_color(ppm)

def level_counts(df: pd.DataFrame) -> dict:
    return {
        "Good":     int((df["co2_ppm"] < 800).sum()),
        "Moderate": int(((df["co2_ppm"] >= 800)  & (df["co2_ppm"] < 1000)).sum()),
        "Elevated": int(((df["co2_ppm"] >= 1000) & (df["co2_ppm"] < 1200)).sum()),
        "High":     int((df["co2_ppm"] >= 1200).sum()),
    }

def parse_ts(ts_val) -> datetime:
    ts = int(ts_val)
    if ts > 10_000_000_000:
        ts = ts // 1000
    return datetime.fromtimestamp(ts, tz=timezone.utc)

# ── Data ──────────────────────────────────────────────────────────────────────
@st.cache_data(ttl=None)
def fetch_dynamodb() -> pd.DataFrame:
    ddb = boto3.resource(
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
        {"timestamp_utc": parse_ts(r["ts"]),
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

    for boundary in [800, 1000, 1200]:
        if y_min < boundary < y_max:
            fig.add_hline(
                y=boundary,
                line=dict(color="rgba(0,0,0,0.15)", width=1, dash="dot"),
            )

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
        height=340,
        margin=dict(l=0, r=80, t=10, b=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                   ticksuffix=" ppm", range=[y_min, y_max]),
    )
    return fig

def pie_chart(counts: dict, title: str) -> go.Figure:
    pairs  = [(l, c, v) for (l, c, v) in zip(PIE_LABELS, PIE_COLORS,
               [counts["Good"], counts["Moderate"], counts["Elevated"], counts["High"]]) if v > 0]
    total  = sum(v for *_, v in pairs)

    if total == 0:
        fig = go.Figure(go.Pie(
            labels=["No data"], values=[1],
            marker_colors=["#e0e0e0"], textinfo="label", hoverinfo="skip",
        ))
    else:
        labels, colors, values = zip(*pairs)
        fig = go.Figure(go.Pie(
            labels=list(labels), values=list(values),
            marker=dict(colors=list(colors), line=dict(color="white", width=2)),
            textinfo="percent",
            hole=0.55,
            hovertemplate="%{label}<br><b>%{value} readings</b> (%{percent})<extra></extra>",
        ))

    fig.update_layout(
        title=dict(text=title, font=dict(size=11), x=0, xanchor="left"),
        height=160,
        margin=dict(l=0, r=0, t=28, b=0),
        paper_bgcolor="white",
        showlegend=False,
    )
    return fig

def analysis_pie_chart(counts: dict) -> go.Figure:
    pairs = [(l, c, v) for (l, c, v) in zip(PIE_LABELS, PIE_COLORS,
              [counts["Good"], counts["Moderate"], counts["Elevated"], counts["High"]]) if v > 0]
    total = sum(v for *_, v in pairs)

    if total == 0:
        fig = go.Figure(go.Pie(labels=["No data"], values=[1],
                               marker_colors=["#e0e0e0"], textinfo="label", hoverinfo="skip"))
    else:
        labels, colors, values = zip(*pairs)
        fig = go.Figure(go.Pie(
            labels=list(labels), values=list(values),
            marker=dict(colors=list(colors), line=dict(color="white", width=2)),
            textinfo="percent", hole=0.52,
            hovertemplate="%{label}<br><b>%{value} readings</b> (%{percent})<extra></extra>",
        ))
    fig.update_layout(
        height=280, margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="white", showlegend=True,
        legend=dict(orientation="h", yanchor="bottom", y=-0.35,
                    xanchor="center", x=0.5, font=dict(size=10)),
    )
    return fig

def analysis_line_chart(daily_avg: pd.Series) -> go.Figure:
    vals  = daily_avg.values
    y_min = max(300, (int(min(vals)) // 50) * 50 - 50)
    y_max = (int(max(vals)) // 50) * 50 + 100

    fig = go.Figure()

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

    for boundary in [800, 1000, 1200]:
        if y_min < boundary < y_max:
            fig.add_hline(
                y=boundary,
                line=dict(color="rgba(0,0,0,0.15)", width=1, dash="dot"),
            )

    fig.add_trace(go.Scatter(
        x=daily_avg.index.astype(str),
        y=vals,
        mode="lines+markers",
        line=dict(color="#2c3e50", width=2),
        marker=dict(
            color=[dot_color(int(v)) for v in vals],
            size=8,
            line=dict(color="white", width=1.5),
        ),
        hovertemplate="%{x}<br><b>%{y} ppm</b><extra></extra>",
    ))

    fig.update_layout(
        height=280,
        margin=dict(l=0, r=80, t=10, b=0),
        paper_bgcolor="white", plot_bgcolor="white",
        showlegend=False,
        xaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0",
                   ticksuffix=" ppm", range=[y_min, y_max]),
    )
    return fig

def analysis_bar_chart(counts: dict) -> go.Figure:
    fig = go.Figure(go.Bar(
        x=["Good<br><800", "Moderate<br>800–1000",
           "Elevated<br>1000–1200", "High<br>≥1200"],
        y=[counts["Good"], counts["Moderate"], counts["Elevated"], counts["High"]],
        marker_color=PIE_COLORS,
        marker_line_width=0,
        hovertemplate="%{y} readings<extra></extra>",
    ))
    fig.update_layout(
        height=280,
        margin=dict(l=0, r=0, t=10, b=0),
        paper_bgcolor="white", plot_bgcolor="white",
        showlegend=False,
        xaxis=dict(showgrid=False),
        yaxis=dict(showgrid=True, gridcolor="#f0f0f0"),
    )
    return fig

# ── Bubble HTML ───────────────────────────────────────────────────────────────
def bubble_html(value: int, label: str) -> str:
    color  = zone_color(value)
    bg     = color + "18"
    border = color + "55"
    return f"""
<div style="display:flex;flex-direction:column;align-items:center;justify-content:center;
            width:72px;height:72px;border-radius:50%;
            background:{bg};border:1.5px solid {border};text-align:center;gap:2px">
  <div style="font-size:1rem;font-weight:600;color:{color};line-height:1">{value}</div>
  <div style="font-size:9px;color:#888;text-transform:uppercase;letter-spacing:.04em;margin-top:2px">{label}</div>
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
    page   = st.radio("Page", ["📅  Daily View", "📊  Analysis"])
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
        if st.button("🔄 Refresh data"):
            st.session_state.pop("df_cache", None)
            fetch_dynamodb.clear()
            st.rerun()
        auto_refresh = st.toggle("Auto-refresh", value=False)
        if auto_refresh:
            refresh_min = st.slider("Refresh every (minutes)", 1, 30, 2)
    else:
        st.divider()
        uploaded = st.file_uploader("Upload CSV", type=["csv"])

# ── Load data ─────────────────────────────────────────────────────────────────
df = pd.DataFrame()

if "Live" in source:
    if "df_cache" not in st.session_state:
        with st.spinner("Fetching from DynamoDB…"):
            try:
                st.session_state.df_cache       = fetch_dynamodb()
                st.session_state.last_fetched   = datetime.now().strftime('%H:%M:%S')
            except Exception as exc:
                st.error(f"DynamoDB error: {exc}")
                st.stop()
    df = st.session_state.df_cache
    st.sidebar.caption(f"Last fetched: {st.session_state.get('last_fetched', '—')}")
else:
    if uploaded is None:
        st.info("📁  Upload a CSV file in the sidebar to view the dashboard.")
        st.stop()
    df = load_csv(uploaded)

if df.empty:
    st.warning("No data found.")
    st.stop()

df, removed = filter_invalid(df)
df = df[df["timestamp_utc"] >= MIN_DATE].reset_index(drop=True)
if df.empty:
    st.warning("All readings were zero or invalid.")
    st.stop()

df["ts_local"]   = df["timestamp_utc"] + pd.Timedelta(hours=tz_offset)
df["date_local"] = df["ts_local"].dt.date
days             = sorted(df["date_local"].unique())
total_all        = len(df)

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 1 — DAILY VIEW
# ══════════════════════════════════════════════════════════════════════════════
if "Daily" in page:
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

    for day_date in days:
        day_df   = df[df["date_local"] == day_date].copy()
        day_name = DAYS[pd.Timestamp(day_date).weekday()]
        total    = len(day_df)

        mean_ppm = round(day_df["co2_ppm"].mean())
        max_ppm  = int(day_df["co2_ppm"].max())
        min_ppm  = int(day_df["co2_ppm"].min())
        duration = (day_df["ts_local"].iloc[-1] - day_df["ts_local"].iloc[0]).total_seconds() / 3600

        hour          = day_df["ts_local"].dt.hour
        office_df     = day_df[(hour >= office_start) & (hour < office_end)]
        non_office_df = day_df[(hour < office_start)  | (hour >= office_end)]
        oc  = level_counts(office_df)
        noc = level_counts(non_office_df)

        st.markdown(f"""
<div style="display:flex;align-items:center;justify-content:space-between;
            background:linear-gradient(135deg,#e8f1fb,#dbeafe);
            border-left:4px solid #378ADD;
            border-radius:12px;padding:1rem 1.5rem;margin-bottom:.75rem">
  <div>
    <div style="font-size:1rem;font-weight:600;color:#1e293b">
      {day_name}
      <span style="font-weight:400;color:#64748b;font-size:.9rem">
        &nbsp;{pd.Timestamp(day_date).strftime("%B %d, %Y")}
      </span>
    </div>
    <div style="font-size:12px;color:#94a3b8;margin-top:3px">
      {day_df["ts_local"].iloc[0].strftime("%I:%M %p").lstrip("0")} –
      {day_df["ts_local"].iloc[-1].strftime("%I:%M %p").lstrip("0")} {tz_label}
      &nbsp;·&nbsp; {total} readings &nbsp;·&nbsp; {duration:.1f} h
    </div>
  </div>
  <div style="display:flex;gap:10px">
    {bubble_html(mean_ppm, "Average")}
    {bubble_html(max_ppm,  "Peak")}
    {bubble_html(min_ppm,  "Min")}
  </div>
</div>
""", unsafe_allow_html=True)

        col_line, col_pies = st.columns([3, 1.2])

        with col_line:
            st.plotly_chart(line_chart(day_df, tz_offset),
                            use_container_width=True, key=f"line_{day_date}")

        with col_pies:
            st.plotly_chart(
                pie_chart(oc,  f"☀️ Office ({office_start:02d}:00–{office_end:02d}:00)"),
                use_container_width=True, key=f"pie_o_{day_date}"
            )
            st.plotly_chart(
                pie_chart(noc, "🌙 Non-office hours"),
                use_container_width=True, key=f"pie_n_{day_date}"
            )

        st.divider()

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

# ══════════════════════════════════════════════════════════════════════════════
# PAGE 2 — ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
else:
    st.title("CO₂ Analysis")

    filter_col1, filter_col2 = st.columns([2, 3])

    with filter_col1:
        period = st.selectbox("Period", ["Weekly", "Monthly", "Yearly", "Custom range"])

    with filter_col2:
        if period == "Custom range":
            date_from, date_to = st.date_input(
                "Date range",
                value=(df["date_local"].min(), df["date_local"].max()),
                min_value=df["date_local"].min(),
                max_value=df["date_local"].max(),
            )
        else:
            last_date = df["date_local"].max()
            last_ts   = pd.Timestamp(last_date)
            if period == "Weekly":
                date_from = (last_ts - pd.Timedelta(days=6)).date()
            elif period == "Monthly":
                date_from = (last_ts - pd.DateOffset(months=1)).date()
            else:
                date_from = (last_ts - pd.DateOffset(years=1)).date()
            date_to = last_date
            st.caption(f"Showing: {date_from} → {date_to}")

    ana_df = df[
        (df["date_local"] >= date_from) &
        (df["date_local"] <= date_to)
    ].copy()

    if ana_df.empty:
        st.warning("No data for selected period.")
        st.stop()

    total_ana  = len(ana_df)
    counts_ana = level_counts(ana_df)
    pct        = lambda v: round(v / total_ana * 100) if total_ana else 0

    c1, c2, c3, c4, c5, c6 = st.columns(6)
    c1.metric("Average CO₂",   f"{round(ana_df['co2_ppm'].mean())} ppm")
    c2.metric("Peak CO₂",      f"{int(ana_df['co2_ppm'].max())} ppm")
    c3.metric("Minimum CO₂",   f"{int(ana_df['co2_ppm'].min())} ppm")
    c4.metric("Good",          f"{pct(counts_ana['Good'])}%",
              f"{counts_ana['Good']} readings")
    c5.metric("Moderate",      f"{pct(counts_ana['Moderate'])}%",
              f"{counts_ana['Moderate']} readings")
    c6.metric("High / Elevated",
              f"{pct(counts_ana['Elevated'] + counts_ana['High'])}%",
              f"{counts_ana['Elevated'] + counts_ana['High']} readings")

    st.write("")

    ch1, ch2 = st.columns(2)

    with ch1:
        st.subheader("Average CO₂ per day")
        daily_avg = ana_df.groupby("date_local")["co2_ppm"].mean().round()
        st.plotly_chart(analysis_line_chart(daily_avg),
                        use_container_width=True, key="ana_line")

    with ch2:
        st.subheader("Level distribution")
        st.plotly_chart(analysis_pie_chart(counts_ana),
                        use_container_width=True, key="ana_pie")

    st.subheader("Readings per level")
    st.plotly_chart(analysis_bar_chart(counts_ana),
                    use_container_width=True, key="ana_bar")


# ── Auto-refresh ──────────────────────────────────────────────────────────────
if auto_refresh:
    time.sleep(refresh_min * 60)
    st.session_state.pop("df_cache", None)
    fetch_dynamodb.clear()
    st.rerun()
