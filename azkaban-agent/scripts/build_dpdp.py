"""Extract selected DPDP Act 2023 sections (verbatim) for the offline RAG stub.

    curl -L -o dpdp.pdf https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf
    python build_dpdp.py dpdp.pdf azkaban_agent/data/dpdp_sections.json      (needs: pip install pypdf)
"""
import json
import re
import sys

URL = "https://www.meity.gov.in/static/uploads/2024/06/2bf1f0e9f04e6fb4f8fef35e82c42aa5.pdf"
WANT = {
    "4": ("Grounds for processing personal data", ["consent", "lawful_purpose"]),
    "5": ("Notice", ["consent", "notice"]),
    "6": ("Consent", ["consent", "purpose_limitation", "data_minimisation"]),
    "7": ("Certain legitimate uses", ["legitimate_use"]),
    "8": ("General obligations of Data Fiduciary", ["processor", "security", "retention", "third_party"]),
    "9": ("Processing of personal data of children", ["children", "tracking", "targeted_advertising"]),
    "16": ("Processing of personal data outside India", ["cross_border"]),
    "33": ("Penalties", ["penalty"]),
}


def main(pdf: str, out: str) -> None:
    import pypdf
    text = "\n".join(p.extract_text() or "" for p in pypdf.PdfReader(pdf).pages)
    lines = text.splitlines()
    starts = [(i, m.group(1)) for i, l in enumerate(lines) if (m := re.match(r"^\s?(\d{1,2})\. ", l))]
    sections = []
    for idx, (i, num) in enumerate(starts):
        if num not in WANT:
            continue
        j = starts[idx + 1][0] if idx + 1 < len(starts) else len(lines)
        body = " ".join(l.strip() for l in lines[i:j])
        body = re.sub(r"\s+", " ", body).strip()
        title, tags = WANT[num]
        sections.append({"source": "Digital Personal Data Protection Act, 2023", "section": f"Section {num}",
                         "title": title, "tags": tags, "url": URL, "text": body[:4000]})
    # Definition of personal data, s.2(t)
    for k, l in enumerate(lines):
        if l.strip().startswith("(t) “personal data”"):
            sections.append({"source": "Digital Personal Data Protection Act, 2023", "section": "Section 2(t)",
                             "title": "Definition of personal data", "tags": ["definition", "personal_data"],
                             "url": URL, "text": " ".join(x.strip() for x in lines[k:k + 2])})
            break
    # Schedule (penalty amounts)
    for k, l in enumerate(lines):
        if l.strip() == "THE SCHEDULE":
            sections.append({"source": "Digital Personal Data Protection Act, 2023", "section": "Schedule",
                             "title": "Penalties schedule", "tags": ["penalty"], "url": URL,
                             "text": re.sub(r"\s+", " ", " ".join(lines[k:k + 60]))[:4000]})
            break
    json.dump(sections, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{len(sections)} sections -> {out}: {[s['section'] for s in sections]}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
