"""毎日の自動処理。

  python scripts/daily.py morning   # 朝: その日の全レースを予想して固定する（2回目以降は何もしない）
  python scripts/daily.py update    # 日中: 展示・オッズ・結果を取り込み、成績を更新する
  python scripts/daily.py records   # 成績だけ作り直す
"""
import datetime as dt
import glob
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from fetch_web import beforeinfo, odds3t, racelist, resultlist, venues_today  # noqa: E402
from model import ROOT, RacerState, boat_features, group_races, load_history, load_model, predict_win  # noqa: E402
from parse_files import VENUES, parse_b, read_lzh  # noqa: E402
from picks import add_confidence, analyze_race, select_top  # noqa: E402

DAYS = os.path.join(ROOT, "data", "days")
JST = dt.timezone(dt.timedelta(hours=9))


def now():
    return dt.datetime.now(JST)


def day_path(hd):
    return os.path.join(DAYS, f"{hd}.json")


def save_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def load_json(path, default=None):
    if not os.path.exists(path):
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def racer_state():
    st = RacerState()
    for race in group_races(load_history()):
        st.update_race(race)
    return st


def program_today(hd):
    """番組表ファイル → だめなら公式サイトの出走表。"""
    import requests
    d = dt.datetime.strptime(hd, "%Y%m%d")
    url = f"https://www1.mbrace.or.jp/od2/B/{d:%Y%m}/b{d:%y%m%d}.lzh"
    try:
        r = requests.get(url, timeout=60)
        if r.status_code == 200 and len(r.content) > 1000:
            fn = f"/tmp/b{d:%y%m%d}.lzh"
            open(fn, "wb").write(r.content)
            races = parse_b(read_lzh(fn))
            if races:
                return list(races.values())
    except Exception as e:  # noqa: BLE001
        print("B file failed", e)
    races = []
    for jcd in venues_today(hd):
        for rno in range(1, 13):
            rl = racelist(hd, jcd, rno)
            if rl and len(rl["boats"]) == 6:
                races.append({"jcd": jcd, "rno": rno, "grade": "", "deadline": rl["deadline"], "boats": rl["boats"]})
    return races


def morning(hd=None, force=False):
    hd = hd or now().strftime("%Y%m%d")
    path = day_path(hd)
    if os.path.exists(path) and not force:
        print("already fixed", hd)
        return
    model = load_model()
    harv = tuple(model.get("harville", (0.85, 0.75)))
    st = racer_state()
    prog = program_today(hd)
    if not prog:
        print("no program yet", hd)
        return
    races = []
    for race in prog:
        boats = sorted(race["boats"], key=lambda b: b["lane"])
        feats, extras = [], []
        for b in boats:
            f, ex = boat_features({k: str(v) for k, v in b.items()} | {"lane": b["lane"]}, st, race["jcd"])
            feats.append(f)
            extras.append(ex)
        p = predict_win(model, np.array([feats]))[0]
        ai = analyze_race(p, harv)
        races.append({
            "jcd": race["jcd"], "venue": VENUES.get(race["jcd"], race["jcd"]), "rno": race["rno"],
            "grade": race.get("grade", ""), "deadline": race["deadline"],
            "boats": [{
                "lane": b["lane"], "toban": b["toban"], "name": b["name"], "cls": b["cls"], "branch": b["branch"],
                "age": b["age"], "nat_win": b["nat_win"], "loc_win": b["loc_win"],
                "motor_2": b["motor_2"], "boat_2": b["boat_2"],
                "c_win": round(ex["c_win"], 3), "c_top3": round(ex["c_top3"], 3), "c_n": ex["c_n"],
                "st_avg": round(ex["st_avg"], 3),
            } for b, ex in zip(boats, extras)],
            "ai": ai,
        })
    add_confidence(races)
    races.sort(key=lambda r: (r["deadline"], r["jcd"]))
    gen = now()
    gen_hm = gen.strftime("%H:%M")
    # 予想を作った時点で締切前のレースだけを、AI予想・頭2艇の対象にする
    open_races = [r for r in races if r["deadline"] > gen_hm or gen.strftime("%Y%m%d") < hd]
    top = select_top(open_races)
    for r in races:
        r["ai"]["score"] = round(r["ai"]["score"], 4)
    day = {
        "date": hd, "fixed_at": gen.strftime("%Y-%m-%d %H:%M"),
        "model": {"trained_at": model.get("trained_at"), "train_to": model.get("train_to")},
        "picks": [f"{r['jcd']}-{r['rno']}" for r in top],
        "head2": [f"{r['jcd']}-{r['rno']}" for r in open_races if r["ai"]["head2"]],
        "races": races,
        "updated_at": gen.strftime("%Y-%m-%d %H:%M"),
    }
    save_json(path, day)
    print("fixed", hd, len(races), "races; picks", day["picks"], "head2", len(day["head2"]))


def minutes(hm):
    h, m = hm.split(":")
    return int(h) * 60 + int(m)


def update(hd=None):
    hd = hd or now().strftime("%Y%m%d")
    path = day_path(hd)
    day = load_json(path)
    t = now()
    if not day and hd == t.strftime("%Y%m%d") and t.hour >= 5:
        morning(hd)  # 朝の実行が遅れた・失敗したときの予備
        day = load_json(path)
    if not day:
        print("no day file", hd)
        return
    cur = t.hour * 60 + t.minute
    if hd < t.strftime("%Y%m%d"):
        cur = 48 * 60  # 前日分は全レース締切後として扱う
    focus = set(day["picks"]) | set(day["head2"])
    by_key = {f"{r['jcd']}-{r['rno']}": r for r in day["races"]}
    # 1) 結果（締切を過ぎたレースがある場だけ）
    venues = sorted({r["jcd"] for r in day["races"]
                     if minutes(r["deadline"]) + 5 <= cur and not r.get("result")})
    for jcd in venues:
        res = resultlist(hd, jcd)
        for rno, v in res.items():
            r = by_key.get(f"{jcd}-{rno}")
            if r and not r.get("result"):
                r["result"] = v
    # 2) 対象レースの展示とオッズ（締切35分前〜締切）
    for key in sorted(focus):
        r = by_key[key]
        left = minutes(r["deadline"]) - cur
        if r.get("result") or left < -2 or left > 35:
            continue
        if not r.get("tenji") and left <= 30:
            bi = beforeinfo(hd, r["jcd"], r["rno"])
            if bi:
                r["tenji"] = {str(k): v for k, v in bi.items()}
                times = sorted((v["tenji"], k) for k, v in bi.items() if v.get("tenji"))
                for rank, (_, lane) in enumerate(times, 1):
                    r["tenji"][str(lane)]["rank"] = rank
        if key in day["picks"]:
            od = odds3t(hd, r["jcd"], r["rno"])
            if od:
                inv = sum(1 / v for v in od.values() if v)
                r["odds"] = {k: od.get(k) for k in r["ai"]["bets"]}
                r["mkt"] = {k: round((1 / od[k]) / inv, 4) for k in r["ai"]["bets"] if od.get(k)}
                r["odds_at"] = t.strftime("%H:%M")
    day["updated_at"] = t.strftime("%Y-%m-%d %H:%M")
    save_json(path, day)
    records()


def records():
    """全日の記録から成績をまとめる。予想を固定した時点で締切前だったレースだけを数える。"""
    days = []
    for fn in sorted(glob.glob(os.path.join(DAYS, "*.json"))):
        day = load_json(fn)
        by_key = {f"{r['jcd']}-{r['rno']}": r for r in day["races"]}
        row = {"date": day["date"]}
        for kind in ("top5", "strong", "head2"):
            row[kind] = {"races": 0, "points": 0, "hits": 0, "pay": 0, "pending": 0}
        for key in day["picks"]:
            r = by_key.get(key)
            if not r:
                continue
            res = r.get("result")
            for kind, bets in (("top5", r["ai"]["bets"]), ("strong", r["ai"]["strong"])):
                if not bets:
                    continue
                a = row[kind]
                if not res:
                    a["pending"] += 1
                    continue
                a["races"] += 1
                a["points"] += len(bets)
                if res["tri"] in bets:
                    a["hits"] += 1
                    a["pay"] += res["pay"]
        for key in day["head2"]:
            r = by_key.get(key)
            if not r:
                continue
            a = row["head2"]
            res = r.get("result")
            if not res:
                a["pending"] += 1
                continue
            a["races"] += 1
            a["hits"] += int(res["tri"].split("-")[0]) in r["ai"]["head2"]
        days.append(row)
    total = {}
    for kind in ("top5", "strong", "head2"):
        s = {k: sum(d[kind][k] for d in days) for k in ("races", "points", "hits", "pay")}
        if s["points"]:
            s["roi"] = round(s["pay"] / (s["points"] * 100) * 100, 1)
        total[kind] = s
    out = {"updated_at": now().strftime("%Y-%m-%d %H:%M"), "since": days[0]["date"] if days else None,
           "total": total, "days": days[::-1]}
    save_json(os.path.join(ROOT, "data", "records.json"), out)
    # 画面用の一覧（新しい順）
    save_json(os.path.join(ROOT, "data", "days_index.json"), [d["date"] for d in days[::-1]])


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "update"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "morning":
        morning(arg, force="--force" in sys.argv)
    elif cmd == "update":
        update(arg)
    elif cmd == "records":
        records()
