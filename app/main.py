from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.errors import (
    CommitmentAlreadyReleased,
    CommitmentNotFound,
    InsufficientAvailableStock,
    ProductAlreadyExists,
    ProductNotFound,
)
from app.repository import SQLiteInventoryRepository


class QuantityRequest(BaseModel):
    quantity: int = Field(gt=0, strict=True, description="Quantidade inteira maior que zero")


class CommitmentRequest(QuantityRequest):
    model_config = ConfigDict(str_strip_whitespace=True)

    reference: str = Field(min_length=1, max_length=100, description="Pedido ou motivo associado")


class ProductRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)


class ProductPatchRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    product_id: str | None = Field(default=None, min_length=1, max_length=100)
    name: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode="after")
    def validate_patch_fields(self):
        if not self.model_fields_set:
            raise ValueError("Informe ao menos um campo para atualizar.")
        if any(getattr(self, field) is None for field in self.model_fields_set):
            raise ValueError("Os campos enviados não podem ser nulos.")
        return self


def create_app(database_path: str | None = None) -> FastAPI:
    path = database_path or os.getenv("INVENTORY_DATABASE", "data/inventory.db")
    repository = SQLiteInventoryRepository(path)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield

    app = FastAPI(
        title="Controle de Estoque",
        description="API para entradas, saídas, reservas e bloqueios de estoque.",
        version="1.0.0",
        lifespan=lifespan,
    )
    app.state.repository = repository

    @app.exception_handler(ProductNotFound)
    async def product_not_found(_, exc: ProductNotFound):
        return JSONResponse(status_code=404, content={"detail": f"Produto '{exc}' não encontrado."})

    @app.exception_handler(ProductAlreadyExists)
    async def product_exists(_, exc: ProductAlreadyExists):
        return JSONResponse(status_code=409, content={"detail": f"Produto '{exc}' já existe."})

    @app.exception_handler(InsufficientAvailableStock)
    async def insufficient_stock(_, exc: InsufficientAvailableStock):
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CommitmentNotFound)
    async def commitment_not_found(_, exc: CommitmentNotFound):
        return JSONResponse(status_code=404, content={"detail": f"Reserva/bloqueio '{exc}' não encontrado."})

    @app.exception_handler(CommitmentAlreadyReleased)
    async def commitment_released(_, exc: CommitmentAlreadyReleased):
        return JSONResponse(status_code=409, content={"detail": "A reserva ou o bloqueio já foi liberado."})

    @app.post("/products/{product_id}", status_code=status.HTTP_201_CREATED, tags=["Estoque"])
    def create_product(product_id: str):
        return repository.create_product(product_id)

    @app.post("/products", status_code=status.HTTP_201_CREATED, tags=["Estoque"])
    def create_named_product(request: ProductRequest):
        return repository.create_product(request.product_id.strip(), request.name.strip())

    @app.patch("/products/{product_id}", tags=["Estoque"])
    def update_product(product_id: str, request: ProductPatchRequest):
        return repository.update_product(product_id, request.product_id, request.name)

    @app.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT, tags=["Estoque"])
    def delete_product(product_id: str):
        repository.delete_product(product_id)

    @app.get("/products", tags=["Estoque"])
    def list_products():
        return repository.list_products()

    @app.get("/products/{product_id}", tags=["Estoque"])
    def get_product(product_id: str):
        return repository.get_product(product_id)

    @app.get("/products/{product_id}/commitments", tags=["Reservas e bloqueios"])
    def list_commitments(product_id: str):
        return repository.list_commitments(product_id)

    @app.post("/products/{product_id}/entries", tags=["Estoque"])
    def add_stock(product_id: str, request: QuantityRequest):
        return repository.add_stock(product_id, request.quantity)

    @app.post("/products/{product_id}/withdrawals", tags=["Estoque"])
    def withdraw(product_id: str, request: QuantityRequest):
        return repository.withdraw(product_id, request.quantity)

    def create_commitment(product_id: str, kind: Literal["reservation", "block"], request: CommitmentRequest):
        return repository.create_commitment(product_id, kind, request.reference, request.quantity)

    @app.post("/products/{product_id}/reservations", status_code=status.HTTP_201_CREATED, tags=["Reservas e bloqueios"])
    def reserve(product_id: str, request: CommitmentRequest):
        return create_commitment(product_id, "reservation", request)

    @app.post("/products/{product_id}/blocks", status_code=status.HTTP_201_CREATED, tags=["Reservas e bloqueios"])
    def block(product_id: str, request: CommitmentRequest):
        return create_commitment(product_id, "block", request)

    @app.get("/commitments/{commitment_id}", tags=["Reservas e bloqueios"])
    def get_commitment(commitment_id: str):
        return repository.get_commitment(commitment_id)

    @app.post("/commitments/{commitment_id}/release", tags=["Reservas e bloqueios"])
    def release(commitment_id: str):
        return repository.release(commitment_id)

    frontend = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
    app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()
