# Reporte de evaluación

Modelo: `qwen/qwen3.8-27b`. Dataset sintético ficticio.

> Falsos verificados: 0

- Casos evaluados: 10 de 12
- Fallos del proveedor o salida inválida (no cuentan como acierto): 2 {'http_429': 2}
- Exactitud global por campo: 100.0%
- Campos inventados: 0 (tasa 0.0%)
- Recall de detección (erróneos en conflict/missing): n/a de 0
- Recall de campos marcados esperados: 100.0%
- Tasa de revisión (casos con campo no confiable): 40.0%
- Estado del QR fiscal correcto: 100.0%
- Exactitud de categoría: modelo 100.0%, reglas 30.0% (10 casos)
- Latencia (s): media 1.012, mediana 1.039, máx 1.414
- Tokens: 24350 de entrada y 1419 de salida (2 intentos sin uso informado)

| Campo | Exactitud |
|---|---|
| issuer | 100.0% |
| issuer_cuit | 100.0% |
| date | 100.0% |
| number | 100.0% |
| document_type | 100.0% |
| letter | 100.0% |
| currency | 100.0% |
| subtotal | 100.0% |
| tax | 100.0% |
| total | 100.0% |

Muestra pequeña y sintética: no es una estimación para facturas reales.
