class InventoryError(Exception):
    """Base class for expected inventory rule violations."""


class ProductNotFound(InventoryError):
    pass


class ProductAlreadyExists(InventoryError):
    pass


class CommitmentNotFound(InventoryError):
    pass


class CommitmentAlreadyReleased(InventoryError):
    pass


class InsufficientAvailableStock(InventoryError):
    def __init__(self, available: int, requested: int):
        self.available = available
        self.requested = requested
        super().__init__(f"Estoque disponível insuficiente: {available} disponível, {requested} solicitado.")
