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
# 2. LOGISTICS ENGINE (HYBRID)
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_app_hybrid_v1", timeout=10)
        self.gmaps_key = GOOGLE_MAPS_KEY
        
        # 1. HARDCODED COORDINATES (Speed Layer - US Domestic Major/Regional)
        self.AIRPORT_COORDS = {
            # Northeast
            "BOS": (42.3656, -71.0096), "JFK": (40.6413, -73.7781), "EWR": (40.6895, -74.1745),
            "LGA": (40.7769, -73.8740), "PHL": (39.8729, -75.2437), "BWI": (39.1754, -76.6684),
            "IAD": (38.9531, -77.4565), "DCA": (38.8512, -77.0402), "PIT": (40.4914, -80.2328),
            # Southeast
            "MIA": (25.7959, -80.2870), "ATL": (33.6407, -84.4277), "MCO": (28.4312, -81.3081),
            "FLL": (26.0742, -80.1506), "TPA": (27.9772, -82.5311), "CLT": (35.2140, -80.9431),
            "RDU": (35.8801, -78.7880), "BNA": (36.1263, -86.6774), "MEM": (35.0424, -89.9767),
            "ORF": (36.8946, -76.2012), "RIC": (37.5052, -77.3197), "RSW": (26.5362, -81.7552),
            # Midwest
            "ORD": (41.9742, -87.9073), "MDW": (41.7868, -87.7522), "DTW": (42.2162, -83.3554),
            "MSP": (44.8848, -93.2223), "STL": (38.7472, -90.3614), "MCI": (39.2976, -94.7139),
            "CVG": (39.0461, -84.6621), "CLE": (41.4058, -81.8539), "IND": (39.7173, -86.2944),
            "CMH": (39.9980, -82.8919), "MKE": (42.9472, -87.8966),
            # South/Texas
            "DFW": (32.8998, -97.0403), "IAH": (29.9902, -95.3368), "AUS": (30.1975, -97.6664),
            "HOU": (29.6454, -95.2788), "SAT": (29.5337, -98.4698), "MSY": (29.9911, -90.2592),
            "OKC": (35.3931, -97.6007), "TUL": (36.1984, -95.8882), "ELP": (31.8075, -106.3776),
            # West/Mountain
            "LAX": (33.9425, -118.4080), "SFO": (37.6189, -122.3748), "SEA": (47.4489, -122.3094),
            "LAS": (36.0840, -115.1537), "PHX": (33.4343, -112.0116), "DEN": (39.8561, -104.6737),
            "SLC": (40.7899, -111.9791), "PDX": (45.5887, -122.5975), "SAN": (32.7338, -117.1933),
            "SMF": (38.6954, -121.5908), "SJC": (37.3619, -121.9290), "OAK": (37.7213, -122.2207),
            "SNA": (33.6762, -117.8675), "ONT": (34.0560, -117.6012), "BOI": (43.5644, -116.2228),
            # AK/HI
            "ANC": (61.1743, -149.9961), "HNL": (21.3186, -157.9224)
        }

        # 2. LOAD USER DATA (Hours Layer)
        # Structure: self.CARGO_DATA['BHM']['American'] = {'open': time, 'close': time}
        self.CARGO_DATA = {}
        self._load_cargo_file("cargo_master.csv")

    def _load_cargo_file(self, filename):
        """Ingests the user's detailed CSV."""
        try:
            df = pd.read_csv(filename)
            # Clean headers to match keys
            df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
            
            for _, row in df.iterrows():
                try:
                    code = str(row.get('airport_code', '')).strip().upper()
                    airline = str(row.get('airline', 'General')).strip()
                    hours_raw = str(row.get('weekday', '')) # Using Weekday as default
                    
                    if not code or len(code) != 3: continue
                    
                    if code not in self.CARGO_DATA:
                        self.CARGO_DATA[code] = {}
                        
                    # Parse specific hours "06:00-22:00"
                    if "-" in hours_raw:
                        start_str, end_str = hours_raw.split("-")
                        start_t = self._parse_time(start_str)
                        end_t = self._parse_time(end_str)
                        if start_t and end_t:
                            self.CARGO_DATA[code][airline] = {"open": start_t, "close": end_t, "raw": hours_raw}
                            
                except Exception:
                    continue
                    
        except FileNotFoundError:
            st.warning(f"⚠️ File '{filename}' not found. Using defaults.")

    def _parse_time(self, raw_time: str):
        if not raw_time: return None
        cleaned = str(raw_time).strip().replace(".", "").upper()
        patterns = ["%H:%M", "%I:%M%p", "%I:%M %p"]
        for pattern in patterns:
            try:
                return datetime.datetime.strptime(cleaned, pattern).time()
            except ValueError:
                continue
        return None

    def _get_cargo_window(self, airport_code: str, airline_name: str = None):
        """Smart lookup: Tries specific airline first, then generic."""
        code = airport_code.upper()
        data = self.CARGO_DATA.get(code)
        
        # Default Fallback
        default_win = {"open": datetime.time(5,0), "close": datetime.time(23,0), "label": "05:00-23:00 (Est)"}
        
        if not data:
            return default_win

        # 1. Try Exact Airline Match
        if airline_name:
            for key in data:
                # Fuzzy match "American Airlines" vs "American"
                if airline_name.lower() in key.lower() or key.lower() in airline_name.lower():
                    w = data[key]
                    return {"open": w['open'], "close": w['close'], "label": f"{w['raw']} ({key})"}

        # 2. Fallback: Find the "Widest" window
        earliest = datetime.time(23, 59)
        latest = datetime.time(0, 0)
        found = False
        
        for key, w in data.
