"""予想の選び方（毎朝の予想と過去検証の両方で同じものを使う）。"""
import numpy as np

from model import trifecta_probs

MARKS = ["◎", "○", "▲", "△"]
TOP_N_RACES = 5      # AI予想で出すレース数
HEAD2_MAX_P1 = 0.21  # 1号艇の1着率がこれ以下なら頭2艇の対象
STRONG_P = 0.20      # 「確率20%以上だけ」の基準（計算値で判定）


def analyze_race(p, harville):
    p = np.asarray(p, dtype=float)
    tri = trifecta_probs(p, *harville)
    top = sorted(tri.items(), key=lambda kv: -kv[1])
    order = list(np.argsort(-p))
    score = float(p.max()) * 0.5 + sum(v for _, v in top[:6]) * 0.5
    head2 = None
    if p[0] <= HEAD2_MAX_P1:
        others = [i for i in order if i != 0][:2]
        head2 = [int(i) + 1 for i in others]
    return {
        "p": [round(float(x), 4) for x in p],
        "marks": {str(int(i) + 1): MARKS[n] for n, i in enumerate(order[:4])},
        "honmei": int(order[0]) + 1,
        "top": [[k, round(v, 4)] for k, v in top[:10]],
        "bets": [k for k, _ in top[:5]],
        "strong": [k for k, v in top[:5] if v >= STRONG_P],
        "score": score,
        "head2": head2,
    }


def add_confidence(races):
    """その日のレースの中での順位から自信度（0〜100）を付ける。"""
    if not races:
        return
    scores = sorted(r["ai"]["score"] for r in races)
    n = len(scores)
    for r in races:
        rank = sum(1 for s in scores if s <= r["ai"]["score"])
        r["ai"]["conf"] = int(round(100 * rank / n)) if n > 1 else 50


def select_top(races, n=TOP_N_RACES):
    return sorted(races, key=lambda r: -r["ai"]["score"])[:n]
