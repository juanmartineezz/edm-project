import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from folium.plugins import MarkerCluster, LocateControl
from geopy.distance import geodesic
from opencage.geocoder import OpenCageGeocode
from dotenv import load_dotenv
import os
# --- CONFIGURACIÓN INICIAL DE PÁGINA ---
st.set_page_config(page_title="Ruta Cultural Valenbisi", page_icon="🚲", layout="wide", initial_sidebar_state="collapsed")

# --- CARGAR CSS PERSONALIZADO ---
def local_css(file_name):
    try:
        with open(file_name, encoding='UTF-8') as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        pass
local_css("style.css")
load_dotenv()
# --- CLAVES DE API ---
OPENCAGE_KEY=os.getenv("OPENCAGE_KEY")
geocoder = OpenCageGeocode(OPENCAGE_KEY)

# --- INICIALIZAR SESSION STATE ---
if 'total_co2_ahorrado_sesion' not in st.session_state: st.session_state.total_co2_ahorrado_sesion = 0.0
if 'rutas_calculadas_sesion' not in st.session_state: st.session_state.rutas_calculadas_sesion = 0
if 'selected_destination_tab1' not in st.session_state: st.session_state.selected_destination_tab1 = ""
if 'ordered_stops' not in st.session_state: st.session_state.ordered_stops = None
if 'current_stop_index' not in st.session_state: st.session_state.current_stop_index = 0
if 'navigation_mode' not in st.session_state: st.session_state.navigation_mode = False
if 'tour_completed' not in st.session_state: st.session_state.tour_completed = False
if 'tour_summary_stats' not in st.session_state: st.session_state.tour_summary_stats = {}

# --- FUNCIONES DE LÓGICA ---
@st.cache_data(ttl=3600)
def load_and_categorize_centros(filepath):
    try:
        df = pd.read_csv(filepath, encoding='utf-8')
        required_cols = ['nombre', 'geo_point_2d', 'informacion_recurso']
        if not all(col in df.columns for col in required_cols): return pd.DataFrame()
        df = df.dropna(subset=required_cols)
        coords = df['geo_point_2d'].str.strip('[]').str.split(',', expand=True)
        df['latitude'] = pd.to_numeric(coords[0], errors='coerce')
        df['longitude'] = pd.to_numeric(coords[1], errors='coerce')
        df = df.dropna(subset=['latitude', 'longitude'])
        df['nombre_centro'] = df['nombre'].str.replace(r'^\d+\s*-\s*', '', regex=True).str.strip()
        df['info_url'] = df['informacion_recurso']
        return df[['nombre_centro', 'latitude', 'longitude', 'info_url']].drop_duplicates(subset=['nombre_centro']).sort_values(by='nombre_centro').reset_index(drop=True)
    except Exception: return pd.DataFrame()

@st.cache_data(ttl=300)
def get_valenbisi_data():
    base_url = "https://valencia.opendatasoft.com/api/explore/v2.1/catalog/datasets/valenbisi-disponibilitat-valenbisi-dsiponibilidad/records"
    all_data = []
    try:
        for offset in range(0, 400, 100):
            res = requests.get(f"{base_url}?limit=100&offset={offset}", timeout=15); res.raise_for_status()
            data = res.json(); results = data.get("results", [])
            if not results: break
            all_data.extend(results)
    except requests.exceptions.RequestException: pass
    if not all_data: return pd.DataFrame()
    df = pd.json_normalize(all_data)
    api_col_map = {"geo_point_2d.lat": "latitude", "geo_point_2d.lon": "longitude", "available": "bicis_disponibles", "name": "nombre_estacion_api", "number": "numero_estacion", "address": "direccion_estacion", "total": "capacidad_total", "free": "bornes_libres", "status": "status"}
    df.rename(columns={k: v for k, v in api_col_map.items() if k in df.columns}, inplace=True)
    if 'nombre_estacion_api' in df.columns: df['nombre_estacion'] = df['nombre_estacion_api']
    elif 'numero_estacion' in df.columns: df['nombre_estacion'] = "Estación " + df['numero_estacion'].astype(str)
    else: df['nombre_estacion'] = "Estación Desconocida"
    if not all(col in df.columns for col in ["latitude", "longitude", "bicis_disponibles", "nombre_estacion", "bornes_libres"]): return pd.DataFrame()
    for col in ["bicis_disponibles", "bornes_libres", "capacidad_total"]: df[col] = pd.to_numeric(df.get(col), errors='coerce').fillna(0).astype(int)
    if "status" in df.columns: df = df[df['status'].astype(str).str.upper() == 'OPEN']
    return df

@st.cache_data
def geocode_address(address):
    if not address: return None
    try:
        results = geocoder.geocode(address, bounds="-0.53,39.35,-0.25,39.60", limit=1, language='es')
        return (results[0]['geometry']['lat'], results[0]['geometry']['lng']) if results else None
    except Exception: return None

@st.cache_data
def get_route(start_coords, end_coords, profile='bike'):
    if not start_coords or not end_coords: return None, 0, 0
    url = f"http://router.project-osrm.org/route/v1/{profile}/{start_coords[1]},{start_coords[0]};{end_coords[1]},{end_coords[0]}?overview=full&geometries=geojson"
    try:
        res = requests.get(url, timeout=12); res.raise_for_status()
        route = res.json().get('routes', [{}])[0]
        return route.get('geometry'), route.get('distance', 0) / 1000, route.get('duration', 0) / 60
    except requests.exceptions.RequestException: return None, 0, 0

def find_closest_station(target_coords, estaciones_df, min_required=1, criteria_col="bicis_disponibles"):
    if not target_coords or estaciones_df.empty: return None
    estaciones_validas = estaciones_df[estaciones_df[criteria_col] >= min_required].copy()
    if estaciones_validas.empty: return None
    estaciones_validas['distancia'] = estaciones_validas.apply(lambda r: geodesic(target_coords, (r['latitude'], r['longitude'])).m, axis=1)
    return estaciones_validas.sort_values('distancia').iloc[0].to_dict()

def get_trip_details(start_coords, end_coords, valenbisi_df, min_bikes, min_docks):
    # Lógica de caminata para distancias cortas
    if geodesic(start_coords, end_coords).meters < 500:
        geom, dist, time = get_route(start_coords, end_coords, 'foot')
        if not geom: return {'error': 'No se pudo calcular la ruta a pie.'}
        return {'trip_type': 'walk', 'total_dist': dist, 'total_time': time, 'geoms': {'walk_only': geom}, 'error': None}
    
    # Lógica normal de Valenbisi
    estacion_origen = find_closest_station(start_coords, valenbisi_df, min_bikes, "bicis_disponibles")
    if not estacion_origen: return {'error': 'No se encontró estación de origen con suficientes bicis.'}
    estacion_destino = find_closest_station(end_coords, valenbisi_df, min_docks, "bornes_libres")
    if not estacion_destino: return {'error': 'No se encontró estación de destino con suficientes bornes.'}
    coords_origen, coords_destino = (estacion_origen['latitude'], estacion_origen['longitude']), (estacion_destino['latitude'], estacion_destino['longitude'])
    geom_p1, dist_p1, time_p1 = get_route(start_coords, coords_origen, 'foot')
    geom_b, dist_b, time_b = get_route(coords_origen, coords_destino, 'bike')
    geom_p2, dist_p2, time_p2 = get_route(coords_destino, end_coords, 'foot')
    if not all([geom_p1, geom_b, geom_p2]): return {'error': 'No se pudo calcular la ruta completa.'}
    return {'trip_type': 'valenbisi', 'estacion_origen': estacion_origen, 'estacion_destino': estacion_destino, 'geoms': {'pie1': geom_p1, 'bici': geom_b, 'pie2': geom_p2}, 'dists': {'pie1': dist_p1, 'bici': dist_b, 'pie2': dist_p2}, 'times': {'pie1': time_p1, 'bici': time_b, 'pie2': time_p2}, 'total_time': time_p1 + time_b + time_p2, 'total_dist': dist_p1 + dist_b + dist_p2, 'co2_saved_kg': (dist_b * 135) / 1000, 'error': None}

@st.cache_data
def get_optimal_route_order(points_df):
    coords = list(zip(points_df['latitude'], points_df['longitude'])); num_points = len(coords)
    dist_matrix = [[0] * num_points for _ in range(num_points)]
    for i in range(num_points):
        for j in range(i + 1, num_points):
            dist = geodesic(coords[i], coords[j]).km
            dist_matrix[i][j] = dist_matrix[j][i] = dist
    current_idx, path = 0, [0]
    unvisited = list(range(1, num_points))
    while unvisited:
        next_idx = min(unvisited, key=lambda x: dist_matrix[current_idx][x])
        path.append(next_idx); unvisited.remove(next_idx); current_idx = next_idx
    return points_df.iloc[path].copy().reset_index(drop=True)

def add_map_layers(folium_map, valenbisi_data):
    tiles = {"Normal": 'OpenStreetMap', "Claro": 'CartoDB positron', "Oscuro": 'CartoDB dark_matter', "Satélite": 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'}
    for name, tile in tiles.items(): folium.TileLayer(tile, attr='Esri' if name == 'Satélite' else '', name=name).add_to(folium_map)
    if not valenbisi_data.empty:
        cluster = MarkerCluster(name="Todas las Estaciones", overlay=True, control=True, show=False).add_to(folium_map)
        for _, row in valenbisi_data.iterrows():
            folium.Marker(location=[row['latitude'], row['longitude']], tooltip=f"<b>{row.get('nombre_estacion', 'N/A')}</b><br>Bicis: {row.get('bicis_disponibles', 0)} | Bornes: {row.get('bornes_libres', 0)}", icon=folium.Icon(color="lightgray", icon_color="#666666", icon="bicycle", prefix="fa")).add_to(cluster)

def calculate_calories(distance_km, duration_min):
    if duration_min == 0: return 0
    speed_kmh = distance_km / (duration_min / 60)
    min_speed, max_speed = 15, 28
    min_kcal_hr, max_kcal_hr = 400, 900
    clamped_speed = max(min_speed, min(speed_kmh, max_speed))
    kcal_per_hour = min_kcal_hr + (clamped_speed - min_speed) * (max_kcal_hr - min_kcal_hr) / (max_speed - min_speed)
    return kcal_per_hour * (duration_min / 60)

# --- CARGA INICIAL ---
centros_df = load_and_categorize_centros("nuevos_centros.csv")
valenbisi_df = get_valenbisi_data()
st.title("🚲 Ruta Cultural Valenbisi")
st.markdown("Planifica tus recorridos por Valencia de forma sostenible, eficiente e interactiva.")
tab1, tab2 = st.tabs(["🗺️ Ruta a un Destino", "🧭 Planificador de Tour Interactivo"])

# --- PESTAÑA 1 ---
with tab1:
    st.header("Planifica un viaje a un único punto de interés")
    def on_destination_change(): st.session_state.selected_destination_tab1 = st.session_state.dest_tab1_widget
    form_cols = st.columns([2, 2, 1])
    with form_cols[0]: user_address_tab1 = st.text_input("📍 Tu dirección en Valencia", key="addr_tab1")
    with form_cols[1]:
        options = [""] + sorted(centros_df['nombre_centro'].unique()) if not centros_df.empty else [""]
        st.selectbox("🏛️ Elige un destino", options, key="dest_tab1_widget", index=options.index(st.session_state.selected_destination_tab1) if st.session_state.selected_destination_tab1 in options else 0, on_change=on_destination_change)
    with form_cols[2]: min_bikes_tab1 = st.slider("Min. bicis/bornes", 0, 10, 1, key="min_b_tab1")
    if st.button("🚀 Calcular Ruta Individual", use_container_width=True):
        if not user_address_tab1 or not st.session_state.selected_destination_tab1: st.warning("Por favor, introduce tu dirección y selecciona un destino.")
        else:
            with st.spinner("Calculando tu ruta..."):
                start_coords = geocode_address(user_address_tab1)
                if not start_coords: st.error("No se pudo encontrar tu dirección.")
                else:
                    destino_info = centros_df[centros_df['nombre_centro'] == st.session_state.selected_destination_tab1].iloc[0]
                    trip = get_trip_details(start_coords, (destino_info['latitude'], destino_info['longitude']), valenbisi_df, min_bikes_tab1, min_bikes_tab1)
                    if trip.get('error'): st.error(trip['error'])
                    else:
                        st.markdown("### Tu Ruta Sugerida"); map_cols = st.columns([3, 2])
                        with map_cols[0]:
                            m = folium.Map(location=start_coords, zoom_start=15); add_map_layers(m, valenbisi_df)
                            fg = folium.FeatureGroup(name="Ruta Principal").add_to(m)
                            if trip['trip_type'] == 'walk':
                                folium.GeoJson(trip['geoms']['walk_only'], style_function=lambda x: {"color": "#1abc9c", "weight": 7, "dashArray": "5, 5"}).add_to(fg)
                            else: # valenbisi
                                folium.GeoJson(trip['geoms']['pie1'], style_function=lambda x: {"color": "#E74C3C", "weight": 5, "dashArray": "5, 5"}).add_to(fg)
                                folium.GeoJson(trip['geoms']['bici'], style_function=lambda x: {"color": "#3498DB", "weight": 7}).add_to(fg)
                                folium.GeoJson(trip['geoms']['pie2'], style_function=lambda x: {"color": "#F39C12", "weight": 5, "dashArray": "5, 5"}).add_to(fg)
                                folium.Marker((trip['estacion_origen']['latitude'], trip['estacion_origen']['longitude']), tooltip=f"Origen: {trip['estacion_origen']['nombre_estacion']} (Bicis: {trip['estacion_origen']['bicis_disponibles']})", icon=folium.Icon(color="blue", icon="bicycle", prefix="fa")).add_to(fg)
                                folium.Marker((trip['estacion_destino']['latitude'], trip['estacion_destino']['longitude']), tooltip=f"Destino: {trip['estacion_destino']['nombre_estacion']} (Bornes: {trip['estacion_destino']['bornes_libres']})", icon=folium.Icon(color="orange", icon="parking", prefix="fa")).add_to(fg)
                            folium.Marker(start_coords, tooltip="Tu Ubicación", icon=folium.Icon(color="green", icon="street-view", prefix="fa")).add_to(fg)
                            folium.Marker((destino_info['latitude'], destino_info['longitude']), tooltip=f"Destino: {destino_info['nombre_centro']}", icon=folium.Icon(color="purple", icon="flag-checkered", prefix="fa")).add_to(fg)
                            folium.LayerControl().add_to(m); m.fit_bounds(fg.get_bounds()); folium_static(m, height=450)
                        with map_cols[1]:
                            if trip['trip_type'] == 'walk':
                                st.info("🚶‍♂️ Tu destino está muy cerca. ¡Te recomendamos ir andando!")
                                st.markdown(f"<div class='summary-card'><h4>Resumen del Paseo</h4><p>⏱️ <strong>Tiempo Total:</strong> {trip['total_time']:.0f} min</p><p>👟 <strong>Distancia Total:</strong> {trip['total_dist']:.2f} km</p></div>", unsafe_allow_html=True)
                            else:
                                st.markdown(f"<div class='summary-card'><h4>Resumen del Viaje</h4><p>⏱️ <strong>Tiempo Total:</strong> {trip['total_time']:.0f} min</p><p>👟 <strong>Distancia Total:</strong> {trip['total_dist']:.2f} km</p><p>🌿 <strong>CO₂ Ahorrado:</strong> {trip['co2_saved_kg']:.3f} kg</p></div>", unsafe_allow_html=True)
                                with st.expander("Ver detalles del itinerario"):
                                    st.write(f"🚶 **A pie (inicio):** {trip['dists']['pie1']:.2f} km / {trip['times']['pie1']:.0f} min"); st.write(f"🚲 **En bici:** {trip['dists']['bici']:.2f} km / {trip['times']['bici']:.0f} min"); st.write(f"🚶 **A pie (final):** {trip['dists']['pie2']:.2f} km / {trip['times']['pie2']:.0f} min")
                            if 'info_url' in destino_info and pd.notna(destino_info['info_url']): st.markdown(f'<a href="{destino_info["info_url"]}" target="_blank" class="info-link">📄 Conocer más sobre {destino_info["nombre_centro"]}</a>', unsafe_allow_html=True)

# --- PESTAÑA 2 ---
with tab2:
    st.header("Crea y sigue tu ruta cultural paso a paso")
    if not st.session_state.navigation_mode and not st.session_state.tour_completed:
        st.markdown("#### 1. Configura tu Tour")
        with st.form("multi_route_form"):
            user_address_tab2 = st.text_input("📍 Tu punto de partida", key="addr_tab2")
            puntos_seleccionados = st.multiselect("🏛️ Selecciona los destinos a visitar (2 o más)", sorted(centros_df['nombre_centro'].unique()) if not centros_df.empty else [], key="dest_tab2")
            submit_plan = st.form_submit_button("🗺️ Planificar Mi Tour", use_container_width=True)
        if submit_plan:
            if not user_address_tab2 or len(puntos_seleccionados) < 2: st.warning("Introduce una dirección de partida y selecciona al menos 2 destinos.")
            else:
                with st.spinner("Optimizando el orden de las paradas..."):
                    start_coords = geocode_address(user_address_tab2)
                    if not start_coords: st.error("No se pudo encontrar la dirección de partida.")
                    else:
                        start_point_df = pd.DataFrame([{'nombre_centro': 'PUNTO DE PARTIDA', 'latitude': start_coords[0], 'longitude': start_coords[1], 'info_url': None}])
                        selected_points_df = centros_df[centros_df['nombre_centro'].isin(puntos_seleccionados)]
                        points_to_visit_df = pd.concat([start_point_df, selected_points_df], ignore_index=True)
                        st.session_state.ordered_stops = get_optimal_route_order(points_to_visit_df)
                        st.session_state.current_stop_index = 0
        if st.session_state.ordered_stops is not None:
            st.markdown("---"); st.markdown("#### 2. Tu Ruta Optimizada (Vista Previa)")
            stops_df = st.session_state.ordered_stops
            m_overview = folium.Map(location=[stops_df['latitude'].mean(), stops_df['longitude'].mean()], zoom_start=13); add_map_layers(m_overview, valenbisi_df)
            fg_overview = folium.FeatureGroup(name="Ruta Teórica").add_to(m_overview)
            points = list(zip(stops_df['latitude'], stops_df['longitude']))
            folium.PolyLine(points, color='grey', weight=3, opacity=0.8, dash_array='10, 5').add_to(fg_overview)
            for i, stop in stops_df.iterrows():
                folium.Marker(location=[stop['latitude'], stop['longitude']], tooltip=f"Parada {i}: {stop['nombre_centro']}", icon=folium.Icon(color="purple" if i > 0 else "green", icon=str(i), prefix='fa')).add_to(fg_overview)
            folium.LayerControl().add_to(m_overview); m_overview.fit_bounds(fg_overview.get_bounds()); folium_static(m_overview, height=400)
            with st.expander("Ver orden de visita sugerido"):
                for i, stop in stops_df.iterrows(): st.markdown(f"**{i}.** {stop['nombre_centro']}")
            if st.button("▶️ Empezar Ruta Interactiva", use_container_width=True, type="primary"):
                st.session_state.navigation_mode = True; st.session_state.tour_summary_stats = {'distancia': 0.0, 'tiempo_bici': 0.0, 'co2': 0.0, 'calorias': 0.0}
                st.rerun()

    elif st.session_state.navigation_mode:
        stops = st.session_state.ordered_stops; current_idx = st.session_state.current_stop_index
        current_stop = stops.iloc[current_idx]; next_stop = stops.iloc[current_idx + 1]
        start_coords, end_coords = (current_stop['latitude'], current_stop['longitude']), (next_stop['latitude'], next_stop['longitude'])
        st.markdown(f"### 🧭 Etapa {current_idx + 1} de {len(stops) - 1}")
        st.subheader(f"De: {current_stop['nombre_centro']}  →  A: {next_stop['nombre_centro']}")
        min_bikes_nav = st.slider("Min. bicis/bornes para esta etapa", 0, 10, 1, key=f"min_b_nav_{current_idx}")
        with st.spinner("Buscando la mejor ruta en tiempo real..."):
            trip = get_trip_details(start_coords, end_coords, valenbisi_df.copy(), min_bikes_nav, min_bikes_nav)
        if trip.get('error'): st.error(f"Error al calcular esta etapa: {trip['error']}. Intenta con menos bicis/bornes o reinicia el tour.")
        else:
            map_nav, info_nav = st.columns([3, 2])
            with map_nav:
                m_nav = folium.Map(location=start_coords, zoom_start=15); add_map_layers(m_nav, valenbisi_df)
                fg_nav = folium.FeatureGroup(name=f"Ruta Etapa {current_idx + 1}").add_to(m_nav)
                if trip['trip_type'] == 'walk':
                    folium.GeoJson(trip['geoms']['walk_only'], style_function=lambda x: {"color": "#1abc9c", "weight": 7, "dashArray": "5, 5"}).add_to(fg_nav)
                else: # valenbisi
                    folium.GeoJson(trip['geoms']['pie1'], style_function=lambda x: {"color": "#E74C3C", "weight": 5, "dashArray": "5, 5"}).add_to(fg_nav)
                    folium.GeoJson(trip['geoms']['bici'], style_function=lambda x: {"color": "#3498DB", "weight": 7}).add_to(fg_nav)
                    folium.GeoJson(trip['geoms']['pie2'], style_function=lambda x: {"color": "#F39C12", "weight": 5, "dashArray": "5, 5"}).add_to(fg_nav)
                    folium.Marker((trip['estacion_origen']['latitude'], trip['estacion_origen']['longitude']), tooltip=f"Coger Bici (Bicis: {trip['estacion_origen']['bicis_disponibles']})", icon=folium.Icon(color="blue", icon="bicycle", prefix="fa")).add_to(fg_nav)
                    folium.Marker((trip['estacion_destino']['latitude'], trip['estacion_destino']['longitude']), tooltip=f"Dejar Bici (Bornes: {trip['estacion_destino']['bornes_libres']})", icon=folium.Icon(color="orange", icon="parking", prefix="fa")).add_to(fg_nav)
                folium.Marker(start_coords, tooltip=f"Estás aquí: {current_stop['nombre_centro']}", icon=folium.Icon(color="green", icon="street-view", prefix="fa")).add_to(fg_nav)
                folium.Marker(end_coords, tooltip=f"Próximo Destino: {next_stop['nombre_centro']}", icon=folium.Icon(color="purple", icon="flag-checkered", prefix="fa")).add_to(fg_nav)
                folium.LayerControl().add_to(m_nav); m_nav.fit_bounds(fg_nav.get_bounds()); folium_static(m_nav, height=500)
            with info_nav:
                st.markdown(f"<div class='summary-card'><h4>Detalles de la Etapa</h4><p>⏱️ <strong>Tiempo Aprox.:</strong> {trip['total_time']:.0f} min</p><p>👟 <strong>Distancia Aprox.:</strong> {trip['total_dist']:.2f} km</p></div>", unsafe_allow_html=True)
                st.markdown("#### Instrucciones:")
                if trip['trip_type'] == 'walk':
                    st.info(f"🚶‍♂️ El siguiente destino está muy cerca. Simplemente camina hasta **{next_stop['nombre_centro']}** ({trip['total_time']:.0f} min).")
                else:
                    st.info(f"1. Camina a la est. **{trip['estacion_origen']['nombre_estacion']}** ({trip['times']['pie1']:.0f} min).")
                    st.info(f"2. Coge una bici y pedalea a **{trip['estacion_destino']['nombre_estacion']}** ({trip['times']['bici']:.0f} min).")
                    st.info(f"3. Camina hasta tu destino: **{next_stop['nombre_centro']}** ({trip['times']['pie2']:.0f} min).")
                if next_stop['info_url'] and pd.notna(next_stop['info_url']): st.markdown(f'<a href="{next_stop["info_url"]}" target="_blank" class="info-link-small">📄 Ver info de {next_stop["nombre_centro"]}</a>', unsafe_allow_html=True)
                st.markdown("---")
                if st.button(f"✅ He llegado a {next_stop['nombre_centro']}", use_container_width=True, type="primary"):
                    stats = st.session_state.tour_summary_stats
                    stats['distancia'] += trip['total_dist']
                    if trip['trip_type'] == 'valenbisi':
                        stats['tiempo_bici'] += trip['times']['bici']; stats['co2'] += trip['co2_saved_kg']
                        stats['calorias'] += calculate_calories(trip['dists']['bici'], trip['times']['bici'])
                    st.session_state.rutas_calculadas_sesion += 1; st.session_state.current_stop_index += 1
                    if st.session_state.current_stop_index >= len(stops) - 1:
                        st.session_state.navigation_mode = False; st.session_state.tour_completed = True
                    st.rerun()
        if st.button("❌ Terminar y Salir del Tour"):
            st.session_state.navigation_mode = False; st.session_state.ordered_stops = None; st.session_state.current_stop_index = 0
            st.rerun()

    elif st.session_state.tour_completed:
        st.balloons()
        st.header("🎉 ¡Felicidades! Has completado tu tour cultural.")
        stats = st.session_state.tour_summary_stats; trees_equivalent = stats['co2'] / 0.060
        st.markdown("<div class='summary-card-final'>", unsafe_allow_html=True)
        st.markdown("### Resumen de tu Aventura")
        cols = st.columns(4)
        cols[0].metric("Distancia Total", f"{stats['distancia']:.2f} km")
        cols[1].metric("CO₂ Ahorrado", f"{stats['co2']:.3f} kg")
        cols[2].metric("Calorías Quemadas", f"~{stats['calorias']:.0f} kcal")
        cols[3].metric("Equivale a", f"{trees_equivalent:.1f} árboles/día")
        st.markdown("</div>", unsafe_allow_html=True)
        st.info("Las calorías y la equivalencia en árboles son estimaciones para dar una idea de tu impacto positivo.")
        if st.button("👍 Planificar un Nuevo Tour", use_container_width=True):
            st.session_state.navigation_mode = False; st.session_state.ordered_stops = None
            st.session_state.current_stop_index = 0; st.session_state.tour_completed = False
            st.session_state.tour_summary_stats = {}
            st.rerun()

# --- PIE DE PÁGINA COMÚN ---
st.markdown("---")
st.markdown(f"CO₂ total ahorrado en esta sesión: **{st.session_state.total_co2_ahorrado_sesion:.3f} kg** | Rutas calculadas: **{st.session_state.rutas_calculadas_sesion}**")