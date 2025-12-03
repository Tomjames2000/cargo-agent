import streamlit as st
import pandas as pd
import datetime
import requests
import math
import re
from dateutil import parser, relativedelta
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# IMPORT FLIGHT RELIABILITY MODULE (Graceful fail if missing)
try:
    from modules.fra_engine import analyze_reliability
    HAS_FRA = True
except ImportError:
    HAS_FRA = False

# ==============================================================================
# 1. VISUAL CONFIGURATION (Dark Mode / Command Center)
# ==============================================================================
st.set_page_config(
    page_title="Cargo Logistics Master", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="expanded"
)

# Custom CSS for "Command Center" look
st.markdown("""
<style>
    /* Card Styling */
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
    /* Timeline Styling */
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
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. SECURITY
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

try:
    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
    GOOGLE_MAPS_KEY = st.secrets.get("GOOGLE_MAPS_KEY", None)
    AVIATION_EDGE_KEY = st.secrets.get("AVIATION_EDGE_KEY", None)
except:
    st.error("❌ Critical Error: API Keys missing.")
    st.stop()

# ==============================================================================
# 3. LOGISTICS ENGINE
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_command_v56_final", timeout=10)
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
        # 1. Check Master CSV
        if self.master_df is not None and len(location) == 3:
            match = self.master_df[self.master_df['airport_code'] == location.upper()]
            if not match.empty: return (match.iloc[0]['latitude_deg'], match.iloc[0]['longitude_deg'])
        
        # 2. Check DB
        if location.upper() in self.AIRPORT_DB: return self.AIRPORT_DB[location.upper()]["coords"]
        
        # 3. Google Maps Geocoding
        if GOOGLE_MAPS_KEY:
            try:
                url = "https://maps.googleapis.com/maps/api/geocode/json"
                params = {"address": location, "key": GOOGLE_MAPS_KEY}
                r = requests.get(url, params=params, timeout=5)
                data = r.json()
                if data['status'] == 'OK':
                    loc = data['results'][0]['geometry']['location']
                    return (loc['lat'], loc['lng'])
            except: pass

        # 4. Fallback Geocoding
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
        try:
            r = requests.get(url, params={"engine": "google", "q": f"{airline} cargo hours {airport_code} {day_name}", "api_key": SERPAPI_KEY, "num": 1}, timeout=5)
            snip = r.json().get("organic_results", [{}])[0].get("snippet", "No data")
            return {"status": "Unverified", "hours": f"Web: {snip[:40]}...", "source": "Web Search"}
        except: return {"status": "Unknown", "hours": "Unknown", "source": "No Data"}

    def check_time_in_range(self, target_time, range_str):
        if any(x in range_str.lower() for x in ["no cargo", "closed", "n/a"]): return False
        if "24" in range_str or "Daily" in range_str: return True
        try:
            times = re.findall(r'\d{1,2}:\d{2}', range_str)
            if len(times) != 2: return True
            start, end = datetime.datetime.strptime(times[0], "%H:%M").time(), datetime.datetime.strptime(times[1], "%H:%M").time()
            check = datetime.datetime.strptime(target_time, "%H:%M").time()
            if start <= end: return start <= check <= end
            else: return start <= check or check <= end
        except: return True

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
            if self.master_df is not None:
                try:
                    unique = self.master_df[['airport_code', 'airport_name', 'latitude_deg', 'longitude_deg']].drop_duplicates()
                    for _, row in unique.iterrows():
                        if row['airport_code'] not in self.AIRPORT_DB:
                            dist = geodesic(user_coords, (row['latitude_deg'], row['longitude_deg'])).miles
                            candidates.append({"code": row['airport_code'], "name": row['airport_name'], "air_miles": round(dist, 1)})
                except: pass
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
                    if elem['status'] == 'OK':
                        return {"miles": round(elem['distance']['value'] * 0.000621371, 1), "time_str": f"{int(elem.get('duration_in_traffic', elem['duration'])['value'] // 3600)}h {int((elem.get('duration_in_traffic', elem['duration'])['value'] % 3600) // 60)}m", "time_min": round(elem.get('duration_in_traffic', elem['duration'])['value']/60)}
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
        # 1. Aviation Edge
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

        # 2. SerpApi Backup
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
                    "Conn Apt": conn_apt,
                    "Conn Time": conn_time_str,
                    "Conn Min": conn_min
                })
            return results
        except: return []

# ==============================================================================
# 3. DASHBOARD UI
# ==============================================================================

st.sidebar.title("🎮 Control Panel")

# --- INPUTS ---
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
        if diff <= 0: diff += 7
        days_to_search.append({"day": d, "date": (today + datetime.timedelta(days=diff)).strftime("%Y-%m-%d")})

with st.sidebar.expander("⚙️ Settings"):
    custom_p_buff = st.sidebar.number_input("Pickup Buffer", 120)
    custom_d_buff = st.sidebar.number_input("Del Buffer", 120)
    min_conn = st.sidebar.number_input("Min Conn", 60)
    show_all = st.sidebar.checkbox("Show All Airlines", False)

run_btn = st.sidebar.button("🚀 Run Analysis", type="primary")

# --- MAIN OUTPUT ---
if run_btn:
    tools = LogisticsTools()
    
    with st.status("📡 Establishing Logistics Chain...", expanded=True) as status:
        
        # 1. GEOGRAPHY
        st.write("📍 Geocoding Locations...")
        p_res = [tools.get_airport_details(p_manual)] if p_manual else tools.find_nearest_airports(p_addr)
        d_res = [tools.get_airport_details(d_manual)] if d_manual else tools.find_nearest_airports(d_addr)
        
        if not p_res or not p_res[0]:
            st.error(f"Could not resolve Pickup. Check address or override code.")
            st.stop()
        if not d_res or not d_res[0]:
            st.error(f"Could not resolve Delivery. Check address or override code.")
            st.stop()
            
        p_apt, d_apt = p_res[0], d_res[0]
        p_code, p_name = p_apt['code'], p_apt['name']
        d_code, d_name = d_apt['code'], d_apt['name']
        
        # 2. DRIVE
        st.write(f"🚚 Routing ({p_code}-{d_code})...")
        d1 = tools.get_road_metrics(p_addr, p_code) or {"miles": 20, "time_str": "30m", "time_min": 30}
        d2 = tools.get_road_metrics(d_code, d_addr) or {"miles": 20, "time_str": "30m", "time_min": 30}
        
        # 3. MATH
        p_drive_used = max(d1['time_min'], custom_p_buff)
        total_prep = p_drive_used + 60
        
        base_dt = p_date if mode == "One-Time (Ad-Hoc)" else datetime.datetime.strptime(days_to_search[0]['date'], "%Y-%m-%d").date()
        earliest_dep = datetime.datetime.combine(base_dt, p_time) + datetime.timedelta(minutes=total_prep)
        earliest_str = earliest_dep.strftime("%H:%M")
        
        latest_arr_dt = None
        total_post = 0
        if del_time:
            d_drive_used = max(d2['time_min'], custom_d_buff)
            total_post = d_drive_used + 60
            dummy_del = datetime.datetime.combine(base_dt + datetime.timedelta(days=del_offset), del_time)
            latest_arr_dt = dummy_del - datetime.timedelta(minutes=total_post)
        
        # 4. FLIGHTS
        st.write("✈️ Analyzing Flights & Risk...")
        valid, rejected, airline_hours = [], [], {}
        
        for day in days_to_search:
            raw = tools.search_flights(p_code, d_code, day['date'], show_all)
            for f in raw:
                s_date = datetime.datetime.strptime(day['date'], "%Y-%m-%d")
                if (p_code, f['Airline']) not in airline_hours:
                    airline_hours[(p_code, f['Airline'])] = tools.get_cargo_hours(p_code, f['Airline'], s_date)
                if (d_code, f['Airline']) not in airline_hours:
                    airline_hours[(d_code, f['Airline'])] = tools.get_cargo_hours(d_code, f['Airline'], s_date)
                
                p_h = airline_hours[(p_code, f['Airline'])]
                d_h = airline_hours[(d_code, f['Airline'])]
                
                reason = None
                if p_h['hours'] == "No Cargo": reason = "No Origin Cargo Facility"
                
                tender_dt = datetime.datetime.strptime(f['Dep Time'], "%H:%M") - datetime.timedelta(minutes=120)
                if not tools.check_time_in_range(tender_dt.strftime("%H:%M"), p_h['hours']): reason = f"Origin Closed ({p_h['hours']})"
                
                if f['Dep Time'] < earliest_str: reason = f"Too Early ({f['Dep Time']})"
                if f['Conn Apt'] != "Direct" and f['Conn Min'] < min_conn: reason = "Short Connection"
                
                if latest_arr_dt:
                    try:
                        f_dt = datetime.datetime.strptime(f['Arr Full'], "%Y-%m-%d %H:%M") if 'T' in f['Arr Full'] else datetime.datetime.strptime(f"{day['date']} {f['Arr Time']}", "%Y-%m-%d %H:%M")
                        if f['Arr Time'] < f['Dep Time']: f_dt += datetime.timedelta(days=1)
                        
                        loop_dl = datetime.datetime.strptime(day['date'], "%Y-%m-%d") + datetime.timedelta(days=del_offset)
                        loop_dl = loop_dl.replace(hour=del_time.hour, minute=del_time.minute)
                        loop_limit = loop_dl - datetime.timedelta(minutes=total_post)
                        
                        if f_dt > loop_limit: reason = "Arrives Too Late"
                    except: pass
                
                if reason:
                    f['Reason'] = reason
                    f['Day'] = day['day']
                    rejected.append(f)
                else:
                    # FRA Check
                    fra_score, fra_risk = 100, []
                    if HAS_FRA and AVIATION_EDGE_KEY:
                        res = analyze_reliability(f['Flight'], AVIATION_EDGE_KEY)
                        if "score" in res:
                            fra_score, fra_risk = res['score'], res['risk_factors']
                    
                    rec_time = (datetime.datetime.strptime(f['Arr Time'], "%H:%M") + datetime.timedelta(minutes=60)).strftime("%H:%M")
                    note_parts = []
                    if not tools.check_time_in_range(rec_time, d_h['hours']): note_parts.append(f"⚠️ AM Recovery ({d_h['hours']})")
                    if fra_risk: note_parts.append(f"⛈️ Risk: {fra_risk[0]}")
                    
                    f['Notes'] = " ".join(note_parts) if note_parts else "Standard Ops"
                    f['Reliability'] = fra_score
                    f['Days of Op'] = day['day']
                    valid.append(f)

        status.update(label="Mission Plan Generated", state="complete", expanded=False)

    # --- A. EXECUTIVE SUMMARY ---
    st.markdown("## 📊 Executive Summary")
    
    if valid:
        best = sorted(valid, key=lambda x: (x['Arr Time'], -x['Reliability']))[0]
        rec_text = f"The recommended routing is via **{best['Airline']} Flight {best['Flight']}**."
        rec_text += f" Departing {best['Origin']} at {best['Dep Time']} and arriving {best['Dest']} at {best['Arr Time']} offers the optimal balance of speed and reliability."
        
        if "AM Recovery" in best['Notes']: 
            rec_text += " **Note:** Flight arrives during facility closure; freight will be available for recovery the next morning."
        
        if best['Reliability'] < 70: 
            rec_text += " ⚠️ **Caution:** High risk of weather delay identified on this route."
            
        st.info(f"**Recommendation:** {rec_text}")
    else:
        st.error("No valid flights found that meet all constraints.")

    m1, m2, m3 = st.columns(3)
    m1.metric("Origin Drive", f"{d1['time_str']}", f"{d1['miles']} mi")
    m2.metric("Air Transit", valid[0]['Duration'] if valid else "N/A", f"{len(valid)} Options")
    m3.metric("Dest Drive", f"{d2['time_str']}", f"{d2['miles']} mi")

    # --- B. VISUAL TIMELINE ---
    st.markdown("### ⛓️ Logistics Chain Visualization")
    timeline_html = f"""
    <div class="timeline-container">
        <div class="timeline-point">
            <div style="font-size:24px">📦</div>
            <div style="font-weight:bold">Pickup</div>
            <div style="color:#4ade80">{p_time.strftime('%H:%M')}</div>
        </div>
        <div class="timeline-line"></div>
        <div class="timeline-point">
            <div style="font-size:24px">🚛</div>
            <div style="font-size:12px; color:#94a3b8">{d1['time_str']}</div>
        </div>
        <div class="timeline-line"></div>
        <div class="timeline-point">
            <div style="font-size:24px">🛫</div>
            <div style="font-weight:bold">Departs</div>
            <div style="color:#facc15">{valid[0]['Dep Time'] if valid else '--:--'}</div>
        </div>
        <div class="timeline-line"></div>
        <div class="timeline-point">
            <div style="font-size:24px">🛬</div>
            <div style="font-weight:bold">Arrives</div>
            <div style="color:#facc15">{valid[0]['Arr Time'] if valid else '--:--'}</div>
        </div>
        <div class="timeline-line"></div>
        <div class="timeline-point">
            <div style="font-size:24px">🏁</div>
            <div style="font-weight:bold">Deadline</div>
            <div style="color:#f87171">{del_time.strftime('%H:%M') if del_time else 'Open'}</div>
        </div>
    </div>
    """
    st.markdown(timeline_html, unsafe_allow_html=True)

    # --- C. ORIGIN / DEST CARDS ---
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-header">ORIGIN: {p_code}</div>
            <div class="metric-value">{p_name}</div>
            <div style="margin-top:10px; font-size:0.9rem">
                📍 <strong>Drive:</strong> {d1['miles']} mi ({d1['time_str']})<br>
                ⏰ <strong>Earliest Dep:</strong> {earliest_dep_str}<br>
                🏢 <strong>Facility Hours:</strong><br>
                {list(airline_hours.values())[0]['hours'] if airline_hours else 'N/A'}
            </div>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-header">DESTINATION: {d_code}</div>
            <div class="metric-value">{d_name}</div>
            <div style="margin-top:10px; font-size:0.9rem">
                📍 <strong>Drive:</strong> {d2['miles']} mi ({d2['time_str']})<br>
                ⏰ <strong>Latest Arr:</strong> {latest_arr_str if latest_arr_dt else 'N/A'}<br>
                🏢 <strong>Facility Hours:</strong><br>
                {list(airline_hours.values())[1]['hours'] if len(airline_hours)>1 else 'N/A'}
            </div>
        </div>
        """, unsafe_allow_html=True)

    # --- D. TACTICAL TABLE ---
    st.markdown("### ✅ Recommended Flights")
    if valid:
        grouped = {}
        for f in valid:
            key = (f['Airline'], f['Flight'], f['Dep Time'], f['Arr Time'])
            if key not in grouped:
                grouped[key] = f.copy()
                grouped[key]['Days of Op'] = {f['Days of Op']}
            else:
                grouped[key]['Days of Op'].add(f['Days of Op'])
        
        rows = []
        for f in grouped.values():
            days = sorted(list(f['Days of Op']), key=lambda x: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun","One-Time"].index(x) if x in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun","One-Time"] else 99)
            f['Days of Op'] = ", ".join(days)
            rows.append(f)
            
        df = pd.DataFrame(rows)
        cols = ["Airline", "Flight", "Days of Op", "Dep Time", "Arr Time", "Duration", "Notes", "Reliability"]
        
        st.dataframe(
            df[cols], 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "Reliability": st.column_config.ProgressColumn(
                    "Risk Score",
                    format="%d%%",
                    min_value=0,
                    max_value=100,
                ),
                "Notes": st.column_config.TextColumn("Operational Notes", width="large")
            }
        )
    else:
        if rejected_flights:
            with st.expander("View Rejected Options"):
                st.dataframe(pd.DataFrame(rejected_flights)[["Airline", "Flight", "Dep Time", "Reason"]])
