# ExpenseLens: documentación técnica

Detalle de contratos, límites y decisiones. La visión general está en el
[README](../README.md).

## Validar y normalizar un comprobante

`POST /receipts/validate` recibe la transcripción (del modelo o corregida por una
persona) y opcionalmente el QR fiscal devuelto por la extracción:

```json
{
  "receipt": {
    "issuer": "Comercio ficticio",
    "issuer_cuit": "30-00000000-7",
    "date": "15/10/2026",
    "number": "0001-00000001",
    "document_type": "factura",
    "letter": "A",
    "currency": "$",
    "subtotal": "1.000,00",
    "tax": "210,00",
    "total": "1.210,00"
  },
  "fiscal_qr": null
}
```

La respuesta incluye `receipt` normalizado (`"1210.00"`, `"2026-10-15"`,
`"30000000007"`, `"ARS"`), `issues` con `code`, `field` y `severity`,
`field_status` por campo, `movement` y `requires_human_review: true`.

### Normalización (`normalize.py`)

| Entrada | Resultado | Regla |
|---|---|---|
| `1.234,56`, `$ 1.234,56`, `1,234.56` | `1234.56` | El último separador con 1–2 dígitos es el decimal. |
| `1.234` o `1,234` | `null` + `ambiguous_amount` | Un solo grupo de tres dígitos puede ser miles o decimales: no se adivina. |
| `-150,00`, `(150,00)` | `150.00` | Importes absolutos; el signo lo da el tipo de comprobante. |
| `15/10/2026` | `2026-10-15` | Día primero, formato argentino. |
| `$` | `ARS` + `currency_inferred_from_symbol` (info) | En Argentina `$` es pesos, pero se informa la inferencia. |
| `US$`, `U$S` | `USD` | Nunca se convierte a pesos. |
| `30-00000000-7` | `30000000007` | Dígito verificador módulo 11; inválido queda `null` + `invalid_cuit`. |

### Reglas (`rules.py`)

| Código | Cuándo | Severidad |
|---|---|---|
| `missing_field` | Falta un campo requerido. Siempre: emisor, fecha, moneda, total. Facturas y notas: CUIT, número, letra. Factura A: subtotal e IVA. | warning |
| `tax_already_included` | `subtotal == total` con IVA > 0: el neto ya incluía el IVA. | warning |
| `total_below_subtotal` | El total es menor que el subtotal: probable confusión de campos. | warning |
| `total_mismatch` | `subtotal + tax != total`, exacto con `Decimal`. | warning |
| `subtotal_equals_total` | Subtotal igual al total sin IVA discriminado: suele ser una copia del total (hallazgo de `eval-002`). | warning |
| `unexpected_tax` | Factura C con IVA discriminado. | warning |
| `future_date` | Fecha posterior a hoy. | warning |
| `qr_mismatch` | El campo contradice el QR fiscal. | warning |
| `credit_note` | Nota de crédito: `movement = credit`, resta en lugar de sumar. | info |
| `foreign_currency` | USD o EUR: se conserva la moneda original. | info |

`field_status` resume cada campo: `verified` (coincide con el QR), `conflict`,
`missing`, `unverified` (leído por el modelo, sin segunda fuente) o `empty`.
Las reglas señalan; **nunca corrigen ni aprueban** datos.

## QR fiscal ARCA (`fiscal_qr.py`)

Las facturas electrónicas argentinas incluyen un QR (RG 4892/2020) con el texto
`https://www.arca.gob.ar/fe/qr/?p={JSON en Base64}`, según la
[especificación oficial](https://www.arca.gob.ar/fe/qr/documentos/QRespecificaciones.pdf).

- Se decodifica **localmente** con zxing-cpp antes de llamar al modelo, sobre
  los píxeles ya decodificados y validados (imagen o páginas PDF renderizadas).
- Se exige `https`, host `afip.gob.ar` o `arca.gob.ar`, ruta `/fe/qr/`,
  Base64 y JSON válidos, `ver = 1`, CUIT con dígito verificador correcto,
  importes numéricos con hasta dos decimales y tipo de autorización CAE/CAEA.
  Cualquier otro QR se informa como `fiscal_qr_status = invalid`.
- Se contrastan CUIT, fecha, punto de venta y número, tipo, letra, moneda y total.
  Coincidencia → `verified`; diferencia → `qr_mismatch`.
- El QR **no completa** campos vacíos ni reemplaza la lectura del documento:
  no contiene emisor, subtotal, impuestos ni conceptos. La interfaz ofrece usar
  su valor campo por campo, como acción explícita de la persona.
- Un QR válido no prueba que el comprobante sea auténtico: no se consulta a ARCA.

## Extraer un comprobante con Groq (opt-in, solo local)

`POST /receipts/extract` recibe JPEG, PNG o PDF como cuerpo binario, con los mismos
límites de inspección. Requiere el header `X-Allow-External-Processing: true`;
sin él devuelve 403. Con el proveedor deshabilitado o sin clave devuelve 503.
**Ese header expresa consentimiento, no es autenticación ni control de acceso.**

Al habilitarlo y usar ese endpoint, se envía la imagen completa a Groq, incluidos
los metadatos presentes. En PDF se envían imágenes renderizadas de todas sus páginas,
no el archivo original ni sus metadatos no visibles. Usar solo ejemplos ficticios o documentos cuyo envío
esté autorizado; no se ha evaluado aquí la política de retención del proveedor.
No habilitar logs de depuración del SDK/HTTP con documentos o claves reales.

El Adapter usa `qwen/qwen3.8-27b`, listado en la [documentación de visión de Groq](https://console.groq.com/docs/vision).
La cuenta respondió con ese modelo en JPEG y PDF con texto en la primera prueba.
PNG y PDF escaneado recibieron HTTP 429, no un resultado de extracción.
Se usa JSON mode, no una garantía de esquema: se exigen exactamente las diez
claves de `RawReceipt` y se validan con Pydantic. El modelo **transcribe** los
valores tal como aparecen (`"1.234,56"`, `"15/10/2026"`, `"$"`); normalizar,
calcular y validar es trabajo de código determinista. Datos desconocidos quedan
`null`; los importes no se corrigen. La revisión humana sigue siendo obligatoria.

Una solicitud realiza como máximo una llamada: sin retries ni reparación,
1024 tokens máximos de salida y timeout SDK de 20 segundos por operación de red
(no un límite total de duración de la petición). Errores 502/503/504 no incluyen
respuestas crudas del proveedor. Un HTTP 429 se distingue como
`503 provider_rate_limited`, sin reintentar. Los tests usan MockTransport y clave ficticia.

### PDF con texto o escaneado

Se renderizan todas las páginas en orden, sin extraer texto por un camino
alternativo. Se envían juntas en **una sola llamada**, con un único resultado
para el comprobante; nunca se suman automáticamente totales entre páginas.
Un archivo debe contener un único comprobante: el prompt pide no mezclar
identidades, pero no hay detección determinista de varios comprobantes.

- Hasta 3 páginas y 5 MiB de entrada; rechaza PDF cifrados.
- Renderizador PDFium en un proceso nuevo por documento, sin heredar claves
  ni variables del servidor. No se ejecuta PDFium simultáneamente en threads.
- Máximo 1400 píxeles por lado, 2 millones de píxeles por página y 5 MiB de JPEG
  generados en total; escala máxima 2 píxeles por punto. La reducción puede
  perder letras pequeñas: no demuestra exactitud de lectura.
- Proceso de render con timeout de 10 segundos. Fallos y timeout devuelven 422;
  exceso de geometría o salida devuelve 413. Se procesa todo antes de llamar a Groq.
- Se cierran páginas y bitmaps por página. No hay almacenamiento intermedio.

El presupuesto de píxeles limita los bitmaps solicitados, **no es un límite duro
de RAM del parser nativo**. El proceso separado limita su duración y evita el
uso concurrente de PDFium en threads, pero no constituye una sandbox. La inspección
previa con pypdf aún ocurre en el proceso servidor, sin timeout dedicado.
No hay persistencia.

## Inspeccionar un archivo (solo desarrollo local)

`POST /documents/inspect` recibe el **archivo como cuerpo binario**, no multipart,
JSON, base64 ni una URL. No confía en la extensión, nombre ni MIME declarado.
No escribe el documento a disco ni lo envía a terceros.

```bash
curl --fail-with-body http://127.0.0.1:8000/documents/inspect \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @examples/synthetic/receipt.png
```

Respuesta: `format` (`jpeg`, `png` o `pdf`), `size_bytes`, `pages` (solo PDF;
`null` para imagen) y `requires_human_review: true`. No hay campos extraídos.

| Control | Límite / comportamiento |
|---|---|
| Bytes reales | Máximo 5 MiB, comprobado durante recepción, sin confiar en Content-Length. |
| JPEG / PNG | Máximo 12 millones de píxeles; verifica y decodifica; rechaza animación. |
| PDF | Máximo 3 páginas; rechaza cifrados, documentos vacíos y estructura inválida detectable. |
| Errores | 413: exceso de límites; 415: formato no admitido; 422: vacío o inválido. |

En `/documents/inspect`, el PDF escaneado pasa la misma inspección estructural
que un PDF con texto. Ese endpoint no renderiza ni valida todos los streams: recibir 200
no garantiza que un PDF pueda renderizarse ni que sea seguro o contenga un recibo.
Un comprobante por archivo es una convención de uso, no una detección automática.

El límite de píxeles se comprueba antes de decodificar imágenes. El de páginas
requiere parsear el PDF. La inspección corre en un thread; solo el renderizado
PDF de extracción tiene proceso separado y timeout. **No hay sandbox, límite
duro de memoria ni control de concurrencia.** Antes de exposición pública o
WhatsApp se necesitan límites del servidor/proxy, aislamiento de todos los parsers,
timeout de recepción, autenticación y control de uso. No es antivirus ni sanitizador.

### Ejemplos ficticios

`examples/synthetic/` contiene el mismo recibo ficticio en PNG, JPEG y PDF
rasterizado (equivalente a escaneado), PDF con texto y un PDF inválido. Todos sin datos reales
ni validez fiscal; prueban ingreso, no calidad de OCR. Para regenerarlos:

```bash
uv run python examples/generate_receipts.py
```

## Canales de ingreso previstos

Separaremos el canal de ingreso del procesamiento:

```text
Web (primero) ────────────┐
                         ├─ validar archivo → extraer → validar datos → revisar
WhatsApp (futuro) ────────┘
```

El procesamiento no dependerá de objetos HTTP ni de mensajes de WhatsApp.
La futura integración será un Adapter de entrada, no otro extractor.
Por ahora no hay conexión, webhook, descarga ni envío de mensajes.

El contenido documental se tratará como dato no confiable, no como instrucciones
para el futuro modelo. No se habilitan ZIP, documentos Office ni URLs arbitrarias.

WhatsApp requerirá además autenticación del webhook, control de acceso a los
adjuntos, deduplicación de eventos y una política de retención y borrado.
El envío de comprobantes a un proveedor externo se informará explícitamente.
No implementar estos controles todavía no habilita un despliegue público.

