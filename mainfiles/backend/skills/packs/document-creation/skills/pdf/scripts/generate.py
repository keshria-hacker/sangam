#!/usr/bin/env python3
"""Deterministic minimal PDF writer (stdlib only). Usage:
python3 generate.py --title "Doc" --out out.pdf --sections '[{"heading":"H","body":"B"}]'
Prints the output path on stdout."""
import argparse, json

def esc(t):
    return t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

def wrap(text, width=95):
    lines, cur = [], ""
    for w in text.split():
        if len(cur) + len(w) + 1 > width and cur: lines.append(cur); cur = w
        else: cur = f"{cur} {w}".strip()
    if cur: lines.append(cur)
    return lines or [""]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--sections", default="[]")
    a = ap.parse_args()
    lines = [a.title, ""]
    for s in json.loads(a.sections):
        if s.get("heading"): lines.append(s["heading"])
        if s.get("body"): lines.extend(wrap(s["body"]))
        lines.append("")
    stream_lines, y = [], 750
    for line in lines:
        if y < 40: break
        stream_lines.append(f"BT /F1 12 Tf 40 {y} Td ({esc(line)}) Tj ET"); y -= 16
    stream = "\n".join(stream_lines).encode("latin-1", "replace")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    out = bytearray(b"%PDF-1.4\n"); offsets = []
    for i, obj in enumerate(objs, start=1):
        offsets.append(len(out)); out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out); out += f"xref\n0 {len(objs)+1}\n".encode() + b"0000000000 65535 f \n"
    for off in offsets: out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    open(a.out, "wb").write(bytes(out))
    print(a.out)

if __name__ == "__main__":
    main()
