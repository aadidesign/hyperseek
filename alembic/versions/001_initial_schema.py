"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enable extensions
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Documents
    op.create_table(
        "documents",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("url", sa.Text(), nullable=False, unique=True),
        sa.Column("title", sa.Text()),
        sa.Column("raw_content", sa.Text()),
        sa.Column("clean_content", sa.Text()),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("source_metadata", JSONB()),
        sa.Column("crawled_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("indexed_at", sa.DateTime(timezone=True)),
        sa.Column("word_count", sa.Integer()),
        sa.Column("language", sa.String(10), server_default="en"),
    )
    op.create_index("ix_documents_url", "documents", ["url"])
    op.create_index("ix_documents_source", "documents", ["source"])

    # Inverted Index
    op.create_table(
        "inverted_index",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("term", sa.String(255), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("term_frequency", sa.Integer(), nullable=False),
        sa.Column("positions", sa.ARRAY(sa.Integer())),
        sa.UniqueConstraint("term", "document_id", name="uq_term_document"),
    )
    op.create_index("ix_inverted_index_term", "inverted_index", ["term"])
    op.create_index("ix_inverted_index_document_id", "inverted_index", ["document_id"])

    # Document Stats
    op.create_table(
        "document_stats",
        sa.Column("document_id", UUID(as_uuid=True), primary_key=True),
        sa.Column("total_terms", sa.Integer(), nullable=False),
        sa.Column("unique_terms", sa.Integer(), nullable=False),
    )

    # Collection Stats
    op.create_table(
        "collection_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("total_documents", sa.Integer(), server_default="0"),
        sa.Column("avg_document_length", sa.Float(), server_default="0.0"),
    )
    # Insert singleton row
    op.execute("INSERT INTO collection_stats (id, total_documents, avg_document_length) VALUES (1, 0, 0.0)")

    # Document Embeddings (pgvector)
    op.create_table(
        "document_embeddings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_text", sa.Text(), nullable=False),
        sa.UniqueConstraint("document_id", "chunk_index", name="uq_doc_chunk"),
    )
    op.create_index("ix_document_embeddings_document_id", "document_embeddings", ["document_id"])
    # Add vector column via raw SQL (Alembic doesn't natively handle pgvector types)
    op.execute("ALTER TABLE document_embeddings ADD COLUMN embedding vector(384)")

    # Query Logs
    op.create_table(
        "query_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("api_key_id", UUID(as_uuid=True)),
        sa.Column("search_type", sa.String(20)),
        sa.Column("results_count", sa.Integer()),
        sa.Column("latency_ms", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_query_logs_query_text", "query_logs", ["query_text"])
    op.create_index("ix_query_logs_created_at", "query_logs", ["created_at"])

    # Click Events
    op.create_table(
        "click_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("query_log_id", UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_click_events_query_log_id", "click_events", ["query_log_id"])
    op.create_index("ix_click_events_document_id", "click_events", ["document_id"])

    # API Keys
    op.create_table(
        "api_keys",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("tier", sa.String(20), server_default="free"),
        sa.Column("rate_limit", sa.Integer(), server_default="100"),
        sa.Column("daily_quota", sa.Integer(), server_default="1000"),
        sa.Column("is_active", sa.Boolean(), server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])

    # Crawl Jobs
    op.create_table(
        "crawl_jobs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("source", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), server_default="pending"),
        sa.Column("config", JSONB()),
        sa.Column("documents_found", sa.Integer(), server_default="0"),
        sa.Column("documents_indexed", sa.Integer(), server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_crawl_jobs_source", "crawl_jobs", ["source"])
    op.create_index("ix_crawl_jobs_status", "crawl_jobs", ["status"])

    # Autocomplete Terms
    op.create_table(
        "autocomplete_terms",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("term", sa.String(255), nullable=False, unique=True),
        sa.Column("frequency", sa.Integer(), server_default="1"),
        sa.Column("source", sa.String(20), server_default="query"),
    )
    # Trigram index for prefix matching
    op.execute(
        "CREATE INDEX ix_autocomplete_terms_trgm ON autocomplete_terms USING gin (term gin_trgm_ops)"
    )


def downgrade() -> None:
    op.drop_table("autocomplete_terms")
    op.drop_table("crawl_jobs")
    op.drop_table("api_keys")
    op.drop_table("click_events")
    op.drop_table("query_logs")
    op.drop_table("document_embeddings")
    op.drop_table("collection_stats")
    op.drop_table("document_stats")
    op.drop_table("inverted_index")
    op.drop_table("documents")
