"""BOAT RACE公式サイト（boatrace.jp）から当日の情報を読む。"""
import re
import time

import requests
from bs4 import BeautifulSoup

BASE = "https://www.boatrace.jp/owpc/pc/race"
UA = {"User-Agent": "Mozilla/5.0 (kyotei-ai-lab personal use)"}
Z2H = str.maketrans("０１２３４５６７８９", "0123456789")
_session = requests.Session()


def get(path, **params):
    for i in range(3):
        try:
            r = _session.get(f"{BASE}/{path}", params=params, headers=UA, timeout=30)
            r.raise_for_status()
            time.sleep(0.4)
            return BeautifulSoup(r.text, "html.parser")
        except requests.RequestException:
            time.sleep(3 + i * 3)
    return None


def venues_today(hd):
    s = get("index", hd=hd)
    if not s:
        return []
    return sorted(set(re.findall(r"jcd=(\d\d)", str(s))))


def deadlines(s):
    """racelist/beforeinfo等のページ上部の締切予定時刻（12個）"""
    for tbl in s.select("div.table1 table"):
        t = re.sub(r"\s+", " ", tbl.get_text(" ", strip=True))
        if "締切予定時刻" in t:
            return re.findall(r"\d{1,2}:\d{2}", t)
    return []


def racelist(hd, jcd, rno):
    s = get("racelist", rno=rno, jcd=jcd, hd=hd)
    if not s:
        return None
    boats = []
    for tb in s.select("div.table1.is-tableFixed__3rdadd table tbody"):
        tds = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)) for td in tb.select("tr")[0].select("td")]
        try:
            lane = int(tds[0].translate(Z2H))
            m = re.match(r"(\d{4}) / (\S\d) (.+?) (\S+?)/\S+ (\d+)歳/([\d.]+)kg", tds[2])
            nat = tds[4].split()
            loc = tds[5].split()
            mo = tds[6].split()
            bo = tds[7].split()
            boats.append({
                "lane": lane, "toban": m.group(1), "cls": m.group(2), "name": m.group(3).replace(" ", ""),
                "branch": m.group(4), "age": int(m.group(5)), "weight": int(float(m.group(6))),
                "nat_win": float(nat[0]), "nat_2": float(nat[1]), "loc_win": float(loc[0]), "loc_2": float(loc[1]),
                "motor_no": int(mo[0]), "motor_2": float(mo[1]), "boat_no": int(bo[0]), "boat_2": float(bo[1]),
            })
        except (AttributeError, IndexError, ValueError):
            continue
    dl = deadlines(s)
    return {"boats": boats, "deadline": dl[rno - 1] if len(dl) >= rno else ""}


def beforeinfo(hd, jcd, rno):
    s = get("beforeinfo", rno=rno, jcd=jcd, hd=hd)
    if not s:
        return None
    out = {}
    for tb in s.select("table.is-w748 tbody"):
        tds = [td.get_text(" ", strip=True) for td in tb.select("td")]
        try:
            lane = int(tds[0])
        except (ValueError, IndexError):
            continue
        tenji = tds[4] if len(tds) > 4 else ""
        tilt = tds[5] if len(tds) > 5 else ""
        out[lane] = {"tenji": float(tenji) if re.match(r"^\d\.\d\d$", tenji) else None,
                     "tilt": tilt, "weight": tds[3] if len(tds) > 3 else ""}
    course = 0
    for x in s.select(".table1_boatImage1"):
        t = x.get_text(" ", strip=True).split()
        if len(t) >= 2 and t[0].isdigit():
            course += 1
            lane = int(t[0])
            st = t[1]
            if lane in out:
                out[lane]["ex_course"] = course
                out[lane]["ex_st"] = st
    if not any(v.get("tenji") for v in out.values()):
        return None
    return out


def odds3t(hd, jcd, rno):
    s = get("odds3t", rno=rno, jcd=jcd, hd=hd)
    if not s:
        return None
    vals = [td.get_text(strip=True) for td in s.select("td.oddsPoint")]
    if len(vals) != 120:
        return None
    out = {}
    for r in range(20):
        for f in range(6):
            first = f + 1
            others = [x for x in range(1, 7) if x != first]
            second = others[r // 4]
            third = [x for x in others if x != second][r % 4]
            v = vals[r * 6 + f]
            try:
                out[f"{first}-{second}-{third}"] = float(v)
            except ValueError:
                pass
    return out or None


def resultlist(hd, jcd):
    """{rno: {'tri': '1-2-3', 'pay': 1860}}（確定したレースのみ）"""
    s = get("resultlist", jcd=jcd, hd=hd)
    if not s:
        return {}
    t = re.sub(r"\s+", " ", s.get_text(" ", strip=True)).replace("¥", "&yen;")
    out = {}
    for m in re.finditer(r"(\d{1,2})R (\d) - (\d) - (\d) (?:&yen;|￥|¥)\s?([\d,]+)", t):
        out[int(m.group(1))] = {"tri": f"{m.group(2)}-{m.group(3)}-{m.group(4)}",
                                "pay": int(m.group(5).replace(",", ""))}
    # 返還・不成立は「特払い」等の表記になるので、ここでは扱わない
    return out
