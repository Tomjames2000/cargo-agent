"""
Cargo Logistics Master Streamlit app.
NFO/Ground Routing with Google Maps & Cargo Hours Integration.
"""

import streamlit as st
import pandas as pd
import datetime
import requests
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# ==============================================================================
# 1. SECURITY & CONFIG
# ==============================================================================
st.set_page_config(page_title="Cargo Logistics Master", layout="wide", page_icon="✈️")

def check_password():
    """Returns `True` if the user had the correct password."""
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔒 Enter Team Password:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 Enter Team Password:", type="password", on_change=password_entered, key="password")
        st.error("⛔ Incorrect Password")
        return False
    else:
        return True

if not check_password():
    st.stop()

# CHECK API KEYS
try:
    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
    if not SERPAPI_KEY:
        raise KeyError("SERPAPI_KEY is empty")
except Exception:
    st.error("❌ System Error: SERPAPI_KEY not found in Secrets.")
    st.stop()

try:
    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_KEY"]
    if not GOOGLE_MAPS_KEY:
        raise KeyError("GOOGLE_MAPS_KEY is empty")
except Exception:
    st.error("❌ System Error: GOOGLE_MAPS_KEY not found in Secrets. Add it to use Google Geocoding + Distance Matrix APIs.")
    st.stop()

# ==============================================================================
# 2. LOGISTICS ENGINE
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_app_optimized_v32", timeout=10)
        self.gmaps_key = GOOGLE_MAPS_KEY
        
        # Major Hub Coordinates
        self.AIRPORT_DB = {
            "SEA": (47.4489, -122.3094), "PDX": (45.5887, -122.5975),
            "SFO": (37.6189, -122.3748), "LAX": (33.9425, -118.4080),
            "ORD": (41.9742, -87.9073),  "DFW": (32.8998, -97.0403),
            "JFK": (40.6413, -73.7781),  "ATL": (33.6407, -84.4277),
            "MIA": (25.7959, -80.2870),  "CLT": (35.2140, -80.9431),
            "MEM": (35.0424, -89.9767),  "CVG": (39.0461, -84.6621),
            "DEN": (39.8561, -104.6737), "PHX": (33.4343, -112.0116),
            "IAH": (29.9902, -95.3368),  "BOS": (42.3656, -71.0096),
            "EWR": (40.6895, -74.1745),  "MCO": (28.4312, -81.3081),
            "LGA": (40.7769, -73.8740),  "DTW": (42.2162, -83.3554),
            "MSP": (44.8848, -93.2223),  "SLC": (40.7899, -111.9791)
        }
        
        # Simplified cargo hours windows (local time). Defaults to 24/7 when absent.
        self.CARGO_HOURS = {
            "SEA": ("05:00", "23:00"), "PDX": ("05:00", "22:30"),
            "SFO": ("04:30", "23:30"), "LAX": ("05:00", "23:59"),
            "ORD": ("04:30", "23:30"), "DFW": ("05:00", "23:30"),
            "JFK": ("05:00", "23:30"), "ATL": ("05:00", "23:00"),
            "MIA": ("05:00", "23:00"), "CLT": ("05:00", "22:30"),
            "MEM": ("05:00", "23:30"), "CVG": ("05:00", "23:00"),
            "DEN": ("05:00", "23:00"), "PHX": ("05:00", "23:00"),
            "IAH": ("05:00", "23:30"), "BOS": ("05:00", "22:30"),
            "EWR": ("05:00", "23:00"), "MCO": ("05:00", "23:00"),
            "LGA": ("05:00", "22:00"), "DTW": ("05:00", "
