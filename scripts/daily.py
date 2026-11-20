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
from fetch_web import UA, beforeinfo, odds3t, racelist, resultlist, venues_today  # noqa: E402
from model import ROOT, RacerState, boat_features, group_races, load_history, load_model, predict_win  # noqa: E402
from parse_files import VENUES, parse_b, read_lzh  # noqa: E402
from model2 import KEYS, State2, load_model2, race_features, scores, tenji_block, trifecta2  # noqa: E402
from picks import add_confidence, analyze_race, konsetsu_target, select_top  # noqa: E402

DAYS = os.path.join(ROOT, "data", "days")
FEAT = os.path.join(ROOT, "data", "feat")
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


def racer_state(rows=None):
    st = RacerState()
    for race in group_races(rows if rows is not None else load_history()):
        st.update_race(race)
    return st


def konsetsu_ranks(rows, hd):
    """選手ごとに、hd の前日まで同じ場で続けて走った今節の着順を集める。{(登録番号, 場): [着順,...]}"""
    d0 = dt.datetime.strptime(hd, "%Y%m%d").date()
    by = {}
    for r in rows:
        if r["date"] < hd:
            by.setdefault(r["toban"], []).append(r)
    out = {}
    for toban, rs in by.items():
        jcd = rs[-1]["jcd"]
        last = d0
        ranks = []
        for r in reversed(rs):
            d = dt.datetime.strptime(r["date"], "%Y%m%d").date()
            if r["jcd"] != jcd or (last - d).days > 1:
                break
            last = d
            if r["rank"] not in ("", None) and int(r["rank"]) > 0:
                ranks.append(int(r["rank"]))
        if ranks:
            out[(toban, jcd)] = ranks
    return out


def state2(rows):
    st = State2()
    for race in group_races(rows):
        st.update_race(race)
    return st


def ai2_from_scores(sc):
    p1, tri = trifecta2(*sc)
    order = np.argsort(-tri)
    return {"p": [round(float(x), 4) for x in p1],
            "top": [[KEYS[i], round(float(tri[i]), 4)] for i in order[:10]],
            "bets": [KEYS[i] for i in order[:5]],
            "score": round(float(p1.max()) * 0.5 + float(tri[order[:6]].sum()) * 0.5, 4)}, tri


def add_ai2(races, rows, hd):
    """第2版AIの朝の予想を各レースに付け、直前用の特徴量を data/feat に保存する。"""
    try:
        m2 = load_model2()
    except FileNotFoundError:
        return None
    st = state2(rows)
    feats = {}
    for r in races:
        X, _ = race_features([{k: str(v) for k, v in b.items()} for b in r["boats"]], st, r["jcd"], hd)
        r["ai2"], _ = ai2_from_scores(scores(m2["morning"], X))
        feats[f"{r['jcd']}-{r['rno']}"] = np.round(X, 5).tolist()
    os.makedirs(FEAT, exist_ok=True)
    import gzip
    with gzip.open(os.path.join(FEAT, f"{hd}.json.gz"), "wt") as f:
        json.dump(feats, f, separators=(",", ":"))
    return m2


def add_konsetsu(races, ks):
    for r in races:
        for b in r["boats"]:
            rk = ks.get((str(b["toban"]), r["jcd"]), [])
            b["ks_n"] = len(rk)
            b["ks_avg"] = round(sum(rk) / len(rk), 2) if rk else None


def program_today(hd):
    """番組表ファイル → だめなら公式サイトの出走表。"""
    import requests
    d = dt.datetime.strptime(hd, "%Y%m%d")
    url = f"https://www1.mbrace.or.jp/od2/B/{d:%Y%m}/b{d:%y%m%d}.lzh"
    try:
        r = requests.get(url, headers=UA, timeout=60)
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
    rows = load_history()
    st = racer_state(rows)
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
                "age": b["age"], "nat_win": b["nat_win"], "nat_2": b["nat_2"], "loc_win": b["loc_win"],
                "weight": b["weight"], "motor_2": b["motor_2"], "boat_2": b["boat_2"],
                "c_win": round(ex["c_win"], 3), "c_top3": round(ex["c_top3"], 3), "c_n": ex["c_n"],
                "st_avg": round(ex["st_avg"], 3),
            } for b, ex in zip(boats, extras)],
            "ai": ai,
        })
    add_confidence(races)
    add_konsetsu(races, konsetsu_ranks(rows, hd))
    m2 = add_ai2(races, rows, hd)
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
        "konsetsu": [f"{r['jcd']}-{r['rno']}" for r in open_races if konsetsu_target(r)],
        "picks2": [f"{r['jcd']}-{r['rno']}" for r in sorted(open_races, key=lambda r: -r["ai2"]["score"])[:5]] if m2 else [],
        "model2": {"trained_at": m2.get("trained_at"), "train_to": m2.get("train_to")} if m2 else None,
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
    focus = set(day["picks"]) | set(day["head2"]) | set(day.get("konsetsu", []))
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
        if key in day["picks"] or key in day.get("konsetsu", []):
            od = odds3t(hd, r["jcd"], r["rno"])
            if od:
                inv = sum(1 / v for v in od.values() if v)
                ks = list(dict.fromkeys(r["ai"]["bets"] + [r["ai"]["top"][0][0]]))
                r["odds"] = {k: od.get(k) for k in ks}
                r["mkt"] = {k: round((1 / od[k]) / inv, 4) for k in ks if od.get(k)}
                r["odds_at"] = t.strftime("%H:%M")
    # 3) 第2版AIの直前予想（締切8分前〜1分前に、展示とその時点のオッズで決める）
    if hd == t.strftime("%Y%m%d"):
        try:
            live_v2(hd, day, cur, t)
        except Exception as e:  # noqa: BLE001
            print("live_v2 failed", e)
    day["updated_at"] = t.strftime("%Y-%m-%d %H:%M")
    save_json(path, day)
    records()


LIVE = os.path.join(ROOT, "data", "live")


def ev_bets(tri, odds):
    """期待値ルールで買い目を選ぶ（picks.EV_RULE。未設定なら買わない）。"""
    from picks import EV_RULE
    if not EV_RULE:
        return []
    c = []
    for i, k in enumerate(KEYS):
        o = odds[i]
        if not o:
            continue
        p = float(tri[i])
        if p >= EV_RULE["min_p"] and EV_RULE["min_odds"] <= o <= EV_RULE["max_odds"] and p * o >= EV_RULE["min_ev"]:
            c.append((p * o, k))
    c.sort(reverse=True)
    return [k for _, k in c[:EV_RULE["max_points"]]]


def live_v2(hd, day, cur, t):
    import gzip
    fp = os.path.join(FEAT, f"{hd}.json.gz")
    if not os.path.exists(fp):
        return
    feats = json.load(gzip.open(fp, "rt"))
    lp = os.path.join(LIVE, f"{hd}.json.gz")
    live = json.load(gzip.open(lp, "rt")) if os.path.exists(lp) else {}
    m2 = None
    changed = False
    for r in day["races"]:
        key = f"{r['jcd']}-{r['rno']}"
        left = minutes(r["deadline"]) - cur
        if key in live or key not in feats or r.get("result") or not (1 <= left <= 5):
            continue
        bi = beforeinfo(hd, r["jcd"], r["rno"])
        od = odds3t(hd, r["jcd"], r["rno"])
        if not bi or not od:
            continue
        if not r.get("tenji"):
            r["tenji"] = {str(k): v for k, v in bi.items()}
        m2 = m2 or load_model2()
        X = np.hstack([np.array(feats[key]), tenji_block([bi.get(i, {}).get("tenji") for i in range(1, 7)])])
        a, tri = ai2_from_scores(scores(m2["tenji"], X))
        olist = [od.get(k) for k in KEYS]
        live[key] = {"at": t.strftime("%H:%M"), "tri": [round(float(x), 5) for x in tri], "odds": olist}
        bets = ev_bets(tri, olist)
        r["v2live"] = {"at": t.strftime("%H:%M"), "p": a["p"],
                       "top": [[k, pp, od.get(k)] for k, pp in a["top"][:5]],
                       "bets": bets, "odds": {k: od.get(k) for k in bets}}
        changed = True
    if changed:
        os.makedirs(LIVE, exist_ok=True)
        with gzip.open(lp, "wt") as f:
            json.dump(live, f, separators=(",", ":"))


def records():
    """全日の記録から成績をまとめる。予想を固定した時点で締切前だったレースだけを数える。"""
    days = []
    for fn in sorted(glob.glob(os.path.join(DAYS, "*.json"))):
        day = load_json(fn)
        by_key = {f"{r['jcd']}-{r['rno']}": r for r in day["races"]}
        row = {"date": day["date"]}
        for kind in ("top5", "strong", "head2", "konsetsu", "v2top5", "v2ev"):
            row[kind] = {"races": 0, "points": 0, "hits": 0, "pay": 0, "pending": 0}
        for key in day.get("picks2", []):
            r = by_key.get(key)
            if not r or not r.get("ai2"):
                continue
            a = row["v2top5"]
            res = r.get("result")
            if not res:
                a["pending"] += 1
                continue
            a["races"] += 1
            a["points"] += len(r["ai2"]["bets"])
            if res["tri"] in r["ai2"]["bets"]:
                a["hits"] += 1
                a["pay"] += res["pay"]
        for r in day["races"]:
            bets = (r.get("v2live") or {}).get("bets")
            if not bets:
                continue
            a = row["v2ev"]
            res = r.get("result")
            if not res:
                a["pending"] += 1
                continue
            a["races"] += 1
            a["points"] += len(bets)
            if res["tri"] in bets:
                a["hits"] += 1
                a["pay"] += res["pay"]
        for key in day.get("konsetsu", []):
            r = by_key.get(key)
            if not r:
                continue
            a = row["konsetsu"]
            res = r.get("result")
            if not res:
                a["pending"] += 1
                continue
            bet = r["ai"]["top"][0][0]
            a["races"] += 1
            a["points"] += 1
            if res["tri"] == bet:
                a["hits"] += 1
                a["pay"] += res["pay"]
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
    for kind in ("top5", "strong", "head2", "konsetsu", "v2top5", "v2ev"):
        s = {k: sum(d[kind][k] for d in days) for k in ("races", "points", "hits", "pay")}
        if s["points"]:
            s["roi"] = round(s["pay"] / (s["points"] * 100) * 100, 1)
        total[kind] = s
    out = {"updated_at": now().strftime("%Y-%m-%d %H:%M"), "since": days[0]["date"] if days else None,
           "total": total, "days": days[::-1]}
    save_json(os.path.join(ROOT, "data", "records.json"), out)
    # 画面用の一覧（新しい順）
    save_json(os.path.join(ROOT, "data", "days_index.json"), [d["date"] for d in days[::-1]])


def fill_results():
    """公式サイトから結果が取れなかった日を、過去データ（競走成績ファイル）で埋める。"""
    rows = load_history()
    res = {}
    for r in rows:
        if r["tri"] and r["tri_pay"] not in ("", "0"):
            res[(r["date"], r["jcd"], int(r["rno"]))] = {"tri": r["tri"], "pay": int(float(r["tri_pay"]))}
    for fn in sorted(glob.glob(os.path.join(DAYS, "*.json"))):
        day = load_json(fn)
        n = 0
        for r in day["races"]:
            v = res.get((day["date"], r["jcd"], int(r["rno"])))
            if v and not r.get("result"):
                r["result"] = v
                n += 1
        if n:
            save_json(fn, day)
            print("filled", day["date"], n)
    records()


def ai2_attach(hd=None):
    """固定済みの日に第2版AIの朝の予想を付ける（締切前のレースだけを第2版の対象にする）。"""
    hd = hd or now().strftime("%Y%m%d")
    path = day_path(hd)
    day = load_json(path)
    if not day or day.get("picks2"):
        print("skip", hd)
        return
    rows = [r for r in load_history() if r["date"] < hd]
    last = {r["toban"]: r for r in rows}
    for r in day["races"]:
        for b in r["boats"]:
            h = last.get(str(b["toban"]), {})
            b.setdefault("nat_2", float(h.get("nat_2") or 30))
            b.setdefault("weight", int(float(h.get("weight") or 52)))
    m2 = add_ai2(day["races"], rows, hd)
    if not m2:
        return
    t = now()
    hm = t.strftime("%H:%M")
    open_races = [r for r in day["races"] if r["deadline"] > hm or t.strftime("%Y%m%d") < hd]
    day["picks2"] = [f"{r['jcd']}-{r['rno']}" for r in sorted(open_races, key=lambda r: -r["ai2"]["score"])[:5]]
    day["model2"] = {"trained_at": m2.get("trained_at"), "train_to": m2.get("train_to"), "attached_at": t.strftime("%Y-%m-%d %H:%M")}
    save_json(path, day)
    print("ai2", hd, day["picks2"])


def konsetsu_backfill():
    """記録開始前の日に、朝の予想と前日までの成績だけで今節本命を付け直す（予想そのものは変えない）。"""
    rows = load_history()
    for fn in sorted(glob.glob(os.path.join(DAYS, "*.json"))):
        day = load_json(fn)
        if "konsetsu" in day:
            continue
        hd = day["date"]
        add_konsetsu(day["races"], konsetsu_ranks(rows, hd))
        gen_hm = day["fixed_at"][11:16]
        gen_d = day["fixed_at"][:10].replace("-", "")
        day["konsetsu"] = [f"{r['jcd']}-{r['rno']}" for r in day["races"]
                           if (r["deadline"] > gen_hm or gen_d < hd) and konsetsu_target(r)]
        save_json(fn, day)
        print(hd, day["konsetsu"])
    records()


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "update"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "morning":
        morning(arg, force="--force" in sys.argv)
    elif cmd == "update":
        update(arg)
    elif cmd == "records":
        records()
    elif cmd == "all_done":
        d = load_json(day_path(now().strftime("%Y%m%d")))
        sys.exit(0 if d and all(r.get("result") or r.get("canceled") for r in d["races"]) else 1)
    elif cmd == "ai2_attach":
        ai2_attach(arg)
    elif cmd == "fill_results":
        fill_results()
    elif cmd == "konsetsu_backfill":
        konsetsu_backfill()
