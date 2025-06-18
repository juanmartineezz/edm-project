
import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static # Usamos folium_static para evitar problemas de estado con st_folium en el bucle principal
from folium.plugins import MarkerCluster, LocateControl, Fullscreen
from geopy.geocoders import Nominatim
from geopy.distance import geodesic
from opencage.geocoder import OpenCageGeocode
import pyproj
from datetime import datetime, date
import random
import os
from dotenv import load_dotenv
# --- CONFIGURACIÓN INICIAL DE PÁGINA ---
st.set_page_config(
    page_title="Ruta Cultural Valenbisi",
    page_icon="🚲",
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CARGAR CSS PERSONALIZADO ---
def local_css(file_name):
    try:
        with open(file_name, encoding='UTF-8') as f:
            st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        st.warning(f"Archivo CSS '{file_name}' no encontrado. Se usarán estilos por defecto.")

local_css("style.css") # Asegúrate que tu CSS se llama style.css

# --- CLAVES DE API ---
load_dotenv()
OPENCAGE_KEY = os.getenv("OPENCAGE_KEY", "")
OPENWEATHER_KEY = os.getenv("OPENWEATHER_KEY", "")  # Asegúrate de que tienes la clave configurada en tu entorno


if not OPENCAGE_KEY:
    st.error("🔑 Clave de OpenCage no configurada. La geocodificación no funcionará.")
    st.stop()
geocoder = OpenCageGeocode(OPENCAGE_KEY)

# --- INICIALIZAR SESSION STATE ---
if 'last_address' not in st.session_state: st.session_state.last_address = ""
if 'last_centro_nombre' not in st.session_state: st.session_state.last_centro_nombre = "" # Guardar nombre para el selectbox
if 'min_bicis_bornes' not in st.session_state: st.session_state.min_bicis_bornes = 1
if 'total_co2_ahorrado_sesion' not in st.session_state: st.session_state.total_co2_ahorrado_sesion = 0.0
if 'rutas_calculadas_sesion' not in st.session_state: st.session_state.rutas_calculadas_sesion = 0
# 'active_tab' ya no es necesario si usamos rerun para preseleccionar

# --- FUNCIONES DE CARGA Y PROCESAMIENTO DE DATOS ---
# (Las funciones load_and_categorize_centros, get_valenbisi_data, geocode_address, 
# get_route, find_closest_stations_valenbisi, find_nearby_pois, 
# get_weather_valencia, display_weather son las mismas que en app_final_v7.py, 
# las omito aquí por brevedad pero deben estar presentes en tu archivo)

@st.cache_data(ttl=3600) 
def load_and_categorize_centros(filepath):
    try:
        df = pd.read_csv(filepath, encoding='utf-8') # Especificar encoding
    except FileNotFoundError:
        st.error(f"❌ Archivo de centros culturales '{filepath}' no encontrado.")
        return pd.DataFrame()
    except Exception as e:
        st.error(f"❌ Error leyendo el archivo CSV de centros: {e}")
        return pd.DataFrame()
    
    df.columns = df.columns.str.strip().str.lower()
    required_cols = ['x', 'y', 'equipamien']
    if not all(col in df.columns for col in required_cols):
        missing = [col for col in required_cols if col not in df.columns]
        st.error(f"El archivo CSV de centros debe contener las columnas: {', '.join(missing)}.")
        return pd.DataFrame()
        
    df = df.dropna(subset=required_cols)
    if df.empty:
        st.warning("No hay datos de centros culturales con coordenadas y nombre válidos.")
        return pd.DataFrame()
    
    try:
        transformer = pyproj.Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
        df['x_float'] = pd.to_numeric(df['x'], errors='coerce')
        df['y_float'] = pd.to_numeric(df['y'], errors='coerce')
        df = df.dropna(subset=['x_float', 'y_float'])
        if df.empty:
            st.warning("Coordenadas X o Y no válidas en los datos de centros tras la conversión.")
            return pd.DataFrame()
        df['longitude'], df['latitude'] = transformer.transform(df['x_float'].values, df['y_float'].values)
    except Exception as e:
        st.error(f"❌ Error transformando coordenadas de centros: {e}")
        return pd.DataFrame()

    categorias_keywords = {
        "Museos": ['museo', 'museu', 'oceanogràfic', 'hemisfèric', 'muma', 'muvim', 'l\'iber', 'corpus', 'prehistoria', 'etnología', 'ciencias naturales', 'ciencias', 'fallero'],
        "Teatros y Salas de Concierto": ['teatro', 'teatre', 'auditori', 'música', 'arts escèniques', 'flumen', 'olympia', 'principal', 'talia', 'musical', 'escalante', 'palau de la música', 'sala'],
        "Bibliotecas y Archivos": ['biblioteca', 'arxiu', 'hemeroteca', 'lectura', 'documentación'],
        "Monumentos y Palacios": ['palau', 'palacio', 'llotja', 'lonja', 'església', 'iglesia', 'catedral', 'monestir', 'monasterio', 'torres', 'portal', 'ermita', 'basílica', 'almodí', 'almudín', 'cripta', 'refugio antiaéreo', 'cementerio', 'ateneo', 'casino'],
        "Galerías y Exposiciones": ['galería', 'galeria', 'sala exposiciones', 'exposición', 'centre d\'art', 'atarazanas', 'atarazanes', 'ivam', 'caixaforum', 'beneficencia', 'la nau'],
        "Fundaciones y Centros Culturales Diversos": ['centre cultural', 'centro cultural', 'fundació', 'fundación', 'instituto', 'institució', 'casa de la cultura', 'las naves', 'rambleta', 'nou d\'octubre'],
    }

    def categorize_centro(nombre):
        if pd.isna(nombre): return "Otros Equipamientos"
        nombre_lower = str(nombre).lower()
        for categoria, keywords in categorias_keywords.items():
            if any(keyword in nombre_lower for keyword in keywords):
                return categoria
        return "Otros Equipamientos"

    df['categoria'] = df['equipamien'].apply(categorize_centro)
    
    df_filtered = df[df['categoria'] != "Otros Equipamientos"].copy()
    df_filtered.rename(columns={'equipamien': 'nombre_centro', 'telefono': 'telefono_centro'}, inplace=True)
    
    cols_to_keep = ['nombre_centro', 'latitude', 'longitude', 'categoria']
    if 'telefono_centro' in df_filtered.columns:
        df_filtered['telefono_centro'] = df_filtered['telefono_centro'].astype(str).str.replace(r'\.0$', '', regex=True)
        cols_to_keep.append('telefono_centro')

    result_df = df_filtered[cols_to_keep].drop_duplicates(subset=['nombre_centro'])
    return result_df.sort_values(by=['categoria', 'nombre_centro']).reset_index(drop=True)


@st.cache_data(ttl=300) 
def get_valenbisi_data():
    # ... (Mantener la versión corregida de get_valenbisi_data de app_final_v6.py)
    base_url = "https://valencia.opendatasoft.com/api/explore/v2.1/catalog/datasets/valenbisi-disponibilitat-valenbisi-dsiponibilidad/records"
    all_data = []
    for offset in range(0, 400, 100): # Pide hasta 400 registros en total (100 por página)
        url = f"{base_url}?limit=100&offset={offset}"
        try:
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            data = res.json()
            results = data.get("results", [])
            if not results: break
            all_data.extend(results)
        except requests.exceptions.RequestException as e:
            st.warning(f"⚠️ Error al obtener datos de Valenbisi (offset={offset}): {e}.")
            break 
        except Exception as e:
            st.error(f"❌ Error inesperado procesando datos de Valenbisi: {e}")
            return pd.DataFrame()

    if not all_data:
        st.error("❌ No se pudieron obtener datos de Valenbisi en ninguna petición.")
        return pd.DataFrame()
        
    df = pd.json_normalize(all_data)

    api_col_map = {
        "geo_point_2d.lat": "latitude", "geo_point_2d.lon": "longitude",
        "available": "bicis_disponibles", "name": "nombre_estacion_api", 
        "number": "numero_estacion", "address": "direccion_estacion",
        "total": "capacidad_total", "free": "bornes_libres",
        "status": "estado_estacion", "updated_at": "ultima_actualizacion"
    }
    
    cols_to_rename_present = {k: v for k, v in api_col_map.items() if k in df.columns}
    df.rename(columns=cols_to_rename_present, inplace=True)

    if 'nombre_estacion_api' in df.columns: df['nombre_estacion'] = df['nombre_estacion_api']
    elif 'numero_estacion' in df.columns: df['nombre_estacion'] = "Estación " + df['numero_estacion'].astype(str)
    else: df['nombre_estacion'] = "Estación Desconocida"
    if 'nombre_estacion_api' in df.columns: df.drop(columns=['nombre_estacion_api'], inplace=True, errors='ignore')

    essential_cols = ["latitude", "longitude", "bicis_disponibles", "nombre_estacion", "bornes_libres", "capacidad_total"]
    if not all(col in df.columns for col in essential_cols):
        missing = [col for col in essential_cols if col not in df.columns]
        st.error(f"❌ Faltan columnas Valenbisi post-procesado: {', '.join(missing)}. Disponibles: {list(df.columns)}")
        return pd.DataFrame()
        
    df = df.dropna(subset=["latitude", "longitude"])
    
    numeric_cols = ["bicis_disponibles", "bornes_libres", "capacidad_total"]
    for col in numeric_cols:
        if col in df.columns: df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0).astype(int)
        else: df[col] = 0 
            
    if "estado_estacion" in df.columns: df = df[df['estado_estacion'].astype(str).str.upper() == 'OPEN']
    
    final_desired_cols = ["nombre_estacion", "direccion_estacion", "latitude", "longitude", "bicis_disponibles", "bornes_libres", "capacidad_total", "ultima_actualizacion", "numero_estacion"]
    final_cols_to_select = [col for col in final_desired_cols if col in df.columns]
    final_df = df[list(set(final_cols_to_select))].reset_index(drop=True)

    if 'ultima_actualizacion' in final_df.columns:
        final_df['ultima_actualizacion'] = pd.to_datetime(final_df['ultima_actualizacion'], errors='coerce', utc=True).dt.strftime('%d/%m/%Y %H:%M')
    return final_df

@st.cache_data
def geocode_address(address):
    # ... (sin cambios)
    if not address: return None, None
    bounds = "-0.53,39.35,-0.25,39.60" 
    try:
        results = geocoder.geocode(address, bounds=bounds, limit=5, language='es', countrycode='ES', pretty=1, no_annotations=1)
        if results:
            for r in results:
                comp = r.get('components', {})
                city_type = comp.get('_type', '').lower()
                city_name = comp.get('city', comp.get('town', comp.get('municipality', ''))).lower()
                if 'valencia' in city_name and city_type in ['city', 'town', 'municipality']:
                    return r['geometry']['lat'], r['geometry']['lng']
            st.sidebar.warning(f"⚠️ Dirección '{address}' no confirmada en Valencia. Usando el resultado más relevante.")
            return results[0]['geometry']['lat'], results[0]['geometry']['lng']
        else:
            return None, None
    except Exception as e:
        st.sidebar.error(f"❌ Error geocodificando: {e}")
        return None, None


@st.cache_data
def get_route(start_coords, end_coords, profile='foot'):
    # ... (sin cambios, devuelve steps=[] )
    if not start_coords or not end_coords or start_coords == (None,None) or end_coords == (None,None):
        return None, 0, 0, []
    start_lon, start_lat = start_coords[1], start_coords[0]
    end_lon, end_lat = end_coords[1], end_coords[0]
    url = f"http://router.project-osrm.org/route/v1/{profile}/{start_lon},{start_lat};{end_lon},{end_lat}?overview=full&geometries=geojson&alternatives=false&steps=false"
    try:
        res = requests.get(url, timeout=12)
        res.raise_for_status()
        data = res.json()
        if data.get('routes') and len(data['routes']) > 0:
            route_geometry = data['routes'][0]['geometry']
            distance_km = data['routes'][0]['distance'] / 1000
            duration_min = data['routes'][0]['duration'] / 60
            return route_geometry, distance_km, duration_min, [] # Steps no son necesarios ahora
        else:
            return None, 0, 0, []
    except requests.exceptions.RequestException as e:
        st.warning(f"⚠️ Error conectando con OSRM ({profile}): {e}")
        return None, 0, 0, []
    except Exception as e:
        st.warning(f"⚠️ Error procesando ruta OSRM ({profile}): {e}")
        return None, 0, 0, []

@st.cache_data
def find_closest_stations_valenbisi(target_coords, estaciones_df, min_required=1, criteria_col="bicis_disponibles", n_stations=3):
    # ... (sin cambios)
    if target_coords == (None, None) or target_coords is None or estaciones_df.empty:
        return pd.DataFrame() 
    if criteria_col not in estaciones_df.columns:
        st.error(f"La columna criterio '{criteria_col}' no se encuentra en los datos de Valenbisi. Columnas disponibles: {list(estaciones_df.columns)}")
        return pd.DataFrame()
    estaciones_df[criteria_col] = pd.to_numeric(estaciones_df[criteria_col], errors='coerce').fillna(0)
    estaciones_validas = estaciones_df[estaciones_df[criteria_col] >= min_required].copy()
    if estaciones_validas.empty: return pd.DataFrame()
    estaciones_validas.dropna(subset=['latitude', 'longitude'], inplace=True)
    if estaciones_validas.empty: return pd.DataFrame()
    estaciones_validas['distancia_target'] = estaciones_validas.apply(
        lambda row: geodesic(target_coords, (row['latitude'], row['longitude'])).meters,
        axis=1
    )
    if estaciones_validas.empty or estaciones_validas['distancia_target'].empty:
        return pd.DataFrame()
    return estaciones_validas.sort_values(by='distancia_target').head(n_stations)

def find_nearby_pois(center_coords, all_pois_df, radius_km=0.75, exclude_name=""):
    # ... (sin cambios)
    if all_pois_df.empty or center_coords is None:
        return pd.DataFrame()
    nearby_pois_list = []
    for idx, poi in all_pois_df.iterrows():
        if pd.notna(poi['latitude']) and pd.notna(poi['longitude']):
            poi_coords = (poi['latitude'], poi['longitude'])
            distance = geodesic(center_coords, poi_coords).km
            if distance <= radius_km and poi['nombre_centro'] != exclude_name:
                poi_data = poi.to_dict()
                poi_data['distancia_al_centro_km'] = distance
                nearby_pois_list.append(poi_data)
    return pd.DataFrame(nearby_pois_list).sort_values(by='distancia_al_centro_km')

@st.cache_data(ttl=1800) 
def get_weather_valencia(api_key):
    # ... (sin cambios)
    if not api_key or api_key == "TU_CLAVE_OPENWEATHERMAP_AQUI":
        return None
    lat, lon = 39.4699, -0.3763
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={api_key}&units=metric&lang=es"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.sidebar.warning(f"🌦️ No se pudo obtener el tiempo: {e}")
        return None

def display_weather(weather_data):
    # ... (sin cambios)
    if weather_data and weather_data.get("weather") and weather_data.get("main"):
        description = weather_data["weather"][0]["description"].capitalize()
        temp = weather_data["main"]["temp"]
        icon_code = weather_data["weather"][0]["icon"]
        icon_url = f"http://openweathermap.org/img/wn/{icon_code}.png"
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"**Tiempo en Valencia:**")
        col1, col2 = st.sidebar.columns([1,3])
        with col1: st.image(icon_url, width=40)
        with col2: st.markdown(f"{description}<br>{temp}°C", unsafe_allow_html=True)
        st.sidebar.markdown("---")


# --- CARGA DE DATOS ---
centros_df_categorized = load_and_categorize_centros("v_infociudad.csv")
valenbisi_df_processed = get_valenbisi_data() 
weather_data = get_weather_valencia(OPENWEATHER_KEY)


# --- INTERFAZ USUARIO EN LA BARRA LATERAL ---
st.sidebar.image("https://upload.wikimedia.org/wikipedia/commons/thumb/e/e4/Valenbisi_logo.svg/1200px-Valenbisi_logo.svg.png", use_container_width=True)
if weather_data: display_weather(weather_data)
st.sidebar.header("⚙️ Configura tu Ruta")

# Preparar opciones para el selectbox de centros
opciones_centros_sidebar = [""] 
if not centros_df_categorized.empty:
    opciones_centros_sidebar.extend(sorted(list(centros_df_categorized['nombre_centro'].unique())))

# Determinar el índice por defecto para el centro cultural
default_centro_nombre = st.session_state.get('last_centro_nombre', "")
default_centro_idx = 0
if default_centro_nombre and default_centro_nombre in opciones_centros_sidebar:
    default_centro_idx = opciones_centros_sidebar.index(default_centro_nombre)

with st.sidebar.form(key="filters_form"):
    min_bicis_bornes_sidebar = st.slider("Mín. bicis/bornes en estación:", min_value=0, max_value=10, value=st.session_state.get('min_bicis_bornes', 1), step=1, help="Mínimo de bicis en origen Y bornes en destino. 0 para ruta directa en bici al centro.")
    user_address_sidebar = st.text_input("📍 Tu dirección en Valencia:", value=st.session_state.get('last_address', ""), placeholder="Ej: Calle Colón, 20")

    if not centros_df_categorized.empty:
        centro_sel_sidebar = st.selectbox("🏛️ Elige un centro cultural:", options=opciones_centros_sidebar, index=default_centro_idx)
    else:
        st.sidebar.error("❌ No se cargaron los centros culturales.")
        centro_sel_sidebar = None
    
    col_btn1, col_btn2 = st.columns(2)
    with col_btn1: submit_button_sidebar = st.form_submit_button(label="🚀 ¡Calcular!", use_container_width=True)
    with col_btn2: clear_button_sidebar = st.form_submit_button(label="🧹 Limpiar", use_container_width=True)

if clear_button_sidebar:
    st.session_state.last_address = ""
    st.session_state.last_centro_nombre = "" 
    st.session_state.min_bicis_bornes = 1
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.markdown(f"<p class='sidebar-footer'>CO₂ ahorrado en esta sesión: <br><strong>{st.session_state.total_co2_ahorrado_sesion:.3f} kg</strong></p>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p class='sidebar-footer'>Rutas calculadas: {st.session_state.get('rutas_calculadas_sesion', 0)}</p>", unsafe_allow_html=True)
st.sidebar.markdown("<hr class='sidebar-hr'>", unsafe_allow_html=True)
with st.sidebar.expander("ℹ️ Sobre Valenbisi", expanded=False):
    st.markdown("Valenbisi es el servicio público de alquiler de bicicletas de Valencia. Es una forma excelente y sostenible de moverse por la ciudad. Encuentra más en su [web oficial](https://www.valenbisi.es/).", unsafe_allow_html=True)
with st.sidebar.expander("🔗 Enlaces Útiles"):
    st.markdown("- [Agenda Cultural de Valencia (Ayto.)](https://www.valencia.es/cas/cultura)", unsafe_allow_html=True)
    st.markdown("- [Visit Valencia (Turismo)](https://www.visitvalencia.com/)", unsafe_allow_html=True)
st.sidebar.markdown("<p class='sidebar-footer'>Desarrollado con Streamlit.<br>Datos de Valenbisi y Ayto. Valencia.</p>", unsafe_allow_html=True)


# --- PESTAÑAS DE LA APLICACIÓN ---
# Corregido el nombre de la primera pestaña
tab1_title = "🗺️ Ruta Personalizada"
tab2_title = "💡 Sugerencias Culturales"
tab1, tab2 = st.tabs([tab1_title, tab2_title])


with tab1: 
    # Mapa interactivo inicial si no se ha calculado ruta
    if not submit_button_sidebar: # Mostrar solo si no se ha enviado el formulario de la sidebar
        st.info("👋 ¡Bienvenido! Introduce tu dirección, selecciona un centro cultural y pulsa '¡Calcular!' en la barra lateral para comenzar.")
        
        map_initial_coords = (39.4699, -0.3763) 
        m_interactive = folium.Map(location=map_initial_coords, zoom_start=13, tiles="CartoDB positron")
        # m_interactive.add_child(folium.LatLngPopup()) # Puede ser molesto
        LocateControl().add_to(m_interactive)
        Fullscreen().add_to(m_interactive)

        if not centros_df_categorized.empty:
            centros_cluster = MarkerCluster(name="Centros Culturales").add_to(m_interactive)
            for idx, row in centros_df_categorized.iterrows():
                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    tooltip=f"{row['nombre_centro']}\nCategoría: {row.get('categoria','N/A')}",
                    icon=folium.Icon(color="purple", icon="landmark", prefix="fa")
                ).add_to(centros_cluster)
        
        st.markdown("### 🗺️ Explora Valencia: Centros Culturales Disponibles")
        folium_static(m_interactive, height=450) # Usar folium_static para el mapa de bienvenida


    if submit_button_sidebar:
        st.session_state.last_address = user_address_sidebar
        st.session_state.last_centro_nombre = centro_sel_sidebar # Guardar nombre
        st.session_state.min_bicis_bornes = min_bicis_bornes_sidebar
        st.session_state.rutas_calculadas_sesion +=1

        if not user_address_sidebar: st.sidebar.error("⚠️ Introduce tu dirección.")
        elif not centro_sel_sidebar: st.sidebar.error("⚠️ Selecciona un centro cultural.")
        elif valenbisi_df_processed.empty or centros_df_categorized.empty: st.error("❌ Faltan datos esenciales. No se puede calcular la ruta.")
        else:
            with st.spinner("🌍 Geocodificando tu dirección..."):
                user_coords_val = geocode_address(user_address_sidebar)

            if user_coords_val == (None, None):
                st.error("❌ No se pudo geolocalizar tu dirección. Intenta ser más específico.")
            else:
                destino_info_val = centros_df_categorized[centros_df_categorized['nombre_centro'] == centro_sel_sidebar].iloc[0]
                destino_coords_val = (destino_info_val['latitude'], destino_info_val['longitude'])

                with st.spinner(f"🚲 Buscando estación origen con ≥ {min_bicis_bornes_sidebar} bicis..."):
                    estaciones_origen_candidatas = find_closest_stations_valenbisi(user_coords_val, valenbisi_df_processed, min_bicis_bornes_sidebar, "bicis_disponibles", n_stations=3)
                
                if estaciones_origen_candidatas.empty:
                    st.error(f"❌ No hay estaciones con al menos {min_bicis_bornes_sidebar} bicis cerca. Prueba con menos.")
                else:
                    estacion_origen_val = estaciones_origen_candidatas.iloc[0] 
                    estacion_origen_coords_val = (estacion_origen_val['latitude'], estacion_origen_val['longitude'])
                    
                    estacion_destino_val = None
                    estaciones_destino_candidatas = pd.DataFrame() 
                    ruta_a_pie_final_val, dist_a_pie_final_val, tiempo_a_pie_final_val, _ = None, 0, 0, []

                    if min_bicis_bornes_sidebar > 0:
                        with st.spinner(f"🅿️ Buscando estación destino con ≥ {min_bicis_bornes_sidebar} aparcamientos..."):
                            estaciones_destino_candidatas = find_closest_stations_valenbisi(destino_coords_val, valenbisi_df_processed, min_bicis_bornes_sidebar, "bornes_libres", n_stations=3)
                        if not estaciones_destino_candidatas.empty:
                            estacion_destino_val = estaciones_destino_candidatas.iloc[0]
                        else:
                            st.warning(f"⚠️ No se encontró estación destino con {min_bicis_bornes_sidebar} aparcamientos. Ruta en bici será directa al centro.")
                    
                    ruta_a_pie_inicio_osrm, dist_a_pie_inicio_osrm, tiempo_a_pie_inicio_osrm, _ = get_route(user_coords_val, estacion_origen_coords_val, profile='foot')

                    if estacion_destino_val is not None: 
                        estacion_destino_coords_val = (estacion_destino_val['latitude'], estacion_destino_val['longitude'])
                        ruta_bici_osrm_val, dist_bici_osrm_val, tiempo_bici_osrm_val, _ = get_route(estacion_origen_coords_val, estacion_destino_coords_val, profile='bike')
                        ruta_a_pie_final_val, dist_a_pie_final_val, tiempo_a_pie_final_val, _ = get_route(estacion_destino_coords_val, destino_coords_val, profile='foot')
                    else:
                        estacion_destino_coords_val = destino_coords_val 
                        ruta_bici_osrm_val, dist_bici_osrm_val, tiempo_bici_osrm_val, _ = get_route(estacion_origen_coords_val, destino_coords_val, profile='bike')
                    
                    st.markdown("## 🗺️ Tu Ruta Sugerida")
                    
                    if 'telefono_centro' in destino_info_val and pd.notna(destino_info_val['telefono_centro']) and str(destino_info_val['telefono_centro']).lower() not in ['nan', 'none', '']:
                        info_centro_str = f"📞 Teléfono: {str(destino_info_val['telefono_centro']).replace('.0','')}"
                    else:
                        info_centro_str = "📞 Teléfono no disponible."

                    with st.expander(f"ℹ️ Información del Destino: {destino_info_val['nombre_centro']}", expanded=True):
                        st.markdown(f"**Categoría:** {destino_info_val.get('categoria', 'N/A')}")
                        st.markdown(info_centro_str)
                        st.markdown(f"📍 **Coordenadas:** Lat: {destino_info_val['latitude']:.5f}, Lon: {destino_info_val['longitude']:.5f}")

                    pois_cercanos_df = find_nearby_pois(destino_coords_val, centros_df_categorized, radius_km=0.75, exclude_name=destino_info_val['nombre_centro'])

                    map_view, info_view = st.columns([3, 2]) 
                    with map_view:
                        # ... (código del mapa igual que v5)
                        folium_map_render = folium.Map(location=user_coords_val, zoom_start=14, tiles="OpenStreetMap") 
                        folium.TileLayer('CartoDB positron', name="Claro", show=True).add_to(folium_map_render)
                        folium.TileLayer('CartoDB dark_matter', name="Oscuro").add_to(folium_map_render)
                        folium.TileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', attr='Esri', name='Satélite (Esri)').add_to(folium_map_render)
                        LocateControl().add_to(folium_map_render)
                        Fullscreen().add_to(folium_map_render)

                        valenbisi_cluster_group = MarkerCluster(name="Todas las Estaciones Valenbisi", overlay=True, control=True, show=False).add_to(folium_map_render)
                        if not valenbisi_df_processed.empty:
                            for idx, row in valenbisi_df_processed.iterrows():
                                folium.Marker(location=[row['latitude'], row['longitude']], tooltip=f"{row.get('nombre_estacion', 'N/A')}<br>Bicis: {row.get('bicis_disponibles',0)} | Bornes: {row.get('bornes_libres',0)}",icon=folium.Icon(color="lightgray", icon_color="#666666", icon="bicycle", prefix="fa")).add_to(valenbisi_cluster_group)
                        
                        fg_rutas_principales = folium.FeatureGroup(name="Ruta Principal y Marcadores", show=True).add_to(folium_map_render)
                        folium.Marker(user_coords_val, tooltip="📍 Tu Ubicación", icon=folium.Icon(color="green", icon="street-view", prefix="fa")).add_to(fg_rutas_principales)
                        folium.Marker(estacion_origen_coords_val, tooltip=f"🚲 Est. Origen: {estacion_origen_val.get('nombre_estacion', 'N/A')}", icon=folium.Icon(color="blue", icon="bicycle", prefix="fa")).add_to(fg_rutas_principales)
                        if estacion_destino_val is not None: folium.Marker((estacion_destino_val['latitude'], estacion_destino_val['longitude']), tooltip=f"🅿️ Est. Destino: {estacion_destino_val.get('nombre_estacion', 'N/A')}", icon=folium.Icon(color="orange", icon="parking", prefix="fa")).add_to(fg_rutas_principales)
                        folium.Marker(destino_coords_val, tooltip=f"🏛️ {destino_info_val['nombre_centro']}", icon=folium.Icon(color="red", icon="university", prefix="fa")).add_to(fg_rutas_principales)

                        if ruta_a_pie_inicio_osrm: folium.GeoJson(ruta_a_pie_inicio_osrm, name="A pie a Est. Origen", style_function=lambda x: {"color": "#E74C3C", "weight": 5, "opacity": 0.8, "dashArray": "5, 5"}).add_to(fg_rutas_principales)
                        if ruta_bici_osrm_val: folium.GeoJson(ruta_bici_osrm_val, name="En Bici", style_function=lambda x: {"color": "#3498DB", "weight": 7, "opacity": 0.9}).add_to(fg_rutas_principales)
                        if ruta_a_pie_final_val and estacion_destino_val is not None: folium.GeoJson(ruta_a_pie_final_val, name="A pie a Destino Final", style_function=lambda x: {"color": "#F39C12", "weight": 5, "opacity": 0.8, "dashArray": "5, 5"}).add_to(fg_rutas_principales)
                        
                        if not pois_cercanos_df.empty:
                            fg_pois_cercanos = folium.FeatureGroup(name="Puntos de Interés Cercanos", show=False).add_to(folium_map_render)
                            for idx, poi in pois_cercanos_df.iterrows():
                                folium.Marker(location=[poi['latitude'], poi['longitude']], tooltip=f"{poi['nombre_centro']}<br>Dist: {poi['distancia_al_centro_km']:.2f} km", icon=folium.Icon(color="purple", icon="info-circle", prefix="fa")).add_to(fg_pois_cercanos)
                        
                        folium.LayerControl(collapsed=False).add_to(folium_map_render)
                        
                        bounds_points = [user_coords_val, estacion_origen_coords_val, destino_coords_val]
                        if estacion_destino_val is not None: bounds_points.append((estacion_destino_val['latitude'], estacion_destino_val['longitude']))
                        valid_bounds_points = [p for p in bounds_points if p and all(c is not None for c in p)]
                        if valid_bounds_points: folium_map_render.fit_bounds(valid_bounds_points, padding=(0.005, 0.005))
                        
                        folium_static(folium_map_render, height=600)

                    with info_view:
                        st.subheader("📝 Detalles del Viaje")
                        # ... (código de info_view igual que v6)
                        st.markdown(f"""<div class='result-card'><h4>🚶 Tramo 1: A Estación Valenbisi</h4><ul class='info-list'>
                            <li><strong>Estación Origen:</strong> {estacion_origen_val.get('nombre_estacion', 'N/A')}</li>
                            <li><strong>Dirección:</strong> {estacion_origen_val.get('direccion_estacion', 'N/A')}</li>
                            <li><strong>Distancia (ruta):</strong> {dist_a_pie_inicio_osrm:.2f} km</li>
                            <li><strong>Tiempo (ruta):</strong> {tiempo_a_pie_inicio_osrm:.0f} min</li>
                            <li><strong>Bicis allí:</strong> {estacion_origen_val.get('bicis_disponibles', 'N/A')} ({estacion_origen_val.get('capacidad_total','N/A')} total)</li>
                            <li><strong>Últ. Act.:</strong> {estacion_origen_val.get('ultima_actualizacion', 'N/A')}</li></ul></div>""", unsafe_allow_html=True)
                        
                        if not estaciones_origen_candidatas.empty and len(estaciones_origen_candidatas) > 1:
                            with st.expander("🥈🥉 Otras estaciones de origen cercanas"):
                                for idx, row in estaciones_origen_candidatas.iloc[1:].iterrows():
                                    st.markdown(f"- **{row.get('nombre_estacion','N/A')}**: {row.get('bicis_disponibles','N/A')} bicis ({geodesic(user_coords_val, (row['latitude'], row['longitude'])).km:.2f} km)")
                        
                        if estacion_destino_val is not None:
                            destino_bici_nombre_val = estacion_destino_val.get('nombre_estacion', destino_info_val['nombre_centro'])
                        else:
                            destino_bici_nombre_val = destino_info_val['nombre_centro']

                        st.markdown(f"""<div class='result-card'><h4>🚴 Tramo 2: En Bici</h4><ul class='info-list'>
                            <li><strong>Desde:</strong> {estacion_origen_val.get('nombre_estacion', 'N/A')}</li>
                            <li><strong>Hasta:</strong> {destino_bici_nombre_val}</li>
                            <li><strong>Distancia (ruta):</strong> {dist_bici_osrm_val:.2f} km</li>
                            <li><strong>Tiempo (ruta):</strong> {tiempo_bici_osrm_val:.0f} min</li>
                            {f"<li><strong>Bornes libres (est. destino):</strong> {estacion_destino_val.get('bornes_libres', 'N/A')} ({estacion_destino_val.get('capacidad_total','N/A')} total)</li>" if estacion_destino_val is not None else ""}
                            {f"<li><strong>Últ. Act. (est. destino):</strong> {estacion_destino_val.get('ultima_actualizacion', 'N/A')}</li>" if estacion_destino_val is not None else ""}
                            </ul></div>""", unsafe_allow_html=True)

                        if estacion_destino_val is not None and not estaciones_destino_candidatas.empty and len(estaciones_destino_candidatas) > 1 :
                            with st.expander("🥈🥉 Otras estaciones de destino cercanas"):
                                for idx, row in estaciones_destino_candidatas.iloc[1:].iterrows():
                                    st.markdown(f"- **{row.get('nombre_estacion','N/A')}**: {row.get('bornes_libres','N/A')} bornes ({geodesic(destino_coords_val, (row['latitude'], row['longitude'])).km:.2f} km del centro)")

                        total_dist_final = dist_a_pie_inicio_osrm + dist_bici_osrm_val
                        total_tiempo_final = tiempo_a_pie_inicio_osrm + tiempo_bici_osrm_val

                        if estacion_destino_val is not None and dist_a_pie_final_val > 0.01: 
                            st.markdown(f"""<div class='result-card'><h4>🚶 Tramo 3: Al Centro Cultural</h4><ul class='info-list'>
                                <li><strong>Desde:</strong> {estacion_destino_val.get('nombre_estacion', 'N/A')}</li>
                                <li><strong>Hasta:</strong> {destino_info_val['nombre_centro']}</li>
                                <li><strong>Distancia (ruta):</strong> {dist_a_pie_final_val:.2f} km</li>
                                <li><strong>Tiempo (ruta):</strong> {tiempo_a_pie_final_val:.0f} min</li></ul></div>""", unsafe_allow_html=True)
                            total_dist_final += dist_a_pie_final_val
                            total_tiempo_final += tiempo_a_pie_final_val
                        
                        st.markdown(f"<div class='summary-card'><h3>Resumen Total:</h3>"
                                    f"<p>👟 Distancia: <strong>{total_dist_final:.2f} km</strong></p>"
                                    f"<p>⏱️ Tiempo: <strong>{total_tiempo_final:.0f} minutos</strong></p></div>", 
                                    unsafe_allow_html=True)
                        
                        if dist_bici_osrm_val > 0:
                            CO2_POR_KM_COCHE_GRAMOS = 135 
                            ahorro_co2_gramos = dist_bici_osrm_val * CO2_POR_KM_COCHE_GRAMOS
                            ahorro_co2_kg = ahorro_co2_gramos / 1000
                            st.session_state.total_co2_ahorrado_sesion += ahorro_co2_kg
                            
                            CO2_ARBOL_DIA_KG = 0.060 
                            arboles_dia_equivalente = ahorro_co2_kg / CO2_ARBOL_DIA_KG

                            st.markdown(f"""
                            <div class='co2-card'>
                                <h4>🌿 ¡Tu Contribución Ecológica!</h4>
                                <p>Al elegir la bici para el tramo de {dist_bici_osrm_val:.2f} km, has evitado emitir aproximadamente:</p>
                                <p class='co2-main'><strong>{ahorro_co2_kg:.3f} kg de CO₂</strong></p>
                                <p>(Comparado con un viaje promedio en coche)</p>
                                <p>Esto equivale al trabajo de <strong>{arboles_dia_equivalente:.1f} árboles</strong> absorbiendo CO₂ durante un día.</p>
                                <p class='co2-thanks'>¡Gracias por un viaje más verde! 💚</p>
                            </div>
                            """, unsafe_allow_html=True)
                        
                        if not pois_cercanos_df.empty:
                            st.markdown("<div class='result-card'><h4><span class='icon'>✨</span> Cercanías del Destino</h4><ul class='info-list'>", unsafe_allow_html=True)
                            for idx, poi in pois_cercanos_df.head(3).iterrows():
                                poi_info_item = f"<li><strong>{poi['nombre_centro']}</strong> ({poi['distancia_al_centro_km']:.2f} km)"
                                if 'telefono_centro' in poi and pd.notna(poi['telefono_centro']) and str(poi['telefono_centro']).lower() != 'nan':
                                    poi_info_item += f" <br><span class='poi-phone'>📞 {str(poi['telefono_centro']).replace('.0','')}</span>"
                                poi_info_item += "</li>"
                                st.markdown(poi_info_item, unsafe_allow_html=True)
                            st.markdown("</ul></div>", unsafe_allow_html=True)


with tab2: # Sugerencias Culturales
    st.header("💡 Sugerencias Culturales y Descubrimientos")
    st.markdown("---")

    if not centros_df_categorized.empty:
        # 1. Sugerencia del Día
        st.subheader("🌟 Sugerencia del Día")
        today = date.today()
        seed_value = today.year * 1000 + today.timetuple().tm_yday 
        
        if today == date(2025, 5, 31):
             centro_sugerido_nombre = "MUSEO DE BELLAS ARTES DE VALENCIA"
             if centro_sugerido_nombre not in centros_df_categorized['nombre_centro'].values:
                 random.seed(seed_value)
                 sugerencia_dia = centros_df_categorized.sample(1, random_state=random.randint(0,10000)).iloc[0]
             else:
                 sugerencia_dia = centros_df_categorized[centros_df_categorized['nombre_centro'] == centro_sugerido_nombre].iloc[0]
        else:
            random.seed(seed_value) 
            sugerencia_dia = centros_df_categorized.sample(1, random_state=random.randint(0,10000)).iloc[0]

        st.markdown(f"<div class='suggestion-card'>", unsafe_allow_html=True)
        st.markdown(f"### {sugerencia_dia['nombre_centro']}")
        st.markdown(f"**Categoría:** {sugerencia_dia.get('categoria', 'N/A')}")
        if 'telefono_centro' in sugerencia_dia and pd.notna(sugerencia_dia['telefono_centro']) and str(sugerencia_dia['telefono_centro']).lower() not in ['nan', 'none', '']:
            st.markdown(f"📞 {str(sugerencia_dia['telefono_centro']).replace('.0','')}")
        
        if st.button(f"🗺️ Planificar ruta a {sugerencia_dia['nombre_centro']}", key=f"sugerencia_{sugerencia_dia['nombre_centro'].replace(' ', '_')}"):
            # Actualizar el session_state para el selectbox de la otra pestaña
            if sugerencia_dia['nombre_centro'] in opciones_centros_sidebar:
                 st.session_state.last_centro_nombre = sugerencia_dia['nombre_centro']
            st.rerun() # Rerun para que la tab1 se actualice con la selección
        st.markdown(f"</div>", unsafe_allow_html=True)
        st.markdown("---")

        # 2. Ruta Aleatoria
        st.subheader("🎲 ¿Indeciso? ¡Prueba una Ruta Aleatoria!")
        if st.button("✨ Generar Ruta Cultural Aleatoria"):
            centro_aleatorio = centros_df_categorized.sample(1).iloc[0]
            if centro_aleatorio['nombre_centro'] in opciones_centros_sidebar:
                st.session_state.last_centro_nombre = centro_aleatorio['nombre_centro']
            st.rerun()
        st.markdown("---")

        # 3. Estadísticas y Filtrado por Categoría
        st.subheader("📊 Explora por Categorías")
        categorias_unicas = sorted(centros_df_categorized['categoria'].unique())
        
        stats_cols = st.columns(len(categorias_unicas) if len(categorias_unicas) <=5 else 5) # Max 5 columnas para stats
        for i, cat in enumerate(categorias_unicas):
            count = len(centros_df_categorized[centros_df_categorized['categoria'] == cat])
            with stats_cols[i % len(stats_cols)]: # Distribuir en columnas
                st.metric(label=cat, value=count)
        
        st.markdown("#### Filtrar Centros por Categoría:")
        categoria_seleccionada_filtro = st.selectbox("", ["Todas"] + categorias_unicas, key="filtro_cat_sug")
        
        if categoria_seleccionada_filtro != "Todas":
            centros_a_mostrar = centros_df_categorized[centros_df_categorized['categoria'] == categoria_seleccionada_filtro]
        else:
            centros_a_mostrar = centros_df_categorized
        
        if not centros_a_mostrar.empty:
            # Usar columnas para mostrar los centros de forma más compacta
            num_items_por_col = (len(centros_a_mostrar) + 2) // 3 # Distribuir en 3 columnas
            cols_display_centros = st.columns(3)
            
            current_col_idx = 0
            for idx, row in centros_a_mostrar.iterrows():
                with cols_display_centros[current_col_idx % 3]:
                    container = st.container()
                    container.markdown(f"**{row['nombre_centro']}**")
                    if 'telefono_centro' in row and pd.notna(row['telefono_centro']) and str(row['telefono_centro']).lower() != 'nan':
                         container.caption(f"📞 {str(row['telefono_centro']).replace('.0','')}")

                    if container.button("📍 Planificar", key=f"plan_sug_{row['nombre_centro'].replace(' ', '_')}", use_container_width=True):
                        if row['nombre_centro'] in opciones_centros_sidebar:
                             st.session_state.last_centro_nombre = row['nombre_centro']
                        st.rerun()
                    container.markdown("---") # Separador entre items de la columna
                current_col_idx +=1
        else:
            st.write("No hay centros para la categoría seleccionada.")
    else:
        st.warning("No hay datos de centros culturales para mostrar sugerencias.")

# --- Lógica para el mapa inicial si no hay submit_button presionado
if not submit_button_sidebar:
    with tab1: # Mostrar mapa de bienvenida en la pestaña de ruta personalizada
        st.info("👋 ¡Bienvenido! Configura tu ruta en la barra lateral o explora los centros en el mapa y pulsa '¡Calcular!'.")
        
        map_initial_coords = (39.4699, -0.3763) 
        m_interactive = folium.Map(location=map_initial_coords, zoom_start=13, tiles="CartoDB positron")
        LocateControl().add_to(m_interactive)
        Fullscreen().add_to(m_interactive)

        if not centros_df_categorized.empty:
            centros_cluster_welcome = MarkerCluster(name="Centros Culturales").add_to(m_interactive)
            for idx, row in centros_df_categorized.iterrows():
                folium.Marker(
                    location=[row['latitude'], row['longitude']],
                    tooltip=f"{row['nombre_centro']}\nCategoría: {row.get('categoria','N/A')}",
                    icon=folium.Icon(color="purple", icon="landmark", prefix="fa")
                ).add_to(centros_cluster_welcome)
        
        st.markdown("### 🗺️ Mapa de Valencia: Centros Culturales Disponibles")
        folium_static(m_interactive, height=450)

        if valenbisi_df_processed.empty:
            st.error("⚠️ No se pudieron cargar los datos de Valenbisi. La aplicación puede no funcionar correctamente.")
        if centros_df_categorized.empty:
             st.error("⚠️ No se pudieron cargar los datos de los centros culturales.")

