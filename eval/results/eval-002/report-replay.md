# Reporte de evaluación

Reglas reaplicadas offline sobre las transcripciones guardadas; el modelo no se volvió a llamar.

Modelo: `qwen/qwen3.8-27b`. Dataset sintético ficticio.

> Falsos verificados: 0

- Casos evaluados: 9 de 12
- Fallos del proveedor o salida inválida (no cuentan como acierto): 3 {'http_429': 3}
- Exactitud global por campo: 96.7%
- Campos inventados: 3 (tasa 16.7%)
- Recall de detección (erróneos en conflict/missing): 100.0% de 3
- Recall de campos marcados esperados: 100.0%
- Tasa de revisión (casos con campo no confiable): 66.7%
- Estado del QR fiscal correcto: 100.0%
- Latencia (s): media 1.666, mediana 1.225, máx 7.831
- Tokens: 21414 de entrada y 1272 de salida (3 intentos sin uso informado)

| Campo | Exactitud |
|---|---|
| issuer | 100.0% |
| issuer_cuit | 100.0% |
| date | 100.0% |
| number | 100.0% |
| document_type | 100.0% |
| letter | 100.0% |
| currency | 100.0% |
| subtotal | 66.7% |
| tax | 100.0% |
| total | 100.0% |

Muestra pequeña y sintética: no es una estimación para facturas reales.
