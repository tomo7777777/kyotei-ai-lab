"""競艇AIラボ 予想モデル 第2版（numpyだけで動く）。

第1版との違い
- 1着だけでなく、2着・3着もそれぞれ学習する（3連単の確率をより正確にする）
- 今節の成績、直近の平均着順、場ごとの枠の強さ、隣の艇との関係などを追加
- 展示タイムを使う「直前版」も作れる（展示の後に確率を出し直す）
選手の成績などは「そのレースより前の日」のデータだけを使う。
"""
import datetime as dt
import itertools
import json
import os
from collections import defaultdict

import numpy as np

from model import CLS, LANE_PRIOR, ROOT, group_races

MODEL2_PATH = os.path.join(ROOT, "data", "model2.json")

BASE = [
    "nat_win", "nat_2", "loc_win", "motor_2", "boat_2", "cls", "age", "weight",
    "c_win", "c_top2", "c_top3", "st_avg", "recent_win", "recent_avg", "recent_top3",
    "ks_avg", "ks_n", "ks_win", "venue_lane",
    "in_st_diff", "in_cls_diff", "out_max_win",
]
LANE_GROUPS = {"g1": (1,), "g2": (2,), "g34": (3, 4), "g56": (5, 6)}
INTER = ["nat_win", "c_win", "st_avg", "motor_2", "ks_avg", "cls", "in_st_diff"]
TENJI = ["tj_diff", "tj_rank", "tj_best"]


def feature_names(tenji=False):
    names = list(BASE) + [f"lane{L}" for L in range(2, 7)]
    for g in LANE_GROUPS:
        names += [f"{g}_{x}" for x in INTER]
    if tenji:
        names += TENJI + [f"{g}_tj_diff" for g in LANE_GROUPS]
    return names


def _d(s):
    return dt.date(int(s[:4]), int(s[4:6]), int(s[6:8]))


class State2:
    """日付順に更新する選手・場の成績集計（同じ日のレースは翌日から反映）。"""

    def __init__(self):
        self.course = defaultdict(lambda: [0, 0, 0, 0])
        self.st = defaultdict(lambda: [0.0, 0])
        self.recent = defaultdict(list)
        self.vlane = defaultdict(lambda: [0, 0])  # (jcd, lane) -> [出走, 1着]
        self.series = {}  # toban -> [jcd, 最後の日付, [着順...]]

    def update_race(self, rows):
        for r in rows:
            rank = int(r["rank"]) if r["rank"] not in ("", None) else 0
            toban, lane, jcd, d = r["toban"], int(r["lane"]), r["jcd"], r["date"]
            s = self.series.get(toban)
            if not s or s[0] != jcd or (_d(d) - _d(s[1])).days > 1:
                s = [jcd, d, []]
                self.series[toban] = s
            s[1] = d
            if rank == 0:
                continue
            s[2].append(rank)
            c = self.course[(toban, lane)]
            c[0] += 1
            c[1] += rank == 1
            c[2] += rank <= 2
            c[3] += rank <= 3
            if r["st"] not in ("", None):
                st = float(r["st"])
                if 0 <= st < 1:
                    self.st[toban][0] += st
                    self.st[toban][1] += 1
            rec = self.recent[toban]
            rec.append(rank)
            if len(rec) > 30:
                del rec[0]
            v = self.vlane[(jcd, lane)]
            v[0] += 1
            v[1] += rank == 1

    def konsetsu(self, toban, jcd, hd):
        s = self.series.get(toban)
        if not s or s[0] != jcd or (_d(hd) - _d(s[1])).days > 1 or s[1] >= hd:
            return []
        return s[2]


def race_features(boats, st: State2, jcd, hd, tenji=None):
    """boats: 6艇の dict（lane, toban, nat_win, nat_2, loc_win, motor_2, boat_2, cls, age, weight）。
    tenji: 6艇の展示タイム（無ければ None）。戻り値: (6, F) の配列と画面用の補足。"""
    raw = []
    for b in boats:
        lane, toban = int(b["lane"]), b["toban"]
        n, w, t2, t3 = st.course[(toban, lane)]
        k = 8.0
        pw = LANE_PRIOR[lane - 1]
        s, sn = st.st[toban]
        rec = st.recent[toban]
        ks = st.konsetsu(toban, jcd, hd)
        vn, vw = st.vlane[(jcd, lane)]
        nat_win = float(b["nat_win"])
        raw.append({
            "lane": lane,
            "nat_win": nat_win, "nat_2": float(b["nat_2"]) / 10, "loc_win": float(b["loc_win"]) or nat_win,
            "motor_2": float(b["motor_2"]) / 10, "boat_2": float(b["boat_2"]) / 10,
            "cls": CLS.get(b["cls"], 1), "age": float(b["age"]) / 10, "weight": float(b["weight"]) / 10,
            "c_win": (w + k * pw) / (n + k) * 10, "c_top2": (t2 + k * min(0.95, pw * 1.9)) / (n + k) * 10,
            "c_top3": (t3 + k * min(0.97, pw * 2.6)) / (n + k) * 10,
            "st_avg": (s + 0.17 * 5) / (sn + 5) * 10,
            "recent_win": (sum(1 for x in rec if x == 1) + 0.15 * 5) / (len(rec) + 5) * 10,
            "recent_avg": (sum(rec) + 3.5 * 5) / (len(rec) + 5),
            "recent_top3": (sum(1 for x in rec if x <= 3) + 0.5 * 5) / (len(rec) + 5) * 10,
            "ks_avg": (sum(ks) + 3.5 * 2) / (len(ks) + 2), "ks_n": min(len(ks), 8) / 4,
            "ks_win": (sum(1 for x in ks if x == 1) + 0.15 * 2) / (len(ks) + 2) * 10,
            "venue_lane": (vw + 100 * pw) / (vn + 100) * 10,
            "_n": n, "_ks": ks,
        })
    for i, f in enumerate(raw):
        inner = raw[i - 1] if i > 0 else None
        f["in_st_diff"] = (f["st_avg"] - inner["st_avg"]) if inner else 0.0
        f["in_cls_diff"] = (f["cls"] - inner["cls"]) if inner else 0.0
        f["out_max_win"] = max((x["nat_win"] for x in raw[i + 1:i + 4]), default=0.0) - f["nat_win"]
    names = feature_names(False)
    X = []
    for f in raw:
        lane = f["lane"]
        for L in range(2, 7):
            f[f"lane{L}"] = 1.0 if lane == L else 0.0
        for g, lanes in LANE_GROUPS.items():
            on = 1.0 if lane in lanes else 0.0
            for x in INTER:
                f[f"{g}_{x}"] = on * f[x]
        X.append([f[x] for x in names])
    X = np.array(X, dtype=np.float64)
    if tenji is not None:
        X = np.hstack([X, tenji_block(tenji)])
    extra = [{"ks_n": len(f["_ks"]), "ks_avg": round(sum(f["_ks"]) / len(f["_ks"]), 2) if f["_ks"] else None,
              "c_n": f["_n"]} for f in raw]
    return X, extra


def tenji_block(tenji):
    """展示タイム6艇分 -> (6, 7) の特徴量（TENJI と枠グループ別の展示差）。"""
    t = np.array([float(x or 0) for x in tenji], dtype=float)
    ok = t > 0
    best = t[ok].min() if ok.any() else 0
    out = []
    for i in range(6):
        lane = i + 1
        if ok[i]:
            diff = (t[i] - best) * 10
            rank = 1 + int(sum(t[ok] < t[i]))
            top = 1.0 if rank == 1 else 0.0
        else:
            diff, rank, top = 1.0, 3.5, 0.0
        out.append([diff, rank, top] + [diff if lane in lanes else 0.0 for lanes in LANE_GROUPS.values()])
    return np.array(out, dtype=np.float64)


def build_dataset2(rows, tenji=False):
    st = State2()
    X, R, meta = [], [], []
    day, pending = None, []
    for race in group_races(rows):
        d = race[0]["date"]
        if d != day:
            for pr in pending:
                st.update_race(pr)
            pending, day = [], d
        pending.append(race)
        if len(race) != 6:
            continue
        ranks = [int(r["rank"] or 0) for r in race]
        if sorted(x for x in ranks if x)[:3] != [1, 2, 3]:
            continue
        tj = None
        if tenji:
            tj = [float(r["tenji"] or 0) for r in race]
            if sum(1 for x in tj if x > 0) < 5:
                continue
        x, _ = race_features(race, st, race[0]["jcd"], d, tj)
        X.append(x)
        R.append([ranks.index(1), ranks.index(2), ranks.index(3)])
        meta.append({"date": d, "jcd": race[0]["jcd"], "rno": int(race[0]["rno"]), "ranks": ranks,
                     "tri": race[0]["tri"], "tri_pay": int(race[0]["tri_pay"] or 0)})
    for pr in pending:
        st.update_race(pr)
    return np.array(X), np.array(R), meta, st


def _softmax_masked(z, mask):
    z = np.where(mask, z, -1e9)
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z) * mask
    return e / e.sum(axis=1, keepdims=True)


def _fit_stage(Xs, R, stage, l2=1e-3, epochs=300, lr=0.05):
    n = len(R)
    mask = np.ones((n, 6), bool)
    for s in range(stage):
        mask[np.arange(n), R[:, s]] = False
    onehot = np.zeros((n, 6))
    onehot[np.arange(n), R[:, stage]] = 1
    w = np.zeros(Xs.shape[2])
    m = np.zeros_like(w)
    v = np.zeros_like(w)
    for t in range(1, epochs + 1):
        p = _softmax_masked(Xs @ w, mask)
        g = np.einsum("nk,nkf->f", p - onehot, Xs) / n + l2 * w
        m = 0.9 * m + 0.1 * g
        v = 0.999 * v + 0.001 * g * g
        w -= lr * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return w


def fit2(X, R, names):
    mu = X.reshape(-1, X.shape[2]).mean(axis=0)
    sd = X.reshape(-1, X.shape[2]).std(axis=0) + 1e-9
    Xs = (X - mu) / sd
    ws = [_fit_stage(Xs, R, s).tolist() for s in range(3)]
    return {"w": ws, "mu": mu.tolist(), "sd": sd.tolist(), "features": names}


def scores(model, X):
    Xs = (np.asarray(X) - np.array(model["mu"])) / np.array(model["sd"])
    return [Xs @ np.array(w) for w in model["w"]]  # 各 (..., 6)


PERMS = [(i, j, k) for i, j, k in itertools.permutations(range(6), 3)]
KEYS = [f"{i+1}-{j+1}-{k+1}" for i, j, k in PERMS]


def trifecta2(s1, s2, s3):
    """1レース分のスコア（各6）から3連単120通りの確率（KEYS の順）。"""
    e1, e2, e3 = np.exp(s1 - s1.max()), np.exp(s2 - s2.max()), np.exp(s3 - s3.max())
    p1 = e1 / e1.sum()
    out = np.empty(120)
    for n, (i, j, k) in enumerate(PERMS):
        p2 = e2[j] / (e2.sum() - e2[i])
        p3 = e3[k] / (e3.sum() - e3[i] - e3[j])
        out[n] = p1[i] * p2 * p3
    return p1, out


def save_model2(model, path=MODEL2_PATH):
    with open(path, "w") as f:
        json.dump(model, f, ensure_ascii=False, indent=1)


def load_model2(path=MODEL2_PATH):
    with open(path) as f:
        return json.load(f)
