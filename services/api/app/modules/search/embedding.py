import hashlib
import math
import struct

from app.config import get_settings
from app.logging_config import get_logger

logger = get_logger(__name__)


def generate_mock_embedding(text: str) -> list[float]:
    """
    Generate a deterministic mock embedding from text for development.
    Uses MD5 hash to create reproducible vectors.
    
    Note: Replace with real embedding model in production (e.g., multilingual-e5-large).
    """
    settings = get_settings()
    dimension = settings.embedding_dimension
    
    hash_bytes = hashlib.md5(text.encode("utf-8")).digest()
    
    embedding: list[float] = []
    for i in range(dimension):
        seed_bytes = hash_bytes + struct.pack("I", i)
        hash_val = hashlib.md5(seed_bytes).digest()
        # Use integer conversion to avoid NaN/Inf from float unpacking
        int_val = int.from_bytes(hash_val[:4], byteorder="little", signed=False)
        # Map to [-1, 1] range
        normalized = (int_val / (2**32 - 1)) * 2.0 - 1.0
        embedding.append(normalized)
    
    # Normalize to unit vector
    norm = math.sqrt(sum(x * x for x in embedding))
    if norm > 0:
        embedding = [x / norm for x in embedding]
    
    return embedding


async def get_query_embedding(query: str) -> list[float]:
    return generate_mock_embedding(query)
