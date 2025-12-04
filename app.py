import streamlit as st
import pandas as pd
import datetime
import requests
import math
import re
from dateutil import parser, relativedelta
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# IMPORT FLIGHT RELIABILITY MODULE
try:
    from modules.fra_engine import analyze_reliability
    HAS_FRA = True
except ImportError:
    HAS_FRA = False

# ==============================================================================
# 1. VISUAL CONFIGURATION
# ==============================================================================
st.set_page_config(
    page_title="Cargo Logistics Master", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    .metric-card {
        background-color: #1e293b;
        border: 1px solid #334155;
        padding: 20px;
        border-radius: 10px;
        color: #f8fafc;
        height: 100%;
    }
    .metric-header {
        color: #94a3b8;
        font-size: 0.85rem;
        text-transform: uppercase;
        letter-spacing: 0.05em;
        margin-bottom: 8px;
    }
    .metric-value {
        font-size: 1.5rem;
        font-weight: 700;
        color: #f8fafc;
    }
    .timeline-container {
        display: flex;
        justify-content: space-between;
        align-items: center;
        background-color: #0f172a;
        padding: 25px;
        border-radius: 12px;
        border: 1px solid #1e293b;
        margin: 20px 0;
        color: #e2e8f0;
    }
    .timeline-point {
        text-align: center;
        position: relative;
        z-index: 2;
    }
    .timeline-line {
        flex-grow: 1;
        height: 4px;
        background: linear-gradient(90deg, #3b82f6 0%, #10b981 100%);
        margin: 0 15px;
        border-radius: 2px;
        opacity: 0.5;
    }
    /* Make the data editor checkboxes larger and centered if possible */
    [data-testid="stCheckbox"] {
        display: flex;
        justify-content: center;
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. SECURITY & API KEY LOADING
# ==============================================================================
def check_password():
    def password_entered():
        if st.session_state["password"] == st.secrets["APP_PASSWORD"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        st.text_input("🔒 Authorization Code:", type="password", on_change=password_entered, key="password")
        return False
    elif not st.session_state["password_correct"]:
        st.text_input("🔒 Authorization Code:", type="password", on_change=password_entered, key="password")
        st.error("⛔ Access Denied")
        return False
    else:
        return True

if not check_password():
    st.stop()

# Securely load keys
SERPAPI_KEY = st.secrets.get("SERPAPI_KEY")
GOOGLE_MAPS_KEY = st.secrets.get("GOOGLE_MAPS_KEY")
AVIATION_EDGE_KEY = st.secrets.get("AVIATION_EDGE_KEY")

if not SERPAPI_KEY: 
    st.warning("⚠️ SERPAPI_KEY is missing. Web-based backup search will be disabled.")
if not AVIATION_EDGE_KEY: 
    st.error("❌ AVIATION_EDGE_KEY is missing. Real-time flight data cannot be retrieved.")

# ==============================================================================
# 3. LOGISTICS ENGINE (Real-Time)
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_command_v59_interactive", timeout=10)
        self.master_df = None
        try:
            self.master_df = pd.read_csv("cargo_master.csv")
            self.master_df.columns = [c.strip().lower().replace(" ", "_") for c in self.master_df.columns]
        except: pass
        
        self.AIRPORT_DB = {
            "SEA": {"name": "Seattle-Tacoma Intl", "coords": (47.4489, -122.3094)},
            "PDX": {"name": "Portland Intl", "coords": (45.5887, -122.5975)},
            "SFO": {"name": "San Francisco Intl", "coords": (37.6189, -122.3748)},
            "LAX": {"name": "Los Angeles Intl", "coords": (33.9425, -118.4080)},
            "ORD": {"name": "Chicago O'Hare Intl", "coords": (41.9742, -87.9073)},
            "DFW": {"name": "Dallas/Fort Worth Intl", "coords": (32.8998, -97.0403)},
            "JFK": {"name": "John F. Kennedy Intl", "coords": (40.6413, -73.7781)},
            "ATL": {"name": "Hartsfield-Jackson Atlanta", "coords": (33.6407, -84.4277)},
            "MIA": {"name": "Miami Intl", "coords": (25.7959, -80.2870)},
            "CLT": {"name": "Charlotte Douglas Intl", "coords": (35.2140, -80.9431)},
            "MEM": {"name": "Memphis Intl", "coords": (35.0424, -89.9767)},
            "CVG": {"name": "Cincinnati/N Kentucky", "coords": (39.0461, -84.6621)},
            "DEN": {"name": "Denver Intl", "coords": (39.8561, -104.6737)},
            "PHX": {"name": "Phoenix Sky Harbor", "coords": (33.4343, -112.0116)},
            "IAH": {"name": "George Bush Intercontinental", "coords": (29.9902, -95.3368)},
            "BOS": {"name": "Logan Intl", "coords": (42.3656, -71.0096)},
            "EWR": {"name": "Newark Liberty Intl", "coords": (40.6895, -74.1745)},
            "MCO": {"name": "Orlando Intl", "coords": (28.4312, -81.3081)},
            "LGA": {"name": "LaGuardia", "coords": (40.7769, -73.8740)},
            "DTW": {"name": "Detroit Metro", "coords": (42.2162, -83.3554)},
            "MSP": {"name": "Minneapolis–Saint Paul", "coords": (44.8848, -93.2223)},
            "SLC": {"name": "Salt Lake City Intl", "coords": (40.7899, -111.9791)},
            "STL": {"name": "St. Louis Lambert Intl", "coords": (38.7487, -90.3700)}
        }

    def _get_coords(self, location: str):
        if self.master_df is not None and len(location) == 3:
            match = self.master_df[self.master_df['airport_code'] == location.upper()]
            if not match.empty: return (match.iloc[0]['latitude_deg'], match.iloc[0]['longitude_deg'])
        if location.upper() in self.AIRPORT_DB: return self.AIRPORT_DB[location.upper()]["coords"]
        if GOOGLE_MAPS_KEY:
            try:
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {"address": location, "key": GOOGLE_MAPS_KEY}
                r = requests.get(url, params=params, timeout=5)
                data = r.json()
                if data['status'] == 'OK': return (data['results'][0]['geometry']['location']['lat'], data['results'][0]['geometry']['location']['lng'])
            except: pass
        try:
            clean = location.replace("Suite", "").replace("#", "").split(",")[0] + ", " + location.split(",")[-1]
            loc = self.geolocator.geocode(clean)
            if loc: return (loc.latitude, loc.longitude)
        except: pass
        return None

    def get_airport_details(self, code):
        code = code.upper()
        if AVIATION_EDGE_KEY:
            try:
                r = requests.get("https://aviation-edge.com/v2/public/airportDatabase", params={"key": AVIATION_EDGE_KEY, "codeIataAirport": code}, timeout=5)
                d = r.json()
                if d and isinstance(d, list): return {"code": code, "name": d[0].get("nameAirport", code), "coords": (float(d[0]['latitudeAirport']), float(d[0]['longitudeAirport']))}
            except: pass
        if self.master_df is not None:
            match = self.master_df[self.master_df['airport_code'] == code]
            if not match.empty: return {"code": code, "name": match.iloc[0]['airport_name'], "coords": (match.iloc[0]['latitude_deg'], match.iloc[0]['longitude_deg'])}
        if code in self.AIRPORT_DB: return {"code": code, "name": self.AIRPORT_DB[code]["name"], "coords": self.AIRPORT_DB[code]["coords"]}
        return None

    def get_cargo_hours(self, airport_code, airline, date_obj):
        day_name = date_obj.strftime("%A")
        col_map = {"Saturday": "saturday", "Sunday": "sunday"}
        day_col = col_map.get(day_name, "weekday") 
        if self.master_df is not None:
            mask = (self.master_df['airport_code'] == airport_code) & (self.master_df['airline'].str.contains(airline, case=False, na=False))
            row = self.master_df[mask]
            if not row.empty:
                hours_str = str(row.iloc[0][day_col])
                if any(x in hours_str.lower() for x in ['nan', 'closed', 'n/a', 'no cargo']): return {"status": "Closed", "hours": "No Cargo", "source": "Master File"}
                return {"status": "Open", "hours": hours_str, "source": "Master File"}
        url = "https://serpapi.com/search"
        if SERPAPI_KEY:
            try:
                r = requests.get(url, params={"engine": "google", "q": f"{airline} cargo hours {airport_code} {day_name}", "api_key": SERPAPI_KEY, "num": 1}, timeout=5)
                snip = r.json().get("organic_results", [{}])[0].get("snippet", "No data")
                return {"status": "Unverified", "hours": f"Web: {snip[:40]}...", "source": "Web Search"}
            except: pass
        return {"status": "Unknown", "hours": "Unknown", "source": "No Data"}

    def check_time_in_range(self, target_time, range_str):
        if any(x in range_str.lower() for x in ["no cargo", "closed", "n/a"]): return False
        if "24" in range_str or "daily" in range_str: return True
        try:
            times = re.findall(r'\d{1,2}:\d{2}', range_str)
            if len(times) != 2: return True
            start, end = datetime.datetime.strptime(times[0], "%H:%M").time(), datetime.datetime.strptime(times[1], "%H:%M").time()
            check = datetime.datetime.strptime(target_time, "%H:%M").time()
            if start <= end: return start <= check <= end
            else: return start <= check or check <= end
        except: return True

    def get_next_open_time(self, current_dt, hours_str):
        if "24" in hours_str or "Daily" in hours_str or not re.search(r'\d{1,2}:\d{2}', hours_str):
            return current_dt
        try:
            times = re.findall(r'\d{1,2}:\d{2}', hours_str)
            start_t = datetime.datetime.strptime(times[0], "%H:%M").time()
            start_dt = current_dt.replace(hour=start_t.hour, minute=start_t.minute, second=0, microsecond=0)
            if current_dt.time() < start_t:
                return start_dt
            else:
                end_t = datetime.datetime.strptime(times[1], "%H:%M").time()
                if start_t > end_t and (current_dt.time() > start_t or current_dt.time() < end_t):
                    return current_dt 
                return start_dt + datetime.timedelta(days=1)
        except:
            return current_dt.replace(hour=9, minute=0, second=0, microsecond=0) + datetime.timedelta(days=1)

    def find_nearest_airports(self, address: str):
        user_coords = self._get_coords(address)
        if not user_coords: return None
        candidates = []
        if AVIATION_EDGE_KEY:
            try:
                r = requests.get("https://aviation-edge.com/v2/public/nearby", params={"key": AVIATION_EDGE_KEY, "lat": user_coords[0], "lng": user_coords[1], "distance": 150}, timeout=8)
                for apt in r.json():
                    if len(apt.get("codeIataAirport", "")) == 3: candidates.append({"code": apt.get("codeIataAirport").upper(), "name": apt.get("nameAirport"), "air_miles": round(float(apt.get("distance")) * 0.621371, 1)})
            except: pass
        if not candidates:
            for code, data in self.AIRPORT_DB.items():
                dist = geodesic(user_coords, data["coords"]).miles
                candidates.append({"code": code, "name": data["name"], "air_miles": round(dist, 1)})
        candidates.sort(key=lambda x: x["air_miles"])
        return candidates[:3]

    def get_road_metrics(self, origin: str, destination: str):
        coords_start = self._get_coords(origin)
        coords_end = self._get_coords(destination)
        if not coords_start or not coords_end: return None
        if GOOGLE_MAPS_KEY:
            try:
                url = "https://maps.googleapis.com/maps/api/distancematrix/json"
                params = {"origins": f"{coords_start[0]},{coords_start[1]}", "destinations": f"{coords_end[0]},{coords_end[1]}", "mode": "driving", "traffic_model": "best_guess", "departure_time": "now", "key": GOOGLE_MAPS_KEY}
                r = requests.get(url, params=params, timeout=8)
                data = r.json()
                if data['status'] == 'OK':
                    elem = data['rows'][0]['elements'][0]
                    if elem['status'] == 'OK': return {"miles": round(elem['distance']['value'] * 0.000621371, 1), "time_str": f"{int(elem.get('duration_in_traffic', elem['duration'])['value'] // 3600)}h {int((elem.get('duration_in_traffic', elem['duration'])['value'] % 3600) // 60)}m", "time_min": round(elem.get('duration_in_traffic', elem['duration'])['value']/60)}
            except: pass
        url = f"https://router.project-osrm.org/route/v1/driving/{coords_start[1]},{coords_start[0]};{coords_end[1]},{coords_end[0]}"
        try:
            r = requests.get(url, params={"overview": "false"}, headers={"User-Agent": "CargoApp/1.0"}, timeout=15)
            data = r.json()
            if data.get("code") == "Ok":
                sec = data['routes'][0]['duration']
                return {"miles": round(data['routes'][0]['distance'] * 0.000621371, 1), "time_str": f"{int(sec // 3600)}h {int((sec % 3600) // 60)}m", "time_min": round(sec/60)}
        except: pass
        dist = geodesic(coords_start, coords_end).miles * 1.3
        return {"miles": round(dist, 1), "time_str": f"{int((dist/50) + 0.5)}h {int(((dist/50) + 0.5)*60)%60}m (Est)", "time_min": int(((dist/50) + 0.5)*60)}

    def search_flights(self, origin, dest, date, show_all_airlines=False):
        if AVIATION_EDGE_KEY:
            try:
                r = requests.get("https://aviation-edge.com/v2/public/flightsFuture", params={"key": AVIATION_EDGE_KEY, "type": "departure", "iataCode": origin, "date": date, "arr_iataCode": dest}, timeout=10)
                data = r.json()
                if isinstance(data, list):
                    results = []
                    for f in data:
                        airline = f.get('airline', {}).get('iataCode', 'UNK')
                        if not show_all_airlines and airline not in ["WN","AA","DL","UA"]: continue
                        dep_time = f.get('departure', {}).get('scheduledTime', '')
                        arr_time = f.get('arrival', {}).get('scheduledTime', '')
                        if not dep_time or not arr_time: continue
                        try:
                            dur = (datetime.datetime.strptime(arr_time.split('.')[0], "%Y-%m-%dT%H:%M:%S") - datetime.datetime.strptime(dep_time.split('.')[0], "%Y-%m-%dT%H:%M:%S")).total_seconds()/60
                            dur_str = f"{int(dur//60)}h {int(dur%60)}m"
                        except: dur_str = "N/A"
                        results.append({
                            "Airline": airline, "Flight": f"{airline}{f.get('flight',{}).get('iataNumber','')}",
                            "Origin": f.get('departure', {}).get('iataCode', origin), "Dep Time": dep_time.split('T')[-1][:5], "Dep Full": dep_time,
                            "Dest": f.get('arrival', {}).get('iataCode', dest), "Arr Time": arr_time.split('T')[-1][:5], "Arr Full": arr_time,
                            "Duration": dur_str, "Conn Apt": "Direct", "Conn Time": "N/A", "Conn Min": 0
                        })
                    if results: return results
            except: pass
        if SERPAPI_KEY:
            try:
                params = {"engine": "google_flights", "departure_id": origin, "arrival_id": dest, "outbound_date": date, "type": "2", "hl": "en", "gl": "us", "currency": "USD", "api_key": SERPAPI_KEY}
                if not show_all_airlines: params["include_airlines"] = "WN,AA,DL,UA"
                r = requests.get("https://serpapi.com/search", params=params)
                data = r.json()
                results = []
                raw = data.get("best_flights", []) + data.get("other_flights", [])
                for f in raw[:20]:
                    legs = f.get('flights', [])
                    if not legs: continue
                    layovers = f.get('layovers', [])
                    conn_apt = layovers[0].get('id', 'Direct') if layovers else "Direct"
                    conn_min = layovers[0].get('duration', 0) if layovers else 0
                    conn_time_str = f"{conn_min//60}h {conn_min%60}m" if layovers else "N/A"
                    dep_full = legs[0].get('departure_airport', {}).get('time', '')
                    arr_full = legs[-1].get('arrival_airport', {}).get('time', '')
                    results.append({
                        "Airline": legs[0].get('airline', 'UNK'),
                        "Flight": " / ".join([l.get('flight_number', '') for l in legs]),
                        "Origin": legs[0].get('departure_airport', {}).get('id', 'UNK'),
                        "Dep Time": dep_full.split()[-1], "Dep Full": dep_full,
                        "Dest": legs[-1].get('arrival_airport', {}).get('id', 'UNK'),
                        "Arr Time": arr_full.split()[-1], "Arr Full": arr_full,
                        "Duration": f"{f.get('total_duration',0)//60}h {f.get('total_duration',0)%60}m",
                        "Conn Apt": conn_apt, "Conn Time": conn_time_str, "Conn Min": conn_min
                    })
                return results
            except: return []
        return []

# ==============================================================================
# 4. FLIGHT PLAN GENERATION
# ==============================================================================
def create_flight_plan_table(plan_data, p_time, del_time, del_offset, p_code, d_code):
    # plan_data is a dictionary where key is Day and value is the 'edited' dataframe for that day
    plan_rows = []
    day_order = {"Mon": 0, "Tue": 1, "Wed": 2, "Thu": 3, "Fri": 4, "Sat": 5, "Sun": 6}
    
    for day, df_day in plan_data.items():
        # Find Primary
        primaries = df_day[df_day['Primary'] == True]
        backups = df_day[df_day['Backup'] == True]
        
        if primaries.empty: continue # Skip days with no primary selected
        
        # Take the first selected primary
        p_flight = primaries.iloc[0]
        b_flight = backups.iloc[0] if not backups.empty else None
        
        # Construct Row
        flt_parts = p_flight['Flight'].split(' / ')
        cnx_flt = flt_parts[1] if len(flt_parts) > 1 else 'N/A'
        
        backup_str = "N/A"
        backup_time_str = "N/A"
        if b_flight is not None:
            backup_str = f"{b_flight['Airline']}{b_flight['Flight'].split(' / ')[0]}"
            # We need to access the raw datetime objects which might be lost in the editor view
            # So we rely on the string formatted columns we created for the editor
            backup_time_str = f"ETD: {b_flight['Dep DateTime Str'].split(' ')[1]} / ETA: {b_flight['Arr DateTime Str'].split(' ')[1]}"

        plan_rows.append({
            "DATE": p_flight['Dep DateTime Str'].split(' ')[0], # Extract MM/DD
            "DAY": day,
            "REQ'D PICK UP": p_time.strftime('%H:%M'),
            "ORIGIN": p_code,
            "DEST": d_code,
            "AIRLINE": p_flight['Airline'],
            "FLT #": flt_parts[0],
            "ETD": p_flight['Dep DateTime Str'].split(' ')[1],
            "CNX FLT": cnx_flt,
            "CNX CITY": "Direct" if "Direct" in str(p_flight.get('Conn Apt', '')) else "Layover", # Simplified for display
            "ETA": p_flight['Arr DateTime Str'].split(' ')[1],
            "DUE TIME": del_time.strftime('%H:%M') if del_time else 'N/A',
            "PREBOOK #": "",
            "BACKUP FLTS": backup_str,
            "BACKUP FLT TIMES": backup_time_str,
            "NOTES": p_flight['Notes']
        })
        
    df_plan = pd.DataFrame(plan_rows)
    if not df_plan.empty:
        df_plan['SortKey'] = df_plan['DAY'].apply(lambda x: day_order.get(x, 99))
        df_plan = df_plan.sort_values(by='SortKey').drop(columns='SortKey')
    return df_plan

# ==============================================================================
# 5. DASHBOARD UI
# ==============================================================================

st.sidebar.title("🎮 Control Panel")
st.sidebar.markdown("**0. Logistics Mode**")
mode_selection = st.sidebar.radio("Function", ["Flight Scheduler", "Flight Reliability Analyzer"], label_visibility="collapsed")

st.sidebar.markdown("**1. Shipment Mode**")
mode = st.sidebar.radio("Frequency", ["One-Time (Ad-Hoc)", "Reoccurring"], label_visibility="collapsed")

st.sidebar.markdown("**2. Locations**")
p_addr = st.sidebar.text_input("Pickup Address", "2008 Altom Ct, St. Louis, MO 63146")
p_manual = st.sidebar.text_input("Origin Override (Opt)", placeholder="e.g. STL")
st.sidebar.markdown("⬇️")
d_addr = st.sidebar.text_input("Delivery Address", "1250 E Hadley St, Phoenix, AZ 85034")
d_manual = st.sidebar.text_input("Dest Override (Opt)", placeholder="e.g. PHX")

st.sidebar.markdown("**3. Timing**")
p_time = st.sidebar.time_input("Ready Time", datetime.time(9, 0))

if mode == "One-Time (Ad-Hoc)":
    p_date = st.sidebar.date_input("Pickup Date", datetime.date.today() + datetime.timedelta(days=1))
else:
    p_date = datetime.date.today()

has_deadline = st.sidebar.checkbox("Strict Delivery Deadline?", value=True)
del_date_obj = None
del_time = None
del_offset = 0

if has_deadline:
    default_del = p_date + datetime.timedelta(days=1)
    del_date_obj = st.sidebar.date_input("Delivery Date", default_del)
    del_time = st.sidebar.time_input("Must Arrive By", datetime.time(18, 0))
    del_offset = (del_date_obj - p_date).days
    if mode == "One-Time (Ad-Hoc)" and del_offset < 0:
        st.sidebar.error("⚠️ Delivery Date cannot be before Pickup Date.")

days_to_search = []
if mode == "One-Time (Ad-Hoc)":
    days_to_search = [{"day": "One-Time", "date": p_date.strftime("%Y-%m-%d")}]
else:
    st.sidebar.info(f"Pattern: Weekly (+{del_offset} Days)")
    days_selected = st.sidebar.multiselect("Days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ["Mon", "Wed", "Fri"])
    day_map = {"Mon":0, "Tue":1, "Wed":2, "Thu":3, "Fri":4, "Sat":5, "Sun":6}
    today = datetime.date.today()
    for d in days_selected:
        target = day_map[d]
        diff = target - today.weekday()
        if diff < 0: diff += 7
        if diff == 0 and mode == "Reoccurring": diff = 7
        days_to_search.append({"day": d, "date": (today + datetime.timedelta(days=diff)).strftime("%Y-%m-%d")})
    days_to_search.sort(key=lambda x: day_map.get(x['day'], 99))

with st.sidebar.expander("⚙️ Adjusters & Filters"):
    st.sidebar.markdown("**Time Buffers (Minutes)**")
    custom_p_buff = st.sidebar.number_input("Pickup Buffer", value=120, step=30)
    custom_d_buff = st.sidebar.number_input("Delivery Buffer", value=120, step=30)
    st.sidebar.markdown("---")
    min_conn_filter = st.sidebar.number_input("Min Conn (Minutes)", value=60, step=15)
    st.sidebar.markdown("---")
    show_all_airlines = st.sidebar.checkbox("Show All Airlines", value=False)

run_btn = st.sidebar.button("🚀 Run Analysis", type="primary")

# --- Session State ---
if 'flight_plan_df' not in st.session_state: st.session_state.flight_plan_df = None
if 'valid_flights' not in st.session_state: st.session_state.valid_flights = []
if 'grouped_flights' not in st.session_state: st.session_state.grouped_flights = {}
if 'p_code' not in st.session_state: st.session_state.p_code = None
if 'd_code' not in st.session_state: st.session_state.d_code = None
if 'earliest_dep_str' not in st.session_state: st.session_state.earliest_dep_str = "N/A"
if 'latest_arr_str' not in st.session_state: st.session_state.latest_arr_str = "N/A"
if 'drive_metrics' not in st.session_state: st.session_state.drive_metrics = {}
if 'airline_hours_cache' not in st.session_state: st.session_state.airline_hours_cache = {}
# NEW: State to hold the editable dataframes
if 'editor_data' not in st.session_state: st.session_state.editor_data = {}

if run_btn:
    st.session_state.flight_plan_df = None 
    st.session_state.valid_flights = []
    st.session_state.grouped_flights = {}
    st.session_state.editor_data = {}
    st.session_state.airline_hours_cache = {}
    
    if mode_selection == "Flight Reliability Analyzer":
        st.markdown("## ⛈️ Flight Reliability Analyzer (FRA) Mode")
        f_num = st.text_input("Full Flight Number (e.g., AA2345)", placeholder="AirlineCode + Number")
        if f_num and HAS_FRA and AVIATION_EDGE_KEY:
            with st.spinner(f"Analyzing {f_num}..."):
                res = analyze_reliability(f_num, AVIATION_EDGE_KEY)
                if "score" in res:
                    score, risks = res['score'], res['risk_factors']
                    st.metric(f"Risk Score for {f_num}", f"{score}%", help="Higher score is lower risk.")
                    st.markdown(f"**Risk Factors:** {', '.join(risks) if risks else 'None detected.'}")
                else:
                    st.error("Could not retrieve data.")
        elif f_num and not HAS_FRA:
            st.warning("The FRA module is not installed.")

    elif mode_selection == "Flight Scheduler":
        p_code = d_code = "Unknown"
        d1 = d2 = {"miles": 0, "time_str": "N/A", "time_min": 0}
        total_prep = total_post = 0
        valid_flights = []
        
        tools = LogisticsTools()
        
        with st.status("📡 Establishing Logistics Chain...", expanded=True) as status:
            p_res = [tools.get_airport_details(p_manual)] if p_manual else tools.find_nearest_airports(p_addr)
            d_res = [tools.get_airport_details(d_manual)] if d_manual else tools.find_nearest_airports(d_addr)
            
            if not p_res or not p_res[0]: st.error("Pickup Location Error"); st.stop()
            if not d_res or not d_res[0]: st.error("Delivery Location Error"); st.stop()
                
            p_apt, d_apt = p_res[0], d_res[0]
            p_code, p_name = p_apt['code'], p_apt['name']
            d_code, d_name = d_apt['code'], d_apt['name']
            st.session_state.p_code, st.session_state.d_code = p_code, d_code

            d1 = tools.get_road_metrics(p_addr, p_code) or {"miles": 20, "time_str": "30m", "time_min": 30}
            d2 = tools.get_road_metrics(d_code, d_addr) or {"miles": 20, "time_str": "30m", "time_min": 30}
            st.session_state.drive_metrics = {'d1': d1, 'd2': d2, 'p_name': p_name, 'd_name': d_name}
            
            p_drive_used = max(d1['time_min'], custom_p_buff)
            total_prep = p_drive_used + 60 
            
            base_dt = datetime.datetime.strptime(days_to_search[0]['date'], "%Y-%m-%d").date()
            earliest_dep = datetime.datetime.combine(base_dt, p_time) + datetime.timedelta(minutes=total_prep)
            st.session_state.earliest_dep_str = earliest_dep.strftime("%H:%M")
            
            latest_arr_dt = None
            if has_deadline and del_time:
                d_drive_used = max(d2['time_min'], custom_d_buff)
                total_post = d_drive_used + 60
                dummy_del = datetime.datetime.combine(base_dt + datetime.timedelta(days=del_offset), del_time)
                latest_arr_dt = dummy_del - datetime.timedelta(minutes=total_post)
                st.session_state.latest_arr_str = latest_arr_dt.strftime("%H:%M")
            
            for day_obj in days_to_search:
                raw_data = tools.search_flights(p_code, d_code, day_obj['date'], show_all_airlines)
                if not raw_data: continue
                
                for f in raw_data:
                    reject_reason = None
                    airline = f['Airline']
                    s_date = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d").date()
                    
                    if (p_code, airline) not in st.session_state.airline_hours_cache:
                        st.session_state.airline_hours_cache[(p_code, airline)] = tools.get_cargo_hours(p_code, airline, s_date)
                    if (d_code, airline) not in st.session_state.airline_hours_cache:
                        st.session_state.airline_hours_cache[(d_code, airline)] = tools.get_cargo_hours(d_code, airline, s_date)
                    
                    p_h = st.session_state.airline_hours_cache[(p_code, airline)]
                    d_h = st.session_state.airline_hours_cache[(d_code, airline)]
                    
                    if p_h['hours'] == "No Cargo": reject_reason = "No Origin Cargo Facility"
                    
                    dep_time_only = datetime.datetime.strptime(f['Dep Time'], "%H:%M").time()
                    base_dep_dt = datetime.datetime.combine(s_date, dep_time_only)
                    tender_dt = base_dep_dt - datetime.timedelta(minutes=custom_p_buff)
                    
                    if not tools.check_time_in_range(tender_dt.strftime("%H:%M"), p_h['hours']): reject_reason = f"Origin Closed ({p_h['hours']})"
                    if f['Dep Time'] < st.session_state.earliest_dep_str: reject_reason = f"Too Early ({f['Dep Time']})"
                    if f['Conn Apt'] != "Direct" and f['Conn Min'] < min_conn_filter: reject_reason = "Short Connection"
                    
                    if latest_arr_dt:
                        try:
                            f_dt = parser.parse(f['Dep Full']).replace(tzinfo=None)
                            f_arr_dt = parser.parse(f['Arr Full']).replace(tzinfo=None)
                            if f_arr_dt < f_dt: f_arr_dt += datetime.timedelta(days=1)
                            
                            loop_dl = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d") + datetime.timedelta(days=del_offset)
                            loop_dl = loop_dl.replace(hour=del_time.hour, minute=del_time.minute, tzinfo=None)
                            loop_limit = loop_dl - datetime.timedelta(minutes=total_post)
                            
                            if f_arr_dt > loop_limit: reject_reason = "Arrives Too Late"
                        except: pass
                    
                    if not reject_reason:
                        try:
                            dep_dt_full = parser.parse(f['Dep Full']).replace(tzinfo=None)
                            arr_dt_full = parser.parse(f['Arr Full']).replace(tzinfo=None)
                            if arr_dt_full < dep_dt_full: arr_dt_full += datetime.timedelta(days=1)

                            f['Dep DateTime'] = dep_dt_full
                            f['Arr DateTime'] = arr_dt_full
                            
                            air_transit_min = int((arr_dt_full - dep_dt_full).total_seconds() / 60)
                            total_transit_min = total_prep + air_transit_min + total_post
                            
                            scheduled_recovery_dt = arr_dt_full + datetime.timedelta(minutes=60)
                            recovery_note = ""

                            if not tools.check_time_in_range(scheduled_recovery_dt.strftime("%H:%M"), d_h['hours']):
                                next_open_dt = tools.get_next_open_time(scheduled_recovery_dt, d_h['hours'])
                                actual_recovery_dt = next_open_dt + datetime.timedelta(minutes=30) 
                                delay_min = int((actual_recovery_dt - scheduled_recovery_dt).total_seconds() / 60)
                                if delay_min > 0:
                                    total_transit_min += delay_min
                                    recovery_note = f"⚠️ Recovery Delay: Avail {actual_recovery_dt.strftime('%m/%d %H:%M')}"

                            f['Total Transit Min'] = total_transit_min
                            f['Total Transit Str'] = f"{total_transit_min//60}h {total_transit_min%60}m"
                            
                            fra_score, fra_risk = 100, []
                            if HAS_FRA and AVIATION_EDGE_KEY:
                                flight_num_for_fra = f['Flight'].split(' / ')[0]
                                res = analyze_reliability(flight_num_for_fra, AVIATION_EDGE_KEY)
                                if "score" in res: fra_score, fra_risk = res['score'], res['risk_factors']
                            
                            note_parts = []
                            if recovery_note: note_parts.append(recovery_note)
                            if fra_risk: note_parts.append(f"⛈️ Risk: {fra_risk[0]}")
                            
                            f['Notes'] = " ".join(note_parts) if note_parts else "Standard Ops"
                            f['Reliability'] = fra_score
                            f['Days of Op'] = day_obj['day']
                            f['Origin Hours'] = p_h['hours']
                            f['Dest Hours'] = d_h['hours']
                            f['Track'] = f"https://flightaware.com/live/flight/{f['Flight'].split(' / ')[0]}"
                            
                            valid_flights.append(f)
                        except: pass

            valid_flights.sort(key=lambda x: (x['Days of Op'], x['Total Transit Min']))
            st.session_state.valid_flights = valid_flights
            
            # Group flights by day for the Interactive Editor
            grouped = {}
            for f in valid_flights:
                day = f['Days of Op']
                if day not in grouped: grouped[day] = []
                # Add checkboxes init state
                f_display = f.copy()
                f_display['Primary'] = False
                f_display['Backup'] = False
                f_display['Dep DateTime Str'] = f['Dep DateTime'].strftime('%m/%d %H:%M')
                f_display['Arr DateTime Str'] = f['Arr DateTime'].strftime('%m/%d %H:%M')
                grouped[day].append(f_display)
            
            st.session_state.grouped_flights = grouped
            status.update(label="Mission Plan Generated", state="complete", expanded=False)

if st.session_state.valid_flights:
    valid_flights = st.session_state.valid_flights
    best = sorted(valid_flights, key=lambda x: (x['Total Transit Min'], -x['Reliability']))[0]
    p_code, d_code = st.session_state.p_code, st.session_state.d_code
    d1, d2 = st.session_state.drive_metrics['d1'], st.session_state.drive_metrics['d2']

    st.markdown("## 📊 Executive Summary")
    rec_text = f"The recommended routing is via **{best['Airline']} Flight {best['Flight']}**."
    if "Recovery Delay" in best['Notes']: rec_text += f" Note: Delivery is delayed until **{best['Notes'].split('Avail ')[-1]}** due to facility hours."
    st.info(f"**Recommendation:** {rec_text}")

    m1, m2, m3 = st.columns(3)
    m1.metric("Origin Drive", f"{d1['time_str']}", f"{d1['miles']} mi")
    m2.metric("Air Transit", valid_flights[0]['Total Transit Str'], f"{len(valid_flights)} Options")
    m3.metric("Dest Drive", f"{d2['time_str']}", f"{d2['miles']} mi")

    # --- Timeline ---
    best_pickup_dt = best['Dep DateTime'].date() 
    best_pickup_date_str = best_pickup_dt.strftime('%m/%d')
    best_dep_date = best['Dep DateTime'].strftime('%m/%d')
    best_arr_date = best['Arr DateTime'].strftime('%m/%d')
    deadline_date_str = (best_pickup_dt + datetime.timedelta(days=del_offset)).strftime('%m/%d')
    
    st.markdown("### ⛓️ Logistics Chain Visualization")
    st.markdown(f"""
    <div class="timeline-container">
        <div class="timeline-point"><div style="font-size:24px">📦</div><div style="font-weight:bold">Pickup</div><div style="color:#4ade80; font-size: 0.8rem;">{best_pickup_date_str}</div><div style="color:#4ade80">{p_time.strftime('%H:%M')}</div></div>
        <div class="timeline-line"></div>
        <div class="timeline-point"><div style="font-size:24px">🚛</div><div style="font-size:12px; color:#94a3b8">{d1['time_str']}</div></div>
        <div class="timeline-line"></div>
        <div class="timeline-point"><div style="font-size:24px">🛫</div><div style="font-weight:bold">Departs</div><div style="color:#facc15; font-size: 0.8rem;">{best_dep_date}</div><div style="color:#facc15">{best['Dep Time']}</div></div>
        <div class="timeline-line"></div>
        <div class="timeline-point"><div style="font-size:24px">🛬</div><div style="font-weight:bold">Arrives</div><div style="color:#facc15; font-size: 0.8rem;">{best_arr_date}</div><div style="color:#facc15">{best['Arr Time']}</div></div>
        <div class="timeline-line"></div>
        <div class="timeline-point"><div style="font-size:24px">🏁</div><div style="font-weight:bold">Deadline</div><div style="color:#f87171; font-size: 0.8rem;">{deadline_date_str}</div><div style="color:#f87171">{del_time.strftime('%H:%M') if del_time else 'Open'}</div></div>
    </div>
    """, unsafe_allow_html=True)

    # --- Origin/Dest Cards ---
    unique_airlines = sorted(list(set(f['Airline'] for f in valid_flights)))
    origin_hours_list = [f"**{a}:** {st.session_state.airline_hours_cache.get((p_code, a), {}).get('hours','N/A')}" for a in unique_airlines]
    dest_hours_list = [f"**{a}:** {st.session_state.airline_hours_cache.get((d_code, a), {}).get('hours','N/A')}" for a in unique_airlines]
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""<div class="metric-card"><div class="metric-header">ORIGIN: {p_code}</div><div class="metric-value">{st.session_state.drive_metrics['p_name']}</div><div style="margin-top:10px; font-size:0.9rem">📍 <strong>Drive:</strong> {d1['miles']} mi ({d1['time_str']})<br>🗓️ <strong>Pickup Date:</strong> {best_pickup_date_str} ({p_time.strftime('%H:%M')})<br>⏰ <strong>Earliest Dep:</strong> {st.session_state.earliest_dep_str}<br>🏢 <strong>Cargo Hours:</strong><br><div style="font-size: 0.8rem; margin-top: 5px;">{"<br>".join(origin_hours_list)}</div></div></div>""", unsafe_allow_html=True)
    with c2:
        st.markdown(f"""<div class="metric-card"><div class="metric-header">DESTINATION: {d_code}</div><div class="metric-value">{st.session_state.drive_metrics['d_name']}</div><div style="margin-top:10px; font-size:0.9rem">📍 <strong>Drive:</strong> {d2['miles']} mi ({d2['time_str']})<br>🗓️ <strong>Deadline:</strong> {deadline_date_str} ({del_time.strftime('%H:%M') if del_time else 'Open'})<br>⏰ <strong>Latest Arr:</strong> {st.session_state.latest_arr_str}<br>🏢 <strong>Cargo Hours:</strong><br><div style="font-size: 0.8rem; margin-top: 5px;">{"<br>".join(dest_hours_list)}</div></div></div>""", unsafe_allow_html=True)

    st.markdown("---")

    # ======================================================================
    # D. RECURRING PLAN BUILDER (INTERACTIVE CHECKBOXES)
    # ======================================================================
    if mode == "Reoccurring" and st.session_state.grouped_flights:
        st.markdown("### 🛠️ Recurring Flight Plan Builder")
        st.info("Select your **Primary** and **Backup** flights using the checkboxes below.")
        
        # Columns to show in editor
        editor_cols = ["Primary", "Backup", "Airline", "Flight", "Dep DateTime Str", "Arr DateTime Str", "Total Transit Str", "Notes", "Reliability"]
        
        day_map = {"Mon":0, "Tue":1, "Wed":2, "Thu":3, "Fri":4, "Sat":5, "Sun":6}
        sorted_days = sorted(st.session_state.grouped_flights.keys(), key=lambda d: day_map.get(d, 99))
        
        with st.form("flight_selector_form"):
            for day in sorted_days:
                st.subheader(f"🗓️ {day}")
                flights_df = pd.DataFrame(st.session_state.grouped_flights[day])
                
                # Use Data Editor for checkboxes
                edited_df = st.data_editor(
                    flights_df[editor_cols],
                    key=f"editor_{day}",
                    hide_index=True,
                    use_container_width=True,
                    column_config={
                        "Primary": st.column_config.CheckboxColumn("Primary", default=False),
                        "Backup": st.column_config.CheckboxColumn("Backup", default=False),
                        "Dep DateTime Str": st.column_config.TextColumn("Departure"),
                        "Arr DateTime Str": st.column_config.TextColumn("Arrival"),
                        "Total Transit Str": st.column_config.TextColumn("Total Time"),
                        "Reliability": st.column_config.ProgressColumn("Risk", format="%d%%", min_value=0, max_value=100)
                    }
                )
                # Store the edited state to process later
                st.session_state.editor_data[day] = edited_df
            
            st.markdown("---")
            submitted = st.form_submit_button("✅ Build Final Plan", type="primary")
            
        if submitted:
            st.session_state.flight_plan_df = create_flight_plan_table(st.session_state.editor_data, p_time, del_time, del_offset, p_code, d_code)
            st.rerun()

    # ONE-TIME MODE DISPLAY
    elif mode == "One-Time (Ad-Hoc)" and valid_flights:
        st.markdown("### ✅ Recommended Flights (One-Time)")
        df_ot = pd.DataFrame(valid_flights)
        df_ot = df_ot.sort_values(by='Total Transit Min')
        df_ot['Dep DateTime Str'] = df_ot['Dep DateTime'].dt.strftime('%m/%d %H:%M')
        df_ot['Arr DateTime Str'] = df_ot['Arr DateTime'].dt.strftime('%m/%d %H:%M')
        
        cols_ot = ["Airline", "Flight", "Dep DateTime Str", "Arr DateTime Str", "Origin Hours", "Dest Hours", "Total Transit Str", "Notes", "Reliability", "Track"]
        st.dataframe(
            df_ot[cols_ot], 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "Dep DateTime Str": st.column_config.TextColumn("Departure"),
                "Arr DateTime Str": st.column_config.TextColumn("Arrival"),
                "Total Transit Str": st.column_config.TextColumn("Total Transit"),
                "Origin Hours": st.column_config.TextColumn("Origin Hours", width="small"), 
                "Dest Hours": st.column_config.TextColumn("Dest Hours", width="small"),
                "Reliability": st.column_config.ProgressColumn("Risk", format="%d%%", min_value=0, max_value=100),
                "Track": st.column_config.LinkColumn("Tracker", display_text="Track"),
            }
        )
        st.markdown("---")

if st.session_state.flight_plan_df is not None:
    st.markdown("## ✈️ Final Recurring Flight Plan")
    PLAN_COLUMNS = ["DATE", "DAY", "REQ'D PICK UP", "ORIGIN", "DEST", "AIRLINE", "FLT #", "ETD", "CNX FLT", "CNX CITY", "ETA", "DUE TIME", "PREBOOK #", "BACKUP FLTS", "BACKUP FLT TIMES", "NOTES"]
    st.dataframe(st.session_state.flight_plan_df[PLAN_COLUMNS], hide_index=True, use_container_width=True)
    st.markdown("---")
elif run_btn and not st.session_state.valid_flights:
    st.error("No valid flights found.")
