# Guía para subir la app a Render

## Por qué Render

Para esta app conviene Render porque:
- Soporta instalación de paquetes del sistema.
- Funciona mejor con OCR.
- Es más estable que Streamlit Cloud para apps pesadas.
- Puedes pagar un plan básico y dejar la app fija.

## Paso 1: Descomprimir

Descomprime el ZIP. Debes tener:

- app.py
- requirements.txt
- render.yaml
- Dockerfile
- README.md

## Paso 2: Crear cuenta en GitHub

Entra a:

https://github.com

Crea una cuenta si no tienes.

## Paso 3: Crear repositorio

1. Click en New repository.
2. Nombre sugerido:

glosa-agencia-aduanal

3. Déjalo Public o Private.
4. Click en Create repository.

## Paso 4: Subir archivos

1. En el repositorio, click en Upload files.
2. Arrastra todos los archivos descomprimidos.
3. Click en Commit changes.

## Paso 5: Crear cuenta en Render

Entra a:

https://render.com

Regístrate con GitHub.

## Paso 6: Crear Web Service

1. En Render, click en New +.
2. Selecciona Web Service.
3. Conecta tu repositorio `glosa-agencia-aduanal`.
4. Render debe detectar el archivo `render.yaml`.
5. Acepta la configuración.

Si te pide datos manuales:

- Environment: Python
- Build Command:

apt-get update && apt-get install -y poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-spa && pip install -r requirements.txt

- Start Command:

streamlit run app.py --server.port=$PORT --server.address=0.0.0.0

## Paso 7: Plan recomendado

Usa mínimo:

Starter

El plan gratuito puede dormirse o fallar con OCR.

## Paso 8: Deploy

Click en Deploy Web Service.

Al terminar, Render te dará un link parecido a:

https://glosa-agencia-aduanal.onrender.com

## Errores comunes

### Error: apt-get not allowed

Usa el Dockerfile. En Render selecciona Runtime Docker.

### Error: Tesseract not found

Revisa que el build command incluya:

tesseract-ocr

### Error: Poppler not found

Revisa que el build command incluya:

poppler-utils

### La app tarda en abrir

Es normal si usa OCR o si el plan es gratuito.

## Recomendación operativa

Para uso de agencia:
- Usa PDFs con texto seleccionable siempre que sea posible.
- Activa OCR solo para escaneados.
- Descarga el Excel y conserva evidencia por expediente.
