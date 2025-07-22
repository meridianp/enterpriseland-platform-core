"""
Core managers package.

Exports manager classes that provide common functionality like
multi-tenancy filtering, soft deletes, and versioning.
"""

from .base import (
    GroupFilteredQuerySet,
    GroupFilteredManager,
    SoftDeleteQuerySet,
    SoftDeleteManager,
    VersionedQuerySet,
    VersionedManager,
)

__all__ = [
    'GroupFilteredQuerySet',
    'GroupFilteredManager',
    'SoftDeleteQuerySet',
    'SoftDeleteManager',
    'VersionedQuerySet',
    'VersionedManager',
]