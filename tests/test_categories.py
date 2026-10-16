import pytest
from fastapi.testclient import TestClient

from expense_lens.categories import suggest_by_rules
from expense_lens.main import app


@pytest.mark.parametrize(
    "issuer,category",
    [
        ("YPF Estacion Centro", "combustible"),
        ("Shell", "combustible"),
        ("AXION energy", "combustible"),
        ("Puma Energy", "combustible"),
        ("Coto CICSA", "supermercado"),
        ("Carrefour Express", "supermercado"),
        ("DIA Argentina", "supermercado"),
        ("Jumbo", "supermercado"),
        ("Disco", "supermercado"),
        ("Vea", "supermercado"),
        ("ChangoMas", "supermercado"),
        ("SUPERMERCADO EL EJEMPLO", "supermercado"),
        ("Farmacia del Pueblo", "salud"),
        ("Farmacity", "salud"),
        ("Edenor SA", "servicios"),
        ("Edesur", "servicios"),
        ("Metrogas", "servicios"),
        ("AySA", "servicios"),
        ("Telecom Argentina", "servicios"),
        ("Movistar", "servicios"),
        ("Claro", "servicios"),
        ("Personal Flow", "servicios"),
        ("SUBE", "transporte"),
        ("Uber Argentina", "transporte"),
        ("Cabify", "transporte"),
        ("Autopistas - Peaje", "transporte"),
        ("Radio Taxi", "transporte"),
        ("Estacionamiento Obelisco", "transporte"),
        ("Restaurante Don Julio", "restaurantes"),
        ("La Parrilla de Juan", "restaurantes"),
        ("Pizzeria Guerrin", "restaurantes"),
        ("Café Tortoni", "restaurantes"),
        ("Bar Dorrego", "restaurantes"),
        ("EASY Argentina", "hogar"),
        ("Sodimac", "hogar"),
        ("Ferretería Modelo SA", "hogar"),
        ("Pinturería Rex", "hogar"),
    ],
)
def test_rules_baseline_matches_issuer_keywords(issuer, category):
    assert suggest_by_rules(issuer) == category


@pytest.mark.parametrize(
    "issuer",
    [None, "", "   ", "Distribuidora Ficticia SA", "Kiosco Dudoso", "Barrio Norte"],
)
def test_rules_baseline_has_no_opinion_without_a_keyword(issuer):
    assert suggest_by_rules(issuer) is None


def test_keywords_match_whole_words_not_substrings():
    assert suggest_by_rules("Diaz Hermanos") is None
    assert suggest_by_rules("Barbería") is None


def test_validate_returns_rules_only_suggestion():
    with TestClient(app) as client:
        body = client.post(
            "/receipts/validate", json={"receipt": {"issuer": "YPF Ruta 9"}}
        ).json()
        empty = client.post("/receipts/validate", json={"receipt": {}}).json()
    assert body["category_suggestion"] == {
        "model": None,
        "rules": "combustible",
        "suggested": "combustible",
        "source": "rules",
    }
    assert empty["category_suggestion"] == {
        "model": None,
        "rules": None,
        "suggested": None,
        "source": None,
    }


def test_every_category_has_one_definition_shared_with_the_prompt():
    """Etiquetas del dataset y modelo usan el mismo criterio escrito."""
    from expense_lens import extraction
    from expense_lens.categories import CATEGORIES, CATEGORY_GUIDE

    assert set(CATEGORY_GUIDE) == set(CATEGORIES)
    for name, definition in CATEGORY_GUIDE.items():
        assert f"{name}: {definition}" in extraction.PROMPT
