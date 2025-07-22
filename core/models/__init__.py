"""
Core models package.

Exports base model classes that can be used throughout the platform.
"""

from .base import (
    UUIDModel,
    TimestampedModel,
    GroupFilteredModel,
    SoftDeleteModel,
    VersionedModel,
)

__all__ = [
    'UUIDModel',
    'TimestampedModel',
    'GroupFilteredModel',
    'SoftDeleteModel',
    'VersionedModel',
]