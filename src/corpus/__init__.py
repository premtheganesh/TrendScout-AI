"""The document corpus: one MongoDB collection, several document types."""

from src.corpus.types import (          # noqa: F401
    COLLECTION, DOC_TYPES, TYPE_NAMES, LEGACY_COLLECTIONS,
    NEO4J_LABEL_TO_TYPE, DocType, normalize_type, label_for,
)
