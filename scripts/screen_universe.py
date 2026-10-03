#!/usr/bin/env python3
"""Build the opportunity screen from data/opportunity/* (whole-market pull)."""
import json

import numpy as np
import pandas as pd

D = "data/opportunity"
uni = pd.read_csv(f"{D}/universe.csv").set_index("symbol")
fund = json.load(open(f"{D}/fundamentals_liquid.json"))


def qkey(r):
    return (r.get("yearReport") or 0) * 4 + (r.get("lengthReport") or 0)


rows = []
for sym, f in fund.items():
    r = {"symbol": sym}
    ra = f.get("ratios") or {}
    r["mcap_bn"] = round(ra["MARKETCAP"] / 1e9) if ra.get("MARKETCAP") else None
    r["pe"] = round(ra["PRICE_TO_EARNINGS"], 1) if ra.get("PRICE_TO_EARNINGS") else None
    r["pb"] = round(ra["PRICE_TO_BOOK"], 2) if ra.get("PRICE_TO_BOOK") else None
    r["dy"] = round(ra["DIVIDEND_YIELD"] * 100, 1) if ra.get("DIVIDEND_YIELD") is not None else None
    inc = f.get("INCOME_STATEMENT") or []
    q = {qkey(x): x for x in inc}
    ks = sorted(q)
    bank = any((x.get("isb38") or 0) for x in inc)
    if ks:
        k = ks[-1]
        r["last_q"] = f"{q[k]['yearReport']}Q{q[k]['lengthReport']}"

        def s(field, keys):
            vals = [q.get(kk, {}).get(field) for kk in keys]
            return None if any(v is None for v in vals) else sum(vals)

        def g(field, n, lag=4):
            cur = s(field, [k - i for i in range(n)])
            prev = s(field, [k - i - lag for i in range(n)])
            if cur is None or prev is None or prev <= 0:
                return cur, None
            return cur, round((cur / prev - 1) * 100, 1)

        pbt_q, r["pbt_q_yoy"] = g("isa16", 1)
        _, r["pbt_prevq_yoy"] = (lambda c, p: (c, p))(*[None, None])
        cur_prev = s("isa16", [k - 1])
        prev_prev = s("isa16", [k - 5])
        r["pbt_prevq_yoy"] = round((cur_prev / prev_prev - 1) * 100, 1) if cur_prev and prev_prev and prev_prev > 0 else None
        pbt6, r["pbt_6m_yoy"] = g("isa16", 2)
        pbt_ttm, r["pbt_ttm_yoy"] = g("isa16", 4)
        rev_field = "isb38" if bank else "isa3"
        _, r["rev_6m_yoy"] = g(rev_field, 2)
        np_ttm, r["np_ttm_yoy"] = g("isa22", 4)
        fin_inc, _ = g("isa6", 2) if not bank else (None, None)
        r["pbt_ttm_bn"] = round(pbt_ttm / 1e9) if pbt_ttm else None
        r["np_ttm_bn"] = round(np_ttm / 1e9) if np_ttm else None
        r["pbt_q_bn"] = round(pbt_q / 1e9) if pbt_q else None
        # share of financial income in 6M PBT (one-off risk proxy)
        if fin_inc and pbt6 and pbt6 > 0:
            r["fin_inc_share_6m"] = round(fin_inc / pbt6 * 100)
    r["bank"] = bank
    bs = sorted(f.get("BALANCE_SHEET") or [], key=qkey)
    if bs and not bank:
        b = bs[-1]
        cash = (b.get("bsa2") or 0) + (b.get("bsa5") or 0) + (b.get("bsb108") or 0)
        debt = (b.get("bsa56") or 0) + (b.get("bsa71") or 0)
        r["net_cash_bn"] = round((cash - debt) / 1e9)
        r["equity_bn"] = round((b.get("bsa78") or 0) / 1e9)
        r["debt_to_equity"] = round(debt / b["bsa78"], 2) if b.get("bsa78") else None
        if r.get("mcap_bn"):
            r["net_cash_to_mcap"] = round(r["net_cash_bn"] / r["mcap_bn"] * 100)
    ov = f.get("overview") or {}
    r["vci_rating"], r["vci_tp"] = ov.get("rating"), (ov.get("targetPrice") or 0) / 1000 or None
    r["state_pct"] = round(ov["statePercentage"] * 100, 1) if ov.get("statePercentage") is not None else None
    r["foreign_pct"] = round(ov["foreignerPercentage"] * 100, 1) if ov.get("foreignerPercentage") is not None else None
    r["foreign_max"] = round(ov["maximumForeignPercentage"] * 100, 1) if ov.get("maximumForeignPercentage") is not None else None
    r["sector"] = ov.get("sectorVn") or ov.get("sector")
    rc = [x for x in (f.get("recs") or []) if x.get("targetPrice")]
    r["n_recs_2026"] = len(rc)
    r["recs_tp_median"] = float(np.median([x["targetPrice"] for x in rc])) if rc else None
    ev = f.get("events") or []
    r["events"] = " | ".join(f"{e.get('disclosureDate')} {e.get('typeDesc')}: {(e.get('note') or '')[:60]}" for e in ev[:4])
    rows.append(r)

fu = pd.DataFrame(rows).set_index("symbol")
df = uni.join(fu, how="inner")
for k in ("vci_tp", "recs_tp_median"):
    df[f"up_{k}"] = ((df[k] / df["close"] - 1) * 100).round(1)
df.to_csv(f"{D}/screen_liquid.csv")
print(len(df), "liquid names with fundamentals")
