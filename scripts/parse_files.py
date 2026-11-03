"""公式ダウンロードデータ（番組表 B / 競走成績 K）の読み込み。"""
import re
import io
import lhafile

VENUES = {
    "01": "桐生", "02": "戸田", "03": "江戸川", "04": "平和島", "05": "多摩川", "06": "浜名湖",
    "07": "蒲郡", "08": "常滑", "09": "津", "10": "三国", "11": "びわこ", "12": "住之江",
    "13": "尼崎", "14": "鳴門", "15": "丸亀", "16": "児島", "17": "宮島", "18": "徳山",
    "19": "下関", "20": "若松", "21": "芦屋", "22": "福岡", "23": "唐津", "24": "大村",
}

Z2H = str.maketrans("０１２３４５６７８９：Ｒ", "0123456789:R")


def read_lzh(path):
    lf = lhafile.Lhafile(path)
    out = []
    for n in lf.namelist():
        out.append(lf.read(n).decode("cp932", errors="replace"))
    return "\n".join(out)


B_BOAT = re.compile(
    r"^([1-6]) (\d{4})(.{4})(\d{2})(.{2})(\d{2})([AB][12]) *([\d.]+) +([\d.]+) +([\d.]+) +([\d.]+) +(\d+) +([\d.]+) +(\d+) +([\d.]+)"
)
B_RACE = re.compile(r"^[\s　]*([０-９0-9]{1,2})Ｒ\s+(\S+).*?締切予定([０-９]{1,2}：[０-９]{2})")


def parse_b(text):
    """番組表 -> {(jcd, rno): {...}}"""
    races = {}
    jcd = None
    cur = None
    for line in text.splitlines():
        line = line.rstrip("\r")
        m = re.match(r"^(\d\d)BBGN", line)
        if m:
            jcd = m.group(1)
            continue
        m = B_RACE.match(line)
        if m and jcd:
            rno = int(m.group(1).translate(Z2H))
            cur = {"jcd": jcd, "rno": rno, "grade": m.group(2).strip("　"),
                   "deadline": m.group(3).translate(Z2H), "boats": []}
            races[(jcd, rno)] = cur
            continue
        if cur is not None and re.match(r"^[1-6] \d{4}", line) and len(line) >= 58:
            try:
                g = [line[0], line[2:6], line[6:10], line[10:12], line[12:14], line[14:16], line[16:18],
                     line[18:23], line[23:29], line[29:34], line[34:40], line[40:43], line[43:49],
                     line[49:52], line[52:58]]
                cur["boats"].append({
                    "lane": int(g[0]), "toban": g[1], "name": g[2].replace("　", ""),
                    "age": int(g[3]), "branch": g[4].replace("　", ""), "weight": int(g[5]),
                    "cls": g[6], "nat_win": float(g[7]), "nat_2": float(g[8]),
                    "loc_win": float(g[9]), "loc_2": float(g[10]),
                    "motor_no": int(g[11]), "motor_2": float(g[12]),
                    "boat_no": int(g[13]), "boat_2": float(g[14]),
                })
            except ValueError:
                pass
    return {k: v for k, v in races.items() if len(v["boats"]) == 6}


K_RACE = re.compile(r"^\s+(\d{1,2})R\s+(\S+).*?H(\d+)m")
K_ROW = re.compile(r"^\s+(\S+)\s+([1-6]) (\d{4}) (.{8,10}?)\s+(\d+)\s+(\d+)\s+([\d.]+)\s+([1-6])\s+([F L]?[\d.]+|[KL]\S*|\.)\s")
K_TRI = re.compile(r"３連単\s+(\d)-(\d)-(\d)\s+(\d+)")


def parse_k(text):
    """競走成績 -> {(jcd, rno): {...}}"""
    res = {}
    jcd = None
    cur = None
    for line in text.splitlines():
        line = line.rstrip("\r")
        m = re.match(r"^(\d\d)KBGN", line)
        if m:
            jcd = m.group(1)
            cur = None
            continue
        m = K_RACE.match(line)
        if m and jcd and "着 艇" not in line:
            rno = int(m.group(1))
            kimarite = line.split()[-1] if line.split() else ""
            cur = {"jcd": jcd, "rno": rno, "rows": [], "tri": None, "tri_pay": None}
            res[(jcd, rno)] = cur
            continue
        if cur is None:
            continue
        if "ﾚｰｽﾀｲﾑ" in line:
            parts = line.split()
            cur["kimarite"] = parts[-1] if parts and parts[-1] not in ("ﾚｰｽﾀｲﾑ",) else ""
            continue
        m = K_ROW.match(line)
        if m:
            rank_s, lane, toban, _name, _mo, _bo, tenji, course, st = m.groups()
            try:
                rank = int(rank_s)
            except ValueError:
                rank = 9  # F, L, 失格, 欠場など
            st_v = None
            st_s = st.strip()
            if re.match(r"^\d*\.\d+$", st_s):
                st_v = float(st_s)
            elif st_s.startswith("F"):
                st_v = -float(st_s[1:]) if re.match(r"^F\d*\.\d+$", st_s) else None
            cur["rows"].append({"rank": rank, "lane": int(lane), "toban": toban,
                                "tenji": float(tenji), "course": int(course), "st": st_v})
            continue
        m = K_TRI.search(line)
        if m and cur["tri"] is None:
            cur["tri"] = f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
            cur["tri_pay"] = int(m.group(4))
    return res
