"""Read local reports without executing scripts, formulas, or external links."""

import csv
import io
import json
import re
from html.parser import HTMLParser
from itertools import chain, islice
from xml.etree import ElementTree as ET
from zipfile import ZipFile


REPORT_SUFFIXES = {".csv", ".tsv", ".json", ".jsonl", ".ndjson", ".txt", ".md", ".log",
                   ".html", ".htm", ".pdf", ".docx", ".xlsx", ".xml"}
DOCUMENT_CONTAINERS = {".docx", ".xlsx"}
MAX_ITEMS = 20_000
MAX_XML = 8 * 1024 * 1024
MAX_PDF_PAGES = 60
MAX_TEXT = 2 * 1024 * 1024


class ReportFormatError(ValueError):
    pass


def local_tag(tag):
    return tag.rsplit("}", 1)[-1]


def parse_xml(data):
    # UTF-16/32 XML can contain NUL bytes before the declaration's letters.
    probe = data.replace(b"\x00", b"").upper()
    if b"<!DOCTYPE" in probe or b"<!ENTITY" in probe:
        raise ReportFormatError("XML with an entity or document type declaration was skipped.")
    return ET.fromstring(data)


def office_xml(archive, member):
    with archive.open(member) as stream:
        data = stream.read(MAX_XML + 1)
    if len(data) > MAX_XML:
        raise ReportFormatError("An Office document section exceeded the local parsing limit.")
    return parse_xml(data)


def decode_text(data):
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeError:
        if b"\x00" in data:
            raise ReportFormatError("The file did not contain readable text.") from None
        return data.decode("cp1252")


def structured_rows(value, label):
    """Walk nested report objects with a bound on the number of visited objects."""
    stack = [iter([value])]
    for index in range(1, MAX_ITEMS + 1):
        while stack:
            item = next(stack[-1], None)
            if item is not None:
                break
            stack.pop()
        else:
            return
        if isinstance(item, dict):
            yield f"{label} {index}", item
            stack.append(iter(value for value in item.values() if isinstance(value, (dict, list))))
        elif isinstance(item, list):
            stack.append(iter(value for value in item if isinstance(value, (dict, list))))


def table_rows(rows, label):
    numbered = enumerate(rows, 1)
    prefix = list(islice(numbered, 12))
    nonempty = [(index, row) for index, row in prefix if any(cell.strip() for cell in row)]
    if not nonempty:
        return
    header_index, row = next(((index, value) for index, value in nonempty if sum(bool(cell.strip()) for cell in value) >= 2),
                             nonempty[0])
    headers = [cell.strip() for cell in row]
    remaining = chain(((index, value) for index, value in prefix if index > header_index), numbered)
    for index, row in islice(remaining, MAX_ITEMS):
        if any(cell.strip() for cell in row):
            yield f"{label} {index}", dict(zip(headers, row))


class ReportHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.skip = False

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.skip = True
        elif not self.skip:
            if tag in {"p", "div", "li", "br", "tr", "h1", "h2", "h3", "h4"}:
                self.parts.append("\n")
            if tag in {"td", "th"}:
                self.parts.append("\t")

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.skip = False

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def text_sections(text, label):
    for index, line in islice(enumerate(io.StringIO(text[:MAX_TEXT]), 1), MAX_ITEMS):
        if line.strip():
            yield f"{label} {index}", line.strip()[:2000]


def docx_sections(data):
    with ZipFile(io.BytesIO(data)) as archive:
        document = office_xml(archive, "word/document.xml")
    for index, paragraph in enumerate(node for node in document.iter() if local_tag(node.tag) == "p"):
        if index >= MAX_ITEMS:
            break
        text = "".join(node.text or "" for node in paragraph.iter() if local_tag(node.tag) == "t")
        if text.strip():
            yield f"DOCX paragraph {index + 1}", text[:2000]
    for index, table in enumerate(node for node in document.iter() if local_tag(node.tag) == "tbl"):
        if index >= 16:
            break
        rows = ([" ".join(value.text or "" for value in cell.iter() if local_tag(value.tag) == "t")
                 for cell in row if local_tag(cell.tag) == "tc"]
                for row in table if local_tag(row.tag) == "tr")
        yield from table_rows(rows, f"DOCX table {index + 1}, row")


def excel_row(row, strings):
    cells = {}
    for cell in row:
        if local_tag(cell.tag) != "c":
            continue
        match = re.fullmatch(r"([A-Z]{1,2})\d+", cell.get("r", ""))
        if not match:
            continue
        column = 0
        for letter in match[1]:
            column = column * 26 + ord(letter) - 64
        if column > 128 or any(local_tag(child.tag) == "f" for child in cell):
            continue
        kind = cell.get("t")
        value = "".join(node.text or "" for node in cell.iter()
                        if local_tag(node.tag) == ("t" if kind == "inlineStr" else "v"))
        if kind == "s":
            value = strings[int(value)] if value.isdecimal() and len(value) < 8 and int(value) < len(strings) else ""
        cells[column] = value
    return [cells.get(position, "") for position in range(1, max(cells, default=0) + 1)]


def xlsx_sections(data):
    with ZipFile(io.BytesIO(data)) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            strings = ["".join(node.text or "" for node in entry.iter() if local_tag(node.tag) == "t")
                       for entry in office_xml(archive, "xl/sharedStrings.xml") if local_tag(entry.tag) == "si"]
        paths = sorted(name for name in archive.namelist() if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name))
        if not paths:
            raise ReportFormatError("No readable worksheets were found.")
        for index, path in enumerate(paths[:16], 1):
            worksheet = office_xml(archive, path)
            rows = (excel_row(row, strings) for row in worksheet.iter() if local_tag(row.tag) == "row")
            yield from table_rows(rows, f"Worksheet {index}, row")


def pdf_sections(data):
    try:
        from pypdf import PdfReader
        from pypdf.errors import PyPdfError
    except ImportError:
        raise ReportFormatError("PDF reading needs the local report dependencies listed in the README.") from None
    try:
        reader = PdfReader(io.BytesIO(data))
        if reader.is_encrypted:
            raise ReportFormatError("Encrypted PDFs need an unlocked copy before analysis.")
        readable = False
        for index, page in enumerate(islice(reader.pages, MAX_PDF_PAGES), 1):
            text = (page.extract_text() or "").strip()
            if text:
                readable = True
                yield from text_sections(text[:60_000], f"PDF page {index}, line")
        if not readable:
            raise ReportFormatError("No text was found in the PDF. Run local OCR and upload a searchable copy.")
    except PyPdfError:
        raise ReportFormatError("The PDF could not be read.") from None


def sections(data, suffix):
    if suffix == ".pdf":
        yield from pdf_sections(data)
    elif suffix == ".docx":
        yield from docx_sections(data)
    elif suffix == ".xlsx":
        yield from xlsx_sections(data)
    elif suffix == ".xml":
        root = parse_xml(data[:MAX_XML]) if len(data) <= MAX_XML else None
        if root is None:
            raise ReportFormatError("The XML report exceeded the local parsing limit.")
        for number, element in enumerate(islice(root.iter(), MAX_ITEMS), 1):
            fields = {local_tag(child.tag): child.text.strip()
                      for child in element if not len(child) and child.text and child.text.strip()}
            if fields:
                yield f"XML record {number}", fields
    else:
        text = decode_text(data)
        if suffix == ".json":
            yield from structured_rows(json.loads(text), "JSON object")
        elif suffix in {".jsonl", ".ndjson"}:
            for index, line in islice(enumerate(io.StringIO(text), 1), MAX_ITEMS):
                if line.strip():
                    value = json.loads(line)
                    if isinstance(value, dict):
                        yield f"JSON line {index}", value
        elif suffix in {".csv", ".tsv"}:
            delimiter = "\t" if suffix == ".tsv" else ","
            yield from table_rows(csv.reader(io.StringIO(text), delimiter=delimiter), "Table row")
        elif suffix in {".html", ".htm"}:
            parser = ReportHTML()
            parser.feed(text[:MAX_TEXT])
            plain = "".join(parser.parts)
            yield from text_sections(plain, "HTML line")
            if "\t" in plain:
                rows = (line.lstrip("\t").split("\t") for line in plain.splitlines() if "\t" in line)
                yield from table_rows(rows, "HTML table row")
        else:
            yield from text_sections(text, "Text line")
