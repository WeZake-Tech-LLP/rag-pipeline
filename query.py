import os
import sys
from dotenv import load_dotenv
import chromadb
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from groq import Groq

load_dotenv()

CHROMA_PATH = "./chroma_db"
COLLECTION_NAME = "knowledge_base"
EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
RERANKER_MODEL_NAME = "cross-encoder/ms-marco-MiniLM-L-6-v2"
INITIAL_RETRIEVAL_COUNT = 15
FINAL_CONTEXT_COUNT = 6

_collection = None
_embed_model = None
_reranker = None
_groq_client = None


def get_collection():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(COLLECTION_NAME)
    return _collection


def get_embed_model():
    global _embed_model
    if _embed_model is None:
        _embed_model = HuggingFaceEmbedding(model_name=EMBED_MODEL_NAME)
    return _embed_model


def get_reranker():
    global _reranker
    if _reranker is None:
        from sentence_transformers import CrossEncoder
        _reranker = CrossEncoder(RERANKER_MODEL_NAME)
    return _reranker


def get_groq_client():
    global _groq_client
    if _groq_client is None:
        _groq_client = Groq(api_key=os.getenv("GROQ_API_KEY"))
    return _groq_client


def _debug_log(message: str) -> None:
    print(message, file=sys.stderr)


def expand_query(question: str) -> str:
    """Expand query with synonyms/related terms for better retrieval"""
    expansion_map = {
        "what is": "define explain describe",
        "how does": "explain mechanism process steps",
        "difference between": "compare contrast distinguish",
        "explain": "describe define elaborate",
        "summarize": "overview summary main points key takeaways",
        "best": "top recommended most effective",
    }
    expanded = question
    for key, expansion in expansion_map.items():
        if key.lower() in question.lower():
            expanded = f"{question} {expansion}"
            break
    return expanded


def query_rag(question: str, filter_type: str = None, filter_url: str = None) -> dict:
    collection = get_collection()

    if collection.count() == 0:
        return {
            "answer": "Knowledge base is empty. Please add some URLs first.",
            "sources": [],
            "chunks": [],
        }

    # Build ChromaDB where filter
    where = None
    if filter_type and filter_type.lower() != "all" and filter_url and filter_url.strip():
        where = {
            "$and": [
                {"type": {"$eq": filter_type.lower()}},
                {"source": {"$eq": filter_url.strip()}},
            ]
        }
    elif filter_type and filter_type.lower() != "all":
        where = {"type": {"$eq": filter_type.lower()}}
    elif filter_url and filter_url.strip():
        where = {"source": {"$eq": filter_url.strip()}}

    # Embed the question
    embed_model = get_embed_model()
    expanded_q = expand_query(question)
    query_embedding = embed_model.get_text_embedding(expanded_q)

    # Query ChromaDB directly
    query_params = {
        "query_embeddings": [query_embedding],
        "n_results": min(INITIAL_RETRIEVAL_COUNT, collection.count()),
        "include": ["documents", "metadatas", "distances"],
    }
    if where:
        query_params["where"] = where

    results = collection.query(**query_params)

    documents = results["documents"][0]
    metadatas = results["metadatas"][0]
    distances = results["distances"][0]

    # Convert distance to similarity score (ChromaDB returns L2 distance)
    scores = [round(1 / (1 + d), 4) for d in distances]

    # Debug logging
    _debug_log(f"[DEBUG] Total chunks retrieved: {len(documents)}")
    for i, (doc, meta, score) in enumerate(zip(documents, metadatas, scores)):
        _debug_log(f"[DEBUG] Chunk {i+1} | Score: {score} | Source: {meta.get('source','?')}")
        _debug_log(f"[DEBUG] Preview: {doc[:100]}...")

    # ── RERANKING ────────────────────────────────────────────────────
    # Retrieval above casts a wide net (INITIAL_RETRIEVAL_COUNT); the
    # cross-encoder reranks by actual relevance to the question, and we
    # keep only the top FINAL_CONTEXT_COUNT for the LLM's context.
    if documents:
        reranker = get_reranker()
        pairs = [[question, doc] for doc in documents]
        rerank_scores = reranker.predict(pairs)

        reranked = sorted(
            zip(rerank_scores, documents, metadatas, scores),
            key=lambda x: x[0],
            reverse=True,
        )[:FINAL_CONTEXT_COUNT]

        rerank_scores, documents, metadatas, scores = (list(x) for x in zip(*reranked))
        _debug_log(f"[DEBUG] Reranked top score: {rerank_scores[0]:.4f}")
    # ────────────────────────────────────────────────────────────────

    # Build context string
    context_str = "\n\n---\n\n".join(
        [
            f"[Source {i+1}] Type: {meta.get('type','unknown')} | "
            f"URL: {meta.get('source','unknown')}\nContent: {doc}"
            for i, (doc, meta) in enumerate(zip(documents, metadatas))
            if doc and doc.strip()
        ]
    )

    if not context_str.strip():
        context_str = "No relevant content found in knowledge base."

    # Call Groq directly
    client = get_groq_client()

    system_prompt = """You are a precise knowledge-base assistant.

Your job is to answer the user's question using the retrieved context.

## Core Rules:

1. MATCH answer length and detail to the question scope:
   - "What is this about?" -> 3-4 sentence summary, no names/links
   - "Explain X in detail" -> detailed multi-point answer
   - "What did X say about Y?" -> focused extract
   - "Compare A and B" -> structured comparison only

2. FILTER out irrelevant details:
   - Skip author names unless the question asks "who"
   - Skip URLs/links found inside content
   - Skip dates unless the question asks "when"
   - Skip promotional language or filler sentences

3. SYNTHESIZE — do not list raw chunks:
   - Combine related points into coherent sentences
   - Never bullet-point unless the question asks for a list
   - Write in flowing prose for summary questions

4. SOURCE citation:
   - End every answer with a single line: Source: <URL>
   - Only cite URLs from the metadata, not URLs found inside content

5. FALLBACK — only if context has zero relevance:
   - Write: "Not found in knowledge base."
   - Then: "--- General Knowledge ---"
   - Provide concise general answer

## Answer length guide:
- "what is / what is this about" -> 3-5 sentences max
- "explain / how does" -> 1-3 short paragraphs
- "summarize" -> 5-7 sentences
- "list / what are" -> bullet points only for this case
- "compare / difference" -> 2-3 sentences per item being compared

Never include raw links, author social handles, or metadata
found inside the ingested content."""

    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context_str}\n\nQuestion: {question}"},
        ],
        temperature=0.3,
        max_tokens=800,
    )

    answer = response.choices[0].message.content or ""

    # Detect if LLM answered from KB or General Knowledge
    answer_from_kb = (
        "Not found in knowledge base" not in answer
        and "--- General Knowledge ---" not in answer
    )

    # Only return sources if answer came from KB
    if answer_from_kb:
        source_urls = list(
            set([m.get("source", "") for m in metadatas if m.get("source")])
        )
    else:
        source_urls = []  # no sources shown for General Knowledge answers

    return {
        "answer": answer,
        "sources": source_urls,
        "chunks": [
            {
                "source": meta.get("source", "unknown"),
                "score": score,
                "preview": doc[:200],
            }
            for doc, meta, score in zip(documents, metadatas, scores)
        ],
    }


def format_query_reply(result: dict) -> str:
    if not result.get("success"):
        return result.get("error", "Query failed.")
    reply = result.get("answer", "")
    sources = result.get("sources") or result.get("source_urls") or []
    if sources:
        reply += "\n\nSources:\n" + "\n".join(f"- {s}" for s in sources)
    return reply


def knowledge_base_is_empty() -> bool:
    return get_collection().count() == 0


def query_knowledge_base(question: str, filter_type: str = None, filter_url: str = None) -> dict:
    clean_question = (question or "").strip()
    if not clean_question:
        return {
            "success": False,
            "answer": "",
            "source_urls": [],
            "similarity_scores": [],
            "debug_chunks": [],
            "error": "Please enter a question.",
        }
    try:
        result = query_rag(clean_question, filter_type=filter_type, filter_url=filter_url)
        chunks = result.get("chunks", [])
        sources_list = result.get("sources", [])
        return {
            "success": True,
            "answer": result.get("answer", ""),
            "source_urls": sources_list,
            "sources": sources_list,
            "similarity_scores": [c.get("score") for c in chunks],
            "debug_chunks": [
                {
                    "index": i + 1,
                    "source": c.get("source", "unknown"),
                    "score": c.get("score"),
                    "preview": c.get("preview", ""),
                }
                for i, c in enumerate(chunks)
            ],
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "answer": "",
            "source_urls": [],
            "similarity_scores": [],
            "debug_chunks": [],
            "error": f"Query failed: {str(exc)}",
        }
