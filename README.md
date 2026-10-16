# ExpenseLens

Aplicación de portfolio para extraer datos de recibos y facturas, validar
inconsistencias y revisarlos antes de exportar. La IA interpreta; el código
calcula; la persona aprueba.

**Estado actual:** API FastAPI y frontend React + TypeScript para cargar archivos
JPEG, PNG y PDF, extraer datos, corregirlos y validar importes antes de la revisión
humana. Incluye vista previa, consentimiento explícito, ejemplos ficticios y pruebas
automatizadas. No guarda comprobantes ni ofrece historial o exportación CSV.
La extracción de imágenes y PDF con Groq está implementada y deshabilitada por
defecto. La [primera prueba real](eval/results/smoke-001/README.md) obtuvo dos
respuestas correctas y dos límites HTTP 429; no se reintentaron los fallos.

## Ejecutar localmente

Requisitos: Python 3.12 o superior y [uv](https://docs.astral.sh/uv/).
Desde esta carpeta:

```bash
uv sync --locked
uv run --env-file .env uvicorn expense_lens.main:app --reload --host 127.0.0.1
```

- Salud: <http://127.0.0.1:8000/health>
- Documentación interactiva: <http://127.0.0.1:8000/docs>
- Contrato OpenAPI: <http://127.0.0.1:8000/openapi.json>

`GET /health` devuelve:

```json
{"status":"ok","service":"expense-lens"}
```

Es una comprobación de respuesta de la API, no de servicios externos.
Servidor local de desarrollo: no desplegar públicamente como está.

### Interfaz web

En otra terminal, desde esta carpeta:

```bash
cd web
npm ci
npm run dev
```

Abrí <http://127.0.0.1:5173> con la API ejecutándose en el puerto 8000.
Vite reenvía `/receipts` a la API local. Seleccioná un archivo, revisá la vista
previa y aceptá el procesamiento externo antes de extraer. Después podés corregir
los campos y usar **Validar correcciones**, que no llama a Groq.

El arranque anterior deja la extracción deshabilitada. Para habilitarla
explícitamente, reemplazá el comando del servidor por:

```bash
EXPENSE_LENS_ENABLE_GROQ=1 uv run --env-file .env uvicorn expense_lens.main:app --reload --host 127.0.0.1
```

Cada extracción autorizada puede consumir cuota del proveedor. El consentimiento
no se conserva al cambiar de archivo. Más detalles en [web/README.md](web/README.md).

### Proveedor seleccionado: Groq

El `.env` local contiene `GROQ_API_KEY`, reutilizada de InboxOps con autorización.
Está ignorado por Git y no debe publicarse. En otra instalación, crear `.env`
localmente y configurar esa variable sin pegar su valor en documentación o logs.
El comando de arranque usa `uv --env-file` para cargarla en el proceso.

Se verificó su carga sin mostrar la clave ni hacer llamadas al proveedor.
La clave sola no habilita extracción: se requiere `EXPENSE_LENS_ENABLE_GROQ=1`
en el entorno del servidor, además del consentimiento explícito por solicitud.

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
Se usa JSON mode, no una garantía de esquema: se exigen las siete claves y se
valida con Pydantic antes de las reglas monetarias. Datos desconocidos quedan
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

## Validar un comprobante

`POST /receipts/validate` recibe datos ya normalizados; no una imagen ni un PDF.
Podés probarlo desde `/docs` con este ejemplo ficticio:

```json
{
  "issuer": "Comercio ficticio",
  "date": "2026-10-15",
  "number": "0001-00000001",
  "currency": "ARS",
  "subtotal": "100.00",
  "tax": "21.00",
  "total": "121.00"
}
```

- Primer alcance: ARS y comprobantes simples sin descuentos, retenciones ni
  cargos adicionales. `tax` representa el total de impuestos separado del subtotal.
  No es una validación fiscal ni cubre todos los formatos de factura argentina.
- Importes como **strings** con punto decimal: hasta 10 dígitos enteros y 2
  decimales. No se admiten números JSON, negativos, coma, notación científica
  ni redondeos implícitos. Los cálculos usan `Decimal`.
- Todos los campos pueden omitirse o ser `null`: quedan ausentes y generan
  `missing_field`. Cero es un importe válido, no un faltante.
- Si están los tres importes, se compara `subtotal + tax == total` exactamente;
  una diferencia genera `total_mismatch`, sin modificar el total.
- La respuesta 200 incluye `receipt`, `issues` y `requires_human_review: true`,
  incluso cuando no se detectan problemas. No se guarda ni aprueba nada.
- Datos mal formados y campos desconocidos devuelven 422. La fecha debe ser una
  fecha válida; no se verifica su autenticidad. Los textos se recortan en sus
  extremos y deben contener entre 1 y 200 caracteres.

Que los importes cierren no demuestra que coincidan con el documento original.

## Verificar

Ejecutar desde `expense-lens/`, no desde el directorio de estudio padre.

```bash
uv run pytest -q
uv run ruff check src tests examples
uv run ruff format --check src tests examples
(cd web && npm test && npm run build)
```

El primer test se ejecutó antes de crear el módulo de la API: falló por módulo
ausente (RED); con la implementación pasa (GREEN).
La combinación actual de Starlette y httpx emite una advertencia de deprecación
del cliente de pruebas; no afecta el resultado y no se oculta.

Para el editor, abrir esta carpeta y seleccionar `.venv/bin/python`.
`pyrightconfig.json` declara ese entorno y `src` como ruta de imports. El LSP
iniciado desde el workspace padre puede seguir sin reconocerlos; durante este
incremento reportó imports faltantes, aunque la suite en el entorno uv pasa.
No se considera un typecheck limpio ni se suprimen esos diagnósticos.

## Diseño incremental

| Área | Decisión |
|---|---|
| API | Python + FastAPI; contratos con Pydantic. |
| Coordinación prevista | Pipeline explícito, sin LangChain ni LangGraph inicialmente. |
| Extracción | SDK Groq, `qwen/qwen3.8-27b`, JPEG/PNG y PDF renderizado, opt-in. |
| Reglas actuales | Faltantes y suma exacta de importes con `Decimal`. |
| Interfaz | React + TypeScript + Vite; carga, vista previa y revisión manual. |

Flujo objetivo: cargar → extraer → normalizar → validar → revisar → exportar.
No se implementan capas vacías antes de necesitarlas.

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

## Próximos pasos

Completar la verificación del flujo en navegador antes de dar esa etapa por cerrada.
Persistencia, historial y exportación requieren definir su alcance. Cualquier nueva
tanda de llamadas reales será separada y acotada; los cuatro intentos originales
se conservan sin reescribir los errores ni tratarlos como respuestas correctas.
Mantener la ejecución local hasta aislar todos los parsers y completar los controles
de despliegue; WhatsApp y almacenamiento siguen fuera de este incremento.

Fuera del alcance inicial: pagos, recomendaciones tributarias, integraciones
bancarias y agentes autónomos. No subir comprobantes reales al repositorio;
`data/`, bases locales y archivos de entorno están excluidos por `.gitignore`.
