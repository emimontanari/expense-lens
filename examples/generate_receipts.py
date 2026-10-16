"""Genera ejemplos ficticios sin validez fiscal; no son un dataset de evaluación."""

from pathlib import Path

from PIL import Image, ImageDraw
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

OUTPUT = Path(__file__).parent / "synthetic"


def main() -> None:
    OUTPUT.mkdir(exist_ok=True)
    with Image.new("RGB", (800, 1000), "white") as image:
        draw = ImageDraw.Draw(image)
        lines = [
            "EJEMPLO FICTICIO - SIN VALIDEZ FISCAL",
            "Emisor: Comercio ficticio",
            "Fecha: 2026-10-15",
            "Numero: 0001-00000001",
            "Moneda: ARS",
            "Subtotal: 100.00",
            "Impuestos: 21.00",
            "Total: 121.00",
        ]
        for row, line in enumerate(lines):
            draw.text((35, 60 + row * 65), line, fill="black", font_size=24)
        image.save(OUTPUT / "receipt.png")
        image.save(OUTPUT / "receipt.jpg", quality=90)
        image.save(OUTPUT / "receipt-scanned.pdf", "PDF", resolution=100)
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=750)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    stream = DecodedStreamObject()
    text = "BT /F1 16 Tf 25 700 Td "
    text += " ".join(f"({line}) Tj 0 -45 Td" for line in lines)
    stream.set_data((text + " ET").encode("ascii"))
    page.replace_contents(stream.flate_encode())
    writer.write(OUTPUT / "receipt-text.pdf")
    (OUTPUT / "invalid.pdf").write_bytes(b"%PDF-1.7\nnot a valid document\n")


if __name__ == "__main__":
    main()
