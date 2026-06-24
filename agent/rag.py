"""Local RAG over the loan-program docs in ``programs/``.

Loads the Markdown program docs with LangChain, splits them, embeds them into a
persistent ChromaDB collection on disk, and exposes ``match_programs()`` to
retrieve the programs most relevant to an enriched lead.
"""
import logging
import os

from langchain_chroma import Chroma
from langchain_community.document_loaders import TextLoader
from langchain_text_splitters import MarkdownTextSplitter

logger = logging.getLogger(__name__)

PROGRAMS_DIR = os.environ.get("PROGRAMS_DIR", "programs")
CHROMA_DIR = os.environ.get("CHROMA_DIR", "chromadb")
COLLECTION_NAME = "loan_programs"


def _embeddings():
    """ChromaDB's built-in default embedding function (all-MiniLM-L6-v2).

    Wrapped so LangChain's Chroma store uses the same local, no-API-key model.
    Imported lazily so importing this module doesn't require the backend.
    """
    from langchain_community.embeddings import (
        SentenceTransformerEmbeddings,
    )

    return SentenceTransformerEmbeddings(model_name="all-MiniLM-L6-v2")


def load_program_documents(programs_dir: str = PROGRAMS_DIR):
    """Load and split every ``*.md`` file in ``programs_dir`` into chunks."""
    splitter = MarkdownTextSplitter(chunk_size=1000, chunk_overlap=150)
    docs = []
    for filename in sorted(os.listdir(programs_dir)):
        if not filename.endswith(".md"):
            continue
        path = os.path.join(programs_dir, filename)
        loaded = TextLoader(path, encoding="utf-8").load()
        for doc in loaded:
            doc.metadata["program"] = os.path.splitext(filename)[0]
        docs.extend(splitter.split_documents(loaded))
    logger.info("Loaded %d chunks from %s", len(docs), programs_dir)
    return docs


def build_index(programs_dir: str = PROGRAMS_DIR, persist_dir: str = CHROMA_DIR) -> Chroma:
    """Build (or rebuild) the ChromaDB index from the program docs."""
    documents = load_program_documents(programs_dir)
    store = Chroma.from_documents(
        documents=documents,
        embedding=_embeddings(),
        collection_name=COLLECTION_NAME,
        persist_directory=persist_dir,
    )
    logger.info("Built ChromaDB index at %s", persist_dir)
    return store


def get_store(persist_dir: str = CHROMA_DIR) -> Chroma:
    """Open the persistent ChromaDB store, building it if it doesn't exist yet."""
    if not os.path.isdir(persist_dir) or not os.listdir(persist_dir):
        return build_index(persist_dir=persist_dir)
    return Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=_embeddings(),
        persist_directory=persist_dir,
    )


def match_programs(lead: dict, k: int = 3, store: Chroma | None = None) -> list[dict]:
    """Return the ``k`` loan-program chunks most relevant to an enriched lead."""
    store = store or get_store()
    results = store.similarity_search(_lead_to_query(lead), k=k)
    return [
        {"program": doc.metadata.get("program", "unknown"), "content": doc.page_content}
        for doc in results
    ]


def _lead_to_query(lead: dict) -> str:
    """Turn a lead (enriched or not) into a natural-language retrieval query."""
    demo = (lead.get("enrichment") or {}).get("demographics") or {}
    parts = [
        f"ZIP code {lead.get('zip_code') or lead.get('zip') or ''}",
        f"loan amount {lead.get('loan_amount', '')}",
        f"credit score {lead.get('credit_score', '')}",
        f"annual income {lead.get('income', '')}",
        f"property type {lead.get('property_type', '')}",
        f"first-time buyer {lead.get('first_time_buyer', '')}",
    ]
    if demo.get("median_household_income"):
        parts.append(f"area median income {demo['median_household_income']}")
    return "Loan programs for: " + ", ".join(p for p in parts if p.strip().rstrip(":"))
