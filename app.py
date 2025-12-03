import streamlit as st
import pandas as pd
import datetime
import requests
import math
import re
from dateutil import parser, relativedelta
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# IMPORT THE NEW MODULE (Make sure modules/fra_engine.py exists!)
try:
    from modules.fra_engine import analyze_reliability
    HAS_FRA_MODULE = True
except ImportError:
    HAS_FRA_MODULE = False

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

try:
    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
    GOOGLE_MAPS_KEY = st.secrets.get("GOOGLE_MAPS_KEY", None)
    AVIATION_EDGE_KEY = st.secrets.get("AVIATION_EDGE_KEY", None)
except:
    st.error("❌ System Error: API Keys missing in Secrets.")
    st.stop()

# ==============================================================================
# 2. LOGISTICS ENGINE (Class)
# ==============================================================================
# ... [Keep the LogisticsTools Class EXACTLY as it was in v45] ...
# (I will paste the class below for completeness, but it is unchanged)
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_app_prod_v46_tabs", timeout=10)
        self.master_df = None
        try:
            self.master_df = pd.read_csv("cargo_master.csv")
            self.master_df.columns = [c.strip().lower().replace(" ", "_") for c in self.master_df.columns]
        except Exception: pass
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
        try:
            clean = location.replace("Suite", "").replace("#", "").split(",")[0] + ", " + location.split(",")[-1]
            loc = self.geolocator.geocode(clean)
            if loc: return (loc.latitude, loc.longitude)
        except: pass
        return None

    def get_airport_details(self, code):
        code = code.upper()
        if AVIATION_EDGE_KEY:
            url = "https://aviation-edge.com/v2/public/airportDatabase"
            try:
                r = requests.get(url, params={"key": AVIATION_EDGE_KEY, "codeIataAirport": code}, timeout=5)
                data = r.json()
                if data and isinstance(data, list):
                    return {"code": code, "name": data[0].get("nameAirport", code), "coords": (float(data[0]['latitudeAirport']), float(data[0]['longitudeAirport']))}
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
            snip = r.json()["organic_results"][0].get("snippet", "") if "organic_results" in r.json() else "No details"
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
                data = r.json()
                if isinstance(data, list):
                    for apt in data:
                        if len(apt.get("codeIataAirport", "")) == 3: candidates.append({"code": apt.get("codeIataAirport").upper(), "name": apt.get("nameAirport"), "air_miles": round(float(apt.get("distance")) * 0.621371, 1)})
                    if candidates:
                        candidates.sort(key=lambda x: x["air_miles"])
                        return candidates[:3]
            except: pass
        
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
                        
                        dep_time_full = f.get('departure', {}).get('scheduledTime', '')
                        arr_time_full = f.get('arrival', {}).get('scheduledTime', '')
                        
                        try:
                            dur = (datetime.datetime.strptime(arr_time_full.split('.')[0], "%Y-%m-%dT%H:%M:%S") - datetime.datetime.strptime(dep_time_full.split('.')[0], "%Y-%m-%dT%H:%M:%S")).total_seconds()/60
                            dur_str = f"{int(dur//60)}h {int(dur%60)}m"
                        except: dur_str = "N/A"

                        results.append({
                            "Airline": airline, "Flight": f"{airline}{f.get('flight',{}).get('iataNumber','')}",
                            "Origin": f.get('departure', {}).get('iataCode', origin), "Dep Time": dep_time_full.split('T')[-1][:5], "Dep Full": dep_time_full,
                            "Dest": f.get('arrival', {}).get('iataCode', dest), "Arr Time": arr_time_full.split('T')[-1][:5], "Arr Full": arr_time_full,
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
            if "best_flights" in data or "other_flights" in data:
                for f in (data.get("best_flights", []) + data.get("other_flights", []))[:20]:
                    legs = f.get('flights', [])
                    if not legs: continue
                    layovers = f.get('layovers', [])
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
                        "Conn Apt": layovers[0].get('id', 'Direct') if layovers else "Direct",
                        "Conn Time": f"{layovers[0].get('duration',0)//60}h {layovers[0].get('duration',0)%60}m" if layovers else "N/A",
                        "Conn Min": layovers[0].get('duration', 0) if layovers else 0
                    })
            return results
        except: return []

# ==============================================================================
# 3. MAIN INTERFACE (TABS)
# ==============================================================================

st.title("Logistics Command Center")
tab1, tab2 = st.tabs(["🚛 Logistics Planner", "🌦️ Risk Analyzer"])

# --- TAB 1: LOGISTICS PLANNER (Your Original App) ---
with tab1:
    st.header("Verified Door-to-Door Scheduler")
    
    col1, col2 = st.columns([1, 2])
    
    with col1: # CONTROLS
        mode = st.radio("Frequency", ["One-Time (Ad-Hoc)", "Reoccurring"])
        p_addr = st.text_input("Pickup Address", "2008 Altom Ct, St. Louis, MO 63146")
        p_manual = st.text_input("Origin Override (Opt)", placeholder="e.g. STL")
        d_addr = st.text_input("Delivery Address", "1250 E Hadley St, Phoenix, AZ 85034")
        d_manual = st.text_input("Dest Override (Opt)", placeholder="e.g. PHX")
        
        p_time = st.time_input("Ready Time", datetime.time(9, 0))
        
        if mode == "One-Time (Ad-Hoc)":
            p_date = st.date_input("Pickup Date", datetime.date.today() + datetime.timedelta(days=1))
            days_to_search = [{"day": "One-Time", "date": p_date.strftime("%Y-%m-%d")}]
        else:
            days_selected = st.multiselect("Days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ["Mon", "Wed", "Fri"])
            today = datetime.date.today()
            day_map = {"Mon":0, "Tue":1, "Wed":2, "Thu":3, "Fri":4, "Sat":5, "Sun":6}
            days_to_search = []
            for d in days_selected:
                diff = day_map[d] - today.weekday()
                if diff <= 0: diff += 7
                days_to_search.append({"day": d, "date": (today + datetime.timedelta(days=diff)).strftime("%Y-%m-%d")})
                
        has_deadline = st.checkbox("Strict Deadline?", value=True)
        del_time = None
        del_offset = 0
        
        if has_deadline:
            del_time = st.time_input("Must Arrive By", datetime.time(18, 0))
            if mode == "One-Time (Ad-Hoc)":
                 d_date = st.date_input("Delivery Date", p_date + datetime.timedelta(days=1))
                 del_offset = (d_date - p_date).days
            else:
                 offset_opt = st.selectbox("Transit Days", ["Same Day", "Next Day (+1)", "+2 Days"], index=1)
                 del_offset = 0 if "Same" in offset_opt else (1 if "Next" in offset_opt else 2)

        with st.expander("Settings"):
            custom_p_buff = st.number_input("Pickup Buffer", 120)
            custom_d_buff = st.number_input("Del Buffer", 120)
            show_all = st.checkbox("Show All Airlines", False)

        run_logistics = st.button("Generate Plan", type="primary")

    with col2: # RESULTS
        if run_logistics:
            tools = LogisticsTools()
            with st.status("Calculating...", expanded=True):
                # 1. Geo
                st.write("📍 Locations...")
                p_res = [tools.get_airport_details(p_manual)] if p_manual else tools.find_nearest_airports(p_addr)
                d_res = [tools.get_airport_details(d_manual)] if d_manual else tools.find_nearest_airports(d_addr)
                
                if not p_res or not d_res:
                    st.error("Location Error")
                    st.stop()
                    
                p_code, d_code = p_res[0]['code'], d_res[0]['code']
                p_name, d_name = p_res[0].get('name',''), d_res[0].get('name','')
                
                # 2. Road
                st.write("🚚 Drives...")
                d1 = tools.get_road_metrics(p_addr, p_code) or {"miles": 20, "time_str": "30m (Est)", "time_min": 30}
                d2 = tools.get_road_metrics(d_code, d_addr) or {"miles": 20, "time_str": "30m (Est)", "time_min": 30}
                
                # 3. Math
                total_prep = max(d1['time_min'], custom_p_buff) + 60
                total_post = max(d2['time_min'], custom_d_buff) + 60
                
                base_date = p_date if mode == "One-Time (Ad-Hoc)" else datetime.datetime.strptime(days_to_search[0]['date'], "%Y-%m-%d").date()
                earliest_dep = datetime.datetime.combine(base_date, p_time) + datetime.timedelta(minutes=total_prep)
                earliest_str = earliest_dep.strftime("%H:%M")
                
                latest_arr_dt = None
                if del_time:
                    dummy_del = datetime.datetime.combine(base_date + datetime.timedelta(days=del_offset), del_time)
                    latest_arr_dt = dummy_del - datetime.timedelta(minutes=total_post)

                # 4. Flights
                st.write("✈️ Flights...")
                valid, rejected, hours_cache = [], [], {}
                
                for day_obj in days_to_search:
                    raw = tools.search_flights(p_code, d_code, day_obj['date'], show_all)
                    for f in raw:
                        reject = None
                        airline = f['Airline']
                        s_date = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d")
                        
                        if (p_code, airline) not in hours_cache: hours_cache[(p_code, airline)] = tools.get_cargo_hours(p_code, airline, s_date)
                        if (d_code, airline) not in hours_cache: hours_cache[(d_code, airline)] = tools.get_cargo_hours(d_code, airline, s_date)
                        
                        p_h = hours_cache[(p_code, airline)]
                        tender_time = (datetime.datetime.strptime(f['Dep Time'], "%H:%M") - datetime.timedelta(minutes=120)).strftime("%H:%M")
                        if not tools.check_time_in_range(tender_time, p_h['hours']): reject = f"Org Closed ({p_h['hours']})"
                        
                        if f['Dep Time'] < earliest_str: reject = f"Too Early ({f['Dep Time']})"
                        
                        if latest_arr_dt and not reject:
                            try:
                                f_dt = datetime.datetime.strptime(f['Arr Full'], "%Y-%m-%d %H:%M") if 'T' not in f['Arr Full'] else datetime.datetime.strptime(f['Arr Full'].split('.')[0], "%Y-%m-%dT%H:%M:%S")
                                if f_dt.time() > latest_arr_dt.time() and (f_dt.date() - s_date.date()).days >= del_offset: reject = "Late Arrival"
                            except: pass

                        if reject:
                            f['Reason'] = reject
                            rejected.append(f)
                        else:
                            f['Days of Op'] = day_obj['day']
                            rec_time = (datetime.datetime.strptime(f['Arr Time'], "%H:%M") + datetime.timedelta(minutes=60)).strftime("%H:%M")
                            d_h = hours_cache[(d_code, airline)]['hours']
                            f['Note'] = f"⚠️ AM Recovery ({d_h})" if not tools.check_time_in_range(rec_time, d_h) else "OK"
                            valid.append(f)

            # RENDER
            st.success(f"Plan: {p_code} -> {d_code}")
            st.info(f"Pickup Drive: {d1['miles']} mi ({d1['time_str']}) | Earliest Dep: {earliest_str}")
            st.info(f"Delivery Drive: {d2['miles']} mi ({d2['time_str']}) | Latest Arr: {latest_arr_dt.strftime('%H:%M') if latest_arr_dt else 'N/A'}")
            
            if valid:
                # Aggregate
                grouped = {}
                for f in valid:
                    k = (f['Airline'], f['Flight'], f['Dep Time'])
                    if k not in grouped: grouped[k] = {**f, 'Days of Op': {f['Days of Op']}}
                    else: grouped[k]['Days of Op'].add(f['Days of Op'])
                
                rows = []
                for f in grouped.values():
                    f['Days of Op'] = ", ".join(sorted(list(f['Days of Op'])))
                    rows.append(f)
                
                st.dataframe(pd.DataFrame(rows)[["Airline", "Flight", "Days of Op", "Dep Time", "Arr Time", "Note", "Conn Apt"]], hide_index=True, use_container_width=True)
            elif rejected:
                st.warning("No valid flights. See rejected:")
                st.dataframe(pd.DataFrame(rejected)[["Airline", "Flight", "Dep Time", "Reason"]], hide_index=True)
            else:
                st.error("No flights found.")

# --- TAB 2: RISK ANALYZER (New Module) ---
with tab2:
    st.header("✈️ Flight Risk Engine")
    
    if not HAS_FRA_MODULE:
        st.warning("⚠️ `modules/fra_engine.py` not found. Please create the file to enable this tab.")
    else:
        with st.form("risk_check"):
            c1, c2 = st.columns([3, 1])
            f_num = c1.text_input("Flight Number (IATA)", "UA2404")
            c2.write("")
            c2.write("")
            check_btn = c2.form_submit_button("Analyze Risk", type="primary")
            
        if check_btn:
            api_key = st.secrets.get("AVIATION_EDGE_KEY", None)
            if not api_key:
                st.error("Aviation Edge Key missing.")
            else:
                with st.status("Analyzing Weather & Regs..."):
                    res = analyze_reliability(f_num, api_key)
                
                if "error" in res:
                    st.error(res['error'])
                else:
                    m1, m2, m3 = st.columns(3)
                    color = "normal" if res['score'] > 60 else "inverse"
                    m1.metric("Reliability Score", f"{res['score']}/100", res['status'], delta_color=color)
                    m2.metric("Dest", res['flight_info']['dest_icao'])
                    m3.metric("Status", res['flight_info']['status'].upper())
                    
                    if res['risk_factors']:
                        st.error(f"Risk Factors: {', '.join(res['risk_factors'])}")
                    else:
                        st.success("✅ No major weather risks detected.")
