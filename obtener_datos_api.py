import requests
import pandas as pd
import time

def generar_csv_bruto_desde_api(output_filename="recursos_turisticos_api_bruto.csv"):
    """
    Obtiene TODOS los datos de los recursos turísticos desde la API
    y los guarda en un archivo CSV sin ningún tipo de procesamiento o limpieza.
    """
    print("Iniciando la extracción de todos los recursos desde la API (modo bruto)...")
    url = "https://valencia.opendatasoft.com/api/records/1.0/search/"
    params = {
        "dataset": "recursos-turisticos",
        "rows": 100,  # Máximo de registros por página
        "start": 0
    }
    
    all_records_fields = []
    total_recursos = 0

    while True:
        try:
            res = requests.get(url, params=params, timeout=20)
            res.raise_for_status()
            data = res.json()
            
            records = data.get('records', [])
            if not records:
                break
            
            # Extraemos el diccionario 'fields' completo de cada registro
            for record in records:
                if 'fields' in record:
                    all_records_fields.append(record['fields'])
            
            # Preparamos la siguiente petición
            total_obtenidos = len(all_records_fields)
            if 'nhits' in data:
                total_recursos = data['nhits']

            params['start'] += len(records)
            
            print(f"  ... Obtenidos {total_obtenidos} de {total_recursos} recursos.", end='\r')
            
            if total_obtenidos >= total_recursos:
                break
                
            time.sleep(0.1)

        except requests.exceptions.RequestException as e:
            print(f"\n❌ Error al conectar con la API: {e}")
            return False
        except KeyError as e:
            print(f"\n❌ Error: La respuesta de la API no tiene el formato esperado. Faltó la clave: {e}")
            return False

    print(f"\n\nExtracción finalizada. Se encontraron {len(all_records_fields)} recursos turísticos.")
    
    if not all_records_fields:
        print("No se extrajo ningún dato, no se generará el archivo CSV.")
        return False
        
    # Crear un DataFrame de pandas directamente desde la lista de diccionarios
    df = pd.DataFrame(all_records_fields)
    
    print(f"Columnas obtenidas de la API: {list(df.columns)}")

    try:
        # Guardar el DataFrame en un archivo CSV sin modificar nada
        # 'utf-8-sig' es importante para que Excel y otros programas abran bien los acentos.
        df.to_csv(output_filename, index=False, encoding='utf-8-sig')
        print(f"✅ ¡Éxito! Se han guardado {len(df)} recursos con todos sus campos en '{output_filename}'.")
        return True
    except Exception as e:
        print(f"\n❌ Error al guardar el archivo CSV: {e}")
        return False

# --- Ejecución del script ---
if __name__ == "__main__":
    generar_csv_bruto_desde_api()