import streamlit as st
import pandas as pd
import requests
import folium
from streamlit_folium import folium_static
from geopy.distance import geodesic
from opencage.geocoder import OpenCageGeocode

# CONFIGURACIÓN DE LA PÁGINA
st.set_page_config(page_title="Ruta sociocultural con Valenbisi", layout="wide")
st.markdown('''
<p style="font-size:28px;">
  🚲🏛&nbsp;&nbsp;&nbsp;<span style="font-weight:bold;">
  Explora <span style="color:#007BFF;">Va</span><span style="color:red;">l</span><span style="color:gold;">e</span><span style="color:red;">n</span><span style="color:gold;">c</span><span style="color:red;">i</span><span style="color:gold;">a</span> con una ruta 
  <span style="text-decoration:underline;">sociocultural</span> y 
  <span style="text-decoration:underline;">sostenible</span> en Valenbisi
  </span>
</p>
''', unsafe_allow_html=True)




# DESCRIPCIÓN DE LA APLICACIÓN
st.markdown("""
Esta app te ayuda a planificar una ruta **sociocultural**:
- Desde tu ubicación actual
- Hasta un centro social o cultural de interés en la ciudad Valencia
- Combinando trayectos óptimos en tiempos y distancias
- Utilizando la red de **Valenbisi** para fomentar el uso de la bicicleta e incentivar el deporte
- Promoviendo la movilidad sostenible y el acceso a la cultura
""")


# CLAVE DE OPENCAGE
OPENCAGE_KEY = "dc45bcf2743f475e93dce4021b6a3982"
geocoder = OpenCageGeocode(OPENCAGE_KEY)

# CARGA CENTROS CULTURALES
@st.cache_data
def load_centros(filepath):
    df = pd.read_csv(filepath)
    df.columns = df.columns.str.strip()
    df = df.dropna(subset=['x', 'y'])
    import pyproj
    transformer = pyproj.Transformer.from_crs("EPSG:25830", "EPSG:4326", always_xy=True)
    df['lon'], df['lat'] = transformer.transform(df['x'].astype(float).values, df['y'].astype(float).values)
    return df[['equipamien', 'lat', 'lon']]

# CARGA ESTACIONES VALENBISI
def get_valenbisi_data():
    base_url = "https://valencia.opendatasoft.com/api/explore/v2.1/catalog/datasets/valenbisi-disponibilitat-valenbisi-dsiponibilidad/records"
    all_data = []
    for offset in [0, 100, 200]:
        url = f"{base_url}?limit=100&offset={offset}"
        res = requests.get(url)
        if res.status_code == 200:
            data = res.json()
            results = data.get("results", [])
            all_data.extend(results)
        else:
            st.error(f"No se pudo obtener información de Valenbisi (offset={offset})")
            return pd.DataFrame()

    df = pd.json_normalize(all_data)
    df = df.dropna(subset=["geo_point_2d.lat", "geo_point_2d.lon", "available", "free"])
    return df

# GEOCODIFICACIÓN
def geocode_address(address):
    bounds = "-0.460,39.405,-0.290,39.530"
    results = geocoder.geocode(address, bounds=bounds, limit=5)
    for result in results:
        components = result.get('components', {})
        if any(val.lower() == 'valencia' for key, val in components.items() if key in ['city', 'town', 'municipality']):
            return result['geometry']['lat'], result['geometry']['lng']
    if results:
        return results[0]['geometry']['lat'], results[0]['geometry']['lng']
    return None, None

# RUTA EN BICI (usando OSRM)
def get_bike_route(start, end):
    url = f"http://router.project-osrm.org/route/v1/bike/{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson"
    res = requests.get(url)
    if res.status_code == 200:
        data = res.json()
        route = data['routes'][0]['geometry']
        dist = data['routes'][0]['distance'] / 1000
        time = data['routes'][0]['duration'] / 60
        return route, dist, time
    return None, None, None

# ENCONTRAR ESTACIÓN MÁS CERCANA
def find_station_near(coord, estaciones, min_unidades=1, tipo="origen"):
    if tipo == "origen":
        estaciones_filtradas = estaciones[estaciones['available'] >= min_unidades]
    else:
        estaciones_filtradas = estaciones[estaciones['free'] >= min_unidades]

    if estaciones_filtradas.empty:
        return None

    estaciones_filtradas['lat'] = estaciones_filtradas['geo_point_2d.lat']
    estaciones_filtradas['lon'] = estaciones_filtradas['geo_point_2d.lon']
    estaciones_filtradas['distancia'] = estaciones_filtradas.apply(
        lambda row: geodesic(coord, (row['lat'], row['lon'])).meters,
        axis=1
    )
    return estaciones_filtradas.loc[estaciones_filtradas['distancia'].idxmin()]

# CARGA DE DATOS
centros = load_centros("v_infociudad.csv")

# Filtrar centros no deseados
centros = centros[~centros['equipamien'].str.contains("ESTANCO|QUIOSCO", case=False, na=False)]

# Cargar datos de Valenbisi
estaciones = get_valenbisi_data()

# PARÁMETROS DE BÚSQUEDA
st.sidebar.header("⚙️ Parámetros")
min_bikes = st.sidebar.slider("¿Cuántas personas sois?", help="Se necesita una bici por persona", min_value=1, max_value=20, value=1)
st.sidebar.markdown("")
st.sidebar.markdown("")
st.sidebar.markdown(
    "La aplicación encuentra automáticamente: \n"
    "- La estación Valenbisi **más cercana a ti** con al menos **{0} bici(s) disponible(s)** \n"
    "- La estación **más cercana a tu destino** con al menos **{0} plaza(s) libre(s) de aparcamiento** \n\n"
    "Todo adaptado al número de personas que viajáis juntas (Número de bicicletas)."
    .format(min_bikes)
)


# DIRECCIÓN Y DESTINO
st.subheader("📍 Punto de partida y destino")
user_dir = st.text_input("Dirección actual", placeholder="Ejemplo: Calle de Benidorm")
centro_seleccionado = st.selectbox("Centro cultural de destino", centros['equipamien'].dropna().unique())

# EJECUCIÓN
if user_dir and centro_seleccionado:
    with st.spinner("🔍 Calculando la mejor ruta..."):
        user_coords = geocode_address(user_dir)
        if user_coords == (None, None):
            st.error("❌ Dirección no encontrada.")
        else:
            destino = centros[centros['equipamien'] == centro_seleccionado].iloc[0]
            destino_coords = (destino['lat'], destino['lon'])

            estacion_origen = find_station_near(user_coords, estaciones, min_bikes, tipo="origen")
            estacion_destino = find_station_near(destino_coords, estaciones, min_bikes, tipo="destino")

            if estacion_origen is None or estacion_destino is None:
                st.error("🚫 No hay estaciones adecuadas con bicis o plazas disponibles.")
            else:
                coords_origen = (estacion_origen['lat'], estacion_origen['lon'])
                coords_destino = (estacion_destino['lat'], estacion_destino['lon'])

                # Tramos a pie (líneas rectas)
                dist_pie1 = geodesic(user_coords, coords_origen).km
                time_pie1 = dist_pie1 / 5 * 60
                dist_pie2 = geodesic(coords_destino, destino_coords).km
                time_pie2 = dist_pie2 / 5 * 60

                # Tramo en bici
                ruta_bici, dist_bici, time_bici = get_bike_route(coords_origen, coords_destino)

                co2_ahorrado = dist_bici * 120 * min_bikes  # 120 gCO2/km/persona

                # MAPA
                m = folium.Map(location=user_coords, zoom_start=14)
                folium.Marker(user_coords, tooltip="Tú", icon=folium.Icon(color="green")).add_to(m)
                folium.Marker(coords_origen, tooltip=f"Salida: {estacion_origen['address']}", icon=folium.Icon(color="blue")).add_to(m)
                folium.Marker(coords_destino, tooltip=f"Llegada: {estacion_destino['address']}", icon=folium.Icon(color="orange")).add_to(m)
                folium.Marker(destino_coords, tooltip=centro_seleccionado, icon=folium.Icon(color="red")).add_to(m)

                # Camino a pie (inicio)
                folium.PolyLine(
                    [user_coords, coords_origen],
                    color="purple", weight=6, dash_array="10,10",
                    tooltip="Camino a pie (origen)"
                ).add_to(m)

                # Ruta en bici
                if ruta_bici:
                    folium.GeoJson(ruta_bici, name="Ruta en bici", style_function=lambda x: {
                        "color": "#0044ff", "weight": 7, "opacity": 0.9
                    }).add_to(m)

                # Camino a pie (final)
                folium.PolyLine(
                    [coords_destino, destino_coords],
                    color="purple", weight=6, dash_array="10,10",
                    tooltip="Camino a pie (destino)"
                ).add_to(m)


                st.subheader("📍 Resultados de la ruta")

                st.success(f"""
🅿️ **Estación de Valenbisi más cercana a tu ubicación:** Estación {estacion_origen['address']}  
  🚲 Bicis disponibles: **{estacion_origen['available']}**

🅿️ **Estación de Valenbisi más cercana al destino deseado:** Estación {estacion_destino['address']}  
  🔎 Plazas libres de estacionamiento: **{estacion_destino['free']}**

---

### 🚶‍♂️ Tramo a pie desde tu ubicación hasta la estación Valenbisi más cercana
| 📍 Desde | {user_dir} |
|---------|------------|
| 📌 Hasta | Estación {estacion_origen['address']} |
| 📏 Distancia | **{dist_pie1:.2f} km** |
| ⏱️ Tiempo estimado | **{time_pie1:.1f} min** |

---

### 🚴‍♀️ Tramo en bici entre las estaciones Valenbisi de salida y llegada
| 📍 Desde | Estación {estacion_origen['address']} |
|---------|------------------------------|
| 📌 Hasta | Estación {estacion_destino['address']} |
| 📏 Distancia | **{dist_bici:.2f} km** |
| ⏱️ Tiempo estimado | **{time_bici:.1f} min** |

---

### 🚶‍♀️ Tramo a pie desde la estación Valenbisi de llegda hasta el destino deseado
| 📍 Desde | Estación {estacion_destino['address']} |
|---------|-------------------------------|
| 📌 Hasta | {destino['equipamien']} |
| 📏 Distancia | **{dist_pie2:.2f} km** |
| ⏱️ Tiempo estimado | **{time_pie2:.1f} min** |

---

🌍 **CO₂ evitado:** **{co2_ahorrado:.0f} g**      (para {min_bikes} persona/s en bici)\n
📎 Basado en una media de **110–158 g CO₂/km** emitidos por vehículos de gasolina o diésel.
""")

                st.subheader("🗺️ Mapa de la ruta")
                folium_static(m)
