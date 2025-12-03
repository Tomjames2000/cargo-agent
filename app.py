import streamlit as st
import pandas as pd
import datetime
import requests
import math
from dateutil import parser, relativedelta
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

# LOAD ALL KEYS
try:
    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
    GOOGLE_MAPS_KEY = st.secrets.get("GOOGLE_MAPS_KEY", None)
    AVIATION_EDGE_KEY = st.secrets.get("AVIATION_EDGE_KEY", None)
except:
    st.error("❌ System Error: API Keys missing in Secrets.")
    st.stop()

# ==============================================================================
# 2. LOGISTICS ENGINE
# ==============================================================================
class LogisticsTools:
    def __init__(self):
        self.geolocator = Nominatim(user_agent="cargo_app_global_v50", timeout=10)
        
        # 1. LOAD MASTER FILE (For Hours/Rules)
        self.master_df = None
        try:
            self.master_df = pd.read_csv("cargo_master.csv")
            self.master_df.columns = [c.strip().lower().replace(" ", "_") for c in self.master_df.columns]
        except Exception as e:
            print(f"CSV Error: {e}")

        # FALLBACK DB (Only used if API fails)
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
        # 1. Master CSV
        if self.master_df is not None and len(location) == 3:
            match = self.master_df[self.master_df['airport_code'] == location.upper()]
            if not match.empty:
                return (match.iloc[0]['latitude_deg'], match.iloc[0]['longitude_deg'])
        
        # 2. Google Maps Geocoding
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

        # 3. Nominatim Fallback
        try:
            clean_loc = location.replace("Suite", "").replace("#", "").split(",")[0] + ", " + location.split(",")[-1]
            loc = self.geolocator.geocode(clean_loc)
            if loc: return (loc.latitude, loc.longitude)
        except: pass
        
        # 4. Fallback DB
        if location.upper() in self.AIRPORT_DB:
            return self.AIRPORT_DB[location.upper()]["coords"]
            
        return None

    @st.cache_data(ttl=3600) # Cache for 1 hour
    def get_airport_details(_self, code):
        """Get Name and Coords for ANY airport code in the world (Cached)."""
        code = code.upper()
        
        # 1. Aviation Edge Global Lookup
        if AVIATION_EDGE_KEY:
            url = "https://aviation-edge.com/v2/public/airportDatabase"
            params = {"key": AVIATION_EDGE_KEY, "codeIataAirport": code}
            try:
                r = requests.get(url, params=params, timeout=5)
                data = r.json()
                if data and isinstance(data, list):
                    item = data[0]
                    return {
                        "code": code,
                        "name": item.get("nameAirport", code),
                        "coords": (float(item['latitudeAirport']), float(item['longitudeAirport']))
                    }
            except: pass

        # 2. Master CSV / Fallback
        if _self.master_df is not None:
            match = _self.master_df[_self.master_df['airport_code'] == code]
            if not match.empty:
                return {
                    "code": code,
                    "name": match.iloc[0]['airport_name'],
                    "coords": (match.iloc[0]['latitude_deg'], match.iloc[0]['longitude_deg'])
                }
        if code in _self.AIRPORT_DB:
            return {"code": code, "name": _self.AIRPORT_DB[code]["name"], "coords": _self.AIRPORT_DB[code]["coords"]}
        
        return None

    @st.cache_data(ttl=3600)
    def find_nearest_airports(_self, address: str):
        """
        1. Geocodes the address.
        2. Asks Aviation Edge for airports within 150km (Cached).
        """
        user_coords = _self._get_coords(address)
        if not user_coords: return None
        
        # --- AVIATION EDGE NEARBY ---
        if AVIATION_EDGE_KEY:
            url = "https://aviation-edge.com/v2/public/nearby"
            params = {
                "key": AVIATION_EDGE_KEY,
                "lat": user_coords[0],
                "lng": user_coords[1],
                "distance": 150
            }
            try:
                r = requests.get(url, params=params, timeout=8)
                data = r.json()
                candidates = []
                if isinstance(data, list):
                    for apt in data:
                        if apt.get("codeIataAirport") and len(apt.get("codeIataAirport")) == 3:
                            candidates.append({
                                "code": apt.get("codeIataAirport").upper(),
                                "name": apt.get("nameAirport"),
                                "air_miles": round(float(apt.get("distance")) * 0.621371, 1)
                            })
                    if candidates:
                        candidates.sort(key=lambda x: x["air_miles"])
                        return candidates[:3]
            except: pass

        # --- FALLBACK LOOP ---
        candidates = []
        for code, data in _self.AIRPORT_DB.items():
            dist = geodesic(user_coords, data["coords"]).miles
            candidates.append({"code": code, "name": data["name"], "air_miles": round(dist, 1)})
        candidates.sort(key=lambda x: x["air_miles"])
        return candidates[:3]

    @st.cache_data(ttl=3600)
    def get_road_metrics(_self, origin: str, destination: str):
        """Cached Road Metrics"""
        coords_start = _self._get_coords(origin)
        coords_end = _self._get_coords(destination)
        if not coords_start or not coords_end: return None
        
        # Google Maps
        if GOOGLE_MAPS_KEY:
            try:
                g_start = f"{coords_start[0]},{coords_start[1]}"
                g_end = f"{coords_end[0]},{coords_end[1]}"
                url = "https://maps.googleapis.com/maps/api/distancematrix/json"
                params = {
                    "origins": g_start, "destinations": g_end,
                    "mode": "driving", "traffic_model": "best_guess", "departure_time": "now",
                    "key": GOOGLE_MAPS_KEY
                }
                r = requests.get(url, params=params, timeout=8)
                data = r.json()
                if data['status'] == 'OK':
                    elem = data['rows'][0]['elements'][0]
                    if elem['status'] == 'OK':
                        meters = elem['distance']['value']
                        seconds = elem.get('duration_in_traffic', elem['duration'])['value']
                        miles = meters * 0.000621371
                        hours = int(seconds // 3600)
                        mins = int((seconds % 3600) // 60)
                        return {"miles": round(miles, 1), "time_str": f"{hours}h {mins}m", "time_min": round(seconds/60)}
            except: pass

        # Fallback Math
        dist = geodesic(coords_start, coords_end).miles * 1.3
        hours = (dist / 50) + 0.5
        return {"miles": round(dist, 1), "time_str": f"{int(hours)}h {int((hours*60)%60)}m (Est)", "time_min": int(hours*60)}

    # --- CARGO HOURS (Not Cached - needs live date) ---
    def get_cargo_hours(self, airport_code, airline, date_obj):
        day_name = date_obj.strftime("%A")
        col_map = {"Saturday": "saturday", "Sunday": "sunday"}
        day_col = col_map.get(day_name, "weekday") 
        
        if self.master_df is not None:
            mask = (self.master_df['airport_code'] == airport_code) & \
                   (self.master_df['airline'].str.contains(airline, case=False, na=False))
            row = self.master_df[mask]
            if not row.empty:
                hours_str = str(row.iloc[0][day_col])
                bad_words = ['nan', 'closed', 'n/a', 'no cargo', 'none', 'unavailable']
                if any(x in hours_str.lower() for x in bad_words):
                    return {"status": "Closed", "hours": "No Cargo", "source": "Master File"}
                return {"status": "Open", "hours": hours_str, "source": "Master File"}
        
        # Web Search Fallback
        return {"status": "Unknown", "hours": "Unknown", "source": "No Data"}

    def check_time_in_range(self, target_time, range_str):
        r_clean = range_str.lower().strip()
        if any(x in r_clean for x in ["no cargo", "closed", "n/a", "none", "unavailable"]): return False
        if "24" in r_clean or "daily" in r_clean: return True
        try:
            times = re.findall(r'\d{1,2}:\d{2}', range_str)
            if len(times) != 2: return True 
            start = datetime.datetime.strptime(times[0], "%H:%M").time()
            end = datetime.datetime.strptime(times[1], "%H:%M").time()
            check = datetime.datetime.strptime(target_time, "%H:%M").time()
            if start <= end: return start <= check <= end
            else: return start <= check or check <= end
        except: return True

    # --- FLIGHT SEARCH ---
    def search_flights(self, origin, dest, date, show_all_airlines=False):
        # Use Aviation Edge
        if AVIATION_EDGE_KEY:
            url = "https://aviation-edge.com/v2/public/flightsFuture"
            params = {"key": AVIATION_EDGE_KEY, "type": "departure", "iataCode": origin, "date": date, "arr_iataCode": dest}
            try:
                r = requests.get(url, params=params, timeout=10)
                data = r.json()
                if not (isinstance(data, dict) and "error" in data) and data:
                    results = []
                    for f in data:
                        dep = f.get('departure', {})
                        arr = f.get('arrival', {})
                        airline = f.get('airline', {})
                        airline_code = airline.get('iataCode', 'UNK')
                        
                        if not show_all_airlines and airline_code not in ["WN","AA","DL","UA"]: continue

                        dep_time_full = dep.get('scheduledTime', '')
                        arr_time_full = arr.get('scheduledTime', '')
                        
                        try:
                            d_dt = datetime.datetime.strptime(dep_time_full.split('.')[0], "%Y-%m-%dT%H:%M:%S")
                            a_dt = datetime.datetime.strptime(arr_time_full.split('.')[0], "%Y-%m-%dT%H:%M:%S")
                            duration_min = (a_dt - d_dt).total_seconds() / 60
                            dur_str = f"{int(duration_min//60)}h {int(duration_min%60)}m"
                        except: dur_str = "N/A"

                        results.append({
                            "Airline": airline_code,
                            "Flight": f"{airline_code}{f.get('flight',{}).get('iataNumber','')}",
                            "Origin": dep.get('iataCode', origin),
                            "Dep Time": dep_time_full.split('T')[-1][:5],
                            "Dest": arr.get('iataCode', dest),
                            "Arr Time": arr_time_full.split('T')[-1][:5],
                            "Arr Full": arr_time_full,
                            "Duration": dur_str,
                            "Conn Apt": "Direct",
                            "Conn Time": "N/A",
                            "Conn Min": 0
                        })
                    if results: return results
            except: pass

        # Backup: SerpApi
        url = "https://serpapi.com/search"
        params = {
            "engine": "google_flights", "departure_id": origin, "arrival_id": dest,
            "outbound_date": date, "type": "2", "hl": "en", "gl": "us", "currency": "USD", "api_key": SERPAPI_KEY
        }
        if not show_all_airlines: params["include_airlines"] = "WN,AA,DL,UA"

        try:
            r = requests.get(url, params=params)
            data = r.json()
            raw = data.get("best_flights", []) + data.get("other_flights", [])
            results = []
            for f in raw[:20]:
                legs = f.get('flights', [])
                if not legs: continue
                layovers = f.get('layovers', [])
                conn_apt = layovers[0].get('id', 'Direct') if layovers else "Direct"
                conn_min = layovers[0].get('duration', 0) if layovers else 0
                conn_time_str = f"{conn_min//60}h {conn_min%60}m" if layovers else "N/A"
                dep_full = legs[0].get('departure_airport', {}).get('time', '') 
                arr_full = legs[-1].get('arrival_airport', {}).get('time', '') 
                if not dep_full or not arr_full: continue

                results.append({
                    "Airline": legs[0].get('airline', 'UNK'),
                    "Flight": " / ".join([l.get('flight_number', '') for l in legs]),
                    "Origin": legs[0].get('departure_airport', {}).get('id', 'UNK'),
                    "Dep Time": dep_full.split()[-1], 
                    "Dest": legs[-1].get('arrival_airport', {}).get('id', 'UNK'),
                    "Arr Time": arr_full.split()[-1], 
                    "Arr Full": arr_full,
                    "Duration": f"{f.get('total_duration',0)//60}h {f.get('total_duration',0)%60}m",
                    "Conn Apt": conn_apt,
                    "Conn Time": conn_time_str,
                    "Conn Min": conn_min
                })
            return results
        except: return []

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
    p_addr = st.text_input("Pickup Address", "2008 Altom Ct, St. Louis, MO 63146")
    p_manual = st.text_input("Origin Airport Override (Optional)", placeholder="e.g. STL")
    st.markdown("⬇️")
    d_addr = st.text_input("Delivery Address", "1250 E Hadley St, Phoenix, AZ 85034")
    d_manual = st.text_input("Destination Airport Override (Optional)", placeholder="e.g. PHX")
    
    st.header("3. Timing & Dates")
    p_time = st.time_input("Pickup Ready Time (HH:MM)", datetime.time(9, 0))
    p_date = st.date_input("Pickup Date", datetime.date.today() + datetime.timedelta(days=1))
    
    has_deadline = st.checkbox("Strict Delivery Deadline?", value=True)
    del_date_obj = None
    del_time = None
    del_offset = 0
    
    if has_deadline:
        default_del = p_date + datetime.timedelta(days=1)
        del_date_obj = st.date_input("Delivery Date", default_del)
        del_time = st.time_input("Must Arrive By (HH:MM)", datetime.time(18, 0))
        del_offset = (del_date_obj - p_date).days
        if del_offset < 0:
            st.error("⚠️ Delivery Date cannot be before Pickup Date.")
            st.stop()

    days_to_search = []
    if mode == "One-Time (Ad-Hoc)":
        days_to_search = [{"day": "One-Time", "date": p_date.strftime("%Y-%m-%d")}]
    else: 
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
        st.write("📍 Resolving Locations...")
        p_res = [tools.get_airport_details(p_manual)] if p_manual else tools.find_nearest_airports(p_addr)
        if p_manual and not p_res[0]: 
             st.error(f"Invalid Manual Origin Code: {p_manual}")
             st.stop()
        elif not p_res:
             st.error(f"Could not locate Pickup Address: '{p_addr}'")
             st.stop()
        
        d_res = [tools.get_airport_details(d_manual)] if d_manual else tools.find_nearest_airports(d_addr)
        if d_manual and not d_res[0]:
             st.error(f"Invalid Manual Dest Code: {d_manual}")
             st.stop()
        elif not d_res:
             st.error(f"Could not locate Delivery Address: '{d_addr}'")
             st.stop()

        p_airport_data = p_res[0]
        d_airport_data = d_res[0]

        p_code = p_airport_data['code']
        p_name = p_airport_data.get('name', 'Unknown')
        d_code = d_airport_data['code']
        d_name = d_airport_data.get('name', 'Unknown')
        
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
            dummy_deadline = datetime.datetime.combine(p_date_base + datetime.timedelta(days=del_offset), del_time)
            latest_arr_dt = dummy_deadline - datetime.timedelta(minutes=total_post)
            latest_arr_str = latest_arr_dt.strftime("%H:%M")
        
        # 4. FLIGHTS
        st.write(f"✈️ Searching Flights ({p_code} -> {d_code})...")
        valid_flights = []
        rejected_flights = [] 
        airline_hours_cache = {} 
        
        for day_obj in days_to_search:
            raw_data = tools.search_flights(p_code, d_code, day_obj['date'], show_all_airlines)
            if isinstance(raw_data, dict) and "error" in raw_data:
                st.error(f"Flight API Error: {raw_data['error']}")
                continue
            if not raw_data: continue
            
            for f in raw_data:
                reject_reason = None
                airline = f['Airline']
                
                search_date_obj = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d")
                
                if (p_code, airline) not in airline_hours_cache:
                     airline_hours_cache[(p_code, airline)] = tools.get_cargo_hours(p_code, airline, search_date_obj)
                if (d_code, airline) not in airline_hours_cache:
                     airline_hours_cache[(d_code, airline)] = tools.get_cargo_hours(d_code, airline, search_date_obj)

                p_hours = airline_hours_cache[(p_code, airline)]
                tender_dt = datetime.datetime.strptime(f['Dep Time'], "%H:%M") - datetime.timedelta(minutes=120)
                tender_time_str = tender_dt.strftime("%H:%M")
                
                if not tools.check_time_in_range(tender_time_str, p_hours['hours']):
                    reject_reason = f"Origin Closed ({p_hours['hours']})"

                if not reject_reason:
                    d_hours = airline_hours_cache[(d_code, airline)]
                    rec_dt = datetime.datetime.strptime(f['Arr Time'], "%H:%M") + datetime.timedelta(minutes=60)
                    rec_time_str = rec_dt.strftime("%H:%M")
                    if not tools.check_time_in_range(rec_time_str, d_hours['hours']):
                         f['Note'] = f"⚠️ AM Recovery ({d_hours['hours']})"

                if f['Dep Time'] < earliest_dep_str and not reject_reason: 
                    reject_reason = f"Too Early (Dep {f['Dep Time']})"
                
                if f['Conn Apt'] != "Direct" and f['Conn Min'] < min_conn_filter and not reject_reason:
                    reject_reason = f"Short Conn ({f['Conn Time']})"
                    
                if latest_arr_dt and not reject_reason:
                    try:
                        flight_arr_dt = datetime.datetime.strptime(f['Arr Full'], "%Y-%m-%d %H:%M") if 'T' in f['Arr Full'] else datetime.datetime.strptime(f"{day_obj['date']} {f['Arr Time']}", "%Y-%m-%d %H:%M")
                        # Date math fix for overnight
                        if f['Arr Time'] < f['Dep Time']: flight_arr_dt += datetime.timedelta(days=1)
                        
                        loop_deadline = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d") + datetime.timedelta(days=del_offset)
                        loop_deadline = loop_deadline.replace(hour=del_time.hour, minute=del_time.minute)
                        loop_latest_arr = loop_deadline - datetime.timedelta(minutes=total_post)
                        
                        if flight_arr_dt > loop_latest_arr:
                             reject_reason = f"Arrives Too Late ({f['Arr Time']})"
                    except: pass

                if reject_reason:
                    f['Reason'] = reject_reason
                    f['Day'] = day_obj['day']
                    rejected_flights.append(f)
                else:
                    f['Days of Op'] = day_obj['day']
                    f['Dest Hours'] = d_hours['hours']
                    f['Track'] = f"https://flightaware.com/live/flight/{f['Flight']}"
                    valid_flights.append(f)
        
        status.update(label="Analysis Complete!", state="complete", expanded=False)

    # --- OUTPUT ---
    st.divider()
    st.subheader("LOGISTICS PLAN")
    
    col1, col2 = st.columns(2)
    with col1:
        st.info(f"**PICKUP: {p_code} - {p_name}**")
        st.markdown(f"""
        * **Ready:** {p_time.strftime('%H:%M')}
        * **Drive Mileage:** {d1['miles']} miles
        * **Drive Time:** {d1['time_str']}
        * **Buffer Logic:** MAX({d1['time_min']}, {custom_p_buff}) + 60 = **{total_prep} min** prep
        * **Earliest Flight:** {earliest_dep_str}
        """)
        
        st.markdown("**Cargo Facility Hours (Origin):**")
        seen = set()
        for (apt, air), val in airline_hours_cache.items():
            if apt == p_code and air not in seen:
                st.caption(f"- {air}: {val['hours']} ({val['source']})")
                seen.add(air)

    with col2:
        st.success(f"**DELIVERY: {d_code} - {d_name}**")
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
            
        st.markdown("**Cargo Facility Hours (Destination):**")
        seen = set()
        for (apt, air), val in airline_hours_cache.items():
            if apt == d_code and air not in seen:
                st.caption(f"- {air}: {val['hours']} ({val['source']})")
                seen.add(air)

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
        cols = ["Airline", "Flight", "Days of Op", "Origin", "Dep Time", "Dest", "Arr Time", "Dest Hours", "Note", "Duration", "Conn Apt", "Track"]
        st.dataframe(
            df[cols], 
            hide_index=True, 
            use_container_width=True,
            column_config={
                "Track": st.column_config.LinkColumn("Tracker", display_text="Live Status")
            }
        )
        
    elif rejected_flights:
        st.warning("⚠️ No valid flights found! Here is what we rejected:")
        rej_df = pd.DataFrame(rejected_flights)
        st.dataframe(rej_df[["Airline", "Flight", "Dep Time", "Arr Time", "Reason", "Day"]], hide_index=True)
        
    else:
        st.error(f"No flights found at all between {p_code} and {d_code}. Try checking 'Show All Airlines'.")
