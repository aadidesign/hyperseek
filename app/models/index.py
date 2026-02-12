import uuid

from sqlalchemy import BigInteger, Float, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InvertedIndex(Base):
    __tablename__ = "inverted_index"
    __table_args__ = (
        UniqueConstraint("term", "document_id", name="uq_term_document"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False, index=True
    )
    term_frequency: Mapped[int] = mapped_column(Integer, nullable=False)
    positions: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))


class DocumentStats(Base):
    __tablename__ = "document_stats"

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    total_terms: Mapped[int] = mapped_column(Integer, nullable=False)
    unique_terms: Mapped[int] = mapped_column(Integer, nullable=False)


class CollectionStats(Base):
    __tablename__ = "collection_stats"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    total_documents: Mapped[int] = mapped_column(Integer, default=0)
    avg_document_length: Mapped[float] = mapped_column(Float, default=0.0)
