"""SQLAlchemy models. Decisions carry an integer rowid (`rid`) because the FTS5 external-content
table needs a stable rowid; the public identifier is the uuid in `id`."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Commune(Base):
    __tablename__ = "communes"

    bfs_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    name: Mapped[str] = mapped_column(String(120))
    canton: Mapped[str] = mapped_column(String(2), index=True)
    language: Mapped[str] = mapped_column(String(2))
    website: Mapped[str] = mapped_column(String(255))
    vendor: Mapped[str | None] = mapped_column(String(60))
    minutes_url: Mapped[str | None] = mapped_column(String(500))
    publicity_regime: Mapped[str | None] = mapped_column(String(60))
    last_crawled: Mapped[datetime | None] = mapped_column(DateTime)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)

    documents: Mapped[list[Document]] = relationship(back_populates="commune")


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    commune_bfs_id: Mapped[int] = mapped_column(ForeignKey("communes.bfs_id"), index=True)
    body: Mapped[str] = mapped_column(String(20))
    source_url: Mapped[str] = mapped_column(String(500))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    meeting_date: Mapped[date | None] = mapped_column(Date, index=True)
    language: Mapped[str] = mapped_column(String(2))
    pages: Mapped[int] = mapped_column(Integer)
    ocr: Mapped[bool] = mapped_column(Boolean, default=False)
    title: Mapped[str] = mapped_column(String(300))
    dropped_decisions: Mapped[int] = mapped_column(Integer, default=0)
    provenance: Mapped[str] = mapped_column(String(30), default="html_links")

    commune: Mapped[Commune] = relationship(back_populates="documents")
    decisions: Mapped[list[Decision]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Decision(Base):
    __tablename__ = "decisions"

    rid: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    document_id: Mapped[str] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    commune_bfs_id: Mapped[int] = mapped_column(ForeignKey("communes.bfs_id"))
    meeting_date: Mapped[date | None] = mapped_column(Date)
    agenda_no: Mapped[str | None] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(30))
    sensitive_topic: Mapped[str] = mapped_column(String(30), default="none")
    summary: Mapped[str] = mapped_column(Text)
    outcome: Mapped[str | None] = mapped_column(String(20))
    votes_for: Mapped[int | None] = mapped_column(Integer)
    votes_against: Mapped[int | None] = mapped_column(Integer)
    amount_chf: Mapped[float | None] = mapped_column(Float)
    refs: Mapped[list[str]] = mapped_column(JSON, default=list)
    office_holders: Mapped[list[str]] = mapped_column(JSON, default=list)
    page_start: Mapped[int] = mapped_column(Integer)
    page_end: Mapped[int] = mapped_column(Integer)
    confidence: Mapped[float | None] = mapped_column(Float)
    contains_private_individuals: Mapped[bool] = mapped_column(Boolean, default=False)
    redaction_applied: Mapped[bool] = mapped_column(Boolean, default=False)
    extraction_model: Mapped[str] = mapped_column(String(60))
    extraction_version: Mapped[str] = mapped_column(String(30))
    language: Mapped[str] = mapped_column(String(2))

    document: Mapped[Document] = relationship(back_populates="decisions")
    commune: Mapped[Commune] = relationship()

    __table_args__ = (
        Index("ix_decisions_commune_date", "commune_bfs_id", "meeting_date"),
        Index("ix_decisions_category", "category"),
        Index("ix_decisions_meeting_date", "meeting_date"),
    )


class HoldingRow(Base):
    """What the archive holds per commune and body, written by the processing stages; the server
    reads it. No foreign key: a body that was crawled and later removed from the configuration keeps
    its row."""

    __tablename__ = "holdings"

    commune_bfs_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    body: Mapped[str] = mapped_column(String(20), primary_key=True)
    kinds: Mapped[list[str]] = mapped_column(JSON, default=list)
    documents: Mapped[int] = mapped_column(Integer, default=0)
    undated: Mapped[int] = mapped_column(Integer, default=0)
    parsed: Mapped[int] = mapped_column(Integer, default=0)
    extracted: Mapped[int] = mapped_column(Integer, default=0)
    records: Mapped[int] = mapped_column(Integer, default=0)
    decisions: Mapped[int] = mapped_column(Integer, default=0)
    first_date: Mapped[date | None] = mapped_column(Date)
    last_date: Mapped[date | None] = mapped_column(Date)
    per_year: Mapped[dict] = mapped_column(JSON, default=dict)
    expected_interval_days: Mapped[float | None] = mapped_column(Float)
    gaps: Mapped[list[dict]] = mapped_column(JSON, default=list)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    listed_not_held: Mapped[int] = mapped_column(Integer, default=0)
    last_crawl: Mapped[datetime | None] = mapped_column(DateTime)
    last_result: Mapped[str | None] = mapped_column(String(40))
    health: Mapped[str] = mapped_column(String(20))
    register_status: Mapped[str | None] = mapped_column(String(30))
    register_note: Mapped[str | None] = mapped_column(Text)
    available_from: Mapped[str | None] = mapped_column(String(10))
    computed_at: Mapped[datetime] = mapped_column(DateTime)


class CatalogPDF(Base):
    """Browsable source documents, independent of extracted/published decisions."""

    __tablename__ = "pdf_catalog"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    commune_bfs_id: Mapped[int] = mapped_column(Integer, index=True)
    commune_name: Mapped[str] = mapped_column(String(120))
    canton: Mapped[str] = mapped_column(String(2), index=True)
    body: Mapped[str] = mapped_column(String(20))
    source_date: Mapped[date | None] = mapped_column(Date, index=True)
    date_precision: Mapped[str] = mapped_column(String(10), default="day")
    title: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    provenance: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(30), index=True)
    decision_count: Mapped[int] = mapped_column(Integer, default=0)
    indexed_at: Mapped[datetime] = mapped_column(DateTime)
