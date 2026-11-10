from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from app.errors import (
    CommitmentAlreadyReleased,
    CommitmentNotFound,
    InsufficientAvailableStock,
    ProductAlreadyExists,
    ProductNotFound,
)


class SQLiteInventoryRepository:
    """SQLite persistence with a transaction per stock-changing operation."""

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        if self.database_path != ":memory:":
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=10, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            with connection:
                yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    product_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL DEFAULT '',
                    total_quantity INTEGER NOT NULL DEFAULT 0 CHECK (total_quantity >= 0)
                );
                CREATE TABLE IF NOT EXISTS commitments (
                    commitment_id TEXT PRIMARY KEY,
                    product_id TEXT NOT NULL REFERENCES products(product_id),
                    kind TEXT NOT NULL CHECK (kind IN ('reservation', 'block')),
                    reference TEXT NOT NULL,
                    quantity INTEGER NOT NULL CHECK (quantity > 0),
                    released INTEGER NOT NULL DEFAULT 0 CHECK (released IN (0, 1))
                );
                CREATE INDEX IF NOT EXISTS ix_commitments_product_active
                    ON commitments(product_id, released, kind);
                CREATE INDEX IF NOT EXISTS ix_commitments_reference
                    ON commitments(reference);
                """
            )
            columns = {row["name"] for row in connection.execute("PRAGMA table_info(products)")}
            if "name" not in columns:
                connection.execute("ALTER TABLE products ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            connection.execute("UPDATE products SET name = product_id WHERE name = ''")

    def _begin(self, connection: sqlite3.Connection) -> None:
        # Acquire the SQLite write lock before reading balances to avoid two writers
        # both spending the same available units.
        connection.execute("BEGIN IMMEDIATE")

    @staticmethod
    def _require_product(connection: sqlite3.Connection, product_id: str) -> sqlite3.Row:
        product = connection.execute(
            "SELECT product_id, name, total_quantity FROM products WHERE product_id = ?", (product_id,)
        ).fetchone()
        if product is None:
            raise ProductNotFound(product_id)
        return product

    @staticmethod
    def _balances(connection: sqlite3.Connection, product_id: str) -> dict[str, int]:
        rows = connection.execute(
            """SELECT kind, COALESCE(SUM(quantity), 0) AS quantity
               FROM commitments WHERE product_id = ? AND released = 0 GROUP BY kind""",
            (product_id,),
        ).fetchall()
        totals = {row["kind"]: row["quantity"] for row in rows}
        return {"reserved": totals.get("reservation", 0), "blocked": totals.get("block", 0)}

    @staticmethod
    def _snapshot(connection: sqlite3.Connection, product: sqlite3.Row) -> dict[str, Any]:
        held = SQLiteInventoryRepository._balances(connection, product["product_id"])
        total = product["total_quantity"]
        return {
            "product_id": product["product_id"],
            "name": product["name"],
            "total": total,
            "available": total - held["reserved"] - held["blocked"],
            "reserved": held["reserved"],
            "blocked": held["blocked"],
        }

    def create_product(self, product_id: str, name: str | None = None) -> dict[str, Any]:
        with self._connect() as connection:
            try:
                connection.execute("INSERT INTO products(product_id, name) VALUES (?, ?)", (product_id, name or product_id))
            except sqlite3.IntegrityError as exc:
                raise ProductAlreadyExists(product_id) from exc
            return self._snapshot(connection, self._require_product(connection, product_id))

    def update_product(
        self, product_id: str, new_product_id: str | None = None, name: str | None = None
    ) -> dict[str, Any]:
        with self._connect() as connection:
            self._begin(connection)
            current = self._require_product(connection, product_id)
            new_product_id = new_product_id if new_product_id is not None else product_id
            name = name if name is not None else current["name"]
            if new_product_id != product_id and connection.execute(
                "SELECT 1 FROM products WHERE product_id = ?", (new_product_id,)
            ).fetchone():
                raise ProductAlreadyExists(new_product_id)

            # Defer FK checks until both the product and its commitments have the new code.
            connection.execute("PRAGMA defer_foreign_keys = ON")
            connection.execute(
                "UPDATE products SET product_id = ?, name = ? WHERE product_id = ?",
                (new_product_id, name, product_id),
            )
            if new_product_id != product_id:
                connection.execute(
                    "UPDATE commitments SET product_id = ? WHERE product_id = ?",
                    (new_product_id, product_id),
                )
            return self._snapshot(connection, self._require_product(connection, new_product_id))

    def delete_product(self, product_id: str) -> None:
        with self._connect() as connection:
            self._begin(connection)
            self._require_product(connection, product_id)
            connection.execute("DELETE FROM commitments WHERE product_id = ?", (product_id,))
            connection.execute("DELETE FROM products WHERE product_id = ?", (product_id,))

    def get_product(self, product_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            return self._snapshot(connection, self._require_product(connection, product_id))

    def list_products(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            products = connection.execute(
                "SELECT product_id, name, total_quantity FROM products ORDER BY name COLLATE NOCASE, product_id COLLATE NOCASE"
            ).fetchall()
            return [self._snapshot(connection, product) for product in products]

    def list_commitments(self, product_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            self._require_product(connection, product_id)
            rows = connection.execute(
                """SELECT commitment_id, product_id, kind, reference, quantity, released
                   FROM commitments WHERE product_id = ? ORDER BY rowid DESC""",
                (product_id,),
            ).fetchall()
            return [{**dict(row), "released": bool(row["released"])} for row in rows]

    def add_stock(self, product_id: str, quantity: int) -> dict[str, Any]:
        with self._connect() as connection:
            self._begin(connection)
            product = self._require_product(connection, product_id)
            connection.execute("UPDATE products SET total_quantity = total_quantity + ? WHERE product_id = ?", (quantity, product_id))
            return self._snapshot(connection, self._require_product(connection, product_id))

    def withdraw(self, product_id: str, quantity: int) -> dict[str, Any]:
        with self._connect() as connection:
            self._begin(connection)
            product = self._require_product(connection, product_id)
            snapshot = self._snapshot(connection, product)
            self._ensure_available(snapshot, quantity)
            connection.execute("UPDATE products SET total_quantity = total_quantity - ? WHERE product_id = ?", (quantity, product_id))
            return self._snapshot(connection, self._require_product(connection, product_id))

    def create_commitment(self, product_id: str, kind: str, reference: str, quantity: int) -> dict[str, Any]:
        with self._connect() as connection:
            self._begin(connection)
            product = self._require_product(connection, product_id)
            snapshot = self._snapshot(connection, product)
            self._ensure_available(snapshot, quantity)
            commitment_id = str(uuid.uuid4())
            connection.execute(
                "INSERT INTO commitments(commitment_id, product_id, kind, reference, quantity) VALUES (?, ?, ?, ?, ?)",
                (commitment_id, product_id, kind, reference, quantity),
            )
            return self._get_commitment(connection, commitment_id)

    @staticmethod
    def _ensure_available(snapshot: dict[str, Any], quantity: int) -> None:
        if snapshot["available"] < quantity:
            raise InsufficientAvailableStock(snapshot["available"], quantity)

    def release(self, commitment_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            self._begin(connection)
            commitment = connection.execute(
                "SELECT * FROM commitments WHERE commitment_id = ?", (commitment_id,)
            ).fetchone()
            if commitment is None:
                raise CommitmentNotFound(commitment_id)
            if commitment["released"]:
                raise CommitmentAlreadyReleased(commitment_id)
            connection.execute("UPDATE commitments SET released = 1 WHERE commitment_id = ?", (commitment_id,))
            return self._get_commitment(connection, commitment_id)

    @staticmethod
    def _get_commitment(connection: sqlite3.Connection, commitment_id: str) -> dict[str, Any]:
        row = connection.execute(
            "SELECT commitment_id, product_id, kind, reference, quantity, released FROM commitments WHERE commitment_id = ?",
            (commitment_id,),
        ).fetchone()
        if row is None:
            raise CommitmentNotFound(commitment_id)
        return {**dict(row), "released": bool(row["released"])}

    def get_commitment(self, commitment_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            return self._get_commitment(connection, commitment_id)
