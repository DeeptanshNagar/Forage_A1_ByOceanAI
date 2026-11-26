"""Load PDF / TXT / MD / DOCX / CSV files into Documents with page / heading / row provenance."""
from __future__ import annotations

import csv
import io
import re
from pathlib import Path

from ..schemas import Document, Section

SUPPORTED = {".pdf", ".txt", ".md", ".markdown", ".docx", ".csv"}
MAX_CHARS_PER_FILE = 3_000_000  # huge files are truncated with a warning (streamed read)
MAX_CSV_ROWS = 50_000


class IngestError(RuntimeError):
    pass


_MD_HEADING = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")


def _looks_like_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 90 or s.endswith((".", ",", ";", ":")):
        return False
    if re.match(r"^(\d+(\.\d+)*[.)]?|[A-Z]\d+\.|[IVX]+\.|section\s+\d+|article\s+\d+)\s+[A-ZÀ-ɏ]", s, re.I if s[:7].lower() in ("section", "article") else 0):
        return len(s.split()) <= 12
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and s.isupper() and len(s.split()) <= 10


def _split_by_headings(text: str, page: int | None = None, md: bool = False,
                       current: str | None = None) -> tuple[list[Section], str | None]:
    sections: list[Section] = []
    buf: list[str] = []
    heading = current

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(Section(text=body, page=page, heading=heading))
        buf.clear()

    for line in text.splitlines():
        m = _MD_HEADING.match(line) if md else None
        if m:
            flush()
            heading = m.group(2).strip()
            continue
        if not md and _looks_like_heading(line):
            flush()
            heading = line.strip()
            continue
        buf.append(line)
    flush()
    return sections, heading


def _read_text(path: Path, warnings: list[str]) -> str:
    size = path.stat().st_size
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        text = f.read(MAX_CHARS_PER_FILE + 1)
    if len(text) > MAX_CHARS_PER_FILE:
        warnings.append(f"{path.name}: file is very large ({size} bytes); only the first {MAX_CHARS_PER_FILE} chars were ingested")
        text = text[:MAX_CHARS_PER_FILE]
    if "�" in text[:5000]:
        warnings.append(f"{path.name}: contains undecodable bytes (not UTF-8?)")
    return text


def load_pdf(path: Path) -> Document:
    from pypdf import PdfReader

    warnings: list[str] = []
    sections: list[Section] = []
    try:
        reader = PdfReader(str(path))
    except Exception as e:  # noqa: BLE001
        return Document(name=path.name, path=str(path), type="pdf", warnings=[f"{path.name}: unreadable PDF ({e})"],
                        size_bytes=path.stat().st_size)
    heading = None
    total = 0
    empty_pages = 0
    for i, page in enumerate(reader.pages, start=1):
        try:
            txt = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            txt = ""
        if len(txt.strip()) < 20:
            empty_pages += 1
            continue
        total += len(txt)
        if total > MAX_CHARS_PER_FILE:
            warnings.append(f"{path.name}: truncated at page {i} (very large PDF)")
            break
        secs, heading = _split_by_headings(txt, page=i, current=heading)
        sections.extend(secs)
    n = len(reader.pages)
    if not sections:
        warnings.append(f"{path.name}: no extractable text in {n} page(s) - scanned/image-only PDF? (OCR not supported); file skipped")
    elif empty_pages:
        warnings.append(f"{path.name}: {empty_pages}/{n} page(s) had no extractable text (scanned pages?)")
    return Document(name=path.name, path=str(path), type="pdf", sections=sections, warnings=warnings,
                    size_bytes=path.stat().st_size)


def load_docx(path: Path) -> Document:
    import docx

    warnings: list[str] = []
    try:
        d = docx.Document(str(path))
    except Exception as e:  # noqa: BLE001
        return Document(name=path.name, path=str(path), type="docx", warnings=[f"{path.name}: unreadable DOCX ({e})"],
                        size_bytes=path.stat().st_size)
    sections: list[Section] = []
    heading = None
    buf: list[str] = []

    def flush() -> None:
        body = "\n".join(buf).strip()
        if body:
            sections.append(Section(text=body, heading=heading))
        buf.clear()

    for p in d.paragraphs:
        style = (p.style.name or "").lower() if p.style is not None else ""
        txt = p.text.strip()
        if not txt:
            continue
        if style.startswith("heading") or style == "title":
            flush()
            heading = txt
        else:
            buf.append(txt)
    flush()
    for ti, table in enumerate(d.tables, start=1):
        rows = []
        for r in table.rows:
            rows.append(" | ".join(c.text.strip() for c in r.cells))
        if rows:
            sections.append(Section(text="\n".join(rows), heading=f"Table {ti}"))
    if not sections:
        warnings.append(f"{path.name}: DOCX contains no text")
    return Document(name=path.name, path=str(path), type="docx", sections=sections, warnings=warnings,
                    size_bytes=path.stat().st_size)


def load_csv(path: Path) -> Document:
    warnings: list[str] = []
    raw = _read_text(path, warnings)
    try:
        dialect = csv.Sniffer().sniff(raw[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.reader(io.StringIO(raw), dialect)
    rows = list(reader)
    if not rows:
        return Document(name=path.name, path=str(path), type="csv", warnings=[f"{path.name}: empty CSV"],
                        size_bytes=path.stat().st_size)
    header = [h.strip() or f"col_{i}" for i, h in enumerate(rows[0])]
    sections = []
    for i, r in enumerate(rows[1: MAX_CSV_ROWS + 1], start=1):
        if not any(c.strip() for c in r):
            continue
        pairs = [f"{h}: {v.strip()}" for h, v in zip(header, r)]
        sections.append(Section(text="; ".join(pairs), row=i))
    if len(rows) - 1 > MAX_CSV_ROWS:
        warnings.append(f"{path.name}: only the first {MAX_CSV_ROWS} rows were ingested")
    return Document(name=path.name, path=str(path), type="csv", sections=sections, warnings=warnings,
                    csv_columns=header, size_bytes=path.stat().st_size)


def load_text(path: Path) -> Document:
    warnings: list[str] = []
    text = _read_text(path, warnings)
    md = path.suffix.lower() in (".md", ".markdown")
    sections, _ = _split_by_headings(text, md=md)
    if not sections:
        warnings.append(f"{path.name}: file is empty")
    return Document(name=path.name, path=str(path), type="md" if md else "txt", sections=sections, warnings=warnings,
                    size_bytes=path.stat().st_size)


def load_file(path: Path) -> Document:
    ext = path.suffix.lower()
    if ext == ".pdf":
        return load_pdf(path)
    if ext == ".docx":
        return load_docx(path)
    if ext == ".csv":
        return load_csv(path)
    return load_text(path)


def list_files(folder: str | Path) -> list[Path]:
    p = Path(folder)
    if p.is_file():
        return [p]
    if not p.exists():
        raise IngestError(f"documents folder not found: {p}")
    return sorted(f for f in p.rglob("*") if f.is_file() and f.suffix.lower() in SUPPORTED and not f.name.startswith("."))


def load_folder(folder: str | Path) -> tuple[list[Document], list[str]]:
    """Returns (documents with text, warnings). Raises IngestError with a helpful message if nothing usable."""
    p = Path(folder)
    files = list_files(p)
    warnings: list[str] = []
    if p.is_dir():
        skipped = [f.name for f in p.rglob("*") if f.is_file() and f.suffix.lower() not in SUPPORTED]
        if skipped:
            warnings.append(f"skipped unsupported file types: {', '.join(skipped[:10])}")
    if not files:
        raise IngestError(f"no supported documents in '{p}'. Supported types: {', '.join(sorted(SUPPORTED))}. "
                          "Add at least one PDF/TXT/MD/DOCX/CSV file.")
    docs = []
    for f in files:
        d = load_file(f)
        warnings.extend(d.warnings)
        if d.sections:
            docs.append(d)
    if not docs:
        raise IngestError(f"none of the {len(files)} file(s) in '{p}' contained extractable text. Warnings: {warnings}")
    return docs, warnings
