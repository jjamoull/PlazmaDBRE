#!/usr/bin/env python3
"""
Find SQL queries embedded in APPLICATION SOURCE CODE (.java, .py, .js, ...).
.sql files (DDL, migrations, seed data) are ignored on purpose.
No foreign-key inference — just where the queries live and what they are.

Report:
  1. Folders with SQL queries (+ counts)
  2. Per file: number of queries
  3. Every query: file, line, type, text

Usage:
    python sql_usage.py /path/to/repo
    python sql_usage.py /path/to/repo --out report.txt
    python sql_usage.py /path/to/repo --csv queries.csv --json queries.json
"""

import argparse
import csv
import json
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

# ---- Only SOURCE CODE — .sql is deliberately excluded -------------------
SOURCE_EXTS = {
    ".py", ".js", ".ts", ".jsx", ".tsx", ".mjs", ".cjs",
    ".java", ".kt", ".scala", ".groovy",
    ".cs", ".go", ".rb", ".php", ".rs", ".swift",
}

SKIP_DIRS = {
    ".git", "node_modules", "venv", ".venv", "env", "__pycache__",
    "dist", "build", "target", "out", "bin", "obj",
    ".idea", ".vscode", "vendor",
    ".mypy_cache", ".pytest_cache", "coverage", ".next", ".nuxt",
}

# ---- Regexes ------------------------------------------------------------
DML_KEYWORDS = r"(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|WITH\s+\w+\s+AS)"
SQL_START_RE = re.compile(rf"^\s*(?:\(?\s*){DML_KEYWORDS}\b", re.IGNORECASE)

JAVA_STRING_BLOCK_RE = re.compile(r'"""([\s\S]*?)"""')
BACKTICK_RE = re.compile(r'`([\s\S]*?)`')
PY_TRIPLE_RE = re.compile(r'(?:"""|\'\'\')([\s\S]*?)(?:"""|\'\'\')')
QUOTED_STRING_RE = re.compile(
    r'"((?:[^"\\]|\\.)*)"'
    r"|'((?:[^'\\]|\\.)*)'",
)
JS_CONCAT_RE = re.compile(r'"\s*\+\s*"|\'\s*\+\s*\'')


@dataclass
class Query:
    file: str
    line: int
    query_type: str
    text: str


# ---- Helpers ------------------------------------------------------------
def line_of(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def clean_sql(s: str) -> str:
    s = JS_CONCAT_RE.sub("", s)
    return re.sub(r"\s+", " ", s).strip()


def looks_like_dml(text: str) -> bool:
    if not text:
        return False
    s = text.strip()
    if len(s) < 10:
        return False
    return bool(SQL_START_RE.match(s[:250]))


def classify(sql: str) -> str:
    s = sql.strip().upper()
    if re.match(r"^(?:\(?\s*)?WITH", s):
        return "WITH (CTE)"
    if re.match(r"^(?:\(?\s*)?SELECT", s):
        return "SELECT"
    if re.match(r"^(?:\(?\s*)?INSERT", s):
        return "INSERT"
    if re.match(r"^(?:\(?\s*)?UPDATE", s):
        return "UPDATE"
    if re.match(r"^(?:\(?\s*)?DELETE", s):
        return "DELETE"
    if re.match(r"^(?:\(?\s*)?MERGE", s):
        return "MERGE"
    return "OTHER"


# ---- Per-language extraction -------------------------------------------
def candidates_python(text: str):
    for m in PY_TRIPLE_RE.finditer(text):
        yield m.group(1), line_of(text, m.start())
    for m in QUOTED_STRING_RE.finditer(text):
        yield (m.group(1) or m.group(2) or ""), line_of(text, m.start())


def candidates_java(text: str):
    for m in JAVA_STRING_BLOCK_RE.finditer(text):
        yield m.group(1), line_of(text, m.start())
    for m in QUOTED_STRING_RE.finditer(text):
        yield (m.group(1) or m.group(2) or ""), line_of(text, m.start())


def candidates_js(text: str):
    for m in BACKTICK_RE.finditer(text):
        yield m.group(1), line_of(text, m.start())
    for m in QUOTED_STRING_RE.finditer(text):
        yield (m.group(1) or m.group(2) or ""), line_of(text, m.start())


def candidates_generic(text: str):
    for m in QUOTED_STRING_RE.finditer(text):
        yield (m.group(1) or m.group(2) or ""), line_of(text, m.start())


CANDIDATE_FN = {
    ".py": candidates_python,
    ".java": candidates_java,
    ".kt": candidates_java,
    ".scala": candidates_java,
    ".groovy": candidates_java,
    ".cs": candidates_java,
    ".js": candidates_js,
    ".jsx": candidates_js,
    ".ts": candidates_js,
    ".tsx": candidates_js,
    ".mjs": candidates_js,
    ".cjs": candidates_js,
}


def extract_queries(text: str, ext: str) -> list[Query]:
    fn = CANDIDATE_FN.get(ext, candidates_generic)
    out = []
    seen = set()
    for raw, line in fn(text):
        stmt = clean_sql(raw)
        if not stmt or not looks_like_dml(stmt):
            continue
        key = (line, stmt)
        if key in seen:
            continue
        seen.add(key)
        out.append(Query(file="", line=line, query_type=classify(stmt), text=stmt))
    return out


# ---- Walk + scan --------------------------------------------------------
def walk_source_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            p = Path(dirpath) / fname
            if p.suffix.lower() in SOURCE_EXTS:
                yield p


def scan_file(path: Path, root: Path) -> list[Query]:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"[warn] could not read {path}: {e}", file=sys.stderr)
        return []
    rel = str(path.relative_to(root))
    qs = extract_queries(text, path.suffix.lower())
    for q in qs:
        q.file = rel
    return qs


# ---- Report -------------------------------------------------------------
def build_report(queries: list[Query], root: Path) -> str:
    by_file = defaultdict(list)
    for q in queries:
        by_file[q.file].append(q)

    by_folder = defaultdict(lambda: {"files": set(), "queries": 0})
    for f, qs in by_file.items():
        folder = str(Path(f).parent) or "."
        by_folder[folder]["files"].add(f)
        by_folder[folder]["queries"] += len(qs)

    out = []
    out.append("=" * 78)
    out.append("SQL QUERIES IN APPLICATION CODE  (.sql / DDL ignored)")
    out.append("=" * 78)
    out.append(f"Root           : {root}")
    out.append(f"Generated      : {datetime.now().isoformat(timespec='seconds')}")
    out.append(f"Folders        : {len(by_folder)}")
    out.append(f"Files          : {len(by_file)}")
    out.append(f"Total queries  : {len(queries)}")
    out.append("")

    # 1. Folders
    out.append("=" * 78)
    out.append("1. FOLDERS WITH EMBEDDED SQL")
    out.append("=" * 78)
    out.append("")
    out.append(f"{'Queries':>8}  {'Files':>5}  Folder")
    out.append(f"{'-'*8}  {'-'*5}  {'-'*50}")
    for folder in sorted(by_folder, key=lambda d: (-by_folder[d]["queries"], d)):
        info = by_folder[folder]
        out.append(f"{info['queries']:>8}  {len(info['files']):>5}  {folder}")
    out.append("")

    # 2. Files
    out.append("=" * 78)
    out.append("2. FILES WITH EMBEDDED SQL")
    out.append("=" * 78)
    out.append("")
    out.append(f"{'Queries':>8}  File")
    out.append(f"{'-'*8}  {'-'*60}")
    for f in sorted(by_file, key=lambda x: (-len(by_file[x]), x)):
        out.append(f"{len(by_file[f]):>8}  {f}")
    out.append("")

    # 3. Queries by file
    out.append("=" * 78)
    out.append("3. QUERIES BY FILE")
    out.append("=" * 78)
    out.append("")
    for f in sorted(by_file):
        qs = sorted(by_file[f], key=lambda q: q.line)
        out.append(f"### {f}  ({len(qs)} quer{'y' if len(qs) == 1 else 'ies'})")
        out.append("")
        for q in qs:
            out.append(f"  L{q.line:<5} [{q.query_type}]")
            out.append(f"         {q.text}")
            out.append("")
        out.append("")

    return "\n".join(out) + "\n"


# ---- Entry point --------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description="Find SQL queries embedded in application source code.")
    ap.add_argument("path", help="Root directory to scan")
    ap.add_argument("--out", help="Report file (default: <repo>/deep_seek_report.txt)")
    ap.add_argument("--csv", help="Also write CSV")
    ap.add_argument("--json", help="Also write JSON")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.exists():
        sys.exit(f"Path not found: {root}")

    all_queries: list[Query] = []
    for path in walk_source_files(root):
        all_queries.extend(scan_file(path, root))

    out_path = Path(args.out) if args.out else (root / "deep_seek_report.txt")

    if not all_queries:
        out_path.write_text(
            f"SQL QUERIES IN APPLICATION CODE\n{'='*78}\n"
            f"Root: {root}\nGenerated: {datetime.now().isoformat(timespec='seconds')}\n\n"
            f"No embedded SQL queries found.\n",
            encoding="utf-8",
        )
        print(f"No embedded SQL found. Report -> {out_path}")
        return

    out_path.write_text(build_report(all_queries, root), encoding="utf-8")
    print(f"Report -> {out_path}  ({len(all_queries)} queries in "
          f"{len(set(q.file for q in all_queries))} files)")

    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["file", "line", "query_type", "query"])
            for q in sorted(all_queries, key=lambda q: (q.file, q.line)):
                w.writerow([q.file, q.line, q.query_type, q.text])
        print(f"CSV -> {args.csv}")

    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(
                [{"file": q.file, "line": q.line, "query_type": q.query_type, "query": q.text}
                 for q in sorted(all_queries, key=lambda q: (q.file, q.line))],
                fh, indent=2,
            )
        print(f"JSON -> {args.json}")


if __name__ == "__main__":
    main()