 (cd "$(git rev-parse --show-toplevel)" && git apply --3way <<'EOF' 
diff --git a/app.py b/app.py
index 916c6064fc9c79daeb232138956e2f01b215451e..4186a5a257de206f4bddc80abcc824f5572bc743 100644
--- a/app.py
+++ b/app.py
@@ -1,118 +1,269 @@
-import streamlit as st
-import pandas as pd
-import datetime
-import requests
-import math
-from geopy.geocoders import Nominatim
-from geopy.distance import geodesic
+"""Cargo Logistics Master Streamlit app.
+
+To run this file as-is, set the following in ``.streamlit/secrets.toml``:
+
+* ``APP_PASSWORD`` – UI password prompt
+* ``SERPAPI_KEY`` – for SerpAPI Google Flights queries
+* ``GOOGLE_MAPS_KEY`` – for Google Geocoding + Distance Matrix calls
+"""
+
+import streamlit as st
+import pandas as pd
+import datetime
+import requests
+from geopy.geocoders import Nominatim
+from geopy.distance import geodesic
 
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
 
-try:
-    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
-except:
-    st.error("❌ System Error: SERPAPI_KEY not found in Secrets.")
-    st.stop()
+try:
+    SERPAPI_KEY = st.secrets["SERPAPI_KEY"]
+except Exception:
+    st.error("❌ System Error: SERPAPI_KEY not found in Secrets.")
+    st.stop()
+
+try:
+    GOOGLE_MAPS_KEY = st.secrets["GOOGLE_MAPS_KEY"]
+except Exception:
+    st.error("❌ System Error: GOOGLE_MAPS_KEY not found in Secrets. Add it to use Google Geocoding + Distance Matrix APIs.")
+    st.stop()
 
 # ==============================================================================
 # 2. LOGISTICS ENGINE (Optimized)
 # ==============================================================================
-class LogisticsTools:
-    def __init__(self):
-        self.geolocator = Nominatim(user_agent="cargo_app_optimized_v31", timeout=10)
-        self.AIRPORT_DB = {
-            "SEA": (47.4489, -122.3094), "PDX": (45.5887, -122.5975),
-            "SFO": (37.6189, -122.3748), "LAX": (33.9425, -118.4080),
+class LogisticsTools:
+    def __init__(self):
+        self.geolocator = Nominatim(user_agent="cargo_app_optimized_v31", timeout=10)
+        self.gmaps_key = GOOGLE_MAPS_KEY
+        self.AIRPORT_DB = {
+            "SEA": (47.4489, -122.3094), "PDX": (45.5887, -122.5975),
+            "SFO": (37.6189, -122.3748), "LAX": (33.9425, -118.4080),
             "ORD": (41.9742, -87.9073),  "DFW": (32.8998, -97.0403),
             "JFK": (40.6413, -73.7781),  "ATL": (33.6407, -84.4277),
             "MIA": (25.7959, -80.2870),  "CLT": (35.2140, -80.9431),
             "MEM": (35.0424, -89.9767),  "CVG": (39.0461, -84.6621),
             "DEN": (39.8561, -104.6737), "PHX": (33.4343, -112.0116),
-            "IAH": (29.9902, -95.3368),  "BOS": (42.3656, -71.0096),
-            "EWR": (40.6895, -74.1745),  "MCO": (28.4312, -81.3081),
-            "LGA": (40.7769, -73.8740),  "DTW": (42.2162, -83.3554),
-            "MSP": (44.8848, -93.2223),  "SLC": (40.7899, -111.9791)
-        }
+            "IAH": (29.9902, -95.3368),  "BOS": (42.3656, -71.0096),
+            "EWR": (40.6895, -74.1745),  "MCO": (28.4312, -81.3081),
+            "LGA": (40.7769, -73.8740),  "DTW": (42.2162, -83.3554),
+            "MSP": (44.8848, -93.2223),  "SLC": (40.7899, -111.9791)
+        }
+        # Simplified cargo hours windows (local time). Defaults to 24/7 when absent.
+        self.CARGO_HOURS = {
+            "SEA": ("05:00", "23:00"),
+            "PDX": ("05:00", "22:30"),
+            "SFO": ("04:30", "23:30"),
+            "LAX": ("05:00", "23:59"),
+            "ORD": ("04:30", "23:30"),
+            "DFW": ("05:00", "23:30"),
+            "JFK": ("05:00", "23:30"),
+            "ATL": ("05:00", "23:00"),
+            "MIA": ("05:00", "23:00"),
+            "CLT": ("05:00", "22:30"),
+            "MEM": ("05:00", "23:30"),
+            "CVG": ("05:00", "23:00"),
+            "DEN": ("05:00", "23:00"),
+            "PHX": ("05:00", "23:00"),
+            "IAH": ("05:00", "23:30"),
+            "BOS": ("05:00", "22:30"),
+            "EWR": ("05:00", "23:00"),
+            "MCO": ("05:00", "23:00"),
+            "LGA": ("05:00", "22:00"),
+            "DTW": ("05:00", "22:30"),
+            "MSP": ("05:00", "22:30"),
+            "SLC": ("05:00", "22:30"),
+        }
+
+    def _parse_time(self, raw_time: str):
+        """Convert assorted time strings to a datetime.time object.
+
+        SerpAPI returns times in multiple formats (e.g., "9:30pm", "9:30 PM",
+        "21:30"). Comparing raw strings can fail, so we normalize the input and
+        try a handful of common patterns before giving up.
+        """
+        if not raw_time:
+            return None
+
+        cleaned = raw_time.strip().replace(".", "")
+        # Normalize casing for AM/PM to make strptime parsing predictable
+        cleaned = cleaned.upper()
+
+        patterns = ["%I:%M%p", "%I:%M %p", "%H:%M"]
+
+        for pattern in patterns:
+            try:
+                return datetime.datetime.strptime(cleaned, pattern).time()
+            except ValueError:
+                continue
+        return None
+
+    def _get_cargo_window(self, airport_code: str):
+        hours = self.CARGO_HOURS.get(airport_code.upper())
+        if not hours:
+            return {"open": None, "close": None, "label": "24/7 (assumed)"}
+
+        start = self._parse_time(hours[0])
+        end = self._parse_time(hours[1])
+        label = f"{hours[0]}-{hours[1]}"
+        return {"open": start, "close": end, "label": label}
+
+    def is_within_cargo_hours(self, airport_code: str, time_obj: datetime.time):
+        window = self._get_cargo_window(airport_code)
+        open_t = window["open"]
+        close_t = window["close"]
+
+        # If we have no specific hours, treat as always open.
+        if not open_t or not close_t:
+            return True, window["label"]
+
+        if open_t <= close_t:
+            ok = open_t <= time_obj <= close_t
+        else:
+            # Overnight window (e.g., 22:00-05:00)
+            ok = time_obj >= open_t or time_obj <= close_t
+        return ok, window["label"]
 
-    def _get_coords(self, location: str):
-        if location.upper() in self.AIRPORT_DB:
-            return self.AIRPORT_DB[location.upper()]
-        try:
-            clean_loc = location.replace("Suite", "").replace("#", "").split(",")[0] + ", " + location.split(",")[-1]
-            loc = self.geolocator.geocode(clean_loc)
-            if loc: return (loc.latitude, loc.longitude)
-        except: pass
-        return None
+    def _get_coords(self, location: str):
+        if location.upper() in self.AIRPORT_DB:
+            return self.AIRPORT_DB[location.upper()]
+
+        cleaned = location.replace("Suite", "").replace("#", "").strip()
+        attempts = [cleaned]
+
+        parts = [p.strip() for p in cleaned.split(",") if p.strip()]
+        if len(parts) >= 3:
+            street, city, rest = parts[0], parts[1], ", ".join(parts[2:])
+            attempts.append(f"{street}, {city}, {rest}")
+            attempts.append(f"{city}, {rest}")
+        elif len(parts) == 2:
+            attempts.append(f"{parts[0]}, {parts[1]}")
+
+        for candidate in attempts:
+            try:
+                resp = requests.get(
+                    "https://maps.googleapis.com/maps/api/geocode/json",
+                    params={"address": candidate, "key": self.gmaps_key},
+                    timeout=10,
+                )
+                data = resp.json()
+                if data.get("status") != "OK":
+                    continue
+                first = data.get("results", [{}])[0].get("geometry", {}).get("location")
+                if first and "lat" in first and "lng" in first:
+                    return (first["lat"], first["lng"])
+            except Exception:
+                continue
+
+        # Fallback to Nominatim only if Google fails for all variants (e.g., quota exceeded)
+        for candidate in attempts:
+            try:
+                loc = self.geolocator.geocode(candidate)
+                if loc:
+                    return (loc.latitude, loc.longitude)
+            except Exception:
+                continue
+        return None
 
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
-    @st.cache_data
-    def get_road_metrics(_self, origin: str, destination: str):
-        coords_start = _self._get_coords(origin)
-        coords_end = _self._get_coords(destination)
-        if not coords_start or not coords_end: return None
-        
-        # OSRM (Robust HTTPS)
-        url = f"https://router.project-osrm.org/route/v1/driving/{coords_start[1]},{coords_start[0]};{coords_end[1]},{coords_end[0]}"
-        headers = {"User-Agent": "CargoApp/1.0"}
+    @st.cache_data
+    def get_road_metrics(_self, origin: str, destination: str):
+        coords_start = _self._get_coords(origin)
+        coords_end = _self._get_coords(destination)
+        if not coords_start or not coords_end: return None
+
+        if _self.gmaps_key:
+            try:
+                g_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
+                resp = requests.get(
+                    g_url,
+                    params={
+                        "origins": f"{coords_start[0]},{coords_start[1]}",
+                        "destinations": f"{coords_end[0]},{coords_end[1]}",
+                        "units": "imperial",
+                        "key": _self.gmaps_key,
+                    },
+                    timeout=15,
+                )
+                g_data = resp.json()
+                element = g_data.get("rows", [{}])[0].get("elements", [{}])[0]
+
+                if g_data.get("status") == "OK" and element.get("status") == "OK":
+                    seconds = element["duration"]["value"]
+                    miles = element["distance"]["value"] * 0.000621371
+                    hours = int(seconds // 3600)
+                    mins = int((seconds % 3600) // 60)
+
+                    return {
+                        "miles": round(miles, 1),
+                        "time_str": f"{hours}h {mins}m",
+                        "time_min": round(seconds/60)
+                    }
+            except Exception:
+                # If Google fails, fall back to OSRM/geodesic
+                pass
+
+        # OSRM (Robust HTTPS)
+        url = f"https://router.project-osrm.org/route/v1/driving/{coords_start[1]},{coords_start[0]};{coords_end[1]},{coords_end[0]}"
+        headers = {"User-Agent": "CargoApp/1.0"}
         
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
@@ -154,52 +305,55 @@ class LogisticsTools:
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
 
-st.title("✈️ Master Cargo Logistics Agent")
-st.markdown("### Verified Door-to-Door Scheduler")
+st.title("✈️ Master Cargo Logistics Agent")
+st.markdown("### Verified Door-to-Door Scheduler")
+st.caption(
+    "Uses Google Geocoding + Distance Matrix (GOOGLE_MAPS_KEY) and SerpAPI Google Flights for live data."
+)
 
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
@@ -234,52 +388,55 @@ with st.sidebar:
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
             
-        p_code = p_apts[0]['code']
-        d_code = d_apts[0]['code']
+        p_code = p_apts[0]['code']
+        d_code = d_apts[0]['code']
+
+        origin_cargo_window = tools._get_cargo_window(p_code)
+        dest_cargo_window = tools._get_cargo_window(d_code)
         
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
         
@@ -291,121 +448,149 @@ if run_btn:
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
                 
-                # Check 1: Departure Time
-                if f['Dep Time'] < earliest_dep_str: 
-                    reject_reason = f"Too Early (Dep {f['Dep Time']})"
-                
-                # Check 2: Connection Time
-                if f['Conn Apt'] != "Direct":
-                    if f['Conn Min'] < min_conn_filter:
-                        reject_reason = f"Short Conn ({f['Conn Time']})"
+                dep_time_obj = tools._parse_time(f.get('Dep Time'))
+                arr_time_obj = tools._parse_time(f.get('Arr Time'))
+
+                # Check 1: Departure Time
+                if dep_time_obj and dep_time_obj < earliest_dep_dt.time():
+                    reject_reason = f"Too Early (Dep {f['Dep Time']})"
+
+                # Check 1b: Origin cargo window
+                if not reject_reason and dep_time_obj:
+                    dep_ok, dep_label = tools.is_within_cargo_hours(p_code, dep_time_obj)
+                    if not dep_ok:
+                        reject_reason = f"Origin cargo closed ({dep_label})"
+
+                # Check 2: Connection Time
+                if f['Conn Apt'] != "Direct":
+                    if f['Conn Min'] < min_conn_filter:
+                        reject_reason = f"Short Conn ({f['Conn Time']})"
 
-                # Check 3: Arrival Deadline
-                if latest_arr_dt and not reject_reason:
-                    try:
-                        # Construct a dummy flight arrival date based on the search date
-                        f_arr_time_str = f['Arr Time']
-                        f_dep_time_str = f['Dep Time']
-                        
-                        f_arr_dt = datetime.datetime.strptime(f"{day_obj['date']} {f_arr_time_str}", "%Y-%m-%d %H:%M")
-                        
-                        # Handle date crossing (e.g. Dep 23:00, Arr 05:00)
-                        if f_arr_time_str < f_dep_time_str: 
-                            f_arr_dt += datetime.timedelta(days=1)
+                # Check 3: Arrival Deadline
+                if latest_arr_dt and not reject_reason:
+                    try:
+                        # Construct a dummy flight arrival date based on the search date
+                        if not arr_time_obj:
+                            raise ValueError("Arrival time missing")
+                        f_arr_dt = datetime.datetime.combine(
+                            datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d").date(),
+                            arr_time_obj,
+                        )
+
+                        # Handle date crossing (e.g. Dep 23:00, Arr 05:00)
+                        if dep_time_obj and arr_time_obj < dep_time_obj:
+                            f_arr_dt += datetime.timedelta(days=1)
                         
                         # Compare against the deadline relative to this specific day loop
                         # Deadline for this loop = Day Date + Offset
                         loop_deadline = datetime.datetime.strptime(day_obj['date'], "%Y-%m-%d") + datetime.timedelta(days=del_offset)
                         loop_deadline = loop_deadline.replace(hour=del_time.hour, minute=del_time.minute)
                         
                         loop_latest_arr = loop_deadline - datetime.timedelta(minutes=total_post)
                         
-                        if f_arr_dt > loop_latest_arr:
-                             reject_reason = f"Arrives Too Late ({f['Arr Time']})"
-                    except: pass
+                        if f_arr_dt > loop_latest_arr:
+                             reject_reason = f"Arrives Too Late ({f['Arr Time']})"
+                    except ValueError as exc:
+                        reject_reason = str(exc)
+                    except Exception:
+                        # If parsing fails for an unexpected reason, defer rejection to
+                        # other checks and allow the flight to pass rather than crash the loop.
+                        pass
+
+                # Check 4: Destination cargo window
+                if not reject_reason and arr_time_obj:
+                    arr_ok, arr_label = tools.is_within_cargo_hours(d_code, arr_time_obj)
+                    if not arr_ok:
+                        reject_reason = f"Destination cargo closed ({arr_label})"
 
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
-        st.markdown(f"""
-        * **Ready:** {p_time.strftime('%H:%M')}
-        * **Drive Mileage:** {d1['miles']} miles
-        * **Drive Time:** {d1['time_str']}
-        * **Buffer Logic:** MAX({d1['time_min']}, {custom_p_buff}) + 60 = **{total_prep} min** prep
-        * **Earliest Flight:** {earliest_dep_str}
-        """)
+        st.markdown(f"""
+        * **Ready:** {p_time.strftime('%H:%M')}
+        * **Drive Mileage:** {d1['miles']} miles
+        * **Drive Time:** {d1['time_str']}
+        * **Buffer Logic:** MAX({d1['time_min']}, {custom_p_buff}) + 60 = **{total_prep} min** prep
+        * **Earliest Flight:** {earliest_dep_str}
+        * **Cargo Hours:** {origin_cargo_window['label']}
+        """)
 
     with col2:
         st.success(f"**DELIVERY: {d_code}**")
         if has_deadline:
             days_str = f"(+{del_offset} Day)" if del_offset > 0 else "(Same Day)"
-            st.markdown(f"""
-            * **Deadline:** {del_time.strftime('%H:%M')} {days_str}
-            * **Drive Mileage:** {d2['miles']} miles
-            * **Drive Time:** {d2['time_str']}
-            * **Buffer Logic:** MAX({d2['time_min']}, {custom_d_buff}) + 60 = **{total_post} min** post
-            * **Must Arrive By:** {latest_arr_str}
-            """)
-        else:
-            st.markdown("*No strict deadline set.*")
+            st.markdown(f"""
+            * **Deadline:** {del_time.strftime('%H:%M')} {days_str}
+            * **Drive Mileage:** {d2['miles']} miles
+            * **Drive Time:** {d2['time_str']}
+            * **Buffer Logic:** MAX({d2['time_min']}, {custom_d_buff}) + 60 = **{total_post} min** post
+            * **Must Arrive By:** {latest_arr_str}
+            * **Cargo Hours:** {dest_cargo_window['label']}
+            """)
+        else:
+            st.markdown(f"""
+            *No strict deadline set.*
+            
+            * **Cargo Hours:** {dest_cargo_window['label']}
+            """)
 
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
         
 
EOF
)
