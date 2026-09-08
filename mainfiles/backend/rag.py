"""
rag.py — chunk + retrieve for document RAG.

Replaces the old approach of stuffing the full extracted document text into
the chat prompt.  Instead, at ingest time we chunk the text and compute
embeddings (via chromadb's built-in ONNX model).  At query time we retrieve
only the top-k most relevant chunks.

Architecture
------------
* ChromaDB in persistent embedded mode (no external server).
* Default embedding: all-MiniLM-L6-v2 (ONNX, ~80 MB on first download).
* Chunking uses a simple character heuristic (~4 chars ≈ 1 token) with
  paragraph-boundary awareness.

Graceful degradation
--------------------
Any failure during indexing or retrieval is caught and logged — the caller
falls back to the full extracted text stored in the database, so a broken
RAG never takes down a chat request.
"""

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

# .. envvar:: CHROMA_DB_PATH
#    Override the persistent chromadb directory (useful in tests).
#

import logging
import os
import re
from pathlib import Path
from typing import Any

import chromadb
from chromadb.config import Settings as ChromaSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# ~500 tokens per chunk (1 token ≈ 4 chars for English prose)
CHUNK_SIZE = 500
# Overlap between consecutive chunks (tokens)
CHUNK_OVERLAP = 100
# Number of chunks to retrieve at query time
TOP_K = 5

# Directory where chromadb stores its persistent index.
# Placed alongside the uploads directory, which is sibling of this file's
# parent (backend/ → backend/../.chromadb).
# Override via the CHROMA_DB_PATH env var (useful in tests).
_env_path = os.environ.get("CHROMA_DB_PATH")
CHROMA_DB_DIR = Path(_env_path) if _env_path else (Path(__file__).resolve().parent.parent / ".chromadb")

# ---------------------------------------------------------------------------
# Lazy-init singleton client / collection
# ---------------------------------------------------------------------------

# Note: chromadb.PersistentClient and chromadb.Collection are functions (not
# classes) in chromadb 1.5.x, so we use Any for the type annotations rather
# than the | union syntax which requires class types.
_client: Any = None
_collection: Any = None


def _get_client() -> Any:
    global _client
    if _client is None:
        CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
        _client = chromadb.PersistentClient(
            path=str(CHROMA_DB_DIR),
            settings=ChromaSettings(anonymized_telemetry=False),
        )
    return _client


def _get_collection() -> Any:
    global _collection
    if _collection is None:
        client = _get_client()
        try:
            _collection = client.get_collection("document_chunks")
        except ValueError:
            _collection = client.create_collection("document_chunks")
        except chromadb.errors.NotFoundError:
            _collection = client.create_collection("document_chunks")
    return _collection


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
) -> list[str]:
    """
    Split *text* into overlapping chunks of approximately *chunk_size* tokens.

    Parameters
    ----------
    text:
        Plain-text content to split.
    chunk_size:
        Target chunk size in tokens (approximate — uses 4 chars/token).
    overlap:
        Overlap between consecutive chunks, in tokens.

    Returns
    -------
    list[str]
        Non-empty chunk strings in order.  Returns ``[text]`` when the input
        is shorter than one chunk; returns ``[]`` for empty/whitespace input.
    """
    text = text.strip()
    if not text:
        return []

    target_chars = chunk_size * 4
    overlap_chars = overlap * 4

    # Split on paragraph boundaries first (double newline).
    raw_paras = re.split(r"\n\s*\n", text)
    paragraphs = [p.strip() for p in raw_paras if p.strip()]
    if not paragraphs:
        return []

    # ---- Accrue paragraphs into chunks with overlap carry-over ----
    chunks: list[str] = []
    current: list[str] = []      # paragraphs in the current chunk
    current_len = 0               # char count of current (incl. "\n\n" sep)

    for para in paragraphs:
        para_len = len(para) + 2  # +2 for the "\n\n" that will join them

        # Lone oversized paragraph → hard-split at target_chars.
        if para_len > target_chars and not current:
            chunks.append(para[:target_chars].strip())
            carry = para[target_chars - overlap_chars:target_chars].strip()
            if carry:
                current, current_len = [carry], len(carry)
            continue

        # Does this paragraph push us over the limit?
        if current_len + para_len > target_chars and current:
            chunks.append("\n\n".join(current))

            # Carry the tail of the just-finished chunk as overlap.
            overlap_paras: list[str] = []
            o_len = 0
            for p in reversed(current):
                pl = len(p) + 2
                if o_len + pl <= overlap_chars:
                    overlap_paras.insert(0, p)
                    o_len += pl
                else:
                    break
            current, current_len = overlap_paras, o_len

        current.append(para)
        current_len += para_len

    if current:
        chunks.append("\n\n".join(current))

    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def index_document(file_id: str, text: str, filename: str) -> int:
    """
    Chunk, embed, and store *text* in the vector index.

    Parameters
    ----------
    file_id:
        Primary key of the ``UploadedFile`` row (used as id-prefix for chunks
        and as a filter key at retrieval time).
    text:
        Full extracted text (already extracted by ``document.extract_text``).
    filename:
        Original filename (stored in metadata for display).

    Returns
    -------
    int
        Number of chunks indexed, or ``-1`` on failure (caller should fall
        back to full-text stuffing).
    """
    try:
        chunks = chunk_text(text)
        if not chunks:
            return 0

        collection = _get_collection()
        ids = [f"{file_id}_{i}" for i in range(len(chunks))]
        metadatas: list[dict[str, Any]] = [
            {"file_id": file_id, "filename": filename, "chunk_index": i}
            for i in range(len(chunks))
        ]

        collection.add(
            documents=chunks,
            ids=ids,
            metadatas=metadatas,
        )

        logger.info(
            "Indexed %d chunks for file %s (%s)", len(chunks), file_id, filename
        )
        return len(chunks)
    except Exception:
        logger.exception("index_document(%s) failed", file_id)
        return -1


# ---------------------------------------------------------------------------
# Retrieval
# ---------------------------------------------------------------------------

def retrieve_relevant_chunks(
    query: str,
    file_ids: list[str],
    top_k: int = TOP_K,
) -> list[dict[str, Any]]:
    """
    Retrieve the top-*top_k* most relevant chunks for *query*.

    Parameters
    ----------
    query:
        The user's latest message text (embedded at query time).
    file_ids:
        The ``UploadedFile`` primary keys to search within.
    top_k:
        Maximum number of chunks to return.

    Returns
    -------
    list[dict]
        Each dict has keys ``text``, ``filename``, and ``score`` (chromadb
        L2 distance; lower is more similar).  Empty list on any error or
        when no data is available.
    """
    if not query or not file_ids:
        return []

    try:
        collection = _get_collection()
        results = collection.query(
            query_texts=[query],
            n_results=min(top_k, 50),  # cap to avoid excessive I/O
            where={"file_id": {"$in": file_ids}},
        )

        chunks: list[dict[str, Any]] = []
        docs = (results or {}).get("documents", [[]])[0]
        metas = (results or {}).get("metadatas", [[]])[0]
        dists = (results or {}).get("distances", [[]])[0]

        for i, doc in enumerate(docs):
            if not doc:
                continue
            meta = metas[i] if i < len(metas) else {}
            score = dists[i] if i < len(dists) else None
            chunks.append({
                "text": doc,
                "filename": meta.get("filename", ""),
                "score": score,
            })

        logger.debug(
            "Retrieved %d chunks for query (top_k=%d)", len(chunks), top_k
        )
        return chunks
    except Exception:
        logger.exception(
            "retrieve_relevant_chunks failed (query=%r, file_ids=%r)",
            query, file_ids,
        )
        return []


# ---------------------------------------------------------------------------
# Cleanup
# ---------------------------------------------------------------------------

def delete_document_chunks(file_id: str) -> bool:
    """Remove all chunks belonging to *file_id* from the vector index."""
    try:
        _get_collection().delete(where={"file_id": file_id})
        logger.info("Deleted chunks for file %s", file_id)
        return True
    except Exception:
        logger.exception("delete_document_chunks(%s) failed", file_id)
        return False


def reset_vector_index() -> None:
    """Drop and recreate the collection (useful in tests)."""
    global _collection
    try:
        client = _get_client()
        client.delete_collection("document_chunks")
    except ValueError:
        pass  # collection didn't exist (older chromadb versions)
    except chromadb.errors.NotFoundError:
        pass  # collection didn't exist (chromadb 1.5.x+)
    _collection = None


def close_client() -> None:
    """Close the chromadb client and clear singletons.

    Primarily used in test teardown so that the temporary SQLite file can
    be cleaned up on Windows (which locks open database files).
    """
    global _client, _collection
    _client = None
    _collection = None
