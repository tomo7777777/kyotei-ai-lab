"""選手の癖ページ用のデータを作る（data/racers/<登番>.json と data/racers_index.json）。"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(__file__))
from model import ROOT, load_history  # noqa: E402
from parse_files import VENUES  # noqa: E402

OUT = os.path.join(ROOT, "data", "racers")


def main():
    rows = load_history()
    info = {}
    course = defaultdict(lambda: defaultdict(lambda: {"n": 0, "w": 0, "t2": 0, "t3": 0, "st": 0.0, "stn": 0}))
    entry = defaultdict(lambda: defaultdict(Counter))  # 枠 -> 実際の進入コース
    kimarite = defaultdict(Counter)
    lost_by = defaultdict(Counter)  # 1コースで負けたときの決まり手
    recent = defaultdict(list)
    fl = defaultdict(lambda: {"F": 0, "L": 0})
    race_kim = {}
    for r in rows:
        race_kim[(r["date"], r["jcd"], r["rno"])] = r["kimarite"]
    for r in rows:
        t = r["toban"]
        info[t] = {"toban": t, "name": r["name"], "branch": r["branch"], "cls": r["cls"], "age": r["age"],
                   "nat_win": r["nat_win"], "nat_2": r["nat_2"]}
        rank = int(r["rank"] or 0)
        c = int(r["course"] or 0)
        if rank == 0 or c == 0:
            continue
        a = course[t][c]
        a["n"] += 1
        a["w"] += rank == 1
        a["t2"] += rank <= 2
        a["t3"] += rank <= 3
        if r["st"] not in ("", None):
            stv = float(r["st"])
            if stv < 0:
                fl[t]["F"] += 1
            elif stv < 1:
                a["st"] += stv
                a["stn"] += 1
        entry[t][int(r["lane"])][c] += 1
        if rank == 1:
            kimarite[t][r["kimarite"]] += 1
        elif c == 1:
            lost_by[t][race_kim.get((r["date"], r["jcd"], r["rno"]), "")] += 1
        recent[t].append([r["date"], r["jcd"], int(r["rno"]), int(r["lane"]), c, rank, r["st"]])
    os.makedirs(OUT, exist_ok=True)
    index = []
    for t, inf in info.items():
        cs = {}
        total = {"n": 0, "w": 0, "t3": 0}
        for c in range(1, 7):
            a = course[t].get(c)
            if not a or not a["n"]:
                cs[str(c)] = None
                continue
            total["n"] += a["n"]
            total["w"] += a["w"]
            total["t3"] += a["t3"]
            cs[str(c)] = {"n": a["n"], "win": round(a["w"] / a["n"], 3), "top2": round(a["t2"] / a["n"], 3),
                          "top3": round(a["t3"] / a["n"], 3),
                          "st": round(a["st"] / a["stn"], 3) if a["stn"] else None}
        ent = {}
        for lane, cnt in entry[t].items():
            n = sum(cnt.values())
            ent[str(lane)] = {"n": n, "same": round(cnt[lane] / n, 3),
                              "inner": round(sum(v for k, v in cnt.items() if k < lane) / n, 3)}
        rec = recent[t][-20:][::-1]
        out = {**inf, "course": cs, "entry": ent, "kimarite": dict(kimarite[t].most_common()),
               "lost_in1": dict(lost_by[t].most_common()), "F": fl[t]["F"], "starts": total["n"],
               "recent": [{"date": x[0], "venue": VENUES.get(x[1], x[1]), "rno": x[2], "lane": x[3],
                           "course": x[4], "rank": x[5], "st": x[6]} for x in rec],
               "period": [rows[0]["date"], rows[-1]["date"]]}
        with open(os.path.join(OUT, f"{t}.json"), "w", encoding="utf-8") as f:
            json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
        index.append([t, inf["name"], inf["branch"], inf["cls"]])
    index.sort()
    with open(os.path.join(ROOT, "data", "racers_index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, separators=(",", ":"))
    print("racers", len(index))


if __name__ == "__main__":
    main()
