# 🚲 Ruta Cultural Valenbisi

Esta aplicación web, desarrollada con Streamlit, te ayuda a planificar tus visitas culturales por Valencia de la forma más sostenible y eficiente: en bici. Combina datos en tiempo real de la disponibilidad de Valenbisi con un listado de puntos de interés cultural para crear rutas inteligentes y personalizadas.


## ¿Qué puedes hacer con esta app?

### 1. Ruta a un Destino
- **¿Quieres ir a un museo o monumento concreto?**  
  1. Introduce tu ubicación y el punto de interés al que quieres ir.  
  2. La app calcula la ruta óptima usando Valenbisi:  
     - Te indica la estación más cercana con bicis disponibles.  
     - Traza la ruta en bici hasta la estación más cercana a tu destino con aparcamientos libres.  
     - Calcula los tramos que debes hacer a pie.  
  3. Si el destino está a menos de 500 m, te recomendará ir andando directamente.

### 2. Planificador de Tour Interactivo
- **¿Te apetece un día completo de cultura?**  
  1. Elige un punto de partida y todos los destinos que te gustaría visitar.  
  2. La aplicación calcula el orden de visita más eficiente para minimizar tus desplazamientos y te muestra una vista previa del recorrido.  
  3. Al empezar el tour, la app se convierte en una guía interactiva, etapa por etapa:  
     - En cada paso, recalcula en tiempo real la mejor ruta con Valenbisi desde tu ubicación actual hasta el siguiente punto.  
     - Siempre tendrás la información más actualizada.  
  4. Al terminar, obtendrás un resumen de tu hazaña:  
     - Distancia recorrida  
     - CO₂ ahorrado  
     - Estimación de calorías quemadas

## Tecnologías y Datos

- **Framework:** Streamlit  
- **Mapas:** Folium (con OpenStreetMap y otras capas base)  
- **Geocodificación:** OpenCage Geocoder  
- **Cálculo de Rutas:** Project OSRM  

**Datos utilizados:**  
- Disponibilidad de Valenbisi: Open Data València  
- Puntos de Interés Cultural: CSV propio con datos de la ciudad desde la API de opendatasoft

## Cómo ejecutar la aplicación localmente

1. **Clona el repositorio**  
   ```bash
   git clone https://github.com/juanmartineezz/edm-project
 
## Cómo ejecutar la aplicación localmente

1. **Instala las dependencias**  
   Se recomienda usar un entorno virtual:
   ```bash
   python -m venv venv
   source venv/bin/activate   # En Windows: venv\Scripts\activate
   pip install -r requirements.txt
## Configura tus claves de API

El código necesita una clave de API de OpenCage para la geocodificación.  
Abre `app.py` y reemplaza el valor de `OPENCAGE_KEY`:

```python
# En app.py
OPENCAGE_KEY = "TU_CLAVE_DE_OPENCAGE_AQUI"

## Ejecuta la app

```bash
streamlit run app.py
## Abre tu navegador

Visita [http://localhost:8501](http://localhost:8501) y ¡empieza a pedalear!

