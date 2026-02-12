from sqlalchemy import BigInteger, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AutocompleteTerm(Base):
    __tablename__ = "autocomplete_terms"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    term: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    frequency: Mapped[int] = mapped_column(Integer, default=1)
    source: Mapped[str] = mapped_column(String(20), default="query")  # query, title, content
