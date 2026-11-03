"""競艇AIラボの予想モデル（numpyだけで動く条件付きロジット）。

各艇のスコアを計算し、レース内でsoftmaxして1着確率を出す。
3連単の確率はハービル式（2着・3着に補正指数）で計算する。
選手のコース別成績などは「そのレースより前の日」のデータだけを使う。
"""
import csv
import glob
import gzip
import itertools
import json
import math
import os
from collections import defaultdict

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HIST = os.path.join(ROOT, "data", "history")
MODEL_PATH = os.path.join(ROOT, "data", "model.json")

CLS = {"A1": 3, "A2": 2, "B1": 1, "B2": 0}
LANE_PRIOR = [0.55, 0.14, 0.12, 0.11, 0.06, 0.02]  # 全国の枠別1着率の目安（平滑化の初期値）

FEATURES = [
    "nat_win", "nat_2", "loc_win", "motor_2", "boat_2", "cls", "age", "weight",
    "c_win", "c_top2", "c_top3", "st_avg", "recent_win",
    "l1_nat_win", "l1_cls", "l1_c_win", "l1_st", "l1_venue", "l1_motor",
    "lane2", "lane3", "lane4", "lane5", "lane6",
]


def load_history():
    rows = []
    for fn in sorted(glob.glob(os.path.join(HIST, "*.csv.gz"))):
        with gzip.open(fn, "rt", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    rows.sort(key=lambda r: (r["date"], r["jcd"], int(r["rno"]), int(r["lane"])))
    return rows


class RacerState:
    """日付順に更新する選手・場の成績集計。"""

    def __init__(self):
        self.course = defaultdict(lambda: [0, 0, 0, 0])  # (toban, lane) -> [出走, 1着, 2連対, 3連対]
        self.st = defaultdict(lambda: [0.0, 0])           # toban -> [ST合計, 回数]
        self.recent = defaultdict(list)                  # toban -> 直近の着順（最大30）
        self.venue = defaultdict(lambda: [0, 0])          # jcd -> [1号艇出走, 1号艇1着]

    def update_race(self, race_rows):
        for r in race_rows:
            rank = int(r["rank"]) if r["rank"] not in ("", None) else 0
            if rank == 0:
                continue  # 欠場
            lane = int(r["lane"])
            c = self.course[(r["toban"], lane)]
            c[0] += 1
            c[1] += rank == 1
            c[2] += rank <= 2
            c[3] += rank <= 3
            if r["st"] not in ("", None):
                st = float(r["st"])
                if 0 <= st < 1:
                    self.st[r["toban"]][0] += st
                    self.st[r["toban"]][1] += 1
            rec = self.recent[r["toban"]]
            rec.append(rank)
            if len(rec) > 30:
                del rec[0]
            if lane == 1:
                v = self.venue[r["jcd"]]
                v[0] += 1
                v[1] += rank == 1


def boat_features(b, st: RacerState, jcd):
    lane = int(b["lane"])
    toban = b["toban"]
    n, w, t2, t3 = st.course[(toban, lane)]
    k = 8.0
    pw = LANE_PRIOR[lane - 1]
    c_win = (w + k * pw) / (n + k)
    c_top2 = (t2 + k * min(0.95, pw * 1.9)) / (n + k)
    c_top3 = (t3 + k * min(0.97, pw * 2.6)) / (n + k)
    s, sn = st.st[toban]
    st_avg = (s + 0.17 * 5) / (sn + 5)
    rec = st.recent[toban]
    recent_win = (sum(1 for x in rec if x == 1) + 0.15 * 5) / (len(rec) + 5)
    vn, vw = st.venue[jcd]
    venue_l1 = (vw + 50 * 0.55) / (vn + 50)
    nat_win = float(b["nat_win"])
    loc_win = float(b["loc_win"]) or nat_win
    cls = CLS.get(b["cls"], 1)
    is1 = 1.0 if lane == 1 else 0.0
    f = {
        "nat_win": nat_win, "nat_2": float(b["nat_2"]) / 10, "loc_win": loc_win,
        "motor_2": float(b["motor_2"]) / 10, "boat_2": float(b["boat_2"]) / 10,
        "cls": cls, "age": float(b["age"]) / 10, "weight": float(b["weight"]) / 10,
        "c_win": c_win * 10, "c_top2": c_top2 * 10, "c_top3": c_top3 * 10,
        "st_avg": st_avg * 10, "recent_win": recent_win * 10,
        "l1_nat_win": is1 * nat_win, "l1_cls": is1 * cls, "l1_c_win": is1 * c_win * 10,
        "l1_st": is1 * st_avg * 10, "l1_venue": is1 * venue_l1 * 10,
        "l1_motor": is1 * float(b["motor_2"]) / 10,
    }
    for L in range(2, 7):
        f[f"lane{L}"] = 1.0 if lane == L else 0.0
    return [f[x] for x in FEATURES], {"c_win": c_win, "c_top2": c_top2, "c_top3": c_top3,
                                      "c_n": n, "st_avg": st_avg, "recent_win": recent_win}


def group_races(rows):
    races = []
    cur_key = None
    cur = []
    for r in rows:
        key = (r["date"], r["jcd"], r["rno"])
        if key != cur_key:
            if cur:
                races.append(cur)
            cur = []
            cur_key = key
        cur.append(r)
    if cur:
        races.append(cur)
    return races


def build_dataset(rows):
    """日付順に特徴量を作る。同じ日の成績はその日の特徴量に使わない。"""
    st = RacerState()
    races = group_races(rows)
    X, Y, meta = [], [], []
    day = None
    pending = []
    for race in races:
        d = race[0]["date"]
        if d != day:
            for pr in pending:
                st.update_race(pr)
            pending = []
            day = d
        pending.append(race)
        if len(race) != 6:
            continue
        ranks = [int(r["rank"] or 0) for r in race]
        if 0 in ranks or sum(1 for x in ranks if x == 1) != 1:
            continue
        feats = [boat_features(r, st, race[0]["jcd"])[0] for r in race]
        X.append(feats)
        Y.append([x == 1 for x in ranks].index(True))
        meta.append({"date": d, "jcd": race[0]["jcd"], "rno": int(race[0]["rno"]),
                     "ranks": ranks, "tri": race[0]["tri"], "tri_pay": int(race[0]["tri_pay"] or 0)})
    for pr in pending:
        st.update_race(pr)
    return np.array(X, dtype=np.float64), np.array(Y), meta, st


def softmax(z):
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def fit(X, Y, l2=1e-3, epochs=400, lr=0.05):
    mu = X.reshape(-1, X.shape[2]).mean(axis=0)
    sd = X.reshape(-1, X.shape[2]).std(axis=0) + 1e-9
    Xs = (X - mu) / sd
    w = np.zeros(X.shape[2])
    m = np.zeros_like(w)
    v = np.zeros_like(w)
    n = len(Y)
    onehot = np.zeros((n, 6))
    onehot[np.arange(n), Y] = 1
    for t in range(1, epochs + 1):
        p = softmax(Xs @ w)
        g = np.einsum("nk,nkf->f", p - onehot, Xs) / n + l2 * w
        m = 0.9 * m + 0.1 * g
        v = 0.999 * v + 0.001 * g * g
        w -= lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return {"w": w.tolist(), "mu": mu.tolist(), "sd": sd.tolist(), "features": FEATURES}


def predict_win(model, X):
    w = np.array(model["w"])
    Xs = (np.asarray(X) - np.array(model["mu"])) / np.array(model["sd"])
    return softmax(Xs @ w)


def trifecta_probs(p, a=0.85, b=0.75):
    """1着確率 p(6) -> {'1-2-3': 確率}"""
    p = np.asarray(p, dtype=float)
    out = {}
    pa = p ** a
    pb = p ** b
    for i, j, k in itertools.permutations(range(6), 3):
        p2 = pa[j] / (pa.sum() - pa[i])
        p3 = pb[k] / (pb.sum() - pb[i] - pb[j])
        out[f"{i+1}-{j+1}-{k+1}"] = p[i] * p2 * p3
    return out


def fit_harville(P, meta):
    best = None
    for a in (0.45, 0.55, 0.65, 0.75, 0.85):
        for b in (0.3, 0.4, 0.5, 0.6, 0.7):
            ll = 0.0
            for p, m in zip(P, meta):
                if not m["tri"]:
                    continue
                ll -= math.log(max(1e-9, trifecta_probs(p, a, b)[m["tri"]]))
            if best is None or ll < best[0]:
                best = (ll, a, b)
    return best[1], best[2]


def save_model(model):
    with open(MODEL_PATH, "w") as f:
        json.dump(model, f, ensure_ascii=False, indent=1)


def load_model():
    with open(MODEL_PATH) as f:
        return json.load(f)
