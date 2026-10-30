# Descargador de imágenes de productos

Aplicación creada con Python + Streamlit para:

- ingresar una URL de un sitio web o producto,
- detectar productos y sus imágenes,
- extraer en lote las imágenes de resultados de búsqueda (incluido SoloTodo),
- extraer información principal del producto,
- agrupar varias fotografías del mismo producto,
- guardar la información y las imágenes en una carpeta local.

## Requisitos

- Python 3.10+
- pip

## Instalación

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Ejecutar la app

```bash
streamlit run app.py
```

La interfaz estará disponible normalmente en:

```text
http://localhost:8501
```

## Salida

Las imágenes se guardan dentro de la carpeta `downloads/` y se organiza por producto.
Desde la interfaz también se pueden descargar todas juntas en un archivo ZIP.

Además, la app genera un archivo JSON con los detalles detectados:

```text
downloads/productos_extraidos.json
```

> En algunos sitios la información puede necesitar ajustes si la estructura HTML no expone datos con JSON-LD o metadatos claros.
