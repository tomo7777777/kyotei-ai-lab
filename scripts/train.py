"""モデルの学習と過去データでの検証。data/model.json と data/backtest.json を作る。"""
import datetime as dt
import json
import math
import os
import sys
from collections import defaultdict

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from model import (ROOT, build_dataset, fit, fit_harville, load_history, predict_win,  # noqa: E402
                   save_model, softmax)
from parse_files import VENUES  # noqa: E402
from picks import analyze_race, add_confidence, select_top  # noqa: E402

TEST_DAYS = 45


def logloss(P, Y):
    return float(-np.mean(np.log(P[np.arange(len(Y)), Y] + 1e-12)))


def evaluate(P, meta, harville):
    by_day = defaultdict(list)
    for p, m in zip(P, meta):
        r = dict(m)
        r["ai"] = analyze_race(p, harville)
        by_day[m["date"]].append(r)
    s = defaultdict(lambda: {"races": 0, "points": 0, "hits": 0, "pay": 0})
    honmei_hit = 0
    n_all = 0
    monthly = defaultdict(lambda: {"points": 0, "pay": 0, "hits": 0, "races": 0})
    for d, races in by_day.items():
        add_confidence(races)
        for r in races:
            n_all += 1
            honmei_hit += r["ranks"][r["ai"]["honmei"] - 1] == 1
            # 全レースで推奨5点
            a = s["all5"]
            a["races"] += 1
            a["points"] += 5
            if r["tri"] in r["ai"]["bets"]:
                a["hits"] += 1
                a["pay"] += r["tri_pay"]
            if r["ai"]["head2"]:
                h = s["head2"]
                h["races"] += 1
                winner = r["ranks"].index(1) + 1
                h["hits"] += winner in r["ai"]["head2"]
                h["p1_lose"] = h.get("p1_lose", 0) + (winner != 1)
        for r in select_top(races):
            for key, bets in (("top5", r["ai"]["bets"]), ("strong", r["ai"]["strong"])):
                if not bets:
                    continue
                a = s[key]
                a["races"] += 1
                a["points"] += len(bets)
                if r["tri"] in bets:
                    a["hits"] += 1
                    a["pay"] += r["tri_pay"]
                if key == "top5":
                    mm = monthly[d[:6]]
                    mm["races"] += 1
                    mm["points"] += len(bets)
                    if r["tri"] in bets:
                        mm["hits"] += 1
                        mm["pay"] += r["tri_pay"]
    out = {}
    for k, v in s.items():
        v = dict(v)
        if "points" in v and v["points"]:
            v["roi"] = round(v["pay"] / (v["points"] * 100) * 100, 1)
        if v.get("races"):
            v["hit_rate"] = round(v["hits"] / v["races"] * 100, 1)
        out[k] = v
    out["honmei_win"] = round(honmei_hit / max(1, n_all) * 100, 1)
    out["n_races"] = n_all
    out["days"] = len(by_day)
    out["monthly_top5"] = {k: {**v, "roi": round(v["pay"] / max(1, v["points"] * 100) * 100, 1)}
                           for k, v in sorted(monthly.items())}
    return out


def main():
    rows = load_history()
    X, Y, meta, _ = build_dataset(rows)
    dates = sorted({m["date"] for m in meta})
    cut = dates[-TEST_DAYS]
    tr = np.array([m["date"] < cut for m in meta])
    te = ~tr
    # 検証の最初の期間は学習の「慣らし」として捨てる（選手成績が貯まっていないため）
    warm = dates[min(30, len(dates) - 1)]
    tr = tr & np.array([m["date"] >= warm for m in meta])
    print("train", tr.sum(), "test", te.sum(), "cut", cut)
    model = fit(X[tr], Y[tr])
    P = predict_win(model, X[te])
    meta_te = [m for m, t in zip(meta, te) if t]
    lane_only = np.tile(np.bincount(Y[tr], minlength=6) / tr.sum(), (te.sum(), 1))
    harv = fit_harville(P[:3000], meta_te[:3000])
    print("harville", harv)
    res = evaluate(P, meta_te, harv)
    res["logloss_model"] = round(logloss(P, Y[te]), 4)
    res["logloss_lane_only"] = round(logloss(lane_only, Y[te]), 4)
    res["test_from"] = meta_te[0]["date"]
    res["test_to"] = meta_te[-1]["date"]
    print(json.dumps(res, ensure_ascii=False, indent=1))

    # 全期間で学習し直して保存
    tr_all = np.array([m["date"] >= warm for m in meta])
    final = fit(X[tr_all], Y[tr_all])
    final["harville"] = list(harv)
    final["trained_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")
    final["train_from"] = warm
    final["train_to"] = dates[-1]
    final["n_races"] = int(tr_all.sum())
    save_model(final)
    with open(os.path.join(ROOT, "data", "backtest.json"), "w") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
