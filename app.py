import os
import math
import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

st.set_page_config(
    page_title="Fishing Conditions",
    page_icon="🎣",
    layout="wide"
)

st.title("🎣 Fishing Conditions")
st.write("Enter a lake and location to get current fishing-condition signals.")

lake_name = st.text_input("Lake name", value="Alice Lake")
location_hint = st.text_input("Province / country / nearby city", value="Squamish, British Columbia, Canada")


def geocode_location(query):
    # Better lake/place search using OpenStreetMap Nominatim
    nominatim_url = "https://nominatim.openstreetmap.org/search"

    headers = {
        "User-Agent": "FishingConditionsAgent/1.0"
    }

    params = {
        "q": query,
        "format": "json",
        "limit": 1,
        "countrycodes": "ca"
    }

    try:
        response = requests.get(
            nominatim_url,
            params=params,
            headers=headers,
            timeout=15
        )
        response.raise_for_status()

        data = response.json()

        if data:
            result = data[0]

            return {
                "name": result.get("display_name"),
                "country": "Canada",
                "admin1": "",
                "latitude": float(result.get("lat")),
                "longitude": float(result.get("lon"))
            }

    except Exception as e:
        print("Nominatim geocode failed:", e)

    # Fallback: Open-Meteo geocoder
    url = "https://geocoding-api.open-meteo.com/v1/search"

    params = {
        "name": query,
        "count": 1,
        "language": "en",
        "format": "json"
    }

    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()

        data = response.json()

        if "results" not in data:
            return None

        result = data["results"][0]

        return {
            "name": result.get("name"),
            "country": result.get("country"),
            "admin1": result.get("admin1"),
            "latitude": result.get("latitude"),
            "longitude": result.get("longitude")
        }

    except Exception:
        return None


def get_weather(latitude, longitude):
    url = "https://api.open-meteo.com/v1/forecast"

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "hourly": [
            "surface_pressure",
            "wind_speed_10m",
            "wind_direction_10m",
            "cloud_cover",
            "precipitation",
            "temperature_2m"
        ],
        "past_days": 3,
        "forecast_days": 2,
        "timezone": "auto"
    }

    response = requests.get(url, params=params, timeout=20)
    response.raise_for_status()

    return response.json()


def wind_direction_to_compass(degrees):
    if degrees is None:
        return "Unknown"

    directions = [
        "N", "NNE", "NE", "ENE",
        "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW",
        "W", "WNW", "NW", "NNW"
    ]

    index = round(degrees / 22.5) % 16
    return directions[index]


def calculate_pressure_trend(df):
    recent = df.dropna(subset=["surface_pressure"]).tail(72)

    if len(recent) < 6:
        return {
            "change_24h": None,
            "change_72h": None,
            "trend": "Insufficient data"
        }

    latest = recent["surface_pressure"].iloc[-1]
    p24 = recent["surface_pressure"].iloc[-24] if len(recent) >= 24 else recent["surface_pressure"].iloc[0]
    p72 = recent["surface_pressure"].iloc[0]

    change_24h = latest - p24
    change_72h = latest - p72

    if change_24h > 2:
        trend = "Rising"
    elif change_24h < -2:
        trend = "Falling"
    else:
        trend = "Stable"

    return {
        "change_24h": round(change_24h, 2),
        "change_72h": round(change_72h, 2),
        "trend": trend
    }


def simple_moon_phase():
    known_new_moon = pd.Timestamp("2000-01-06")
    today = pd.Timestamp.today().normalize()

    days_since = (today - known_new_moon).days
    lunar_cycle = 29.53058867
    age = days_since % lunar_cycle

    if age < 1.85:
        phase = "New Moon"
    elif age < 5.54:
        phase = "Waxing Crescent"
    elif age < 9.23:
        phase = "First Quarter"
    elif age < 12.92:
        phase = "Waxing Gibbous"
    elif age < 16.61:
        phase = "Full Moon"
    elif age < 20.30:
        phase = "Waning Gibbous"
    elif age < 23.99:
        phase = "Last Quarter"
    elif age < 27.68:
        phase = "Waning Crescent"
    else:
        phase = "New Moon"

    illumination = (1 - math.cos(2 * math.pi * age / lunar_cycle)) / 2 * 100

    return {
        "phase": phase,
        "illumination_pct": round(illumination, 1),
        "moon_age_days": round(age, 1)
    }


def score_conditions(current, pressure, precip_72h, moon):
    score = 50

    if pressure["trend"] == "Stable":
        score += 12
    elif pressure["trend"] == "Rising":
        score += 8
    elif pressure["trend"] == "Falling":
        score -= 8

    wind = current.get("wind_speed_10m", 0)

    if 5 <= wind <= 18:
        score += 10
    elif wind > 30:
        score -= 15

    cloud = current.get("cloud_cover", 0)

    if 30 <= cloud <= 80:
        score += 8
    elif cloud < 10:
        score -= 4

    if precip_72h > 15:
        score -= 8
    elif 1 <= precip_72h <= 10:
        score += 4

    if moon["phase"] in ["New Moon", "Full Moon", "First Quarter", "Last Quarter"]:
        score += 5

    return max(0, min(100, round(score)))


def generate_ai_summary(lake_name, location, current, pressure, precip_72h, moon, score):
    if client is None:
        return "OpenAI API key not found. Add OPENAI_API_KEY to your .env file for AI summary."

    prompt = f"""
You are a fishing conditions analyst.

Lake: {lake_name}
Location: {location}

Current / recent signals:
- Fishing condition score: {score}/100
- Barometric pressure trend: {pressure}
- Current air temperature: {current.get("temperature_2m")} C
- Current wind speed: {current.get("wind_speed_10m")} km/h
- Current wind direction: {current.get("wind_direction_10m")} degrees
- Current cloud cover: {current.get("cloud_cover")}%
- Precipitation last 72 hours: {precip_72h} mm
- Moon phase: {moon}

Create a practical fishing report.

Include:
1. Overall fishing outlook
2. Best likely bite window
3. How pressure trend affects fishing
4. How wind/cloud/precipitation affect conditions
5. Suggested approach/lure style
6. Confidence level
7. What data is estimated vs measured

Be clear that water temperature profile, dissolved oxygen, thermocline, pH, water clarity, bathymetry, stocking history, recent catch success, ice-off date, and inundated vegetation are not yet directly measured in this version.
"""

    response = client.responses.create(
        model="gpt-4.1",
        input=prompt
    )

    return response.output_text


if st.button("Analyze Fishing Conditions"):
    search_query = f"{lake_name} lake, {location_hint}"

    with st.spinner("Finding lake/location..."):
        location = geocode_location(search_query)

    if not location:
        st.error("Could not find that lake/location. Try adding a nearby city, park name, or province.")
        st.stop()

    latitude = location["latitude"]
    longitude = location["longitude"]

    st.success(f"Found: {location['name']}")
    st.write(f"Latitude: {latitude}, Longitude: {longitude}")

    with st.spinner("Pulling weather and pressure data..."):
        weather = get_weather(latitude, longitude)

    hourly = weather["hourly"]

    df = pd.DataFrame({
        "time": hourly["time"],
        "surface_pressure": hourly["surface_pressure"],
        "wind_speed_10m": hourly["wind_speed_10m"],
        "wind_direction_10m": hourly["wind_direction_10m"],
        "cloud_cover": hourly["cloud_cover"],
        "precipitation": hourly["precipitation"],
        "temperature_2m": hourly["temperature_2m"],
    })

    current = df.dropna().iloc[-1].to_dict()

    pressure = calculate_pressure_trend(df)
    precip_72h = round(df["precipitation"].tail(72).sum(), 2)
    moon = simple_moon_phase()

    current["wind_compass"] = wind_direction_to_compass(current.get("wind_direction_10m"))

    score = score_conditions(current, pressure, precip_72h, moon)

    st.subheader("🎯 Fishing Conditions Score")
    st.metric("Score", f"{score}/100")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric("Pressure Trend", pressure["trend"])
        st.metric("24h Pressure Change", f"{pressure['change_24h']} hPa")

    with col2:
        st.metric("Wind", f"{round(current['wind_speed_10m'], 1)} km/h")
        st.metric("Direction", current["wind_compass"])

    with col3:
        st.metric("Cloud Cover", f"{round(current['cloud_cover'], 1)}%")
        st.metric("72h Precipitation", f"{precip_72h} mm")

    st.subheader("🌙 Moon Phase")
    st.write(f"{moon['phase']} — {moon['illumination_pct']}% illuminated")
    st.write(f"Moon age: {moon['moon_age_days']} days")

    st.subheader("🌡️ Estimated Surface Conditions")
    st.write(f"Current air temperature near lake: **{round(current['temperature_2m'], 1)}°C**")
    st.caption("Surface water temperature is not directly measured yet. This version uses weather signals only.")

    st.subheader("📈 Weather Data")
    df_chart = df.copy()
    df_chart["time"] = pd.to_datetime(df_chart["time"])

    st.write("Pressure and temperature:")
    st.line_chart(df_chart.set_index("time")[["surface_pressure", "temperature_2m"]])

    st.write("Wind, cloud cover, and precipitation:")
    st.line_chart(df_chart.set_index("time")[["wind_speed_10m", "cloud_cover", "precipitation"]])

    with st.spinner("Generating fishing report..."):
        summary = generate_ai_summary(
            lake_name=lake_name,
            location=location["name"],
            current=current,
            pressure=pressure,
            precip_72h=precip_72h,
            moon=moon,
            score=score
        )

    st.subheader("🤖 Fishing Agent Report")
    st.write(summary)

    st.subheader("Data Coverage")
    coverage = pd.DataFrame([
        ["Barometric pressure trend", "Measured from weather API"],
        ["Wind velocity and direction", "Measured from weather API"],
        ["Cloud cover percentage", "Measured from weather API"],
        ["Precipitation history", "Measured from weather API"],
        ["Moon phase", "Estimated astronomically"],
        ["Surface temperature", "Not directly measured yet"],
        ["Water temperature profile", "Not available in Version 1"],
        ["Bathymetry", "Not available in Version 1"],
        ["Dissolved oxygen", "Not available in Version 1"],
        ["Water clarity", "Not available in Version 1"],
        ["Stocking history", "Not available in Version 1"],
        ["pH levels", "Not available in Version 1"],
        ["Recent catch success", "Not available in Version 1"],
        ["Thermocline depth", "Not available in Version 1"],
        ["Ice-off date", "Not available in Version 1"],
        ["Inundated vegetation", "Not available in Version 1"],
    ], columns=["Metric", "Status"])

    st.dataframe(coverage, use_container_width=True)
