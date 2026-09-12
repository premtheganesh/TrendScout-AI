"""
Embedding storage. Vectors are kept in MongoDB as float32 BSON Binary
(3 KB for 768 dims) rather than a list of doubles (~9 KB), so the corpus
fits a free-tier database and the API can rebuild FAISS from stored
vectors at boot instead of shipping index files around.
"""

from typing import Any, Optional

import numpy as np
from bson import Binary


def to_binary(vector) -> Binary:
    return Binary(np.asarray(vector, dtype='float32').tobytes())


def from_stored(value: Any) -> Optional[np.ndarray]:
    """Decode either storage format; None if there is nothing usable."""
    if value is None:
        return None
    if isinstance(value, (bytes, Binary)):
        return np.frombuffer(bytes(value), dtype='float32').copy()
    if isinstance(value, (list, tuple)):
        return np.asarray(value, dtype='float32')
    return None
