import streamlit as st
import pandas as pd
import datetime
import requests
import math
from dateutil import parser, relativedelta
from geopy.geocoders import Nominatim
from geopy.distance import geodesic

# ==============================================================================
# 1. VISUAL CONFIGURATION (Dark Mode / Command Center)
# ==============================================================================
st.set_page_config(
    page_title="Logistics Command Center", 
    layout="wide", 
    page_icon="✈️",
    initial_sidebar_state="expanded"
)

# Custom CSS for "Command Center" look
st.markdown("""
<style>
    .metric-card {
        background-color: #262730;
        border: 1px solid #464b5c;
        padding: 15px;
        border-radius: 8px;
        text-align: center;
    }
    .stAlert {
        border-radius: 5px; 
    }
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# 2. SECURITY
# ==============================================================================
def check_password():
    """Returns `True` if the user had the correct password."""
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
except:
    st.error("❌ Critical Error: API Keys missing.")
    st.stop()

# ==============================================================================
# 3. LOGISTICS ENGINE (The Logic Core)
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_command_center_v38", timeout=10)
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
        
        # Load Master File
        self.master_df = None
        try:
            self.master_df = pd.read_csv("cargo_master.csv")
            self.master_df.columns = [c.strip().lower().replace(" ", "_") for c in self.master_df.columns]
        except: pass

    def _get_coords(self, location: str):
        if self.master_df is not None and len(location) == 3:
            match = self.master_df[self.master_df['airport_code'] == location.upper()]
            if not match.empty:
                return (match.iloc[0]['latitude_deg'], match.iloc[0]['longitude_deg'])

        if location.upper() in self.AIRPORT_DB:
            return self.AIRPORT_DB[location.upper()]
            
        try:
            clean_loc = location.replace("Suite", "").replace("#", "").split(",")[0]
            loc = self.geolocator.geocode(clean_loc)
            if loc: return (loc.latitude, loc.longitude)
        except: pass
        return None

    def get_cargo_hours(self, airport_code, airline, date_obj):
        day_name = date_obj.strftime("%A")
        col_map = {"Saturday": "saturday", "Sunday": "sunday"}
        day_col = col_map.get(day_name, "weekday") 

        if self.master_df is not None:
            mask = (self.master_df['airport_code'] == airport_code) & \
                   (self.master_df['airline'].str.contains(airline, case=False, na=False))
            row = self.master_df[mask]
            if not row.empty:
                return {"hours": str(row.iloc[0][day_col]), "source": "Master File"}

        # Web Search Fallback (SerpApi)
        url = "https://serpapi.com/search"
        query = f"{airline} cargo hours {airport_code} {day_name}"
        params = {"engine": "google", "q": query, "api_key": SERPAPI_KEY, "num": 1}
        try:
            r = requests.get(url, params=params, timeout=5)
            data = r.json()
            snippet = data.get("organic_results", [{}])[0].get("snippet", "No data")
            return {"hours": f"Web: {snippet[:40]}...", "source": "Web Search"}
        except:
            return {"hours": "Unknown", "source": "None"}

    def check_time_in_range(self, target_time, range_str):
        if "24" in range_str or "Daily" in range_str: return True
        if "Closed" in range_str: return False
        return True # Default safe

    def find_nearest_airports(self, address: str):
        user_coords = self._get_coords(address)
        if not user_coords: return None
        candidates = []
        for code, coords in self.AIRPORT_DB.items():
            dist = geodesic(user_coords, coords).miles
            candidates.append({"code": code, "air_miles": round(dist, 1)})
        candidates.sort(key=lambda x: x["air_miles"])
        return candidates[:3]

    def get_road_metrics(self, origin: str, destination: str):
        coords_start = self._get_coords(origin)
        coords_end = self._get_coords(destination)
        if not coords_start or not coords_end: return None
        
        url = f"https://router.project-osrm.org/route/v1/driving/{coords_start[1]},{coords_start[0]};{coords_end[1]},{coords_end[0]}"
        headers = {"User-Agent": "CargoApp/1.0"}
        
        try:
            r = requests.get(url, params={"overview": "false"}, headers=headers, timeout=15)
            data = r.json()
            if data.get("code") != "Ok": raise Exception("No route")
            sec = data['routes'][0]['duration']
            miles = data['routes'][0]['distance'] * 0.000621371
            hours = int(sec // 3600)
            mins = int((sec % 3600) // 60)
            return {"miles": round(miles, 1), "time_str": f"{hours}h {mins}m", "time_min": round(sec/60)}
        except:
            dist = geodesic(coords_start, coords_end).miles * 1.3
            return {"miles": round(dist, 1), "time_str": "Est", "time_min": int(dist/50*60)}

    def search_flights(self, origin, dest, date, show_all=False):
        url = "https://serpapi.com/search"
        params = {
            "engine": "google_flights", "departure_id": origin, "arrival_id": dest,
            "outbound_date": date, "type": "2",
            "hl": "en", "gl": "us", "currency": "USD", "api_key": SERPAPI_KEY
        }
        if not show_all: params["include_airlines"] = "WN,AA,DL,UA"

        try:
            r = requests.get(url, params=params)
            data = r.json()
            raw = data.get("best_flights", []) + data.get("other_flights", [])
            results = []
            if not raw: return []

            for f in raw[:20]:
                legs = f.get('flights', [])
                if not legs: continue
                layovers = f.get('layovers', [])
                conn_apt = layovers[0].get('id', 'Direct') if layovers else "Direct"
                conn_min = layovers[0].get('duration', 0) if layovers else 0
                
                # Full timestamps
                dep_full = legs[0].get('departure_airport', {}).get('time', '') 
                arr_full = legs[-1].get('arrival_airport', {}).get('time', '')

                results.append({
                    "Airline": legs[0].get('airline', 'UNK'),
                    "Flight": " / ".join([l.get('flight_number', '') for l in legs]),
                    "Origin": legs[0].get('departure_airport', {}).get('id', 'UNK'),
                    "Dep Time": dep_full.split()[-1],
                    "Dep Full": dep_full,
                    "Dest": legs[-1].get('arrival_airport', {}).get('id', 'UNK'),
                    "Arr Time": arr_full.split()[-1],
                    "Arr Full": arr_full,
                    "Duration": f"{f.get('total_duration',0)//60}h {f.get('total_duration',0)%60}m",
                    "Conn Apt": conn_apt,
                    "Conn Min": conn_min,
                    "Conn Time": f"{conn_min//60}h {conn_min%60}m" if layovers else "N/A"
                })
            return results
        except: return []

# ==============================================================================
# 4. DASHBOARD UI (Control Panel Left)
# ==============================================================================

st.sidebar.title("🎮 Control Panel")

# --- INPUT FORM ---
st.sidebar.markdown("**1. Shipment Configuration**")
mode = st.sidebar.radio("Frequency", ["One-Time (Ad-Hoc)", "Reoccurring"], label_visibility="collapsed")

st.sidebar.markdown("**2. Locations**")
p_addr = st.sidebar.text_input("Pickup Address", "1200 6th Ave. Seattle, WA 98101")
p_manual = st.sidebar.text_input("Origin Airport Override (Optional)", placeholder="e.g. SEA")
st.sidebar.markdown("⬇️")
d_addr = st.sidebar.text_input("Delivery Address", "MIA")
d_manual = st.sidebar.text_input("Destination Airport Override (Optional)", placeholder="e.g. MIA")

st.sidebar.markdown("**3. Timing**")
p_time = st.sidebar.time_input("Pickup Ready Time", datetime.time(9, 0))

days_to_search = []
del_date_obj = None
del_time = None
del_offset = 0

if mode == "One-Time (Ad-Hoc)":
    p_date = st.sidebar.date_input("Pickup Date", datetime.date.today() + datetime.timedelta(days=1))
    
    # Delivery Logic
    if st.sidebar.checkbox("Strict Delivery Deadline?", value=True):
        default_del = p_date + datetime.timedelta(days=1)
        del_date_obj = st.sidebar.date_input("Delivery Date", default_del)
        del_time = st.sidebar.time_input("Must Arrive By", datetime.time(18, 0))
        del_offset = (del_date_obj - p_date).days
    
    days_to_search = [{"day": "One-Time", "date": p_date.strftime("%Y-%m-%d")}]

else: # Reoccurring
    days_selected = st.sidebar.multiselect("Days", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ["Mon", "Wed", "Fri"])
    
    if st.sidebar.checkbox("Strict Delivery Deadline?", value=True):
        del_day_option = st.sidebar.selectbox("Delivery Day", ["Same Day", "Next Day (+1)", "2 Days Later (+2)"], index=1)
        if "Next" in del_day_option: del_offset = 1
        elif "2 Days" in del_day_option: del_offset = 2
        else: del_offset = 0
        del_time = st.sidebar.time_input("Must Arrive By", datetime.time(18, 0))

    # Calculate dates
    day_map = {"Mon":0, "Tue":1, "Wed":2, "Thu":3, "Fri":4, "Sat":5, "Sun":6}
    today = datetime.date.today()
    for d in days_selected:
        target = day_map[d]
        ahead = target - today.weekday()
        if ahead <= 0: ahead += 7
        nxt = today + datetime.timedelta(days=ahead)
        days_to_search.append({"day": d, "date": nxt.strftime("%Y-%m-%d")})

# Settings in Expander
with st.sidebar.expander("⚙️ Advanced Settings"):
    custom_p_buff = st.number_input("Pickup Drive Buffer", value=120)
    custom_d_buff = st.number_input("Del. Drive Buffer", value=120)
    min_conn_filter = st.number_input("Min Conn. Time", value=60)
    show_all = st.checkbox("Show All Airlines", value=False)

run_btn = st.sidebar.button("🚀 Calculate Route", type="primary")

# ==============================================================================
# 5. INTELLIGENCE PANEL (Main Area)
# ==============================================================================

if run_btn:
    tools = LogisticsTools()
    
    # --- PHASE 1: CALCULATION ---
    with st.status("📡 Establishing Logistics Chain...", expanded=True) as status:
        
        # 1. Resolve Airports
        st.write("📍 Geocoding locations...")
        p_res = [tools.get_airport_details(p_manual)] if p_manual and hasattr(tools, 'get_airport_details') else tools.find_nearest_airports(p_addr)
        # Fallback if get_airport_details isn't defined in this version
        if p_manual: p_res = [{"code": p_manual.upper(), "name": "Manual Override", "air_miles": 0}]
        elif not p_res: p_res = tools.find_nearest_airports(p_addr)
            
        d_res = [{"code": d_manual.upper(), "name": "Manual Override", "air_miles": 0}] if d_manual else tools.find_nearest_airports(d_addr)
        
        if not p_res or not d_res:
            st.error("Address Lookup Failed.")
            st.stop()
            
        p_code, p_name = p_res[0]['code'], p_res[0].get('name', 'Unknown')
        d_code, d_name = d_res[0]['code'], d_res[0].get('name', 'Unknown')
        
        # 2. Drive Metrics
        st.write(f"🚚 Routing Trucks ({p_code} & {d_code})...")
        d1 = tools.get_road_metrics(p_addr, p_code)
        d2 = tools.get_road_metrics(d_code, d_addr)
        if not d1: d1 = {"miles": 20, "time_str": "30m", "time_min": 30}
        if not d2: d2 = {"miles": 20, "time_str": "30m", "time_min": 30}
        
        # 3. Buffer Math
        total_prep = max(d1['time_min'], custom_p_buff) + 60
        total_post = max(d2['time_min'], custom_d_buff) + 60
        
        if mode == "One-Time (Ad-Hoc)":
            p_date_base = p_date
        else:
            p_date_base = datetime.datetime.strptime(days_to_search[0]['date'], "%Y-%m-%d").date()

        full_p_dt = datetime.datetime.combine(p_date_base, p_time)
        earliest_dep_dt = full_p_dt + datetime.timedelta(minutes=total_prep)
        earliest_dep_str = earliest_dep_dt.strftime("%H:%M")
        
        latest_arr_str = "N/A"
        latest_arr_dt = None
        if del_time:
            dummy_deadline = datetime.datetime.combine(p_date_base + datetime.timedelta(days=del_offset), del_time)
            latest_arr_dt = dummy_deadline - datetime.timedelta(minutes=total_post)
            latest_arr_str = latest_arr_dt.strftime("%H:%M")

        # 4. Flights
        st.write(f"✈️ Scanning Inventory ({p_code}-{d_code})...")
        valid_flights = []
        rejected_flights = []
        airline_hours = {}
        
        for day_obj in days_to_search:
            raw = tools.search_flights(p_code, d_code, day_obj['date'], show_all)
            if isinstance(raw, dict): continue
            
            for f in raw:
                # Hours Lookup
                search_date = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d")
                if (p_code, f['Airline']) not in airline_hours:
                    airline_hours[(p_code, f['Airline'])] = tools.get_cargo_hours(p_code, f['Airline'], search_date)
                if (d_code, f['Airline']) not in airline_hours:
                    airline_hours[(d_code, f['Airline'])] = tools.get_cargo_hours(d_code, f['Airline'], search_date)
                
                # Logic Checks
                reject = None
                
                # Tender Check
                p_h = airline_hours[(p_code, f['Airline'])]
                tender_time = (datetime.datetime.strptime(f['Dep Time'], "%H:%M") - datetime.timedelta(minutes=120)).strftime("%H:%M")
                if not tools.check_time_in_range(tender_time, p_h['hours']): reject = f"Org Closed ({p_h['hours']})"
                
                # Dep Check
                if f['Dep Time'] < earliest_dep_str: reject = f"Too Early (Dep {f['Dep Time']})"
                
                # Conn Check
                if f['Conn Apt'] != "Direct" and f['Conn Min'] < min_conn_filter: reject = "Short Conn"
                
                # Arr Check (Date Aware)
                if latest_arr_dt and not reject:
                    try:
                        f_dt = datetime.datetime.strptime(f['Arr Full'], "%Y-%m-%d %H:%M")
                        # Normalize date reference to day 0 of search loop
                        offset_days = (f_dt.date() - search_date.date()).days
                        # Deadline day offset
                        if offset_days > del_offset: reject = "Arrives Late (Day+)"
                        elif offset_days == del_offset and f_dt.time() > latest_arr_dt.time(): reject = f"Arrives Late ({f['Arr Time']})"
                    except: pass

                if reject:
                    f['Reason'] = reject
                    rejected_flights.append(f)
                else:
                    f['Days of Op'] = day_obj['day']
                    f['Dest Hours'] = airline_hours[(d_code, f['Airline'])]['hours']
                    
                    # Recovery Note
                    rec_time = (datetime.datetime.strptime(f['Arr Time'], "%H:%M") + datetime.timedelta(minutes=60)).strftime("%H:%M")
                    if not tools.check_time_in_range(rec_time, f['Dest Hours']):
                        f['Note'] = f"⚠️ AM Recovery"
                    else:
                        f['Note'] = "OK"
                        
                    valid_flights.append(f)

        status.update(label="Logistics Chain Verified", state="complete", expanded=False)

    # --- PHASE 2: DISPLAY ---
    
    # A. EXECUTIVE SUMMARY (Top Cards)
    st.markdown("## 📋 Mission Summary")
    m1, m2, m3 = st.columns(3)
    m1.metric("Origin", p_code, f"{d1['miles']} mi drive")
    m2.metric("Destination", d_code, f"{d2['miles']} mi drive")
    m3.metric("Valid Options", len(valid_flights), f"{len(rejected_flights)} Rejected")
    
    st.markdown("---")

    # B. VISUAL CHAIN OF CUSTODY
    st.markdown("### ⛓️ Chain of Custody")
    chain_html = f"""
    <div style="display: flex; justify-content: space-between; background-color: #262730; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
        <div style="text-align: center;">
            <div style="font-size: 24px;">🚛</div>
            <div><strong>Pickup</strong></div>
            <div style="color: #4ade80;">{p_time.strftime('%H:%M')}</div>
        </div>
        <div style="align-self: center; font-size: 20px;">➔ {d1['time_str']} ➔</div>
        <div style="text-align: center;">
            <div style="font-size: 24px;">🛫</div>
            <div><strong>Tender</strong></div>
            <div style="color: #facc15;">Before {earliest_dep_str}</div>
        </div>
        <div style="align-self: center; font-size: 20px;">➔ FLIGHT ➔</div>
        <div style="text-align: center;">
            <div style="font-size: 24px;">🛬</div>
            <div><strong>Recovery</strong></div>
            <div style="color: #facc15;">By {latest_arr_str}</div>
        </div>
        <div style="align-self: center; font-size: 20px;">➔ {d2['time_str']} ➔</div>
        <div style="text-align: center;">
            <div style="font-size: 24px;">🏁</div>
            <div><strong>Deadline</strong></div>
            <div style="color: #f87171;">{del_time.strftime('%H:%M') if del_time else 'Any'}</div>
        </div>
    </div>
    """
    st.markdown(chain_html, unsafe_allow_html=True)

    # C. ORIGIN vs DESTINATION INTEL
    c1, c2 = st.columns(2)
    with c1:
        st.info(f"**ORIGIN: {p_name} ({p_code})**")
        st.markdown(f"""
        - **Addr:** {p_addr}
        - **Drive:** {d1['miles']} mi ({d1['time_str']})
        - **Logic:** Ready {p_time.strftime('%H:%M')} + Drive + 2h Buffer + 1h Cutoff
        """)
        if airline_hours:
            with st.expander("Facility Hours (Origin)"):
                st.write(airline_hours) # Raw dump for now, cleaner in table

    with c2:
        st.success(f"**DESTINATION: {d_name} ({d_code})**")
        st.markdown(f"""
        - **Addr:** {d_addr}
        - **Drive:** {d2['miles']} mi ({d2['time_str']})
        - **Logic:** Arr + 1h Recovery + 2h Buffer + Drive < Deadline
        """)

    # D. TACTICAL TABLE
    st.markdown("### ✈️ Tactical Flight Schedule")
    
    if valid_flights:
        # Aggregate
        grouped = {}
        for f in valid_flights:
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
        cols = ["Airline", "Flight", "Days of Op", "Dep Time", "Arr Time", "Duration", "Conn Apt", "Conn Time", "Dest Hours", "Note"]
        
        st.dataframe(
            df[cols], 
            hide_index=True,
            use_container_width=True,
            column_config={
                "Note": st.column_config.TextColumn("Status", help="Operational Notes"),
                "Dest Hours": st.column_config.TextColumn("Dest Hours", width="medium")
            }
        )
    else:
        st.warning("No verified flights found.")
        if rejected_flights:
            with st.expander("View Rejected Options"):
                st.dataframe(pd.DataFrame(rejected_flights)[["Airline", "Flight", "Dep Time", "Reason"]])
