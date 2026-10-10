"""The few pandas operations server.py needs, in plain Python (stdlib only, 10 Oct 2026).

Why: pandas + numpy were ~85% of the site's Vercel function (~60 MB per deployment) and
Vercel keeps every retained deployment's function, so this one site filled most of the
account's 10 GB "Functions Storage" (deploys stop past the cap). The page only reads a few
small CSVs. The scrapers keep pandas (requirements-scraper.txt); only the site dropped it.

The rules are pandas 2.1.4's (what the site ran on Vercel), down to the edge cases a card
can show. tests/test_frames.py checks each one against real pandas:
- read_csv: pandas' default NA strings ("", "NA", "None", "null", ...) are missing; a
  column whose every value is a number becomes numbers (ints, or floats when one is
  missing); an all True/False column becomes bools; blank lines are skipped; short rows
  are padded; a row with too many fields is a broken file (pandas raised).
- concat: an int column turns float when another file lacks it or has floats.
- argsort_quick: numpy's default quicksort ORDER (it is not stable), so a News story whose
  copies share a pub_date keeps exactly the copy pandas kept.
- to_datetime: a column is parsed in the format of its first non-empty value, and a value
  in another shape is missing, like pandas; a single stamp is parsed on its own.
"""
import csv
import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

# pandas._libs.parsers.STR_NA_VALUES (pandas 2.x)
NA_STRINGS = frozenset({
    "", "#N/A", "#N/A N/A", "#NA", "-1.#IND", "-1.#QNAN", "-NaN", "-nan", "1.#IND",
    "1.#QNAN", "<NA>", "N/A", "NA", "NULL", "NaN", "None", "n/a", "nan", "null",
})
TRUE_STRINGS = frozenset({"True", "TRUE", "true"})
FALSE_STRINGS = frozenset({"False", "FALSE", "false"})
_INT = re.compile(r"\s*[+-]?\d+\s*\Z", re.ASCII)   # ASCII: "１２" is text to pandas
_FLOAT = re.compile(r"\s*[+-]?(?:\d+\.?\d*(?:[eE][+-]?\d+)?|\.\d+(?:[eE][+-]?\d+)?|inf|infinity)\s*\Z",
                    re.IGNORECASE | re.ASCII)
_INT64 = 2 ** 63


class Table:
    """A parsed CSV: `columns` (header order) and `rows` (dicts; None = missing)."""

    def __init__(self, columns, rows, kinds=None):
        self.columns = list(columns)
        self.rows = rows
        # per column: "i" int, "f" float, "b" bool, "O" text/mixed, "na" all missing
        self.kinds = kinds or {}

    def __len__(self):
        return len(self.rows)

    def fillna(self, value=""):
        """Missing -> value, in place (DataFrame.fillna)."""
        for r in self.rows:
            for c in self.columns:
                if r.get(c) is None:
                    r[c] = value
        return self


def is_missing(v) -> bool:
    """pd.isna for one value."""
    return v is None or (isinstance(v, float) and math.isnan(v))


def to_text(v) -> str:
    """str() of a cell as pandas' astype(str) gives it (a missing value is "nan")."""
    return "nan" if v is None else str(v)


def to_number(v):
    """pd.to_numeric(v, errors="coerce") for one value: an int, a float, or nan."""
    if isinstance(v, bool):
        return v
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        return v
    if hasattr(v, "item") and not isinstance(v, (str, bytes)):  # numpy scalars (tests pass pandas rows)
        try:
            return to_number(v.item())
        except Exception:
            return math.nan
    if isinstance(v, str):
        if _INT.match(v):
            n = int(v)
            return n if -_INT64 <= n < _INT64 else float(n)
        if _FLOAT.match(v):
            f = float(v)
            if math.isinf(f) and "inf" not in v.lower():
                return math.nan  # "1e400": pandas gives up (nan), Python would say inf
            return f
    return math.nan


def _infer(values):
    """Raw strings of one column -> (typed values, kind), like pandas.read_csv's C parser."""
    missing = [v in NA_STRINGS for v in values]
    present = [v for v, m in zip(values, missing) if not m]
    if not present:
        return [None] * len(values), "na"
    any_missing = any(missing)
    if all(_INT.match(v) for v in present):
        nums = [int(v) for v in present]
        if all(-_INT64 <= n < _INT64 for n in nums):
            it = iter(nums)
            if any_missing:
                return [None if m else float(next(it)) for m in missing], "f"
            return [next(it) for _ in values], "i"
    if all(_FLOAT.match(v) for v in present):
        return [None if m else float(v) for v, m in zip(values, missing)], "f"
    if all(v in TRUE_STRINGS or v in FALSE_STRINGS for v in present):
        vals = [None if m else (v in TRUE_STRINGS) for v, m in zip(values, missing)]
        return vals, ("O" if any_missing else "b")
    return [None if m else v for v, m in zip(values, missing)], "O"


def _header(names):
    """pandas' column names: blank -> "Unnamed: i", repeats -> "a.1", "a.2"."""
    out, seen = [], {}
    for i, n in enumerate(names):
        n = n or f"Unnamed: {i}"
        if n in seen:
            k = seen[n]
            while f"{n}.{k}" in seen:
                k += 1
            seen[n] = k + 1
            n = f"{n}.{k}"
        seen.setdefault(n, 1)
        out.append(n)
    return out


def read_csv(path) -> Table:
    """pd.read_csv(path) with the default options. Raises on an empty or broken file."""
    with open(path, newline="", encoding="utf-8-sig") as f:
        # blank / whitespace-only lines are skipped; a quoted empty field ("") is a row
        lines = [r for r in csv.reader(f, strict=False)
                 if r and not (len(r) == 1 and r[0] and not r[0].strip())]
    if not lines:
        raise ValueError("No columns to parse from file")
    columns = _header(lines[0])
    body = lines[1:]
    n = len(columns)
    skip = 1 if body and len(body[0]) == n + 1 else 0   # pandas then uses column 0 as the index
    raw = []
    for i, r in enumerate(body):
        if len(r) > n + skip:
            raise ValueError(f"Error tokenizing data: expected {n + skip} fields in line {i + 2}, saw {len(r)}")
        r = r[skip:]
        raw.append(r + [""] * (n - len(r)))
    rows = [{} for _ in raw]
    kinds = {}
    for j, c in enumerate(columns):
        vals, kinds[c] = _infer([r[j] for r in raw])
        for row, v in zip(rows, vals):
            row[c] = v
    return Table(columns, rows, kinds)


def concat(tables) -> Table:
    """pd.concat(tables, ignore_index=True) (outer join on columns) with pandas 2.1's value
    casts, checked against pandas for every mix of up to 5 files: a column that is text in
    any file keeps every value as it is; ints turn float when a file has floats, lacks the
    column or has it all-missing; bools turn numbers next to numbers (unless a file lacks
    the column or has it all-missing) and floats next to an all-missing column."""
    columns = []
    for t in tables:
        columns += [c for c in t.columns if c not in columns]
    cast = {}
    for c in columns:
        kinds = [t.kinds.get(c, "O") if c in t.columns else "void" for t in tables]
        real = {k for k in kinds if k not in ("na", "void")}
        has_na, has_void = "na" in kinds, "void" in kinds
        if not real or "O" in real:
            continue
        if real == {"b"}:
            if has_na and not has_void:
                cast[c] = float
        elif "b" in real:
            if not (has_na or has_void):
                cast[c] = float if "f" in real else int
        elif "f" in real or has_na or has_void:
            cast[c] = float
    rows = []
    for t in tables:
        for r in t.rows:
            row = {}
            for c in columns:
                v = r.get(c)
                row[c] = cast[c](v) if v is not None and c in cast else v
            rows.append(row)
    return Table(columns, rows)


def drop_duplicates(rows, keys):
    """DataFrame.drop_duplicates(subset=keys, keep="first"); a missing column is a KeyError."""
    seen, out = set(), []
    for r in rows:
        k = tuple(r[c] for c in keys)
        if k not in seen:
            seen.add(k)
            out.append(r)
    return out


# ---------- numpy's quicksort order (numpy 1.26 npy_aquicksort / npy_aheapsort) ----------
_SMALL_QUICKSORT = 15   # numpy npysort_common.h


def _aheapsort(keys, tosort, lo, n):
    a = lambda i: tosort[lo + i - 1]          # 1-based, like numpy's `a = tosort - 1`

    def put(i, v):
        tosort[lo + i - 1] = v

    def lt(x, y):
        return keys[x] < keys[y]
    for l in range(n >> 1, 0, -1):
        tmp = a(l)
        i, j = l, l << 1
        while j <= n:
            if j < n and lt(a(j), a(j + 1)):
                j += 1
            if lt(tmp, a(j)):
                put(i, a(j))
                i = j
                j += j
            else:
                break
        put(i, tmp)
    while n > 1:
        tmp = a(n)
        put(n, a(1))
        n -= 1
        i, j = 1, 2
        while j <= n:
            if j < n and lt(a(j), a(j + 1)):
                j += 1
            if lt(tmp, a(j)):
                put(i, a(j))
                i = j
                j += j
            else:
                break
        put(i, tmp)


def argsort_quick(keys) -> list:
    """numpy.argsort(kind="quicksort") of an object array: introsort, not stable. pandas'
    sort_values() default; ties land where numpy put them."""
    n = len(keys)
    t = list(range(n))
    if n < 2:
        return t

    def lt(x, y):
        return keys[x] < keys[y]
    pl, pr = 0, n - 1
    stack, depths = [], []
    cdepth = (n.bit_length() - 1) * 2
    while True:
        if cdepth < 0:
            _aheapsort(keys, t, pl, pr - pl + 1)
        else:
            while pr - pl > _SMALL_QUICKSORT:
                pm = pl + ((pr - pl) >> 1)
                if lt(t[pm], t[pl]):
                    t[pm], t[pl] = t[pl], t[pm]
                if lt(t[pr], t[pm]):
                    t[pr], t[pm] = t[pm], t[pr]
                if lt(t[pm], t[pl]):
                    t[pm], t[pl] = t[pl], t[pm]
                vp = t[pm]
                pi, pj = pl, pr - 1
                t[pm], t[pj] = t[pj], t[pm]
                while True:
                    pi += 1
                    while lt(t[pi], vp):
                        pi += 1
                    pj -= 1
                    while lt(vp, t[pj]):
                        pj -= 1
                    if pi >= pj:
                        break
                    t[pi], t[pj] = t[pj], t[pi]
                pk = pr - 1
                t[pi], t[pk] = t[pk], t[pi]
                if pi - pl < pr - pi:
                    stack.append((pi + 1, pr))
                    pr = pi - 1
                else:
                    stack.append((pl, pi - 1))
                    pl = pi + 1
                cdepth -= 1
                depths.append(cdepth)
            for pi in range(pl + 1, pr + 1):          # insertion sort
                vi = t[pi]
                pj = pi
                while pj > pl and lt(vi, t[pj - 1]):
                    t[pj] = t[pj - 1]
                    pj -= 1
                t[pj] = vi
        if not stack:
            break
        pl, pr = stack.pop()
        cdepth = depths.pop()
    return t


def sort_rows(rows, key, ascending=True, stable=False):
    """DataFrame.sort_values(key, ascending, kind="stable" if stable else "quicksort")
    with no missing keys (pandas.core.sorting.nargsort)."""
    keys = [r[key] for r in rows]
    if stable:
        idx = sorted(range(len(keys)), key=keys.__getitem__, reverse=not ascending)
        return [rows[i] for i in idx]
    if ascending:
        return [rows[i] for i in argsort_quick(keys)]
    rev = keys[::-1]
    n = len(keys)
    order = [n - 1 - i for i in argsort_quick(rev)]
    return [rows[i] for i in order[::-1]]


# ---------- dates ----------
_FRACTION = re.compile(r"(\.\d{1,6})\d*", re.ASCII)
_FORMATS = (
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%d %H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%d %H:%M:%S.%f",
    "%Y-%m-%dT%H:%M%z", "%Y-%m-%d %H:%M%z", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d",
    "%a, %d %b %Y %H:%M:%S %Z", "%a, %d %b %Y %H:%M:%S %z",   # RSS (RFC 822) dates
)


_NAT_STRINGS = frozenset({"NaT", "nat", "NAT", "nan", "NaN", "NAN", "now", "today"})


def _utc(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


def parse_stamp(value):
    """pd.to_datetime(str(value), utc=True, errors="coerce") for one stamp: an aware UTC
    datetime (naive = UTC), or None."""
    s = str(value if value is not None else "").strip()
    if not s or s in NA_STRINGS:
        return None
    iso = re.sub(r"[zZ]\Z", "+00:00", s)
    iso = _FRACTION.sub(lambda m: m.group(1).ljust(7, "0"), iso, count=1)
    try:
        return _utc(datetime.fromisoformat(iso))
    except ValueError:
        pass
    try:
        return _utc(parsedate_to_datetime(s))
    except (TypeError, ValueError, IndexError):
        return None


def _strptime(s, fmt):
    try:
        return _utc(datetime.strptime(s, fmt))
    except ValueError:
        return None


def to_datetime(values) -> list:
    """pd.to_datetime(column, utc=True, errors="coerce"): the first non-empty value picks
    the format and a value in another shape is missing (None)."""
    texts = [to_text(v) if not is_missing(v) else "" for v in values]
    # pandas' first_non_null: skips "", "NaT"/"nan" spellings, "now", "today" (NOT "NA")
    first = next((s for s in texts if s and s not in _NAT_STRINGS), None)
    if first is None:
        return [None] * len(texts)
    fmt = next((f for f in _FORMATS if _strptime(first, f)), None)
    if fmt is None:  # pandas couldn't guess a format either: each value on its own
        return [parse_stamp(s) for s in texts]
    return [_strptime(s, fmt) if s else None for s in texts]
