"""Categorías de gasto y línea base determinista por palabras clave del emisor.

La línea base no usa red ni modelo: compite con la sugerencia del modelo y la
persona decide. Sin coincidencia no opina (None).
"""

import re
import unicodedata
from typing import Literal

Category = Literal[
    "supermercado",
    "combustible",
    "restaurantes",
    "servicios",
    "transporte",
    "salud",
    "hogar",
    "otros",
]
CATEGORIES: tuple[str, ...] = Category.__args__

# Criterio único: lo usan el prompt del modelo y las etiquetas del dataset.
CATEGORY_GUIDE: dict[Category, str] = {
    "supermercado": "supermercados, almacenes y autoservicios (alimentos, "
    "bebidas, limpieza e higiene para el consumo cotidiano)",
    "combustible": "estaciones de servicio: nafta, gasoil, GNC y lubricantes",
    "restaurantes": "comidas y bebidas consumidas fuera o por delivery: "
    "restaurantes, bares, cafeterías y parrillas",
    "servicios": "servicios públicos y abonos del hogar: luz, gas, agua, "
    "internet, telefonía, TV y mantenimientos mensuales",
    "transporte": "SUBE, taxi, remís, apps de viaje, peajes, estacionamiento y pasajes",
    "salud": "farmacias, consultas médicas, prepagas y laboratorios",
    "hogar": "ferreterías, pinturerías, muebles, electrodomésticos y "
    "reparaciones de la vivienda",
    "otros": "todo lo demás, incluidos honorarios, consultoría, software y "
    "licencias, librería y reparaciones que no son de la vivienda",
}

KEYWORDS: dict[Category, tuple[str, ...]] = {
    "combustible": ("ypf", "shell", "axion", "puma"),
    "supermercado": (
        "coto",
        "carrefour",
        "dia",
        "jumbo",
        "disco",
        "vea",
        "changomas",
        "supermercado",
    ),
    "salud": ("farmacia", "farmacity"),
    "servicios": (
        "edenor",
        "edesur",
        "metrogas",
        "aysa",
        "telecom",
        "movistar",
        "claro",
        "personal",
    ),
    "transporte": ("sube", "uber", "cabify", "peaje", "taxi", "estacionamiento"),
    "restaurantes": ("restaurante", "parrilla", "pizzeria", "cafe", "bar"),
    "hogar": ("easy", "sodimac", "ferreteria", "pintureria"),
}


def normalize_issuer(issuer: str) -> str:
    """Minúsculas y sin acentos, para comparar palabras."""
    decomposed = unicodedata.normalize("NFD", issuer.casefold())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def suggest_by_rules(issuer: str | None) -> Category | None:
    """Primera categoría (en orden de KEYWORDS) con una palabra clave en el emisor."""
    if not issuer:
        return None
    words = set(re.findall(r"[a-z0-9]+", normalize_issuer(issuer)))
    for category, keywords in KEYWORDS.items():
        if words.intersection(keywords):
            return category
    return None
