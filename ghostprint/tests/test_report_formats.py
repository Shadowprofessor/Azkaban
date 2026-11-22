import io
import json
import unittest
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZipFile

from ghostprint.audit import audit
from ghostprint.generic_evidence import generic_evidence


def zipped(members):
    output = io.BytesIO()
    with ZipFile(output, "w") as archive:
        for name, contents in members.items():
            archive.writestr(name, contents)
    return output.getvalue()


class GenericReportsTest(unittest.TestCase):
    def test_unknown_reports_merge_without_exposing_raw_values(self):
        with TemporaryDirectory() as directory:
            package = Path(directory) / "new-vendor.zip"
            package.write_bytes(zipped({
                "arbitrary/fields.json": json.dumps({"someVendorRows": [
                    {"latitude": 26.123456, "longitude": 75.654321, "permission": "camera", "state": "granted"}
                ]}),
                "flags.csv": "Email address\nclient@example.invalid\n",
                "audit.md": (
                    "Finding #12: Bank account numbers were exposed in a publicly accessible folder.\n"
                    "High risk: No camera permissions were granted.\n"
                    "Finding: The auditor recommends that IP addresses should never be logged.\n"
                ),
            }))
            report = audit([(package, None)])
        self.assertEqual(report["coverage"][0]["parsed_files"], 3)
        claims = {item["category"]: item for item in report["review"]["claims"]}
        self.assertEqual(set(claims), {"location", "contacts", "financial", "permissions"})
        self.assertEqual(claims["location"]["risk"]["level"], "High")
        self.assertEqual(claims["financial"]["risk"]["level"], "Medium")
        self.assertEqual(claims["financial"]["confidence"]["level"], "Medium")
        self.assertIn("Text line 1", claims["financial"]["evidence"][0]["source"])
        rendered = json.dumps(report)
        self.assertNotIn("client@example.invalid", rendered)
        self.assertNotIn("26.123456", rendered)
        self.assertNotIn("publicly accessible folder", rendered)

    def test_unknown_office_documents_are_read_as_reports(self):
        word = zipped({"word/document.xml": (
            '<w:document xmlns:w="urn:word"><w:body><w:p><w:r><w:t>'
            'Audit finding: Session tokens were exposed. '
            '</w:t></w:r></w:p></w:body></w:document>'
        )})
        excel = zipped({"xl/worksheets/sheet1.xml": (
            '<worksheet><sheetData><row><c r="A1" t="inlineStr"><is><t>IP Address</t></is></c></row>'
            '<row><c r="A2" t="inlineStr"><is><t>203.0.113.1</t></is></c></row>'
            '</sheetData></worksheet>'
        )})
        with TemporaryDirectory() as directory:
            paths = [Path(directory) / "Internal audit.docx", Path(directory) / "Current register.xlsx"]
            for path, data in zip(paths, (word, excel)):
                path.write_bytes(data)
            report = audit([(path, None) for path in paths])
        self.assertTrue(all(entry["kind"] == "file" for entry in report["coverage"]))
        findings = report["review"]["claims"]
        self.assertEqual({claim["confidence"]["level"] for claim in findings}, {"Medium", "High"})
        self.assertIn("Worksheet 1, row 2", json.dumps(findings))
        self.assertIn("DOCX paragraph 1", json.dumps(findings))
        self.assertNotIn("203.0.113.1", json.dumps(findings))

    def test_structured_finding_status_and_additional_formats(self):
        result = generic_evidence(b'''{"audit":[
          {"severity":"critical","details":"Customer email addresses are stored in plain text"},
          {"severity":"high","status":"resolved","title":"Camera permissions were granted"}]}''', ".json")
        self.assertEqual(set(result), {("contacts", "reported")})
        self.assertEqual(set(generic_evidence(b"<root><row><device_id>sample-device</device_id></row></root>", ".xml")),
                         {("security", "observed")})
        self.assertEqual(set(generic_evidence(b'{"date_of_birth":"1990-02-01"}\n', ".ndjson")),
                         {("identity", "observed")})
        self.assertEqual(set(generic_evidence(b"permission\tstatus\ncamera\tgranted\n", ".tsv")),
                         {("permissions", "observed")})

    @unittest.skipUnless(find_spec("pypdf"), "PDF support uses the report dependencies")
    def test_pdf_citations_and_image_only_status(self):
        from pypdf import PdfWriter
        from pypdf.generic import ArrayObject, DictionaryObject, NameObject, NumberObject, StreamObject

        with TemporaryDirectory() as directory:
            readable = Path(directory) / "Client audit.pdf"
            blank = Path(directory) / "Unsearchable.pdf"
            writer = PdfWriter()
            page = writer.add_blank_page(width=400, height=600)
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"), NameObject("/FirstChar"): NumberObject(32),
                NameObject("/LastChar"): NumberObject(126), NameObject("/Widths"): ArrayObject([NumberObject(500)] * 95),
            })
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})
            })
            content = StreamObject()
            content.set_data(b"BT /F1 12 Tf 10 550 Td (Email address: client@example.invalid) Tj ET")
            page.replace_contents(content)
            writer.write(readable)
            empty = PdfWriter()
            empty.add_blank_page(width=400, height=600)
            empty.write(blank)
            report = audit([(readable, None), (blank, None)])
        self.assertIn("PDF page 1", report["review"]["claims"][0]["evidence"][0]["source"])
        self.assertNotIn("client@example.invalid", json.dumps(report))
        self.assertIn("local OCR", report["coverage"][1]["notes"][0])
