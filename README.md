# Sistema de Glosa Aduanal - Nivel Agencia

App web para glosa automática de pedimentos contra documentos soporte.

## Incluye

- Glosa comparativa contra PEDIMENTO.
- Revisión de factura, fecha, valor, moneda, incoterm.
- BL, contenedores, sellos y series.
- Peso bruto.
- Validaciones de incrementables para FOB.
- Detección de borrador sin validez.
- Reporte Excel.
- OCR opcional para PDFs escaneados.

## Opción recomendada de despliegue: Render

Render es más simple y estable para OCR que Streamlit Cloud.

### Archivos importantes

- app.py
- requirements.txt
- render.yaml
- Dockerfile

## Despliegue rápido en Render

1. Crea cuenta en https://render.com
2. Crea un repositorio en GitHub.
3. Sube estos archivos.
4. En Render: New + > Web Service.
5. Conecta el repositorio.
6. Si Render detecta `render.yaml`, acepta la configuración.
7. Deploy.

## Sin GitHub

Render normalmente trabaja mejor con GitHub. Si quieres evitarlo totalmente, usa Railway o un VPS; pero para operación diaria Render + GitHub es lo más simple y mantenible.

## Nota

El OCR consume más recursos. Para uso real de agencia, se recomienda plan Starter o superior.
