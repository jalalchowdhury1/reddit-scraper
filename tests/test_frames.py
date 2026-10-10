"""core/frames.py: the site's stand-in for pandas (10 Oct 2026, pandas left the Vercel
function to shrink it ~85%). Part 1 pins each rule with literal answers (no pandas needed).
Part 2 fuzzes against real pandas 2.x when it is installed (CI: requirements-scraper.txt
pins pandas 2.1.4, what the site ran on Vercel)."""
import csv
import io
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import frames  # noqa: E402


def write(tmp_path, text, name="t.csv"):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8", newline="")
    return p


# ---------- part 1: the rules ----------

def test_types_like_pandas(tmp_path):
    t = frames.read_csv(write(tmp_path, "id,n,m,b,bm,x,na\n1wk,1, 2,True,true,NA,\n2ab,3,,False,,None,null\n"))
    assert t.kinds == {"id": "O", "n": "i", "m": "f", "b": "b", "bm": "O", "x": "na", "na": "na"}
    assert t.rows[0] == {"id": "1wk", "n": 1, "m": 2.0, "b": True, "bm": True, "x": None, "na": None}
    assert t.rows[1] == {"id": "2ab", "n": 3, "m": None, "b": False, "bm": None, "x": None, "na": None}
    assert [str(r["m"]) for r in t.fillna("").rows] == ["2.0", ""]   # what a card would show


def test_text_that_only_looks_numeric_stays_text(tmp_path):
    t = frames.read_csv(write(tmp_path, "a,b,c\n１２,1_000,0x10\n"))
    assert t.rows == [{"a": "１２", "b": "1_000", "c": "0x10"}]


def test_lines_header_and_broken_files(tmp_path):
    t = frames.read_csv(write(tmp_path, 'a,a,\n\n1,2,3\n   \n4\n""\n'))
    assert t.columns == ["a", "a.1", "Unnamed: 2"]
    assert [r["a"] for r in t.rows] == [1.0, 4.0, None]               # blank lines skipped, "" kept, short rows padded
    assert len(frames.read_csv(write(tmp_path, "a,b\n"))) == 0      # header only = empty
    with pytest.raises(ValueError):
        frames.read_csv(write(tmp_path, ""))                        # pandas: EmptyDataError
    with pytest.raises(ValueError):
        frames.read_csv(write(tmp_path, "a,b\n1,2\n3,4,5\n"))       # pandas: ParserError
    t = frames.read_csv(write(tmp_path, "a,b\n0,1,2\n0,3,4\n"))      # one extra field = pandas' index column
    assert t.rows == [{"a": 1, "b": 2}, {"a": 3, "b": 4}]
    assert frames.read_csv(write(tmp_path, "﻿id\nx\n")).columns == ["id"]


def test_concat_casts_like_pandas(tmp_path):
    def table(text, name):
        return frames.read_csv(write(tmp_path, text, name))
    ints, floats = table("v\n1\n", "i.csv"), table("v\n1.5\n", "f.csv")
    bools, text = table("v\nTrue\n", "b.csv"), table("v\nx\n", "o.csv")
    empty, other = table("v,k\n,1\n", "na.csv"), table("k\n1\n", "void.csv")
    shown = lambda *ts: [str(r["v"]) for r in frames.concat([*ts]).fillna("").rows]
    # each row = what pandas 2.1.4 printed for the same files
    assert shown(table("v\n1\n", "i1.csv"), table("v\n2\n", "i2.csv")) == ["1", "2"]
    assert shown(ints, floats) == ["1.0", "1.5"]
    assert shown(ints, other) == ["1.0", ""]
    assert shown(ints, text) == ["1", "x"]
    assert shown(table("v\nTrue\n", "b1.csv"), table("v\n7\n", "i3.csv")) == ["1", "7"]
    assert shown(table("v\nTrue\n", "b2.csv"), table("v\n7\n", "i4.csv"), other) == ["True", "7", ""]
    assert shown(bools, empty) == ["1.0", ""]
    assert shown(bools, other) == ["True", ""]


def test_numbers():
    assert frames.to_number(" 12 ") == 12 and frames.to_number("+3") == 3 and frames.to_number("1e3") == 1000.0
    assert frames.to_number("Infinity") == math.inf
    for junk in ("", "1,200", "1.5k", "True", "1_000", "１２", "1e400", None):
        assert math.isnan(frames.to_number(junk)), junk


def test_quicksort_keeps_numpys_tie_order():
    keys = list("cbacbabbbcacababbabc")
    # numpy 1.26 np.array(keys, dtype=object).argsort(kind="quicksort"); a stable sort differs
    assert frames.argsort_quick(keys) == [2, 17, 5, 10, 12, 14, 1, 4, 6, 7, 8, 18, 16, 13, 15, 0, 9, 3, 11, 19]
    rows = [{"k": k, "i": i} for i, k in enumerate("bab")]
    assert [r["i"] for r in frames.sort_rows(rows, "k", ascending=False, stable=True)] == [0, 2, 1]


def test_dates():
    utc = lambda *a: datetime(*a, tzinfo=timezone.utc)
    # the column's first value picks the format; another shape is missing
    assert frames.to_datetime(["", "2026-10-10T06:30:14-04:00", "2026-10-10T21:58:33Z", "2026-06-26 20:43:45"]) == \
        [None, utc(2026, 10, 10, 10, 30, 14), utc(2026, 10, 10, 21, 58, 33), None]
    # "NA" is pandas' first value too: no format, so each value is parsed on its own
    assert frames.to_datetime(["NA", "2026-10-10", "2026-06-26 20:43:45"]) == \
        [None, utc(2026, 10, 10), utc(2026, 6, 26, 20, 43, 45)]
    assert frames.parse_stamp("2026-10-10T21:58:33.5Z") == utc(2026, 10, 10, 21, 58, 33, 500000)
    assert frames.parse_stamp("Sat, 10 Oct 2026 06:30:00 GMT") == utc(2026, 10, 10, 6, 30)
    assert frames.parse_stamp("") is None and frames.parse_stamp("garbage") is None


def test_server_imports_without_pandas(monkeypatch):
    """The site must not need pandas: Vercel installs requirements.txt only."""
    for mod in ("pandas", "numpy", "server"):
        monkeypatch.delitem(sys.modules, mod, raising=False)
    monkeypatch.setitem(sys.modules, "pandas", None)
    monkeypatch.setitem(sys.modules, "numpy", None)
    import server
    assert server.get_data()["reddit_subs"]
    monkeypatch.delitem(sys.modules, "server")
    req = (Path(__file__).resolve().parent.parent / "requirements.txt").read_text().lower()
    assert "pandas" not in req and "numpy" not in req


# ---------- part 2: fuzz against real pandas 2.x ----------

def _pandas2():
    pd = pytest.importorskip("pandas")
    if not pd.__version__.startswith("2."):
        pytest.skip("parity is with pandas 2.x (the version the site ran on Vercel)")
    return pd


def _norm(v):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return None
    if hasattr(v, "item"):
        v = v.item()
    return type(v).__name__, v


@pytest.mark.filterwarnings("ignore")   # pandas' own format/concat warnings
def test_read_csv_and_concat_match_pandas(tmp_path):
    pd = _pandas2()
    rnd = random.Random(7)
    pick = {"int": ["1", "-2", " 3", "+7", ""], "float": ["1.5", ".5", "1e3", "inf", "1", ""],
            "bool": ["True", "False", "true", ""], "na": ["", "NA", "None", "null"],
            "text": ["abc", "1", "x,y", 'q"t', "a\nb", "", "N/A", "True", "2026-10-10T06:30:14-04:00"]}
    for trial in range(300):
        tables, dfs = [], []
        for k in range(rnd.randint(1, 4)):
            cols = list(dict.fromkeys(rnd.choice(["id", "score", "upvotes", "score_real"]) for _ in range(3)))
            fam = {c: rnd.choice(list(pick)) for c in cols}
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            for _ in range(rnd.randint(0, 4)):
                w.writerow([rnd.choice(pick[fam[c]]) for c in cols])
            p = write(tmp_path, buf.getvalue(), f"{k}.csv")
            df, t = pd.read_csv(p), frames.read_csv(p)
            assert list(df.columns) == t.columns
            assert [[_norm(v) for v in r] for r in df.itertuples(index=False, name=None)] == \
                [[_norm(r[c]) for c in t.columns] for r in t.rows], buf.getvalue()
            if not df.empty:
                dfs.append(df)
                tables.append(t)
        if dfs:
            want = pd.concat(dfs, ignore_index=True)
            got = frames.concat(tables)
            if "score_real" in want.columns:
                assert list(want["score_real"].astype(str).str.lower().isin(["true", "1"])) == \
                    [frames.to_text(r.get("score_real")).lower() in ("true", "1") for r in got.rows]
            assert [[str(v) for v in r] for r in want.fillna("").itertuples(index=False, name=None)] == \
                [[str(r[c]) for c in want.columns] for r in got.fillna("").rows]


@pytest.mark.filterwarnings("ignore")   # pandas' own format/concat warnings
def test_sorting_and_dates_match_pandas():
    pd = _pandas2()
    rnd = random.Random(11)
    shapes = ["2026-02-28T05:07:00+00:00", "2026-10-10T06:30:14-04:00", "2026-06-26 20:43:45",
              "2026-10-10T21:58:33Z", "2026-10-10T21:58:33.123456", "2026-10-10", "", "NA", "garbage"]
    for trial in range(200):
        n = rnd.choice([5, 16, 17, 40, 300])
        keys = [rnd.choice(shapes[:4] + [""]) for _ in range(n)]
        df = pd.DataFrame({"k": keys, "i": range(n)}, dtype=object)
        rows = [{"k": k, "i": i} for i, k in enumerate(keys)]
        for asc in (True, False):
            assert list(df.sort_values("k", ascending=asc)["i"]) == \
                [r["i"] for r in frames.sort_rows(rows, "k", ascending=asc)]
        vals = [rnd.choice(shapes) for _ in range(rnd.randint(0, 6))]
        want = [None if pd.isna(x) else x.to_pydatetime()
                for x in pd.to_datetime(pd.Series(vals, dtype=object), utc=True, errors="coerce")]
        assert frames.to_datetime(vals) == want, vals
