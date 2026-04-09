"""
Shared ChromaDB client helpers for MemPalace.
"""

import chromadb
from chromadb.config import Settings
from chromadb.telemetry.product import ProductTelemetryClient, ProductTelemetryEvent
from overrides import override


class NoOpProductTelemetryClient(ProductTelemetryClient):
    """Disable Chroma product telemetry entirely."""

    @override
    def capture(self, event: ProductTelemetryEvent) -> None:
        return


def get_persistent_client(path: str):
    """Create a persistent Chroma client with anonymized telemetry disabled."""
    settings = Settings(
        anonymized_telemetry=False,
        chroma_product_telemetry_impl="mempalace.chroma_client.NoOpProductTelemetryClient",
        chroma_telemetry_impl="mempalace.chroma_client.NoOpProductTelemetryClient",
    )
    return chromadb.PersistentClient(path=path, settings=settings)
