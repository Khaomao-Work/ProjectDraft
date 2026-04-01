import streamlit as st
import datetime
import requests
import folium
from streamlit_folium import st_folium
from optimiser import solve_itinerary

st.set_page_config(page_title="Travel Itinerary Optimizer", layout="wide", page_icon="🌍")

st.markdown("""
<style>
    div.stButton > button[kind="primary"] { width: 100%; font-weight: bold; border-radius: 8px; }
    div[data-testid="stVerticalBlock"] > div[style*="border"] { border-radius: 10px; background-color: rgba(255, 255, 255, 0.02); }
</style>
""", unsafe_allow_html=True)

if 'places' not in st.session_state: st.session_state.places = []
if 'temp_marker' not in st.session_state: st.session_state.temp_marker = None
if 'itineraries' not in st.session_state: st.session_state.itineraries = []

@st.cache_data
def get_route_geometry(start_coords: dict, end_coords: dict, travel_mode="drive") -> dict:
    if "GEOAPIFY_API_KEY" not in st.secrets: return {}
    api_key = st.secrets["GEOAPIFY_API_KEY"]
    start_point, end_point = f"{start_coords['lat']},{start_coords['lon']}", f"{end_coords['lat']},{end_coords['lon']}"
    url = f"https://api.geoapify.com/v1/routing?waypoints={start_point}|{end_point}&mode={travel_mode}&apiKey={api_key}"
    try:
        resp = requests.get(url)
        if resp.status_code == 200 and 'features' in resp.json() and len(resp.json()['features']) > 0:
            return resp.json()['features'][0]['geometry']
    except Exception: pass
    return {}

def clear_search(): st.session_state["search_box"] = ""

with st.sidebar:
    st.header("⚙️ 1. Trip Settings")
    st.subheader("📅 Dates")
    start_date = st.date_input("Start Date", datetime.date.today())
    end_date = st.date_input("End Date", datetime.date.today()) # ค่าเริ่มต้น 1 วัน
    trip_duration_days = (end_date - start_date).days + 1

    st.subheader("🎛️ Preferences")
    travel_style = st.slider("Optimization Balance: 📏 Distance vs. ⏱️ Time", 0, 100, 50)
    max_daily_hours = st.number_input("Max Travel Hours/Day", 1, 24, 8)
    
    with st.expander("🛠️ Advanced Settings", expanded=False):
        constraint_mode = st.radio("Constraint Mode", ["Visit All Places (Flexible Time)", "Strict Time Limit (Drop Places)"], index=0, label_visibility="collapsed")
        flexible_hours = (constraint_mode == "Visit All Places (Flexible Time)")

    st.divider()
    st.subheader("💰 Budget & Constraints")
    max_budget = st.number_input("Maximum Budget (฿)", min_value=0, step=100, value=2000, help="0 = ไม่จำกัดงบ")


st.title("🌍 Travel Itinerary Optimizer")
st.divider()
st.header("📍 2. Manage Locations")
col_map, col_list = st.columns([2, 1])

with col_map:
    st.subheader("Interactive Map")
    search_col1, search_col2 = st.columns([3, 1])
    with search_col1: search_query = st.text_input("Search Place Name", key="search_box", label_visibility="collapsed")
    with search_col2:
        if st.button("Search", use_container_width=True) and search_query:
            api_key = st.secrets.get("GEOAPIFY_API_KEY", "")
            if api_key:
                try:
                    resp = requests.get(f"https://api.geoapify.com/v1/geocode/search?text={search_query}&apiKey={api_key}")
                    if resp.status_code == 200 and resp.json()['features']:
                        coords = resp.json()['features'][0]['geometry']['coordinates']
                        st.session_state.temp_marker = {'lat': coords[1], 'lon': coords[0], 'name': search_query}
                except Exception: pass

    if st.session_state.temp_marker: center, zoom = [st.session_state.temp_marker['lat'], st.session_state.temp_marker['lon']], 13
    elif st.session_state.places: center, zoom = [st.session_state.places[-1]['lat'], st.session_state.places[-1]['lon']], 12
    else: center, zoom = [13.7563, 100.5018], 10

    m = folium.Map(location=center, zoom_start=zoom)
    for p in st.session_state.places:
        folium.Marker([p['lat'], p['lon']], popup=p['name'], icon=folium.Icon(color='green' if p.get('is_hotel') else 'blue', icon='home' if p.get('is_hotel') else 'camera')).add_to(m)

    if st.session_state.temp_marker:
        folium.Marker([st.session_state.temp_marker['lat'], st.session_state.temp_marker['lon']], popup="New Location", icon=folium.Icon(color='red', icon='star')).add_to(m)

    map_output = st_folium(m, height=450, use_container_width=True)

    if map_output['last_clicked']:
        st.session_state.temp_marker = {'lat': map_output['last_clicked']['lat'], 'lon': map_output['last_clicked']['lng'], 'name': "Selected Location"}
        st.rerun()

    if st.session_state.temp_marker:
        st.info("👇 Confirm details for the Red Marker")
        with st.form("confirm_place_form"):
            c1, c2 = st.columns([3, 1])
            with c1: final_name = st.text_input("Name", value=st.session_state.temp_marker['name'])
            with c2: is_hotel = st.checkbox("Is Hotel/Start?")
            c3, c4, c5 = st.columns(3)
            with c3: duration = st.number_input("Duration (hrs)", min_value=0.5, value=2.0, step=0.5, disabled=is_hotel)
            with c4: cost = st.number_input("Entrance Fee (฿)", min_value=0, value=0, step=50, disabled=is_hotel)
            with c5: score = st.slider("Preference ⭐", 1, 5, 3, disabled=is_hotel)
            c6, c7 = st.columns(2)
            with c6: open_time = st.number_input("Open Time (0-24)", min_value=0.0, max_value=24.0, value=8.0, step=0.5, disabled=is_hotel)
            with c7: close_time = st.number_input("Close Time (0-24)", min_value=0.0, max_value=24.0, value=18.0, step=0.5, disabled=is_hotel)

            if st.form_submit_button("➕ Add Place", on_click=clear_search):
                st.session_state.places.append({
                    'name': final_name, 'is_hotel': is_hotel,
                    'duration': duration if not is_hotel else 0, 'cost': cost if not is_hotel else 0,
                    'score': score if not is_hotel else 1, 
                    'open_time': open_time if not is_hotel else 0.0, 'close_time': close_time if not is_hotel else 24.0,
                    'lat': st.session_state.temp_marker['lat'], 'lon': st.session_state.temp_marker['lon']
                })
                st.session_state.temp_marker = None
                st.rerun()

with col_list:
    st.subheader("📋 Your List")
    with st.container(height=450, border=True):
        if not st.session_state.places: st.info("No places added yet.")
        else:
            for i, place in enumerate(st.session_state.places):
                with st.container(border=True):
                    c_info, c_del = st.columns([5, 1])
                    with c_info:
                        st.markdown(f"**{'🏨' if place.get('is_hotel') else '📍'} {place['name']}**")
                        if not place.get('is_hotel'):
                            st.caption(f"⏱️ {place['duration']}h | 💰 ฿{place.get('cost',0)} | ⭐{place.get('score',1)}")
                    with c_del:
                        if st.button("❌", key=f"del_{i}"):
                            st.session_state.places.pop(i)
                            st.rerun()

    st.write("")
    if st.button("🚀 Plan My Trip!", type="primary"):
        if not st.session_state.places: st.error("Please add at least one place.")
        else:
            with st.spinner("🧠 Running Optimization..."):
                obj_weights = {'distance_weight': travel_style/100, 'time_balance_weight': (100-travel_style)/100}
                hotels = [p for p in st.session_state.places if p.get('is_hotel')]
                attractions = [p for p in st.session_state.places if not p.get('is_hotel')]
                
                results = solve_itinerary(
                    potential_hotels=hotels, potential_attractions=attractions,
                    trip_duration_days=trip_duration_days, max_daily_hours=max_daily_hours,
                    is_daily_limit_flexible=flexible_hours, objective_weights=obj_weights,
                    max_budget=max_budget,
                )
                st.session_state['itineraries'] = results or []

st.divider()
st.header("✨ 4. Itinerary Results")
itineraries = st.session_state.get('itineraries', [])
if itineraries:
    for idx, itinerary in enumerate(itineraries):
        st.subheader(f"Option: {itinerary['title']}")
        st.metric("Total Estimated Distance", f"{itinerary['total_distance']:.2f} km")
        col_detail, col_res_map = st.columns([1, 2])
        
        with col_detail:
            for day_idx, daily_plan in enumerate(itinerary['daily_routes']):
                with st.expander(f"**Day {day_idx + 1}**", expanded=True):
                    if daily_plan:
                        for place in daily_plan:
                            st.write(f"{'🏨' if place.get('is_hotel') else '📍'} {place['name']} ({place.get('duration', 0)} hrs)")
                    else: st.write("No attractions planned.")

        with col_res_map:
            if itinerary and 'daily_routes' in itinerary and len(itinerary['daily_routes']) > 0 and len(itinerary['daily_routes'][0]) > 0:
                center_lat, center_lon = itinerary['daily_routes'][0][0].get('lat', 13.7563), itinerary['daily_routes'][0][0].get('lon', 100.5018)
                m_result = folium.Map(location=[center_lat, center_lon], zoom_start=12)
                colors = ['blue', 'green', 'purple', 'orange', 'darkred', 'lightred']
                
                # นำเข้าปลั๊กอินสำหรับทำหมุดตัวเลข
                from folium.plugins import BeautifyIcon

                for day_idx, daily_plan in enumerate(itinerary['daily_routes']):
                    
                    attraction_counter = 1 # ✨ ตัวนับลำดับสถานที่เที่ยว (รีเซ็ตเป็น 1 ใหม่ทุกวัน)
                    
                    for step_idx, place in enumerate(daily_plan):
                        is_hotel = place.get('is_hotel', False)
                        
                        if is_hotel:
                            # 🏨 กรณีเป็นโรงแรม (จุดเริ่มต้น/สิ้นสุด): ไม่ใส่เลข ใช้ไอคอนรูปบ้านสีแดง
                            marker_icon = folium.Icon(color='red', icon='home')
                            popup_text = f"Day {day_idx + 1}: {place['name']} (Hotel/Start)"
                        else:
                            # 📍 กรณีเป็นที่เที่ยว: ใส่ตัวเลขลำดับ 1, 2, 3...
                            marker_icon = BeautifyIcon(
                                icon_shape='marker',
                                number=attraction_counter,
                                border_color='#0275d8',
                                background_color='#0275d8',
                                text_color='white'
                            )
                            popup_text = f"Day {day_idx + 1} - Stop {attraction_counter}: {place['name']}"
                            attraction_counter += 1 # ✨ บวกเลขลำดับขึ้น 1 เฉพาะเมื่อเป็นที่เที่ยว
                            
                        folium.Marker(
                            [place.get('lat', 0), place.get('lon', 0)], 
                            popup=popup_text, 
                            icon=marker_icon
                        ).add_to(m_result)
                        
                    # วาดเส้นทางเชื่อมหมุด
                    for i in range(len(daily_plan) - 1):
                        geom = get_route_geometry({'lat': daily_plan[i].get('lat'), 'lon': daily_plan[i].get('lon')}, {'lat': daily_plan[i+1].get('lat'), 'lon': daily_plan[i+1].get('lon')})
                        if geom and 'coordinates' in geom:
                            folium.PolyLine(locations=[(c[1], c[0]) for c in geom['coordinates'][0]], color=colors[day_idx % len(colors)], weight=4, opacity=0.8).add_to(m_result)

                st_folium(m_result, height=500, use_container_width=True, key=f"final_map_{idx}")
            else: 
                st.warning("⚠️ ไม่สามารถสร้างแผนที่ได้ เนื่องจากเวลาไม่พอ หรือจัดทริปไม่ลงตัว")