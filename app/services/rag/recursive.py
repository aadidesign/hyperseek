import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.rag.generator import (
    build_source_list,
    generate_answer,
    generate_follow_up_queries,
)
from app.services.rag.retriever import RetrievedContext, retrieve_context

logger = logging.getLogger("hyperseek.rag.recursive")


async def recursive_rag(
    query: str,
    db: AsyncSession,
    max_depth: int = 2,
    top_k: int = 5,
) -> dict:
    """Recursive RAG: iteratively refine the answer by generating sub-queries.

    Algorithm:
    1. Retrieve context for the original query
    2. Generate an initial answer
    3. Ask the LLM to generate follow-up queries
    4. Retrieve additional context for each follow-up query
    5. Combine all context and generate a final, more comprehensive answer
    6. Repeat up to max_depth times

    Returns:
        {
            "answer": str,
            "sources": list[dict],
            "model": str,
            "depth_reached": int,
            "queries_executed": list[str],
        }
    """
    all_contexts: list[RetrievedContext] = []
    queries_executed: list[str] = [query]
    current_answer = ""
    depth = 0

    # Initial retrieval
    contexts = await retrieve_context(query, db, top_k=top_k)
    all_contexts.extend(contexts)

    # Generate initial answer
    result = await generate_answer(query, contexts)
    current_answer = result["answer"]

    # Recursive refinement
    while depth < max_depth:
        depth += 1
        logger.info("Recursive RAG depth %d for query: %s", depth, query)

        # Generate follow-up queries
        follow_ups = await generate_follow_up_queries(query, current_answer)
        if not follow_ups:
            logger.info("No follow-up queries generated at depth %d", depth)
            break

        # Retrieve context for each follow-up
        new_contexts = []
        for fq in follow_ups:
            queries_executed.append(fq)
            fq_contexts = await retrieve_context(fq, db, top_k=3)
            new_contexts.extend(fq_contexts)

        if not new_contexts:
            break

        # Deduplicate contexts
        seen_ids = {c.document_id for c in all_contexts}
        for ctx in new_contexts:
            if ctx.document_id not in seen_ids:
                all_contexts.append(ctx)
                seen_ids.add(ctx.document_id)

        # Regenerate answer with all accumulated context
        # Take the top_k * 2 most relevant
        all_contexts.sort(key=lambda c: c.relevance_score, reverse=True)
        best_contexts = all_contexts[: top_k * 2]

        result = await generate_answer(query, best_contexts)
        current_answer = result["answer"]

    return {
        "answer": current_answer,
        "sources": build_source_list(all_contexts[:10]),  # Cap sources in response
        "model": result.get("model", ""),
        "depth_reached": depth,
        "queries_executed": queries_executed,
    }
