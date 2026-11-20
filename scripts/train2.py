"""第2版モデルの学習。data/model2.json（朝版と直前版）を作る。"""
import datetime as dt
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from model import load_history  # noqa: E402
from model2 import build_dataset2, feature_names, fit2, save_model2  # noqa: E402


def main():
    rows = load_history()
    out = {"trained_at": (dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=9)).strftime("%Y-%m-%d %H:%M")}
    for name, tj in (("morning", False), ("tenji", True)):
        X, R, meta, _ = build_dataset2(rows, tenji=tj)
        dates = sorted({m["date"] for m in meta})
        warm = dates[min(30, len(dates) - 1)]
        tr = np.array([m["date"] >= warm for m in meta])
        out[name] = fit2(X[tr], R[tr], feature_names(tj))
        out["train_from"], out["train_to"], out["n_races"] = warm, dates[-1], int(tr.sum())
        print(name, int(tr.sum()), flush=True)
    save_model2(out)


if __name__ == "__main__":
    main()
