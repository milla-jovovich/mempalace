"""Abstract collection interface for MemPalace storage backends."""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class BaseCollection(ABC):
    """Smallest collection contract the rest of MemPalace relies on."""

    @abstractmethod
    def add(
        self,
        *,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def upsert(
        self,
        *,
        documents: List[str],
        ids: List[str],
        metadatas: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        raise NotImplementedError

    @abstractmethod
    def query(self, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def get(self, **kwargs: Any) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def delete(self, **kwargs: Any) -> None:
        raise NotImplementedError

    @abstractmethod
    def count(self) -> int:
        raise NotImplementedError
