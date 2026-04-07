"""Factory for creating storage backend collections based on configuration."""

from ..config import MempalaceConfig


def get_collection(name="mempalace_drawers", create=False, config=None, palace_path=None):
    """Return a collection for the configured storage backend.

    Args:
        name: Collection / index name.
        create: If True, create the collection if it doesn't exist.
        config: MempalaceConfig instance (uses default if None).
        palace_path: Override palace path for ChromaDB backend (ignored by ES).

    Returns:
        A BaseCollection implementation (ChromaCollection or ElasticsearchCollection).
    """
    config = config or MempalaceConfig()
    backend = config.storage_backend

    if backend == "elasticsearch":
        from .elasticsearch_backend import ElasticsearchCollection

        return ElasticsearchCollection(name, config=config, create=create)
    else:
        from .chromadb_backend import ChromaCollection

        return ChromaCollection(name, config=config, create=create, palace_path=palace_path)
