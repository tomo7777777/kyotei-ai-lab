"""番組表と競走成績を日ごとに結合し、data/history/YYYYMM.csv.gz に保存する。

使い方:
  python scripts/build_history.py --raw raw_dir            # 手元のlzhから一括作成
  python scripts/build_history.py --days 3                 # 直近3日分をダウンロードして追記
"""
import argparse
import csv
import datetime as dt
import gzip
import io
import os
import sys
import time

import requests

sys.path.insert(0, os.path.dirname(__file__))
from parse_files import parse_b, parse_k, read_lzh  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history")
FIELDS = ["date", "jcd", "rno", "grade", "lane", "toban", "name", "age", "branch", "weight", "cls",
          "nat_win", "nat_2", "loc_win", "loc_2", "motor_2", "boat_2",
          "rank", "course", "st", "tenji", "tri", "tri_pay", "kimarite"]


def url(kind, d):
    return f"https://www1.mbrace.or.jp/od2/{kind}/{d:%Y%m}/{kind.lower()}{d:%y%m%d}.lzh"


def fetch(kind, d, raw_dir):
    fn = os.path.join(raw_dir, f"{kind.lower()}{d:%y%m%d}.lzh")
    if os.path.exists(fn) and os.path.getsize(fn) > 0:
        return fn
    for _ in range(3):
        try:
            r = requests.get(url(kind, d), timeout=60)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            with open(fn, "wb") as f:
                f.write(r.content)
            return fn
        except requests.RequestException:
            time.sleep(5)
    return None


def day_rows(d, raw_dir):
    bf = os.path.join(raw_dir, f"b{d:%y%m%d}.lzh")
    kf = os.path.join(raw_dir, f"k{d:%y%m%d}.lzh")
    if not (os.path.exists(bf) and os.path.exists(kf)):
        return []
    try:
        b = parse_b(read_lzh(bf))
        k = parse_k(read_lzh(kf))
    except Exception as e:  # 壊れたファイルは飛ばす
        print("skip", d, e)
        return []
    rows = []
    for key, race in b.items():
        res = k.get(key)
        if not res or not res["rows"]:
            continue
        by_lane = {r["lane"]: r for r in res["rows"]}
        for bt in race["boats"]:
            r = by_lane.get(bt["lane"])
            rows.append({
                "date": d.strftime("%Y%m%d"), "jcd": race["jcd"], "rno": race["rno"], "grade": race["grade"],
                "lane": bt["lane"], "toban": bt["toban"], "name": bt["name"], "age": bt["age"],
                "branch": bt["branch"], "weight": bt["weight"], "cls": bt["cls"],
                "nat_win": bt["nat_win"], "nat_2": bt["nat_2"], "loc_win": bt["loc_win"], "loc_2": bt["loc_2"],
                "motor_2": bt["motor_2"], "boat_2": bt["boat_2"],
                "rank": r["rank"] if r else 0, "course": r["course"] if r else 0,
                "st": "" if not r or r["st"] is None else r["st"],
                "tenji": r["tenji"] if r else "",
                "tri": res["tri"] or "", "tri_pay": res["tri_pay"] or "", "kimarite": res.get("kimarite", ""),
            })
    return rows


def load_month(ym):
    fn = os.path.join(HIST, f"{ym}.csv.gz")
    if not os.path.exists(fn):
        return []
    with gzip.open(fn, "rt", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_month(ym, rows):
    os.makedirs(HIST, exist_ok=True)
    rows.sort(key=lambda r: (r["date"], r["jcd"], int(r["rno"]), int(r["lane"])))
    fn = os.path.join(HIST, f"{ym}.csv.gz")
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=FIELDS)
    w.writeheader()
    w.writerows(rows)
    with gzip.open(fn, "wt", encoding="utf-8", compresslevel=9) as f:
        f.write(buf.getvalue())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", default=os.path.join(ROOT, ".raw"))
    ap.add_argument("--days", type=int, default=0, help="直近N日をダウンロードして追記")
    ap.add_argument("--start")
    ap.add_argument("--end")
    a = ap.parse_args()
    os.makedirs(a.raw, exist_ok=True)
    jst_today = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).date()
    if a.days:
        end = jst_today - dt.timedelta(days=1)
        start = end - dt.timedelta(days=a.days - 1)
    else:
        start = dt.datetime.strptime(a.start, "%Y%m%d").date()
        end = dt.datetime.strptime(a.end, "%Y%m%d").date()
    months = {}
    d = start
    while d <= end:
        if a.days:
            fetch("B", d, a.raw)
            fetch("K", d, a.raw)
        rows = day_rows(d, a.raw)
        if rows:
            months.setdefault(d.strftime("%Y%m"), {})[d.strftime("%Y%m%d")] = rows
        d += dt.timedelta(days=1)
    for ym, days in months.items():
        old = [r for r in load_month(ym) if r["date"] not in days]
        new = old + [r for rs in days.values() for r in rs]
        save_month(ym, new)
        print(ym, "days", len(days), "rows", len(new))


if __name__ == "__main__":
    main()
