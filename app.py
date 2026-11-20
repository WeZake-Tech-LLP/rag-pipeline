"""Streamlit app for a local URL-ingested RAG knowledge base."""

from __future__ import annotations

from html import escape
from typing import Optional

import streamlit as st

from ingest import ingest_url, list_ingested_sources, remove_source
from query import knowledge_base_is_empty, query_knowledge_base


def _icon_for_type(source_type: str) -> str:
    if source_type == "youtube":
        return "🎥"
    if source_type == "linkedin":
        return "💼"
    if source_type == "reddit":
        return "👽"
    if source_type == "x":
        return "🐦"
    if source_type == "facebook":
        return "📘"
    if source_type == "instagram":
        return "📷"
    if source_type == "github":
        return "🐙"
    return "📄"


def _truncate_url(url: str, max_len: int = 55) -> str:
    if len(url) <= max_len:
        return url
    return url[: max_len - 3] + "..."


def _normalize_filter_type(ui_value: str) -> Optional[str]:
    mapping = {
        "All": None,
        "YouTube": "youtube",
        "LinkedIn": "linkedin",
        "Reddit": "reddit",
        "X": "x",
        "Facebook": "facebook",
        "Instagram": "instagram",
        "GitHub": "github",
        "Article": "article",
    }
    return mapping.get(ui_value)


st.set_page_config(page_title="RAG Knowledge Base", page_icon="🧠", layout="wide")

# -----------------------------
# Sidebar: Knowledge Base manager
# -----------------------------
with st.sidebar:
    st.title("Knowledge Base")
    url_input = st.text_input("Enter URL to ingest", placeholder="https://example.com/article")

    if st.button("Add to Knowledge Base", use_container_width=True):
        with st.spinner("Ingesting URL into ChromaDB..."):
            result = ingest_url(url_input)
        if result.get("success") and result.get("duplicate"):
            st.warning("URL already exists in knowledge base")
        elif result.get("success"):
            st.success(
                "Added successfully. "
                f"Chunks: {result.get('chunks_stored', 0)} | "
                f"Extraction quality: {result.get('extraction_quality', 'unknown')}"
            )
        else:
            st.error(result.get("message", "Ingestion failed."))

    st.divider()
    st.subheader("Ingested Sources")

    try:
        sources = list_ingested_sources()
        if not sources:
            st.caption("No sources yet.")
        else:
            for src in sources:
                source_type = src.get("type", "article")
                source_url = src.get("source", "")
                icon = _icon_for_type(source_type)
                truncated = _truncate_url(source_url)
                col_link, col_remove = st.columns([6, 1])
                col_link.markdown(f"{icon} [{truncated}]({source_url})")
                if col_remove.button("X", key=f"remove_{source_url}", help="Remove this source", use_container_width=True):
                    remove_source(source_url)
                    st.toast(f"Removed {truncated}")
                    st.rerun()
    except Exception:
        st.caption("Could not load ingested sources.")

# -----------------------------
# Main area: Query interface
# -----------------------------
st.title("Ask Your Knowledge Base")
question = st.text_area("Ask a question...", height=140, placeholder="What does this source say about ...?")

with st.expander("Advanced Filters (optional)"):
    ui_filter_type = st.selectbox("Filter by type", ["All", "YouTube", "LinkedIn", "Reddit", "X", "Facebook", "Instagram", "GitHub", "Article"])
    filter_url = st.text_input("Filter by exact URL (optional)", placeholder="https://...")

if knowledge_base_is_empty():
    st.info("No URLs ingested yet. Add some links in the sidebar to get started.")

if st.button("Ask", type="primary"):
    if not question.strip():
        st.warning("Please enter a question first.")
    elif knowledge_base_is_empty():
        st.info("No URLs ingested yet. Add some links in the sidebar to get started.")
    else:
        with st.spinner("Retrieving relevant chunks and generating answer..."):
            query_result = query_knowledge_base(
                question=question,
                filter_type=_normalize_filter_type(ui_filter_type),
                filter_url=filter_url.strip() or None,
            )

        if not query_result.get("success"):
            st.error(query_result.get("error", "Query failed."))
        else:
            st.markdown("### Answer")
            answer = query_result.get("answer", "")
            answer_display = answer.replace(
                "--- General Knowledge ---",
                "\n🔍 General Knowledge\n",
            )
            answer_html = escape(answer_display).replace("\n", "<br/>")
            st.markdown(
                f"""
                <div style="
                    background-color: #1e1e1e;
                    color: #e8e8e8;
                    padding: 1.5rem 2rem;
                    border-radius: 8px;
                    border-left: 3px solid #00ff88;
                    font-size: 18px;
                    line-height: 1.8;
                    text-align: left;
                    white-space: normal;
                    word-wrap: break-word;
                    font-family: 'Segoe UI', sans-serif;
                    letter-spacing: 0.01em;
                ">
                    <div style="text-align: left; margin: 0;">{answer_html}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            result_sources = query_result.get("sources") or query_result.get(
                "source_urls", []
            )
            if result_sources:
                st.markdown("### Sources used:")
                for url in result_sources:
                    st.markdown(f"- [{url}]({url})")
            else:
                st.markdown(
                    "<p style='color:#888; font-size:14px;'>"
                    "Answered from general knowledge — no KB sources used."
                    "</p>",
                    unsafe_allow_html=True,
                )

            with st.expander("Retrieved chunks & scores"):
                chunks = query_result.get("debug_chunks", [])
                if not chunks:
                    st.write("No chunks retrieved.")
                else:
                    for chunk in chunks:
                        st.write(
                            f"Chunk {chunk.get('index')} | "
                            f"Score: {chunk.get('score')} | "
                            f"Source: {chunk.get('source')}"
                        )
                        st.caption(chunk.get("preview", ""))
