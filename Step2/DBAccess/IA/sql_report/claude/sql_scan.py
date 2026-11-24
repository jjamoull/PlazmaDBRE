#!/usr/bin/env python3
"""
sql_scan.py - find every SQL query in a codebase and summarise it.

Usage:
    python sql_scan.py path/to/plazma-1.05
    python sql_scan.py path/to/plazma-1.05 -e .java .xml .sql
    python sql_scan.py path/to/plazma-1.05 -e "*"        # scan every file

    python sql_scan.py path/to/plazma-1.05 --exclude createdb   # skip folders/files whose path contains "createdb"
    python sql_scan.py path/to/plazma-1.05 --show-sql           # also print the SQL text in the report
    python sql_scan.py path/to/plazma-1.05 --joins-only         # only queries comparing columns of 2+ tables
    python sql_scan.py path/to/plazma-1.05 --ddl                # also keep CREATE/ALTER/DROP

Outputs (in ./sql_report by default):
    claude_report.txt    1) folders containing SQL (files + query counts)
                 2) for each folder: each file with its exact query count
                 3) the location (file + line) of each query
    queries.csv  same data flat (file, line, type, tables, joins, sql) for Excel
"""
import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", "target", "build", "dist", "bin", "obj",
             ".idea", ".venv", "__pycache__", ".svn"}
DEFAULT_EXT = {".java", ".kt", ".scala", ".py", ".php", ".cs", ".vb", ".js",
               ".ts", ".rb", ".go", ".c", ".cpp", ".h", ".pas", ".dpr", ".pl",
               ".jsp", ".cob", ".cbl", ".xml", ".properties", ".sh"}   # .sql scripts excluded by default (add with -e .sql)
RAW_EXT = {".sql", ".xml", ".properties"}   # SQL not inside normal string literals

# ---------- 1. find SQL text ----------------------------------------------

LITERAL = re.compile(
    r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|'
    r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`[^`]*`')
# text allowed between two literals for them to count as one concatenated string
GLUE = re.compile(r'^\s*(?:(?:[+.&]|\|\|)\s*)?'
                  r'(?:([\w.\[\]()]+)\s*(?:[+.&]|\|\|)\s*)?$')
RAW = re.compile(r'(?is)\b(?:select|insert\s+into|update|delete\s+from|merge\s+into|'
                 r'create\s+(?:or\s+replace\s+)?(?:table|view)|alter\s+table)\b')
STARTS = re.compile(r'^\s*(select|insert\s+into|update|delete\s+from|merge\s+into|'
                    r'create\s+(?:or\s+replace\s+)?(?:table|view|index|procedure|'
                    r'function|trigger)|alter\s+table|drop\s+table|truncate|with)\b', re.I)


def unquote(lit):
    for q in ('"""', "'''"):
        if lit.startswith(q):
            return lit[3:-3]
    return lit[1:-1].replace('\\"', '"').replace("\\'", "'")


def trailing_var(text, pos):
    return bool(re.match(r"\s*(?:[+.&]|\|\|)\s*[A-Za-z_$]", text[pos:pos + 40]))


def merged_literals(text):
    """Yield (offset, string, dynamic) with concatenated literals merged."""
    cur = None  # [start, parts, dynamic, end]
    for m in LITERAL.finditer(text):
        body = unquote(m.group())
        if cur:
            g = GLUE.match(text[cur[3]:m.start()])
            if g:
                if g.group(1):          # a variable was spliced in
                    cur[1].append(" ? ")
                    cur[2] = True
                cur[1].append(body)
                cur[3] = m.end()
                continue
            yield cur[0], "".join(cur[1]), cur[2] or trailing_var(text, cur[3])
        cur = [m.start(), [body], False, m.end()]
    if cur:
        yield cur[0], "".join(cur[1]), cur[2] or trailing_var(text, cur[3])


def looks_sql(s):
    m = STARTS.match(s)
    if not m:
        return False
    low, kw = s.lower(), m.group(1).lower().split()[0]
    if kw in ("select", "delete"):
        m2 = re.match(r"\s*select\s+(.*?)\bfrom\b", low, re.S)
        if not re.search(r"\bfrom\b", low):
            return False
        if m2 and re.fullmatch(r"[a-z_ ]+", m2.group(1).strip()) and " " in m2.group(1).strip() \
                and not re.search(r"\b(where|join|group|order|as)\b", low):
            return False        # looks like an English sentence
        return True
    if kw == "update":
        return bool(re.search(r"\bset\b", low))
    if kw == "with":
        return bool(re.search(r"\bselect\b", low))
    return True


def find_queries(path, text):
    if path.suffix.lower() in RAW_EXT:
        end = r";|\Z" if path.suffix.lower() == ".sql" else r"</|;|\Z"
        for m in RAW.finditer(text):
            tail = re.search(end, text[m.start():])
            sql = text[m.start(): m.start() + tail.start()] if tail else text[m.start():]
            if looks_sql(sql):
                yield text.count("\n", 0, m.start()) + 1, sql, False
    else:
        for off, sql, dyn in merged_literals(text):
            if looks_sql(sql):
                yield text.count("\n", 0, off) + 1, sql, dyn


# ---------- 2. analyse one query -------------------------------------------

KW = {"where", "group", "order", "having", "union", "on", "using", "set", "left",
      "right", "inner", "outer", "cross", "full", "natural", "join", "limit",
      "select", "values", "from"}
STOP = (r"\bwhere\b|\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\bunion\b|\bleft\b|"
        r"\bright\b|\binner\b|\bjoin\b|\bcross\b|\bfull\b|\blimit\b|\)|$")


def ident(x):
    return x.strip('`"[]').lower()


def analyse(sql):
    flat = re.sub(r"\s+", " ", sql).strip()
    qtype = STARTS.match(flat).group(1).lower().split()[0]
    tables, aliases = [], {}

    def add(tok):
        parts = tok.split()
        if not parts:
            return
        t = ident(parts[0])
        if not re.fullmatch(r"[\w.]+", t) or t in KW:
            return
        rest = [p for p in parts[1:] if p.lower() != "as"]
        tables.append(t)
        aliases[t] = t
        if rest and rest[0].lower() not in KW and re.fullmatch(r"\w+", rest[0]):
            aliases[ident(rest[0])] = t

    for m in re.finditer(r"\bfrom\s+(.+?)(?=" + STOP + ")", flat, re.I):
        for tok in m.group(1).split(","):
            add(tok)
    for m in re.finditer(r'\b(?:join|update|into)\s+([\w.`"\[\]]+(?:\s+(?:as\s+)?\w+)?)',
                         flat, re.I):
        add(m.group(1))

    pairs = []
    for a1, c1, a2, c2 in re.findall(r"\b(\w+)\.(\w+)\s*=\s*(\w+)\.(\w+)\b", flat):
        t1, t2 = aliases.get(a1.lower()), aliases.get(a2.lower())
        if not (t1 and t2) or (t1, c1.lower()) == (t2, c2.lower()):
            continue
        pairs.append(tuple(sorted([(t1, c1.lower()), (t2, c2.lower())])))
    return qtype, list(dict.fromkeys(tables)), pairs, flat


# ---------- 3. run + report -------------------------------------------------

DML = {"select", "insert", "update", "delete", "merge", "with"}


def read(path):
    for enc in ("utf-8", "cp1252", "latin-1"):
        try:
            return path.read_text(encoding=enc)
        except (UnicodeDecodeError, OSError):
            continue
    return ""


def pretty(sql):
    """Put the main clauses on their own line so long queries are readable."""
    return re.sub(r"\s+(FROM|WHERE|(?:LEFT |RIGHT |INNER |FULL |CROSS )?(?:OUTER )?JOIN|"
                  r"GROUP BY|ORDER BY|HAVING|UNION|VALUES|SET)\b", r"\n\1", sql, flags=re.I)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("root")
    ap.add_argument("-o", "--out", default="sql_report")
    ap.add_argument("-e", "--ext", nargs="*", help='extensions, e.g. .java .xml ("*" = all)')
    ap.add_argument("--exclude", nargs="*", default=[], help="skip paths containing any of these")
    ap.add_argument("--ddl", action="store_true", help="also keep CREATE/ALTER/DROP/TRUNCATE")
    ap.add_argument("--show-sql", action="store_true", help="also print the SQL text in claude_report.txt")
    ap.add_argument("--joins-only", action="store_true",
                    help="keep only queries that compare columns of 2+ tables (useful to infer FKs)")
    args = ap.parse_args()

    exts = {e if e.startswith(".") else "." + e for e in args.ext} if args.ext else DEFAULT_EXT
    root = Path(args.root)
    records = []

    for p in sorted(root.rglob("*")):
        if not p.is_file() or any(d in SKIP_DIRS for d in p.parts):
            continue
        rel = p.relative_to(root)
        if any(x.lower() in str(rel).lower() for x in args.exclude):
            continue
        if "*" not in exts and p.suffix.lower() not in exts:
            continue
        for line, sql, dyn in find_queries(p, read(p)):
            if dyn:
                continue            # dynamic queries are ignored
            qtype, tabs, pairs, flat = analyse(sql)
            if not args.ddl and qtype not in DML:
                continue
            joins = "; ".join(f"{a[0]}.{a[1]} = {b[0]}.{b[1]}" for a, b in dict.fromkeys(pairs))
            if args.joins_only and not joins:
                continue
            records.append(dict(folder=rel.parent.as_posix(), file=rel.as_posix(), line=line,
                                type=qtype, tables=",".join(tabs), joins=joins, sql=flat))

    out_dir = Path(args.out)
    out_dir.mkdir(exist_ok=True)

    with open(out_dir / "queries.csv", "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["folder", "file", "line", "type", "tables", "joins", "sql"])
        w.writeheader()
        w.writerows(records)

    tree = defaultdict(lambda: defaultdict(list))      # folder -> file -> [records]
    for r in records:
        tree[r["folder"]][r["file"]].append(r)

    n_files = sum(len(v) for v in tree.values())
    bar, thin = "=" * 78, "-" * 78
    by_type = Counter(r["type"] for r in records)
    total = ["", "", bar, "TOTAL", bar,
             f"Queries found       : {len(records)}",
             f"Distinct queries    : {len({r['sql'] for r in records})}",
             f"Files with SQL      : {n_files}",
             f"Folders with SQL    : {len(tree)}",
             f"With joins          : {sum(1 for r in records if r['joins'])}",
             "By type             : " + ", ".join(f"{t} {n}" for t, n in by_type.most_common())]
    txt = [bar, f"SQL REPORT - {root.name}", bar,
           f"{len(records)} queries in {n_files} files in {len(tree)} folders", "",
           "", "1. FOLDERS CONTAINING SQL", thin, f"{'FOLDER':60} {'FILES':>6} {'QUERIES':>8} {'WITH JOINS':>11}"]
    for folder, files in sorted(tree.items()):
        txt.append(f"{folder[:60]:60} {len(files):>6} {sum(len(v) for v in files.values()):>8} "
                   f"{sum(1 for v in files.values() for r in v if r['joins']):>11}")

    txt += total
    txt += ["", "", "2. FILES AND QUERY COUNT PER FOLDER", thin]
    for folder, files in sorted(tree.items()):
        txt += ["", f"[{folder}]  {len(files)} files, {sum(len(v) for v in files.values())} queries"]
        for file, rs in sorted(files.items()):
            txt.append(f"    {Path(file).name:55} {len(rs):>6}")

    txt += ["", "", "3. QUERY LOCATIONS (file, line)", bar]
    for folder, files in sorted(tree.items()):
        for file, rs in sorted(files.items()):
            txt += ["", f"{file}  ({len(rs)} queries)"]
            for r in rs:
                txt.append(f"    line {r['line']:<6} {r['type']:<7}  tables: {r['tables'] or '-'}"
                           + (f"  | joins: {r['joins']}" if r["joins"] else ""))
                if args.show_sql:
                    txt += ["        " + ln for ln in pretty(r["sql"]).split("\n")] + [""]


    (out_dir / "claude_report.txt").write_text("\n".join(txt) + "\n", encoding="utf-8-sig")

    print(f"{'folder':60} files  queries")
    for folder, files in sorted(tree.items()):
        print(f"{folder[:60]:60} {len(files):5}  {sum(len(v) for v in files.values()):7}")
    print("\n" + "\n".join(total[3:]))
    print(f"\nFull report: {out_dir}/claude_report.txt   (flat version: {out_dir}/queries.csv)")


if __name__ == "__main__":
    main()