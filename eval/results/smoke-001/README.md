# Primera prueba real: dos respuestas y dos límites del proveedor

Se enviaron cuatro formatos del **mismo comprobante ficticio** a Groq, una vez
cada uno, sin retries ni reparación. No es un benchmark ni una estimación de
exactitud para facturas reales.

| Entrada | Resultado | Campos coincidentes |
|---|---|---|
| PNG | HTTP 429 del proveedor | No evaluables |
| JPEG | Respuesta válida | 7 de 7 |
| PDF con texto | Respuesta válida | 7 de 7 |
| PDF escaneado | HTTP 429 del proveedor | No evaluables |

Los fallos 429 no prueban problemas de lectura de esos formatos. Tampoco las dos
respuestas correctas prueban generalización: el contenido, formato y valores son
simples, sintéticos y equivalentes. No se probó extracción multipágina real.

## Evidencia

- `plan.json`: modelo, hash del prompt, hashes de entradas y valores esperados
  fijados antes de ejecutar.
- `attempts.jsonl`: cuatro intentos, latencias, errores sanitizados, respuestas
  validadas y uso informado. No contiene claves ni headers.
- Modelo que respondió: `qwen/qwen3.8-27b`.
- Tokens conocidos de dos respuestas: 4.128 de entrada y 198 de salida.
  El uso de los otros dos intentos es desconocido, no cero. Sin cálculo monetario.
- El runner terminó con exit 0 porque completó la captura, **no porque todas las
  llamadas fueran exitosas**. No se reintentaron ni reemplazaron los errores.

## Cambio derivado

Después de esta captura, HTTP 429 tiene un error distinguible:
`503 provider_rate_limited`. La evidencia original conserva `provider_error`,
que era el contrato al ejecutarla. La aplicación no reintenta automáticamente.

Continuar con carga, vista previa y revisión manual; ampliar la evaluación con
casos variados en otra tanda autorizada, sin reutilizar esto como un holdout.
