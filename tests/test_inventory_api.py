import pytest
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient

from app.main import create_app
from app.repository import SQLiteInventoryRepository


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "test.db"))


def test_full_inventory_lifecycle_and_independent_commitments(client):
    assert client.post("/products/camisa").status_code == 201
    assert client.post("/products/camisa/entries", json={"quantity": 20}).json()["available"] == 20

    first = client.post("/products/camisa/reservations", json={"reference": "pedido-1", "quantity": 5})
    second = client.post("/products/camisa/reservations", json={"reference": "pedido-2", "quantity": 3})
    block = client.post("/products/camisa/blocks", json={"reference": "avaria-1", "quantity": 2})
    assert first.status_code == second.status_code == block.status_code == 201
    assert first.json()["commitment_id"] != second.json()["commitment_id"]

    state = client.get("/products/camisa").json()
    assert state == {"product_id": "camisa", "name": "camisa", "total": 20, "available": 10, "reserved": 8, "blocked": 2}

    assert client.post(f"/commitments/{first.json()['commitment_id']}/release").json()["released"] is True
    state = client.get("/products/camisa").json()
    assert state == {"product_id": "camisa", "name": "camisa", "total": 20, "available": 15, "reserved": 3, "blocked": 2}


def test_withdrawal_reduces_total_only_when_available(client):
    client.post("/products/item").raise_for_status()
    client.post("/products/item/entries", json={"quantity": 10}).raise_for_status()
    client.post("/products/item/reservations", json={"reference": "pedido-1", "quantity": 4}).raise_for_status()

    response = client.post("/products/item/withdrawals", json={"quantity": 7})
    assert response.status_code == 409
    assert client.get("/products/item").json() == {
        "product_id": "item", "name": "item", "total": 10, "available": 6, "reserved": 4, "blocked": 0
    }

    state = client.post("/products/item/withdrawals", json={"quantity": 6}).json()
    assert state == {"product_id": "item", "name": "item", "total": 4, "available": 0, "reserved": 4, "blocked": 0}


@pytest.mark.parametrize("operation", ["withdrawals", "reservations", "blocks"])
def test_cannot_consume_more_than_available_and_state_is_unchanged(client, operation):
    client.post("/products/item").raise_for_status()
    client.post("/products/item/entries", json={"quantity": 3}).raise_for_status()
    response = client.post(f"/products/item/{operation}", json={"quantity": 4, "reference": "teste"})
    assert response.status_code == 409
    assert client.get("/products/item").json() == {
        "product_id": "item", "name": "item", "total": 3, "available": 3, "reserved": 0, "blocked": 0
    }


@pytest.mark.parametrize("quantity", [0, -1, 1.5])
def test_quantity_must_be_positive_integer(client, quantity):
    client.post("/products/item").raise_for_status()
    response = client.post("/products/item/entries", json={"quantity": quantity})
    assert response.status_code == 422


@pytest.mark.parametrize("reference", ["", "   "])
def test_commitment_reference_cannot_be_blank(client, reference):
    client.post("/products/item").raise_for_status()
    client.post("/products/item/entries", json={"quantity": 2}).raise_for_status()

    response = client.post(
        "/products/item/reservations", json={"reference": reference, "quantity": 1}
    )

    assert response.status_code == 422
    assert client.get("/products/item").json()["available"] == 2


def test_product_and_commitment_errors_are_clear(client):
    assert client.get("/products/unknown").status_code == 404
    client.post("/products/item").raise_for_status()
    assert client.post("/products/item").status_code == 409
    assert client.post("/commitments/unknown/release").status_code == 404

    client.post("/products/item/entries", json={"quantity": 2}).raise_for_status()
    commitment = client.post("/products/item/blocks", json={"reference": "auditoria", "quantity": 1}).json()
    path = f"/commitments/{commitment['commitment_id']}/release"
    assert client.post(path).status_code == 200
    assert client.post(path).status_code == 409


def test_dashboard_queries_list_products_and_commitments(client):
    client.post("/products/item").raise_for_status()
    client.post("/products/item/entries", json={"quantity": 8}).raise_for_status()
    created = client.post(
        "/products/item/reservations", json={"reference": "pedido-9", "quantity": 3}
    )
    created.raise_for_status()

    products = client.get("/products").json()
    commitments = client.get("/products/item/commitments").json()
    assert products == [{"product_id": "item", "name": "item", "total": 8, "available": 5, "reserved": 3, "blocked": 0}]
    assert commitments[0]["commitment_id"] == created.json()["commitment_id"]
    assert commitments[0]["released"] is False


def test_product_can_be_renamed_without_losing_commitments(client):
    client.post("/products", json={"product_id": "cafe-01", "name": "Café"}).raise_for_status()
    client.post("/products/cafe-01/entries", json={"quantity": 12}).raise_for_status()
    reservation = client.post(
        "/products/cafe-01/reservations", json={"reference": "pedido-31", "quantity": 4}
    ).json()

    updated = client.patch(
        "/products/cafe-01", json={"product_id": "cafe-02", "name": "Café especial"}
    )
    assert updated.status_code == 200
    assert updated.json() == {
        "product_id": "cafe-02", "name": "Café especial", "total": 12,
        "available": 8, "reserved": 4, "blocked": 0,
    }
    assert client.get("/products/cafe-01").status_code == 404
    commitments = client.get("/products/cafe-02/commitments").json()
    assert commitments[0]["commitment_id"] == reservation["commitment_id"]
    assert commitments[0]["product_id"] == "cafe-02"


def test_product_patch_accepts_partial_fields_and_rejects_empty_or_null(client):
    client.post("/products", json={"product_id": "item-a", "name": "Nome original"}).raise_for_status()

    rename = client.patch("/products/item-a", json={"name": "Nome atualizado"})
    assert rename.status_code == 200
    assert rename.json()["product_id"] == "item-a"
    assert rename.json()["name"] == "Nome atualizado"

    change_code = client.patch("/products/item-a", json={"product_id": "item-b"})
    assert change_code.status_code == 200
    assert change_code.json()["product_id"] == "item-b"
    assert change_code.json()["name"] == "Nome atualizado"

    assert client.patch("/products/item-b", json={}).status_code == 422
    assert client.patch("/products/item-b", json={"name": None}).status_code == 422
    assert client.patch("/products/item-b", json={"name": "   "}).status_code == 422


def test_product_with_stock_can_be_deleted_after_confirmation(client):
    client.post("/products", json={"product_id": "item-1", "name": "Item"}).raise_for_status()
    client.post("/products/item-1/entries", json={"quantity": 2}).raise_for_status()
    assert client.delete("/products/item-1").status_code == 204
    assert client.get("/products/item-1").status_code == 404


def test_product_with_reservations_and_blocks_can_be_deleted(client):
    client.post("/products", json={"product_id": "item-2", "name": "Item dois"}).raise_for_status()
    client.post("/products/item-2/entries", json={"quantity": 2}).raise_for_status()
    client.post("/products/item-2/reservations", json={"reference": "pedido-55", "quantity": 1}).raise_for_status()
    block = client.post("/products/item-2/blocks", json={"reference": "avaria-3", "quantity": 1}).json()
    client.post(f"/commitments/{block['commitment_id']}/release").raise_for_status()
    assert client.delete("/products/item-2").status_code == 204
    assert client.get("/products/item-2").status_code == 404


def test_product_rename_rejects_duplicate_code(client):
    client.post("/products", json={"product_id": "item-a", "name": "A"}).raise_for_status()
    client.post("/products", json={"product_id": "item-b", "name": "B"}).raise_for_status()
    response = client.patch("/products/item-a", json={"product_id": "item-b", "name": "A2"})
    assert response.status_code == 409
    assert client.get("/products/item-a").json()["name"] == "A"


def test_dashboard_and_assets_are_served_by_the_api(client):
    page = client.get("/")
    stylesheet = client.get("/styles.css")
    script = client.get("/app.js")
    logo = client.get("/itau-logo.png")
    assert page.status_code == stylesheet.status_code == script.status_code == logo.status_code == 200
    assert "Todos os produtos" in page.text
    assert "Sobre o case" in page.text
    assert "4. Regras gerais" in page.text
    assert "metric-products" in page.text
    assert "product-rows" in page.text
    assert "Itaú" in page.text
    assert "Adicionar produto" in page.text
    assert "Após cadastrar" not in page.text
    assert "product-name-input" in page.text
    assert "function deleteProduct" in script.text
    assert 'setAttribute("aria-label"' in script.text
    assert 'row.addEventListener("click", () => selectProduct(product.product_id))' in script.text
    assert "select-product" not in script.text
    assert "Selecionado" not in script.text
    assert "window.confirm" not in script.text
    assert "function showConfirmation" in script.text
    assert 'id="confirm-dialog"' in page.text
    assert "Deseja excluir mesmo assim?" in script.text
    assert 'confirmLabel: "SIM"' in script.text
    assert "serão excluídos" in script.text
    assert "Essa ação não pode ser desfeita." in script.text
    assert '“${product.name}”' in script.text
    assert "Produto excluído." in script.text
    assert "ser?o exclu?dos" not in script.text
    assert "Entendi" not in script.text
    assert "CONFIRMAÇÃO" not in page.text
    assert "max-width: 1680px" in stylesheet.text
    assert "availability-fill" in stylesheet.text
    assert ".select-control" in stylesheet.text
    assert ".movement-form .field input, .submit-button { height: 43px" in stylesheet.text
    assert "@keyframes rise-in" in stylesheet.text
    assert ".dialog-layout" in stylesheet.text
    assert "box-illustration" in stylesheet.text
    assert logo.content.startswith(b"\x89PNG")
    assert "function submitMovement" in script.text


def test_data_persists_between_app_instances(tmp_path):
    database = tmp_path / "persistent.db"
    first_app = create_app(database)
    with TestClient(first_app) as first_client:
        first_client.post("/products/persistente").raise_for_status()
        first_client.post("/products/persistente/entries", json={"quantity": 9}).raise_for_status()

    with TestClient(create_app(database)) as second_client:
        assert second_client.get("/products/persistente").json()["available"] == 9


def test_database_migration_adds_product_name_from_existing_id(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE products (product_id TEXT PRIMARY KEY, total_quantity INTEGER NOT NULL DEFAULT 0)"
        )
        connection.execute("INSERT INTO products(product_id, total_quantity) VALUES ('item-antigo', 3)")

    with TestClient(create_app(database)) as client:
        product = client.get("/products/item-antigo").json()
        assert product["name"] == "item-antigo"
        assert product["available"] == 3


def test_repository_closes_sqlite_connection_after_use(tmp_path):
    repository = SQLiteInventoryRepository(tmp_path / "close.db")
    with repository._connect() as connection:
        connection.execute("SELECT 1")

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")


def test_concurrent_reservations_cannot_oversell(client):
    client.post("/products/item").raise_for_status()
    client.post("/products/item/entries", json={"quantity": 10}).raise_for_status()

    def reserve(index):
        return client.post(
            "/products/item/reservations",
            json={"reference": f"pedido-{index}", "quantity": 6},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(reserve, [1, 2]))

    assert sorted(results) == [201, 409]
    assert client.get("/products/item").json() == {
        "product_id": "item", "name": "item", "total": 10, "available": 4, "reserved": 6, "blocked": 0
    }
