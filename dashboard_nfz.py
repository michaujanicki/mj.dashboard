from __future__ import annotations

from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

DATA_PATH = Path("data") / "wloclawek_history.csv"


@st.cache_data
def load_history(csv_path: Path) -> pd.DataFrame:
    df = pd.read_csv(csv_path)
    df["observed_at"] = pd.to_datetime(df["observed_at"])

    numeric_cols = [
        "records_count",
        "provider_count",
        "min_wait_days",
        "median_wait_days",
        "mean_wait_days",
    ]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    df = df.sort_values("observed_at").dropna(subset=numeric_cols)
    return df


def kpi_delta(current: float, previous: float) -> float:
    if pd.isna(previous):
        return 0.0
    return current - previous


def recommendation(latest: pd.Series, trend_7d: float, load_ratio: float) -> tuple[str, str]:
    if latest["median_wait_days"] > 55 or trend_7d > 2:
        return (
            "Wysoki priorytet",
            "Czas oczekiwania rośnie. Zalecana szybka korekta harmonogramu i zwiększenie dostępności świadczeń.",
        )
    if load_ratio > 5.0:
        return (
            "Uwaga operacyjna",
            "Obciążenie na świadczeniodawcę jest podwyższone. Warto sprawdzić redistribucję pacjentów.",
        )
    return (
        "Sytuacja stabilna",
        "Parametry są w akceptowalnym zakresie. Zalecany bieżący monitoring bez interwencji natychmiastowej.",
    )


def main() -> None:
    st.set_page_config(
        page_title="Panel ekspercki NFZ - kolejki Włocławek",
        page_icon="📈",
        layout="wide",
    )

    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;600;700&family=IBM+Plex+Serif:wght@500;600&display=swap');

        :root {
            --bg-top: #f2f5f3;
            --bg-bottom: #e8efec;
            --card-bg: rgba(255, 255, 255, 0.82);
            --card-border: rgba(31, 59, 53, 0.15);
            --text-main: #132420;
            --text-soft: #3a524c;
            --accent: #1f7a66;
            --accent-soft: #dcefe8;
            --warn: #b44f32;
        }

        .stApp {
            font-family: 'Manrope', sans-serif;
            background: radial-gradient(circle at 90% 10%, #f7fbf9 0%, transparent 35%),
                        linear-gradient(180deg, var(--bg-top) 0%, var(--bg-bottom) 100%);
            color: var(--text-main);
        }

        h1, h2, h3 {
            font-family: 'IBM Plex Serif', serif;
            color: var(--text-main);
            letter-spacing: 0.2px;
        }

        [data-testid="stMetric"] {
            border: 1px solid var(--card-border);
            border-radius: 14px;
            padding: 0.7rem;
            background: var(--card-bg);
            backdrop-filter: blur(6px);
        }

        .signal {
            border: 1px solid var(--card-border);
            border-left: 4px solid var(--accent);
            border-radius: 12px;
            background: var(--card-bg);
            padding: 0.8rem 1rem;
            color: var(--text-soft);
        }
        </style>
        """,
        unsafe_allow_html=True,
    )

    st.title("Panel ekspercki NFZ: monitoring kolejek")
    st.caption("Zakres: Włocławek, przypadek stabilny (case=1). Widok dla analityka operacyjnego i koordynatora dostępności świadczeń.")

    if not DATA_PATH.exists():
        st.error("Brak pliku danych historycznych: data/wloclawek_history.csv")
        return

    df = load_history(DATA_PATH)
    if df.empty:
        st.error("Plik danych jest pusty albo nie zawiera poprawnych rekordów.")
        return

    with st.sidebar:
        st.header("Filtry")
        min_date = df["observed_at"].min().date()
        max_date = df["observed_at"].max().date()

        date_range = st.date_input(
            "Zakres czasu",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date,
        )

        metric_choice = st.selectbox(
            "Główna metryka trendu",
            options=["median_wait_days", "mean_wait_days", "min_wait_days"],
            format_func=lambda x: {
                "median_wait_days": "Mediana czasu oczekiwania",
                "mean_wait_days": "Średni czas oczekiwania",
                "min_wait_days": "Minimalny czas oczekiwania",
            }[x],
        )

    if isinstance(date_range, tuple) and len(date_range) == 2:
        start_date, end_date = pd.to_datetime(date_range[0]), pd.to_datetime(date_range[1])
    else:
        start_date = pd.to_datetime(min_date)
        end_date = pd.to_datetime(max_date)

    filtered = df[(df["observed_at"] >= start_date) & (df["observed_at"] <= end_date + pd.Timedelta(days=1))].copy()
    if filtered.empty:
        st.warning("Brak danych po zastosowaniu filtrów.")
        return

    filtered["rolling_7d"] = filtered[metric_choice].rolling(7, min_periods=2).mean()

    latest = filtered.iloc[-1]
    prev = filtered.iloc[-2] if len(filtered) > 1 else latest

    trend_7d = latest["median_wait_days"] - filtered["median_wait_days"].iloc[max(0, len(filtered) - 8)]
    load_ratio = latest["records_count"] / max(latest["provider_count"], 1)

    col1, col2, col3, col4 = st.columns(4)
    col1.metric(
        "Mediana oczekiwania (dni)",
        f"{latest['median_wait_days']:.1f}",
        f"{kpi_delta(latest['median_wait_days'], prev['median_wait_days']):+.1f}",
    )
    col2.metric(
        "Średnia oczekiwania (dni)",
        f"{latest['mean_wait_days']:.1f}",
        f"{kpi_delta(latest['mean_wait_days'], prev['mean_wait_days']):+.1f}",
    )
    col3.metric(
        "Liczba rekordów", f"{int(latest['records_count'])}", f"{int(kpi_delta(latest['records_count'], prev['records_count'])):+d}"
    )
    col4.metric(
        "Świadczeniodawcy", f"{int(latest['provider_count'])}", f"{int(kpi_delta(latest['provider_count'], prev['provider_count'])):+d}"
    )

    fig_trend = go.Figure()
    fig_trend.add_trace(
        go.Scatter(
            x=filtered["observed_at"],
            y=filtered[metric_choice],
            mode="lines+markers",
            name="Wartość dzienna",
            line={"color": "#1f7a66", "width": 2.4},
            marker={"size": 6},
        )
    )
    fig_trend.add_trace(
        go.Scatter(
            x=filtered["observed_at"],
            y=filtered["rolling_7d"],
            mode="lines",
            name="Średnia krocząca 7 dni",
            line={"color": "#b44f32", "dash": "dash", "width": 2},
        )
    )
    fig_trend.update_layout(
        title="Trend głównej metryki",
        xaxis_title="Data pomiaru",
        yaxis_title="Dni",
        template="plotly_white",
        legend={"orientation": "h", "y": 1.1},
        margin={"l": 10, "r": 10, "t": 50, "b": 20},
    )

    fig_capacity = px.bar(
        filtered,
        x="observed_at",
        y=["records_count", "provider_count"],
        barmode="group",
        labels={"value": "Wartość", "variable": "Zmienne", "observed_at": "Data"},
        color_discrete_sequence=["#215f54", "#8aa79f"],
        title="Obciążenie i podaż świadczeń",
    )
    fig_capacity.update_layout(template="plotly_white", margin={"l": 10, "r": 10, "t": 50, "b": 20})

    left, right = st.columns([1.8, 1.2])
    with left:
        st.plotly_chart(fig_trend, use_container_width=True)
    with right:
        st.plotly_chart(fig_capacity, use_container_width=True)

    status, msg = recommendation(latest, trend_7d, load_ratio)
    st.markdown(
        f"""
        <div class="signal">
        <h3 style="margin: 0 0 0.35rem 0;">Sygnał ekspercki: {status}</h3>
        <p style="margin: 0;">{msg}</p>
        <p style="margin: 0.45rem 0 0 0;"><strong>Wskaźnik obciążenia:</strong> {load_ratio:.2f} rekordów / świadczeniodawcę</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.subheader("Komentarz analityczny")
    st.write(
        "Panel łączy tempo zmian czasu oczekiwania z dostępnością świadczeniodawców. "
        "W praktyce pozwala to szybciej wykryć, czy wzrost kolejki wynika z sezonowości, "
        "czy z ograniczeń podaży."
    )


if __name__ == "__main__":
    main()
