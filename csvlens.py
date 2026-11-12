#!/usr/bin/env python3
"""csvlens - one-file, zero-dependency CSV viewer for the terminal.

  python csvlens.py data.csv
  python csvlens.py data.csv --where "age>30" --where "city~tehran" --sort age:desc
  python csvlens.py data.csv --cols name,age --limit 0
  python csvlens.py data.csv --stats
  python csvlens.py data.csv --json > data.json

Delimiter (comma, semicolon, tab, pipe) is detected automatically.
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import statistics
import sys
from collections import Counter

__version__ = "1.0.0"

if os.name == "nt":
    os.system("")
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass

USE_COLOR = sys.stdout.isatty() and "NO_COLOR" not in os.environ


def c(code, text):
    return f"\033[{code}m{text}\033[0m" if USE_COLOR else str(text)


def die(msg):
    sys.stderr.write(f"error: {msg}\n")
    sys.exit(2)


# ---------------------------------------------------------------- loading
def num(s):
    s = s.strip()
    if not s or s.lower().lstrip("+-") in ("nan", "inf", "infinity"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def load(src):
    try:
        if src in (None, "-"):
            text = sys.stdin.read()
        else:
            with open(src, encoding="utf-8-sig", newline="") as f:
                text = f.read()
    except OSError as e:
        die(e.strerror or str(e))
    try:
        dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    rows = [r for r in csv.reader(io.StringIO(text, newline=""), dialect) if any(x.strip() for x in r)]
    if not rows:
        die("empty file")
    head = [h.strip() or f"col{i + 1}" for i, h in enumerate(rows[0])]
    body = [(r + [""] * len(head))[:len(head)] for r in rows[1:]]
    return head, body


def col_index(head, name):
    if name in head:
        return head.index(name)
    low = [h.lower() for h in head]
    if name.lower() in low:
        return low.index(name.lower())
    if name.isdigit() and 1 <= int(name) <= len(head):
        return int(name) - 1
    die(f"unknown column {name!r}. Columns: {', '.join(head)}")


# ---------------------------------------------------------------- filter / sort
WHERE_RE = re.compile(r"^\s*(.+?)\s*(>=|<=|==|!=|!~|~|>|<|=)\s*(.*?)\s*$")


def parse_where(w, head):
    m = WHERE_RE.match(w)
    if not m:
        die(f"bad --where {w!r}. Use e.g. age>30, name~ada, status==ok")
    col, op, val = m.groups()
    return col_index(head, col), op, val


def test(cell, op, val):
    if op in ("~", "!~"):
        hit = val.lower() in cell.lower()
        return hit if op == "~" else not hit
    a, b = num(cell), num(val)
    x, y = (a, b) if a is not None and b is not None else (cell, val)
    if op in ("=", "=="):
        return x == y
    if op == "!=":
        return x != y
    if op == ">":
        return x > y
    if op == "<":
        return x < y
    if op == ">=":
        return x >= y
    return x <= y


def sort_rows(rows, i, desc):
    filled = [r for r in rows if r[i] != ""]
    empty = [r for r in rows if r[i] == ""]
    numeric = all(num(r[i]) is not None for r in filled)
    filled.sort(key=(lambda r: num(r[i])) if numeric else (lambda r: r[i].lower()), reverse=desc)
    return filled + empty


# ---------------------------------------------------------------- output
def table(head, rows, maxw=40):
    n = len(head)
    widths = [min(maxw, max([len(h)] + [len(r[i]) for r in rows])) for i, h in enumerate(head)]
    termw = shutil.get_terminal_size((110, 20)).columns
    while sum(widths) + 3 * n + 1 > termw and max(widths) > 6:
        widths[widths.index(max(widths))] -= 1
    numeric = [
        any(r[i] != "" for r in rows) and all(num(r[i]) is not None for r in rows if r[i] != "")
        for i in range(n)
    ]

    def cut(s, w):
        s = s.replace("\n", " ")
        return s if len(s) <= w else s[:max(1, w - 1)] + "…"

    def border(l, m, r):
        return l + m.join("─" * (w + 2) for w in widths) + r

    out = [border("┌", "┬", "┐")]
    out.append("│" + "│".join(" " + c("1;36", cut(h, w).ljust(w)) + " " for h, w in zip(head, widths)) + "│")
    out.append(border("├", "┼", "┤"))
    for r in rows:
        cells = []
        for i, (v, w) in enumerate(zip(r, widths)):
            s = cut(v, w)
            cells.append(" " + (s.rjust(w) if numeric[i] else s.ljust(w)) + " ")
        out.append("│" + "│".join(cells) + "│")
    out.append(border("└", "┴", "┘"))
    print("\n".join(out))


def fmt(x):
    return f"{int(x):,}" if float(x).is_integer() else f"{x:,.2f}"


def stats(head, rows):
    for i, h in enumerate(head):
        vals = [r[i] for r in rows]
        filled = [v for v in vals if v != ""]
        nums = [num(v) for v in filled]
        is_num = bool(filled) and all(x is not None for x in nums)
        print(f"\n{c('1;36', h)}  {c('90', 'number' if is_num else 'text')}")
        print(f"  filled  {len(filled):,}/{len(vals):,}   unique  {len(set(filled)):,}")
        if is_num:
            print(f"  min {fmt(min(nums))}   max {fmt(max(nums))}   "
                  f"mean {fmt(statistics.mean(nums))}   median {fmt(statistics.median(nums))}")
        elif filled:
            top = Counter(filled).most_common(3)
            print("  top     " + "   ".join(f"{k[:24]} ({n:,})" for k, n in top))


def main():
    p = argparse.ArgumentParser(prog="csvlens", description="View, filter and summarize CSV files.")
    p.add_argument("file", nargs="?", help="CSV file; stdin if omitted or '-'")
    p.add_argument("--cols", help="comma-separated columns to show (names or 1-based numbers)")
    p.add_argument("-w", "--where", action="append", default=[],
                   help="filter, repeatable (AND): age>30  name~ada  status==ok  (ops: = == != > < >= <= ~ !~)")
    p.add_argument("-s", "--sort", help="column to sort by, add :desc for descending")
    p.add_argument("-l", "--limit", type=int, default=20, help="rows to show (default 20, 0 = all)")
    p.add_argument("--stats", action="store_true", help="per-column summary instead of rows")
    p.add_argument("--json", action="store_true", help="output matching rows as JSON")
    p.add_argument("-V", "--version", action="version", version=__version__)
    a = p.parse_args()

    head, rows = load(a.file)
    total = len(rows)
    for w in a.where:
        i, op, val = parse_where(w, head)
        rows = [r for r in rows if test(r[i], op, val)]
    if a.sort:
        name, _, order = a.sort.partition(":")
        rows = sort_rows(rows, col_index(head, name), order.lower().startswith("d"))
    if a.cols:
        idx = [col_index(head, x.strip()) for x in a.cols.split(",") if x.strip()]
        head, rows = [head[i] for i in idx], [[r[i] for i in idx] for r in rows]

    try:
        if a.stats:
            stats(head, rows)
        elif a.json:
            print(json.dumps([dict(zip(head, r)) for r in rows], ensure_ascii=False, indent=2))
        else:
            shown = rows if a.limit <= 0 else rows[:a.limit]
            table(head, shown)
            print(c("90", f"{len(shown):,} of {len(rows):,} row(s)"
                    + (f" (filtered from {total:,})" if len(rows) != total else "")
                    + f" · {len(head)} column(s)"))
    except BrokenPipeError:
        pass
    except KeyboardInterrupt:
        sys.exit(130)


if __name__ == "__main__":
    main()
