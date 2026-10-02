#!/usr/bin/env python3
"""Condense data/snapshot/fundamentals2.json into a compact table + analyst-recommendation list."""
import json

import pandas as pd

SNAP = "data/snapshot"
f = json.load(open(f"{SNAP}/fundamentals2.json"))
px = pd.read_csv(f"{SNAP}/prices_metrics.csv")
px = px[~px["group"].isin(["global", "crypto"])].set_index("symbol")

rows, recs = [], {}
for sym, v in f.items():
    r = {"symbol": sym}
    vd = {d["ratioCode"]: d["value"] for d in (v.get("vndirect_new") or {}).get("data", []) if isinstance(d, dict)}
    r["mcap_bn"] = round(vd["MARKETCAP"] / 1e9) if vd.get("MARKETCAP") else None
    r["pe_vnd"] = round(vd["PRICE_TO_EARNINGS"], 2) if vd.get("PRICE_TO_EARNINGS") else None
    r["pb_vnd"] = round(vd["PRICE_TO_BOOK"], 2) if vd.get("PRICE_TO_BOOK") else None
    r["div_yield_pct"] = round(vd["DIVIDEND_YIELD"] * 100, 2) if vd.get("DIVIDEND_YIELD") is not None else None
    ov = ((v.get("iq_overview") or {}).get("data") or {})
    for k_src, k in (("rating", "vci_rating"), ("ratingAsOf", "vci_rating_date"), ("targetPrice", "vci_target"),
                     ("upsideToTargetPercent", "vci_upside"), ("projectedTSRPercentage", "vci_tsr"),
                     ("foreignerPercentage", "foreign_own"), ("maximumForeignPercentage", "foreign_max"),
                     ("statePercentage", "state_own"), ("averageMatchValue1Month", "adv_1m")):
        r[k] = ov.get(k_src)
    if r["vci_target"]:
        r["vci_target"] = r["vci_target"] / 1000
    for k in ("vci_upside", "vci_tsr", "foreign_own", "foreign_max", "state_own"):
        if r[k] is not None:
            r[k] = round(r[k] * 100, 1)
    if r["adv_1m"]:
        r["adv_1m"] = round(r["adv_1m"] / 1e9, 1)
    st = (v.get("iq_stats_fin") or {}).get("data") or []
    st = [s for s in st if isinstance(s, dict)]
    st.sort(key=lambda s: (s.get("yearReport") or 0, s.get("quarter") or 0))
    if st:
        last = st[-1]
        r["ttm_period"] = f"{last.get('yearReport')}Q{last.get('quarter')}"
        for k in ("pe", "pb", "roe", "roa", "npl", "netInterestMargin", "casaRatio", "cir", "car",
                  "debtToEquity", "grossMargin", "afterTaxProfitMargin", "loansGrowth", "depositGrowth",
                  "ldrLoanDepositRatio", "loansLossReservesToNPLs"):
            val = last.get(k)
            if val is None:
                continue
            r[f"q_{k}"] = round(val * 100, 2) if k in ("roe", "roa", "npl", "netInterestMargin", "casaRatio", "cir",
                                                       "grossMargin", "afterTaxProfitMargin", "loansGrowth",
                                                       "depositGrowth", "loansLossReservesToNPLs") and abs(val) < 50 else round(val, 2)
        # TTM net income = mcap / pe, YoY change vs 4 quarters earlier
        def ni(s):
            return s["marketCap"] / s["pe"] if s.get("pe") and s.get("marketCap") and s["pe"] > 0 else None
        if len(st) >= 5 and ni(st[-1]) and ni(st[-5]):
            r["ttm_np_yoy_pct"] = round((ni(st[-1]) / ni(st[-5]) - 1) * 100, 1)
        if len(st) >= 9 and ni(st[-5]) and ni(st[-9]):
            r["ttm_np_yoy_prev_pct"] = round((ni(st[-5]) / ni(st[-9]) - 1) * 100, 1)
        hist = [s for s in st if (s.get("yearReport") or 0) >= 2021]
        pes = [s["pe"] for s in hist if s.get("pe") and 0 < s["pe"] < 200]
        pbs = [s["pb"] for s in hist if s.get("pb") and 0 < s["pb"] < 50]
        if pes and r.get("pe_vnd"):
            r["pe_5y_median"] = round(float(pd.Series(pes).median()), 2)
            r["pe_pctile_5y"] = round(float((pd.Series(pes) < r["pe_vnd"]).mean() * 100))
        if pbs and r.get("pb_vnd"):
            r["pb_5y_median"] = round(float(pd.Series(pbs).median()), 2)
            r["pb_pctile_5y"] = round(float((pd.Series(pbs) < r["pb_vnd"]).mean() * 100))
    rc = (v.get("vndirect_recs") or {}).get("data") or []
    rc = [x for x in rc if isinstance(x, dict) and (x.get("reportDate") or "") >= "2025-10-01"]
    recs[sym] = rc
    if rc:
        tps = [x["targetPrice"] for x in rc if x.get("targetPrice") and (x.get("reportDate") or "") >= "2026-04-01"]
        r["recs_6m_n"] = len(tps)
        r["recs_6m_median_tp"] = round(float(pd.Series(tps).median()), 2) if tps else None
        avg = [x.get("avgTargetPrice") for x in rc if x.get("avgTargetPrice")]
        r["bbg_avg_tp"] = round(avg[0], 2) if avg else None
        r["recs_types"] = ",".join(sorted({x.get("type", "") for x in rc if (x.get("reportDate") or "") >= "2026-04-01"}))
    if sym in px.index:
        r["close"] = px.loc[sym, "close"]
        for k in ("vci_target", "recs_6m_median_tp", "bbg_avg_tp"):
            if r.get(k):
                r[f"up_{k}"] = round((r[k] / r["close"] - 1) * 100, 1)
    rows.append(r)

df = pd.DataFrame(rows)
df.to_csv(f"{SNAP}/fundamentals_compact.csv", index=False)
json.dump(recs, open(f"{SNAP}/analyst_recs_12m.json", "w"), ensure_ascii=False, indent=1)
print(f"{len(df)} tickers")
