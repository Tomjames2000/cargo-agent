import requests
import datetime
from dateutil import parser

# --- 1. DATA FETCHING LAYER ---
def get_flight_details(flight_iata, api_key):
    """
    Pulls live/scheduled flight data from Aviation Edge.
    """
    base_url = "https://aviation-edge.com/v2/public/flights"
    params = {
        "key": api_key,
        "flightIata": flight_iata
    }
    
    try:
        response = requests.get(base_url, params=params, timeout=10)
        data = response.json()
        
        # Aviation Edge returns a list. If empty, flight isn't active/found.
        if not data or isinstance(data, dict) and "error" in data:
            return None
            
        # Grab the first result (most relevant active flight)
        flight = data[0]
        
        return {
            "flight_num": flight['flight']['iataNumber'],
            "origin_icao": flight['departure']['icaoCode'],
            "dest_icao": flight['arrival']['icaoCode'],
            "status": flight['status'],
            "arrival_time_est": flight['arrival']['scheduledTime'] # Format: YYYY-MM-DDTHH:MM:SS
        }
    except Exception as e:
        return None

def get_weather_forecast(icao_code):
    """
    Pulls the TAF (Terminal Forecast) from the US Govt (AWC).
    """
    # AWC API is free/open.
    url = f"https://aviationweather.gov/api/data/taf?ids={icao_code}&format=json"
    
    try:
        r = requests.get(url, timeout=10)
        data = r.json()
        if not data:
            return None
        return data[0]['rawTAF'] # Returns the raw forecast string for parsing
    except:
        return "Weather Data Unavailable"

# --- 2. DECISION LOGIC LAYER ---
def analyze_reliability(flight_iata, api_key):
    # Step A: Get Flight Info
    flight_data = get_flight_details(flight_iata, api_key)
    
    if not flight_data:
        return {"error": "Flight not found in Aviation Edge database (Must be Active/Scheduled)."}

    # Step B: Get Weather for Destination
    dest_icao = flight_data['dest_icao']
    taf_raw = get_weather_forecast(dest_icao)
    
    if not taf_raw:
        taf_raw = "No TAF Available"

    # Step C: The Scoring Algorithm (Simplified for V1)
    score = 100
    risks = []
    
    # Logic 1: Check if "Fog" (FG) or "Thunderstorms" (TS) are in the forecast text
    if "TS" in taf_raw: 
        score -= 30
        risks.append("Thunderstorms in Forecast")
    if "FG" in taf_raw or "BR" in taf_raw: # Fog or Mist
        score -= 20
        risks.append("Low Visibility (Fog/Mist)")
    if "SN" in taf_raw: # Snow
        score -= 40
        risks.append("Snow/Icing Operations")
    if "VV" in taf_raw: # Vertical Visibility (Low Ceilings)
        score -= 30
        risks.append("Obscured Ceiling (Low Approach)")
        
    # Logic 2: Status check
    status_lower = str(flight_data['status']).lower()
    if status_lower == 'cancelled':
        score = 0
        risks.append("Flight Already Cancelled")
    elif status_lower == 'incident':
        score = 0
        risks.append("Active Incident")
    elif status_lower == 'diverted':
        score = 0
        risks.append("Flight Diverted")

    # Determine Final Status
    if score > 80: status = "GO / GREEN"
    elif score > 50: status = "CAUTION / YELLOW"
    else: status = "NO-GO / RED"

    return {
        "score": score,
        "status": status,
        "flight_info": flight_data,
        "weather_raw": taf_raw,
        "risk_factors": risks
    }
