import logging
from typing import AsyncIterator

import ollama as ollama_client

from app.config import settings
from app.services.rag.retriever import RetrievedContext

logger = logging.getLogger("hyperseek.rag.generator")

SYSTEM_PROMPT = """You are a knowledgeable search assistant. Your job is to answer user questions 
based strictly on the provided context. Follow these rules:

1. Only use information from the provided context to answer
2. If the context doesn't contain enough information, say so clearly
3. Cite your sources by referencing the document titles and URLs
4. Be concise but thorough
5. If multiple sources agree, synthesize them into a coherent answer
6. If sources conflict, mention both perspectives"""

ANSWER_TEMPLATE = """Context from search results:

{context}

---

User Question: {query}

Provide a comprehensive answer based on the context above. Cite sources using [Title](URL) format."""

RECURSIVE_TEMPLATE = """Based on the initial answer and context, generate 2-3 follow-up search queries 
that would help provide a more complete answer to the original question.

Original question: {query}
Current answer: {current_answer}

Return ONLY the follow-up queries, one per line. No numbering, no explanations."""


def build_context_block(contexts: list[RetrievedContext]) -> str:
    """Format retrieved contexts into a text block for the LLM prompt."""
    blocks = []
    for i, ctx in enumerate(contexts, 1):
        block = f"[Source {i}] {ctx.title}\nURL: {ctx.url}\nContent: {ctx.chunk_text}"
        blocks.append(block)
    return "\n\n".join(blocks)


def build_source_list(contexts: list[RetrievedContext]) -> list[dict]:
    """Build a structured source list for the API response."""
    return [
        {
            "document_id": ctx.document_id,
            "title": ctx.title,
            "url": ctx.url,
            "source": ctx.source,
            "relevance_score": round(ctx.relevance_score, 4),
        }
        for ctx in contexts
    ]


async def generate_answer(
    query: str,
    contexts: list[RetrievedContext],
) -> dict:
    """Generate an LLM answer using retrieved context via Ollama.

    Returns:
        {
            "answer": str,
            "sources": list[dict],
            "model": str,
        }
    """
    if not contexts:
        return {
            "answer": "I couldn't find any relevant information to answer your question.",
            "sources": [],
            "model": settings.llm_model,
        }

    context_block = build_context_block(contexts)
    prompt = ANSWER_TEMPLATE.format(context=context_block, query=query)

    try:
        client = ollama_client.Client(host=settings.ollama_base_url)
        response = client.chat(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        )
        answer = response["message"]["content"]
    except Exception as e:
        logger.error("Ollama generation failed: %s", e)
        # Fallback: return a summary of the context
        answer = _fallback_answer(query, contexts)

    return {
        "answer": answer,
        "sources": build_source_list(contexts),
        "model": settings.llm_model,
    }


async def generate_answer_stream(
    query: str,
    contexts: list[RetrievedContext],
) -> AsyncIterator[str]:
    """Stream an LLM answer token by token for real-time display.

    Yields individual tokens as they're generated.
    """
    if not contexts:
        yield "I couldn't find any relevant information to answer your question."
        return

    context_block = build_context_block(contexts)
    prompt = ANSWER_TEMPLATE.format(context=context_block, query=query)

    try:
        client = ollama_client.Client(host=settings.ollama_base_url)
        stream = client.chat(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            stream=True,
        )
        for chunk in stream:
            token = chunk["message"]["content"]
            if token:
                yield token
    except Exception as e:
        logger.error("Ollama streaming failed: %s", e)
        yield _fallback_answer(query, contexts)


async def generate_follow_up_queries(
    query: str,
    current_answer: str,
) -> list[str]:
    """Ask the LLM to generate follow-up search queries for recursive RAG."""
    prompt = RECURSIVE_TEMPLATE.format(query=query, current_answer=current_answer)

    try:
        client = ollama_client.Client(host=settings.ollama_base_url)
        response = client.chat(
            model=settings.llm_model,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response["message"]["content"]
        queries = [line.strip() for line in raw.strip().split("\n") if line.strip()]
        return queries[:3]  # Cap at 3 follow-up queries
    except Exception as e:
        logger.error("Failed to generate follow-up queries: %s", e)
        return []


def _fallback_answer(query: str, contexts: list[RetrievedContext]) -> str:
    """Generate a simple answer without LLM when Ollama is unavailable."""
    parts = [f"Here's what I found about '{query}':\n"]
    for ctx in contexts[:3]:
        parts.append(f"- **{ctx.title}** ({ctx.url}): {ctx.chunk_text[:200]}...")
    parts.append("\n(Note: LLM synthesis unavailable. Showing raw search results.)")
    return "\n".join(parts)
