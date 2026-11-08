# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Mateusz <109816464+FPGArtktic@users.noreply.github.com>
"""EPUB books: the pages and the outline the later stages read from a PDF.

An EPUB has no pages, so this module cuts its text into some. A page starts
at every target of the table of contents, which makes each bookmark begin a
page of its own, and wherever the text since the last start passes
``config.EPUB_PAGE_CHARS``, at the end of a paragraph. Chunking, written for
PDFs, then works unchanged: it reads pages, bookmarks and a page count.

The text needs no extraction model. Headings, paragraphs, lists and tables
come from the markup, and a listing comes as the publisher typed it: one
``<pre>`` or ``<p class="listing...">`` per line, joined here into one block.
Pictures are left out; their captions stay as text.
"""

from __future__ import annotations

import functools
import posixpath
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from html.entities import name2codepoint
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

from bs4 import BeautifulSoup, NavigableString, Tag

from app import config, log
from app import extract as extract_module
from app.pdf import Bookmark

HEADINGS = {f"h{level}": level for level in range(1, 7)}
# Elements whose content is one paragraph of text.
PARAGRAPHS = {"p", "dt", "dd", "figcaption", "caption", "summary"}
SKIPPED = {"head", "script", "style", "img", "svg", "image", "object", "video"}
LISTS = {"ul", "ol"}
# Elements that hold blocks rather than running text.
BLOCKS = [
    *HEADINGS,
    *PARAGRAPHS,
    *LISTS,
    "pre",
    "table",
    "div",
    "section",
    "article",
    "aside",
    "blockquote",
    "figure",
    "header",
    "footer",
    "nav",
    "li",
]
# "listing", "listing-1linia", "listing-wciety": the class of one line of a
# listing in a Helion book. "listing-podpis" is the caption above it.
LISTING_CLASS_RE = re.compile(r"^listing(?!.*podpis)")
# A page that names the buyer: a publisher's watermark. A chapter is longer.
WATERMARK_PAGE_MAX_CHARS = 1000
NAMED_ENTITY_RE = re.compile(r"&([A-Za-z][A-Za-z0-9]*);")
XML_ENTITIES = {"amp", "lt", "gt", "quot", "apos"}
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
CONTAINER = "META-INF/container.xml"


@dataclass
class Block:
    """One paragraph, heading, list item, table or listing, as markdown."""

    text: str
    code: bool = False
    anchors: set[str] = field(default_factory=set)


@dataclass(frozen=True)
class Entry:
    """A table of contents entry: its title, depth and target."""

    title: str
    level: int
    document: str
    anchor: str | None


@dataclass(frozen=True)
class Book:
    pages: tuple[str, ...]
    bookmarks: tuple[Bookmark, ...]


def is_epub(path: Path) -> bool:
    return path.suffix.lower() == ".epub"


def page_count(path: Path) -> int:
    return len(read(path).pages)


def read_toc(path: Path) -> list[Bookmark]:
    return list(read(path).bookmarks)


def page_text(path: Path, first_page: int, last_page: int) -> str:
    return "\n\n".join(read(path).pages[first_page - 1 : last_page])


def read(path: Path) -> Book:
    """The book's pages and bookmarks, read once per version of the file."""
    stat = path.stat()
    return _read(str(path), stat.st_mtime_ns, stat.st_size)


@functools.lru_cache(maxsize=4)
def _read(path: str, _mtime_ns: int, _size: int) -> Book:
    with zipfile.ZipFile(path) as archive:
        package = _package_path(archive)
        documents, entries = _spine_and_toc(archive, package)
        targets = _targets(entries)
        blocks: list[Block] = []
        for document in documents:
            found = list(_document_blocks(archive, document))
            if _is_watermark_page(found, document, targets):
                log.event("epub", "watermark page left out", document=document)
                continue
            if found:
                found[0].anchors.add(_target(document, None))
            blocks.extend(found)
    pages, starts = paginate(blocks, set(targets))
    bookmarks = tuple(
        Bookmark(entry.title, entry.level, starts[target])
        for entry in entries
        if (target := _resolve(entry, starts)) is not None
    )
    return Book(tuple(pages), bookmarks)


def paginate(
    blocks: list[Block], targets: set[str]
) -> tuple[list[str], dict[str, int]]:
    """Cut blocks into pages. Returns the pages and each target's page.

    Consecutive lines of a listing are joined into one fenced block first,
    so a page never ends inside a listing.
    """
    pages: list[str] = []
    starts: dict[str, int] = {}
    current: list[str] = []
    size = 0
    for block in _join_listings(blocks):
        opens = bool(block.anchors & targets)
        if current and (opens or size >= config.EPUB_PAGE_CHARS):
            pages.append("\n\n".join(current))
            current, size = [], 0
        for anchor in block.anchors:
            starts.setdefault(anchor, len(pages) + 1)
        current.append(block.text)
        size += len(block.text)
    if current:
        pages.append("\n\n".join(current))
    return pages, starts


def _join_listings(blocks: list[Block]) -> Iterator[Block]:
    lines: list[str] = []
    anchors: set[str] = set()
    for block in blocks:
        if block.code:
            lines.append(block.text)
            anchors |= block.anchors
            continue
        if lines:
            yield Block("```\n" + "\n".join(lines) + "\n```", True, anchors)
            lines, anchors = [], set()
        yield block
    if lines:
        yield Block("```\n" + "\n".join(lines) + "\n```", True, anchors)


def _is_watermark_page(blocks: list[Block], document: str, targets: dict) -> bool:
    if any(target[0] == document for target in targets.values()):
        return False
    text = "\n".join(block.text for block in blocks)
    return len(text) <= WATERMARK_PAGE_MAX_CHARS and EMAIL_RE.search(text) is not None


def _package_path(archive: zipfile.ZipFile) -> str:
    container = BeautifulSoup(archive.read(CONTAINER), "xml")
    rootfile = container.find("rootfile")
    if rootfile is None or not rootfile.get("full-path"):
        raise ValueError("EPUB without a package document")
    return str(rootfile["full-path"])


def _spine_and_toc(
    archive: zipfile.ZipFile, package: str
) -> tuple[list[str], list[Entry]]:
    """The documents in reading order, and the table of contents."""
    base = posixpath.dirname(package)
    opf = BeautifulSoup(archive.read(package), "xml")
    manifest = {
        item["id"]: item
        for item in opf.find_all("item")
        if item.get("id") and item.get("href")
    }
    documents = [
        _join(base, manifest[ref["idref"]]["href"])
        for ref in opf.find_all("itemref")
        if ref.get("idref") in manifest and ref.get("linear", "yes") != "no"
    ]
    nav = next(
        (item for item in manifest.values() if "nav" in item.get("properties", "")),
        None,
    )
    ncx = next(
        (
            item
            for item in manifest.values()
            if item.get("media-type") == "application/x-dtbncx+xml"
        ),
        None,
    )
    if ncx is not None:
        path = _join(base, ncx["href"])
        entries = _ncx_entries(archive.read(path), posixpath.dirname(path))
    elif nav is not None:
        path = _join(base, nav["href"])
        entries = _nav_entries(archive.read(path), posixpath.dirname(path))
    else:
        entries = []
    return documents, entries


def _ncx_entries(data: bytes, base: str) -> list[Entry]:
    soup = BeautifulSoup(data, "xml")
    entries: list[Entry] = []
    for point in soup.find_all("navPoint"):
        label = point.find("text")
        content = point.find("content")
        if label is None or content is None or not content.get("src"):
            continue
        level = len(point.find_parents("navPoint"))
        entries.append(_entry(label.get_text(), level, base, str(content["src"])))
    return entries


def _nav_entries(data: bytes, base: str) -> list[Entry]:
    soup = BeautifulSoup(data, "xml")
    toc = next(
        (
            nav
            for nav in soup.find_all("nav")
            if any(
                value.endswith("type") and "toc" in str(nav[value])
                for value in nav.attrs
            )
        ),
        soup.find("nav"),
    )
    if toc is None:
        return []
    return [
        _entry(
            link.get_text(), len(link.find_parents("ol")) - 1, base, str(link["href"])
        )
        for link in toc.find_all("a")
        if link.get("href")
    ]


def _entry(title: str, level: int, base: str, src: str) -> Entry:
    document, _, anchor = unquote(src).partition("#")
    return Entry(
        " ".join(title.split()), max(level, 0), _join(base, document), anchor or None
    )


def _join(base: str, href: str) -> str:
    return str(PurePosixPath(posixpath.normpath(posixpath.join(base, unquote(href)))))


def _target(document: str, anchor: str | None) -> str:
    return f"{document}#{anchor}" if anchor else document


def _targets(entries: list[Entry]) -> dict[str, tuple[str, str | None]]:
    return {
        _target(entry.document, entry.anchor): (entry.document, entry.anchor)
        for entry in entries
    }


def _resolve(entry: Entry, starts: dict[str, int]) -> str | None:
    """The entry's target, else the start of its document if the anchor is gone."""
    for target in (_target(entry.document, entry.anchor), entry.document):
        if target in starts:
            return target
    return None


def _document_blocks(archive: zipfile.ZipFile, document: str) -> Iterator[Block]:
    try:
        data = archive.read(document)
    except KeyError:
        log.event("epub", "spine document missing", document=document)
        return
    soup = BeautifulSoup(_numeric_entities(data), "xml")
    body = soup.find("body")
    if body is None:
        return
    pending = {_target(document, body["id"])} if body.get("id") else set()
    for block in _blocks(body, document, pending):
        block.anchors |= pending
        pending.clear()
        yield block


def _numeric_entities(data: bytes) -> str:
    """The document with HTML's named entities written as numbers.

    An XML parser knows five named entities. XHTML documents use the rest
    of HTML's too, "a&nbsp;standardowe" above all, and the parser drops what
    it does not know: the words on either side ran together.
    """
    return NAMED_ENTITY_RE.sub(_entity_number, data.decode("utf-8", "replace"))


def _entity_number(match: re.Match[str]) -> str:
    name = match.group(1)
    if name in XML_ENTITIES or name not in name2codepoint:
        return match.group(0)
    return f"&#{name2codepoint[name]};"


def _blocks(element: Tag, document: str, pending: set[str]) -> Iterator[Block]:
    """The blocks under ``element``. Anchors on the way wait for the next block."""
    for child in element.children:
        if isinstance(child, NavigableString):
            text = _squeeze(str(child))
            if text and element.name not in ("table", "tr", "tbody", "thead"):
                yield Block(text)
            continue
        if not isinstance(child, Tag) or child.name in SKIPPED:
            continue
        anchors = {_target(document, child["id"])} if child.get("id") else set()
        if child.name in HEADINGS:
            yield _with(
                Block(f"{'#' * HEADINGS[child.name]} {_inline(child)}"), child, document
            )
        elif child.name == "pre" or _is_listing_line(child):
            yield _with(Block(_code_line(child), code=True), child, document)
        elif child.name in PARAGRAPHS:
            text = _inline(child)
            if text:
                yield _with(Block(text), child, document)
            else:
                pending |= anchors | _inner_anchors(child, document)
        elif child.name in LISTS:
            pending |= anchors
            yield from _list_items(child, document, pending)
        elif child.name == "table":
            pending |= anchors
            yield from _table(child, document, pending)
        elif child.find(BLOCKS) is None:
            # Text in a container of its own: a <div> or <span> used as a
            # paragraph, or an empty <a id> that marks where a section starts.
            text = _inline(child)
            if text:
                yield _with(Block(text), child, document)
            else:
                pending |= anchors | _inner_anchors(child, document)
        else:
            pending |= anchors
            yield from _blocks(child, document, pending)


def _with(block: Block, element: Tag, document: str) -> Block:
    if element.get("id"):
        block.anchors.add(_target(document, element["id"]))
    block.anchors |= _inner_anchors(element, document)
    return block


def _inner_anchors(element: Tag, document: str) -> set[str]:
    return {
        _target(document, inner["id"])
        for inner in element.find_all(True)
        if inner.get("id")
    }


def _is_listing_line(element: Tag) -> bool:
    classes = element.get("class") or []
    if isinstance(classes, str):
        classes = classes.split()
    return element.name == "p" and any(LISTING_CLASS_RE.match(name) for name in classes)


def _code_line(element: Tag) -> str:
    """A listing's text as typed: spaces kept, line breaks kept."""
    parts = []
    for node in element.descendants:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif isinstance(node, Tag) and node.name == "br":
            parts.append("\n")
    return "".join(parts).replace("\u00a0", " ").rstrip("\n").rstrip()


def _inline(element: Tag) -> str:
    """Running text of an element. Exponents and indices keep their marks."""
    return _squeeze(_raw_inline(element))


def _raw_inline(element: Tag) -> str:
    # Spaces are squeezed once, over the whole paragraph: the one between
    # "że" and "standardowe" is inside the <span> that holds the second word.
    parts: list[str] = []
    for node in element.children:
        if isinstance(node, NavigableString):
            parts.append(str(node))
        elif not isinstance(node, Tag) or node.name in SKIPPED:
            continue
        elif node.name == "br":
            parts.append(" ")
        elif node.name == "sup":
            parts.append("^" + _bracket(_inline(node)))
        elif node.name == "sub":
            parts.append("_" + _bracket(_inline(node)))
        else:
            parts.append(_raw_inline(node))
    return "".join(parts)


def _bracket(text: str) -> str:
    return text if len(text) <= 1 else "{" + text + "}"


def _squeeze(text: str) -> str:
    return " ".join(text.replace("\u00a0", " ").split())


def _list_items(element: Tag, document: str, pending: set[str]) -> Iterator[Block]:
    numbered = element.name == "ol"
    for number, item in enumerate(element.find_all("li", recursive=False), start=1):
        marker = f"{number}." if numbered else "-"
        nested = [child for child in item.find_all(LISTS, recursive=False)]
        for child in nested:
            child.extract()
        text = _inline(item)
        if text:
            yield _with(Block(f"{marker} {text}"), item, document)
        for child in nested:
            for block in _list_items(child, document, pending):
                block.text = "  " + block.text
                yield block


def _table(element: Tag, document: str, pending: set[str]) -> Iterator[Block]:
    """A table of text as a markdown table; one holding listings, cell by cell."""
    rows = element.find_all("tr")
    cells = [row.find_all(["td", "th"], recursive=False) for row in rows]
    if any(
        cell.find("pre")
        or cell.find("table")
        or any(map(_is_listing_line, cell.find_all("p")))
        for row in cells
        for cell in row
    ):
        for row in cells:
            for cell in row:
                yield from _blocks(cell, document, pending)
        return
    box = _box_text_cell(cells)
    if box is not None:
        yield from _quoted(_blocks(box, document, pending))
        return
    lines = [
        "| " + " | ".join(_inline(cell).replace("|", "\\|") for cell in row) + " |"
        for row in cells
        if row
    ]
    if not lines:
        return
    width = max(len(row) for row in cells)
    lines.insert(1, "|" + " --- |" * width)
    yield _with(Block("\n".join(lines)), element, document)


def _box_text_cell(cells: list[list[Tag]]) -> Tag | None:
    """The text of a box set as a table: one row, text in one cell only.

    A publisher's template lays a tip out as an icon in one cell and the
    text in the next. As a markdown table it reads "|  | a paragraph |",
    and the model and ``verify`` treat it as data to copy row by row.
    """
    if len(cells) != 1:
        return None
    with_text = [cell for cell in cells[0] if _inline(cell)]
    return with_text[0] if len(with_text) == 1 else None


def _quoted(blocks: Iterator[Block]) -> Iterator[Block]:
    for block in blocks:
        block.text = "\n".join(f"> {line}" for line in block.text.splitlines())
        yield block


def extract(book_slug: str, path: Path) -> list[Path]:
    """Write the book's pages where extraction writes a PDF's. Returns them."""
    book = read(path)
    written = []
    for number, text in enumerate(book.pages, start=1):
        target = extract_module.page_markdown_path(book_slug, number)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text.strip() + "\n", encoding="utf-8")
        written.append(target)
    log.event(
        "epub",
        "pages written",
        book=book_slug,
        pages=len(book.pages),
        bookmarks=len(book.bookmarks),
    )
    return written
