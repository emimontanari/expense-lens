"""API local: inspección, validación y extracción Groq explícitamente habilitada."""

from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from expense_lens.documents import (
    MAX_BYTES,
    DocumentError,
    DocumentInspection,
    inspect_document,
)
from expense_lens.extraction import ExtractionError, extract_document_receipt
from expense_lens.receipts import Receipt, ReceiptValidation, validate_receipt

app = FastAPI(
    title="ExpenseLens",
    version="0.1.0",
    description="Extracción y revisión humana de recibos y facturas.",
)


class HealthResponse(BaseModel):
    status: str
    service: str


@app.get("/health", response_model=HealthResponse, tags=["health"])
def health() -> HealthResponse:
    """Confirma que la API responde, no la disponibilidad de futuros proveedores."""
    return HealthResponse(status="ok", service="expense-lens")


@app.post("/receipts/validate", response_model=ReceiptValidation, tags=["receipts"])
def check_receipt(receipt: Receipt) -> ReceiptValidation:
    """Valida datos normalizados sin guardarlos ni aprobarlos."""
    return validate_receipt(receipt)


async def read_document_bytes(request: Request) -> bytes:
    """Recibe bytes crudos (no multipart); limita antes de invocar los parsers."""
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > MAX_BYTES:
            raise HTTPException(status_code=413, detail="document_too_large")
        data.extend(chunk)
    return bytes(data)


@app.post("/documents/inspect", response_model=DocumentInspection, tags=["documents"])
async def check_document(request: Request) -> DocumentInspection:
    data = await read_document_bytes(request)
    try:
        return await run_in_threadpool(inspect_document, data)
    except DocumentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


@app.post("/receipts/extract", response_model=ReceiptValidation, tags=["receipts"])
async def extract_receipt(request: Request) -> ReceiptValidation:
    """Envía imagen o páginas PDF solo con consentimiento y configuración explícitos."""
    if request.headers.get("X-Allow-External-Processing") != "true":
        raise HTTPException(
            status_code=403, detail="external_processing_consent_required"
        )
    data = await read_document_bytes(request)
    try:
        return await run_in_threadpool(extract_document_receipt, data)
    except (DocumentError, ExtractionError) as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc
