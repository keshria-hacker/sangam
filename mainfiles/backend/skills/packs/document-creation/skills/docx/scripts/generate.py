#!/usr/bin/env python3
"""Deterministic .docx generator (stdlib only). Usage:
python3 generate.py --title "Doc" --out out.docx --sections '[{"heading":"H","body":"B"}]'
Prints the output path on stdout."""
import argparse, io, json, zipfile
from xml.sax.saxutils import escape

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sections", default="[]")
    a = ap.parse_args()
    paras = [("Title", a.title)]
    for s in json.loads(a.sections):
        if s.get("heading"): paras.append(("Heading1", s["heading"]))
        if s.get("body"): paras.append(("Normal", s["body"]))
    body = "".join(f'<w:p><w:pPr><w:pStyle w:val="{st}"/></w:pPr><w:r><w:t>{escape(t)}</w:t></w:r></w:p>' for st, t in paras)
    files = {
        "[Content_Types].xml": '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>',
        "_rels/.rels": '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>',
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items(): zf.writestr(name, content)
    open(a.out, "wb").write(buf.getvalue())
    print(a.out)

if __name__ == "__main__":
    main()
