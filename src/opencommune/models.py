"""SQLAlchemy models of the main database: the communes and the internal catalogue of files.
The serving database the web server reads is written by `build.py` (`serving.sql`)."""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
    indexed_at: Mapped[datetime] = mapped_column(DateTime)


class CatalogCommune(Base):
    """Every commune that links a catalogued file. A file can belong to several communes (a joint
    body, a regional association) and a commune has many files (David, 2026-11-13).
    `pdf_catalog.commune_bfs_id` is the commune that fetched the file first."""

    __tablename__ = "pdf_catalog_communes"
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    commune_bfs_id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    source_url: Mapped[str | None] = mapped_column(Text)
