"""過去レースの3連単の最終オッズを集めて data/odds/YYYYMMDD.json.gz に保存する（検証用）。

  python scripts/odds_backfill.py 20260901 20260915
"""
import datetime as dt
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from fetch_web import odds3t  # noqa: E402
from model import ROOT, load_history  # noqa: E402

OUT = os.path.join(ROOT, "data", "odds")


def main(start, end):
    races = sorted({(r["date"], r["jcd"], int(r["rno"])) for r in load_history() if start <= r["date"] <= end})
    by_day = {}
    for d, j, n in races:
        by_day.setdefault(d, []).append((j, n))
    os.makedirs(OUT, exist_ok=True)
    for d, rs in sorted(by_day.items()):
        fn = os.path.join(OUT, f"{d}.json.gz")
        if os.path.exists(fn):
            continue
        out, miss = {}, 0
        for j, n in rs:
            od = odds3t(d, j, n)
            if od:
                out[f"{j}-{n}"] = [od.get(f"{a}-{b}-{c}") for a in range(1, 7) for b in range(1, 7) for c in range(1, 7)
                                   if len({a, b, c}) == 3]
            else:
                miss += 1
            if miss >= 15 and not out:
                print("odds not available", d)
                return
        with gzip.open(fn, "wt", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"))
        print(d, len(out), "races", miss, "missing", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
