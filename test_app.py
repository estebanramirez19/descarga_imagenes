import json

import app
from app import extract_solotodo_products


def make_next_html(data):
    chunk = '0:' + json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    payload = json.dumps([1, chunk], ensure_ascii=False)
    return f"<html><script>self.__next_f.push({payload})</script></html>"


def test_app_exposes_streamlit_main_entrypoint():
    assert hasattr(app, "main")


def test_extracts_every_solotodo_product():
    state = {
        "results": [
            {
                "product_entries": [
                    {
                        "product": {
                            "id": 94902,
                            "name": "Mouse Uno",
                            "slug": "mouse-uno",
                            "picture_url": "https://media.example/uno.jpg",
                            "brand": {"name": "Marca"},
                            "specs": {"weight": 131},
                            "meta_tag_description": "Descripción",
                        },
                        "metadata": {
                            "prices_per_currency": [
                                {"currency": 1, "offer_price": "14990.0"}
                            ]
                        },
                    }
                ]
            },
            {
                "product_entries": [
                    {
                        "product": {
                            "id": 228757,
                            "name": "Mouse Dos",
                            "slug": "mouse-dos",
                            "picture_url": "https://media.example/dos.webp",
                            "brand": {"name": "Otra"},
                            "specs": {},
                        }
                    }
                ]
            },
        ]
    }

    products = extract_solotodo_products(
        make_next_html(state), "https://www.solotodo.cl/search?search=mouse"
    )

    assert [product["name"] for product in products] == ["Mouse Uno", "Mouse Dos"]
    assert products[0]["price"] == "$14.990"
    assert products[0]["weight"] == "131 g"
    assert products[0]["url"] == "https://www.solotodo.cl/products/94902-mouse-uno"
    assert products[1]["images"] == ["https://media.example/dos.webp"]


def test_ignores_other_domains():
    assert extract_solotodo_products("", "https://example.com/search") == []
