"""過去レースの3連単の最終オッズを集めて data/odds/YYYYMMDD.json.gz に保存する（検証用）。

  python scripts/odds_backfill.py 20260901 20260915
保存形式: {"場-R": [120個のオッズ（1-2-3, 1-2-4, ... の順）]}
"""
import gzip
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

sys.path.insert(0, os.path.dirname(__file__))
from fetch_web import UA  # noqa: E402
from model import ROOT, load_history  # noqa: E402

OUT = os.path.join(ROOT, "data", "odds")
ORDER = [f"{a}-{b}-{c}" for a in range(1, 7) for b in range(1, 7) for c in range(1, 7) if len({a, b, c}) == 3]
PAT = re.compile(r'class="oddsPoint[^"]*"[^>]*>\s*([^<]*?)\s*<')


def fetch(hd, jcd, rno, s):
    for i in range(3):
        try:
            r = s.get("https://www.boatrace.jp/owpc/pc/race/odds3t", params={"rno": rno, "jcd": jcd, "hd": hd},
                      headers=UA, timeout=30)
            if r.status_code == 200:
                vals = PAT.findall(r.text)
                if len(vals) != 120:
                    return None
                out = {}
                for row in range(20):
                    for f in range(6):
                        first = f + 1
                        others = [x for x in range(1, 7) if x != first]
                        second = others[row // 4]
                        third = [x for x in others if x != second][row % 4]
                        try:
                            out[f"{first}-{second}-{third}"] = float(vals[row * 6 + f])
                        except ValueError:
                            pass
                return [out.get(k) for k in ORDER]
            print("status", r.status_code, hd, jcd, rno, flush=True)
        except requests.RequestException as e:
            print("error", type(e).__name__, hd, jcd, rno, flush=True)
        time.sleep(3 + 3 * i)
    return None


def main(start, end, workers=3):
    races = sorted({(r["date"], r["jcd"], int(r["rno"])) for r in load_history() if start <= r["date"] <= end})
    by_day = {}
    for d, j, n in races:
        by_day.setdefault(d, []).append((j, n))
    os.makedirs(OUT, exist_ok=True)
    sessions = [requests.Session() for _ in range(workers)]
    for d, rs in sorted(by_day.items()):
        fn = os.path.join(OUT, f"{d}.json.gz")
        if os.path.exists(fn):
            continue
        t0 = time.time()
        with ThreadPoolExecutor(workers) as ex:
            res = list(ex.map(lambda a: fetch(d, a[1][0], a[1][1], sessions[a[0] % workers]), enumerate(rs)))
        out = {f"{j}-{n}": v for (j, n), v in zip(rs, res) if v}
        if not out:
            print("odds not available", d, flush=True)
            continue
        with gzip.open(fn, "wt", encoding="utf-8") as f:
            json.dump(out, f, separators=(",", ":"))
        print(d, len(out), "/", len(rs), f"{time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
