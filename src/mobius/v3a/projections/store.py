"""Injectable projection store seam for v3a projections."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from mobius.persistence.projections import (
    ProjectionRegistry,
    ProjectionUpdater,
    register_projection,
)


class ProjectionStore:
    """Registration surface required by v3a projection modules."""

    def register(
        self,
        event_type_prefix: str,
        updater: ProjectionUpdater,
    ) -> ProjectionUpdater | None:
        """Register ``updater`` for ``event_type_prefix`` and return the previous adapter."""
        raise NotImplementedError


@dataclass
class RegistryProjectionStore(ProjectionStore):
    """Adapter over the production projection registry."""

    registry: ProjectionRegistry | None = None

    def register(
        self,
        event_type_prefix: str,
        updater: ProjectionUpdater,
    ) -> ProjectionUpdater | None:
        """Register ``updater`` with the configured production registry."""
        return register_projection(event_type_prefix, updater, registry=self.registry)


@dataclass
class InMemoryProjectionStore(ProjectionStore):
    """In-memory adapter used by tests and isolated projection rebuilds."""

    registry: ProjectionRegistry = field(default_factory=dict)

    def register(
        self,
        event_type_prefix: str,
        updater: ProjectionUpdater,
    ) -> ProjectionUpdater | None:
        """Register ``updater`` in memory and return any previous adapter."""
        previous = self.registry.get(event_type_prefix)
        self.registry[event_type_prefix] = updater
        return previous

    def as_registry(self) -> Mapping[str, ProjectionUpdater]:
        """Return a read-only view shape accepted by ``apply_projections``."""
        return dict(self.registry)


DEFAULT_V3A_PROJECTION_STORE = RegistryProjectionStore()
