import streamlit as st
import pandas as pd
import datetime
import requests
import math
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

try:
    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
except:
    st.error("❌ System Error: SERPAPI_KEY not found in Secrets.")
    st.stop()

# ==============================================================================
# 2. LOGISTICS ENGINE (Optimized)
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_app_optimized_v31", timeout=10)
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

    def _get_coords(self, location: str):
        if location.upper() in self.AIRPORT_DB:
            return self.AIRPORT_DB[location.upper()]
        try:
            clean_loc = location.replace("Suite", "").replace("#", "").split(",")[0] + ", " + location.split(",")[-1]
            loc = self.geolocator.geocode(clean_loc)
            if loc: return (loc.latitude, loc.longitude)
        except: pass
        return None

    # CACHED: Finds airports instantly if address searched before
    @st.cache_data
    def find_nearest_airports(_self, address: str):
        user_coords = _self._get_coords(address)
        if not user_coords: return None
        candidates = []
        for code, coords in _self.AIRPORT_DB.items():
            dist = geodesic(user_coords, coords).miles
            candidates.append({"code": code, "air_miles": round(dist, 1)})
        candidates.sort(key=lambda x: x["air_miles"])
        return candidates[:3]

    # CACHED: Remembers drive times between locations
    @st.cache_data
    def get_road_metrics(_self, origin: str, destination: str):
        coords_start = _self._get_coords(origin)
        coords_end = _self._get_coords(destination)
        if not coords_start or not coords_end: return None
        
        # OSRM (Robust HTTPS)
        url = f"https://router.project-osrm.org/route/v1/driving/{coords_start[1]},{coords_start[0]};{coords_end[1]},{coords_end[0]}"
        headers = {"User-Agent": "CargoApp/1.0"}
        
        try:
            r = requests.get(url, params={"overview": "false"}, headers=headers, timeout=15)
            data = r.json()
            if data.get("code") != "Ok": raise Exception("No route")
            
            seconds = data['routes'][0]['duration']
            miles = data['routes'][0]['distance'] * 0.000621371
            hours = int(seconds // 3600)
            mins = int((seconds % 3600) // 60)
            
            return {
                "miles": round(miles, 1),
                "time_str": f"{hours}h {mins}m",
                "time_min": round(seconds/60)
            }
        except:
            # Fallback
            dist = geodesic(coords_start, coords_end).miles * 1.3
            hours = (dist / 50) + 0.5
            return {
                "miles": round(dist, 1),
                "time_str": f"{int(hours)}h {int((hours*60)%60)}m (Est)",
                "time_min": int(hours*60)
            }

    # NOT CACHED: Live flight data should always be fresh
    def search_flights(self, origin, dest, date, show_all_airlines=False):
        url = "https://serpapi.com/search"
        params = {
            "engine": "google_flights", "departure_id": origin, "arrival_id": dest,
            "outbound_date": date, "type": "2",
            "hl": "en", "gl": "us", "currency": "USD", "api_key": SERPAPI_KEY
        }
        
        if not show_all_airlines:
            params["include_airlines"] = "WN,AA,DL,UA"

        try:
            r = requests.get(url, params=params)
            data = r.json()
            if "error" in data: return {"error": data["error"]}
                
            raw = data.get("best_flights", []) + data.get("other_flights", [])
            results = []
            if not raw: return []

            for f in raw[:20]:
                legs = f.get('flights', [])
                if not legs: continue
                
                layovers = f.get('layovers', [])
                conn_apt = layovers[0].get('id', 'Direct') if layovers else "Direct"
                
                conn_min = 0
                conn_time_str = "N/A"
                if layovers:
                    conn_min = layovers[0].get('duration', 0)
                    conn_time_str = f"{conn_min//60}h {conn_min%60}m"

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
                    "Conn Time": conn_time_str,
                    "Conn Min": conn_min
                })
            return results
        except Exception as e:
            return {"error": str(e)}

# ==============================================================================
# 3. THE APP UI
# ==============================================================================

st.title("✈️ Master Cargo Logistics Agent")
st.markdown("### Verified Door-to-Door Scheduler")

# Instantiate Tools
tools = LogisticsTools()

with st.sidebar:
    st.header("1. Shipment Mode")
    mode = st.radio("Frequency", ["One-Time (Ad-Hoc)", "Reoccurring"])
    
    st.header("2. Locations")
    p_addr = st.text_input("Pickup Address", "123 Pine St, Seattle, WA")
    d_addr = st.text_input("Delivery Address", "MIA")
    
    st.header("3. Timing & Dates")
    
    # --- UNIVERSAL INPUTS ---
    p_date = st.date_input("Pickup Date", datetime.date.today() + datetime.timedelta(days=1))
    p_time = st.time_input("Pickup Ready Time", datetime.time(9, 0))
    
    has_deadline = st.checkbox("Strict Delivery Deadline?", value=True)
    
    del_date_obj = None
    del_time = None
    del_offset = 0
    
    if has_deadline:
        # Default Delivery Date is Pickup + 1 Day
        default_del = p_date + datetime.timedelta(days=1)
        del_date_obj = st.date_input("Delivery Date", default_del)
        del_time = st.time_input("Must Arrive By (HH:MM)", datetime.time(18, 0))
        
        # Calculate Offset
        del_offset = (del_date_obj - p_date).days
        
        # Safety Check
        if del_offset < 0:
            st.error("⚠️ Delivery Date cannot be before Pickup Date.")
            st.stop()

    days_to_search = []
    
    if mode == "One-Time (Ad-Hoc)":
        days_to_search = [{"day": "One-Time", "date": p_date.strftime("%Y-%m-%d")}]
    else: # Reoccurring
        st.info(f"Pattern: Weekly on days below +{del_offset} Day Transit.")
        days_selected = st.multiselect("Days of Week", ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"], ["Mon", "Wed", "Fri"])
        
        day_map = {"Mon":0, "Tue":1, "Wed":2, "Thu":3, "Fri":4, "Sat":5, "Sun":6}
        today = datetime.date.today()
        for d in days_selected:
            target = day_map[d]
            ahead = target - today.weekday()
            if ahead <= 0: ahead += 7
            nxt = today + datetime.timedelta(days=ahead)
            days_to_search.append({"day": d, "date": nxt.strftime("%Y-%m-%d")})
        
    with st.expander("⏱️ Adjusters & Filters"):
        custom_p_buff = st.number_input("Pickup Drive Buffer (mins)", value=120)
        custom_d_buff = st.number_input("Delivery Drive Buffer (mins)", value=120)
        min_conn_filter = st.number_input("Min Connection Time (mins)", value=60)
        show_all_airlines = st.checkbox("Show All Airlines", value=False)

    run_btn = st.button("Generate Logistics Plan", type="primary")

if run_btn:
    with st.status("Running Logistics Engine...", expanded=True) as status:
        
        # 1. GEOGRAPHY
        st.write("📍 Resolving Airports...")
        p_apts = tools.find_nearest_airports(p_addr)
        d_apts = tools.find_nearest_airports(d_addr)
        
        if not p_apts:
            st.error(f"Could not locate Pickup Address: '{p_addr}'. Try using City, State.")
            st.stop()
        if not d_apts:
            st.error(f"Could not locate Delivery Address: '{d_addr}'. Try using City, State.")
            st.stop()
            
        p_code = p_apts[0]['code']
        d_code = d_apts[0]['code']
        
        # 2. ROADS
        st.write("🚚 Calculating Drive Metrics...")
        d1 = tools.get_road_metrics(p_addr, p_code)
        d2 = tools.get_road_metrics(d_code, d_addr)
        
        if not d1: d1 = {"miles": 20, "time_str": "30m (Est)", "time_min": 30}
        if not d2: d2 = {"miles": 20, "time_str": "30m (Est)", "time_min": 30}
            
        # 3. BUFFER MATH
        pickup_drive_used = max(d1['time_min'], custom_p_buff)
        total_prep = pickup_drive_used + 60
        
        if mode == "One-Time (Ad-Hoc)":
            p_date_base = p_date
        else:
            if not days_to_search:
                st.error("Please select Days of Week.")
                st.stop()
            p_date_base = datetime.datetime.strptime(days_to_search[0]['date'], "%Y-%m-%d").date()

        full_p_dt = datetime.datetime.combine(p_date_base, p_time)
        earliest_dep_dt = full_p_dt + datetime.timedelta(minutes=total_prep)
        earliest_dep_str = earliest_dep_dt.strftime("%H:%M")
        
        latest_arr_dt = None
        total_post = 0
        latest_arr_str = "N/A"
        
        if has_deadline and del_time:
            del_drive_used = max(d2['time_min'], custom_d_buff)
            total_post = del_drive_used + 60
            
            # Deadline Math relative to the base date
            dummy_deadline = datetime.datetime.combine(p_date_base + datetime.timedelta(days=del_offset), del_time)
            latest_arr_dt = dummy_deadline - datetime.timedelta(minutes=total_post)
            latest_arr_str = latest_arr_dt.strftime("%H:%M")
        
        # 4. FLIGHTS
        st.write(f"✈️ Searching Flights ({p_code} -> {d_code})...")
        valid_flights = []
        rejected_flights = [] 
        
        for day_obj in days_to_search:
            raw_data = tools.search_flights(p_code, d_code, day_obj['date'], show_all_airlines)
            
            if isinstance(raw_data, dict) and "error" in raw_data:
                st.error(f"Flight API Error: {raw_data['error']}")
                continue
            
            if not raw_data: continue
            
            for f in raw_data:
                reject_reason = None
                
                # Check 1: Departure Time
                if f['Dep Time'] < earliest_dep_str: 
                    reject_reason = f"Too Early (Dep {f['Dep Time']})"
                
                # Check 2: Connection Time
                if f['Conn Apt'] != "Direct":
                    if f['Conn Min'] < min_conn_filter:
                        reject_reason = f"Short Conn ({f['Conn Time']})"

                # Check 3: Arrival Deadline
                if latest_arr_dt and not reject_reason:
                    try:
                        # Construct a dummy flight arrival date based on the search date
                        f_arr_time_str = f['Arr Time']
                        f_dep_time_str = f['Dep Time']
                        
                        f_arr_dt = datetime.datetime.strptime(f"{day_obj['date']} {f_arr_time_str}", "%Y-%m-%d %H:%M")
                        
                        # Handle date crossing (e.g. Dep 23:00, Arr 05:00)
                        if f_arr_time_str < f_dep_time_str: 
                            f_arr_dt += datetime.timedelta(days=1)
                        
                        # Compare against the deadline relative to this specific day loop
                        # Deadline for this loop = Day Date + Offset
                        loop_deadline = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d") + datetime.timedelta(days=del_offset)
                        loop_deadline = loop_deadline.replace(hour=del_time.hour, minute=del_time.minute)
                        
                        loop_latest_arr = loop_deadline - datetime.timedelta(minutes=total_post)
                        
                        if f_arr_dt > loop_latest_arr:
                             reject_reason = f"Arrives Too Late ({f['Arr Time']})"
                    except: pass

                if reject_reason:
                    f['Reason'] = reject_reason
                    f['Day'] = day_obj['day']
                    rejected_flights.append(f)
                else:
                    f['Days of Op'] = day_obj['day']
                    valid_flights.append(f)
        
        status.update(label="Analysis Complete!", state="complete", expanded=False)

    # --- OUTPUT ---
    st.divider()
    st.subheader("LOGISTICS PLAN")
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**PICKUP: {p_code}**")
        st.markdown(f"""
        * **Ready:** {p_time.strftime('%H:%M')}
        * **Drive Mileage:** {d1['miles']} miles
        * **Drive Time:** {d1['time_str']}
        * **Buffer Logic:** MAX({d1['time_min']}, {custom_p_buff}) + 60 = **{total_prep} min** prep
        * **Earliest Flight:** {earliest_dep_str}
        """)

    with col2:
        st.success(f"**DELIVERY: {d_code}**")
        if has_deadline:
            days_str = f"(+{del_offset} Day)" if del_offset > 0 else "(Same Day)"
            st.markdown(f"""
            * **Deadline:** {del_time.strftime('%H:%M')} {days_str}
            * **Drive Mileage:** {d2['miles']} miles
            * **Drive Time:** {d2['time_str']}
            * **Buffer Logic:** MAX({d2['time_min']}, {custom_d_buff}) + 60 = **{total_post} min** post
            * **Must Arrive By:** {latest_arr_str}
            """)
        else:
            st.markdown("*No strict deadline set.*")

    st.divider()
    
    if valid_flights:
        st.subheader("✅ Verified Flight Schedule")
        
        grouped = {}
        for f in valid_flights:
            key = (f['Airline'], f['Flight'], f['Dep Time'], f['Arr Time'])
            if key not in grouped:
                grouped[key] = f.copy()
                grouped[key]['Days of Op'] = {f['Days of Op']}
            else:
                grouped[key]['Days of Op'].add(f['Days of Op'])
        
        final_rows = []
        for f in grouped.values():
            days_list = sorted(list(f['Days of Op']), key=lambda x: ["Mon","Tue","Wed","Thu","Fri","Sat","Sun","One-Time"].index(x) if x in ["Mon","Tue","Wed","Thu","Fri","Sat","Sun","One-Time"] else 99)
            f['Days of Op'] = ", ".join(days_list)
            final_rows.append(f)
            
        df = pd.DataFrame(final_rows)
        cols = ["Airline", "Flight", "Days of Op", "Origin", "Dep Time", "Dest", "Arr Time", "Duration", "Conn Apt", "Conn Time"]
        st.dataframe(df[cols], hide_index=True, use_container_width=True)
        
    elif rejected_flights:
        st.warning("⚠️ No valid flights found! Here is what we rejected:")
        rej_df = pd.DataFrame(rejected_flights)
        st.dataframe(rej_df[["Airline", "Flight", "Dep Time", "Arr Time", "Reason", "Day"]], hide_index=True)
        
    else:
        st.error(f"No flights found at all between {p_code} and {d_code}. Try checking 'Show All Airlines'.")
