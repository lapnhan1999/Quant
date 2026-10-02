#!/usr/bin/env python3
"""Assemble per-candidate fact sheets (verified data only) for the research workflow."""
import json

import pandas as pd

SNAP = "data/snapshot"
CANDIDATES = {
    "bank": ["VCB", "BID", "CTG", "MBB", "VPB", "TCB", "HDB", "TPB"],
    "broker": ["SSI", "VND"],
    "consumer_tech": ["FPT", "MWG", "MSN", "VNM", "SAB", "FRT"],
    "industrial_energy": ["HPG", "DCM", "POW", "NT2", "PVS", "PC1", "GMD", "REE", "CTR"],
    "real_estate": ["VHM", "IDC", "KDH", "VRE"],
    "defensive_dividend": ["BMP", "DHG", "SIP"],
}

px = pd.read_csv(f"{SNAP}/prices_metrics.csv")
glob = px[px["group"].isin(["global", "crypto"])].set_index("symbol")
px = px[~px["group"].isin(["global", "crypto"])].set_index("symbol")
fu = pd.read_csv(f"{SNAP}/fundamentals_compact.csv").set_index("symbol")
bt = pd.read_csv(f"{SNAP}/backtest_holding_winrates.csv").set_index("sym")
recs = json.load(open(f"{SNAP}/analyst_recs_12m.json"))
news = json.load(open(f"{SNAP}/news.json"))
funds = pd.DataFrame(json.load(open(f"{SNAP}/funds.json")))
crypto = json.load(open(f"{SNAP}/crypto.json"))


def fmt(d, keys):
    out = []
    for k in keys:
        v = d.get(k)
        if v is None or (isinstance(v, float) and pd.isna(v)):
            continue
        out.append(f"{k}={round(v, 3) if isinstance(v, float) else v}")
    return ", ".join(out)


PX_KEYS = ["last_date", "close", "chg_1d_pct", "ret_1w", "ret_1m", "ret_3m", "ret_6m", "ret_ytd", "ret_1y", "ret_3y",
           "high_52w", "high_52w_date", "low_52w", "low_52w_date", "pct_from_52w_high", "pct_from_52w_low",
           "ma20", "ma50", "ma100", "ma200", "pct_vs_ma50", "pct_vs_ma200", "rsi14", "atr14", "atr14_pct",
           "vol_1y_ann_pct", "max_dd_1y_pct", "beta_vs_vnindex", "low_20d", "high_20d", "low_60d", "high_60d",
           "low_120d", "high_120d", "xcheck_sources", "xcheck_max_diff_pct"]
FU_KEYS = ["mcap_bn", "pe_vnd", "pe_5y_median", "pe_pctile_5y", "pb_vnd", "pb_5y_median", "pb_pctile_5y",
           "div_yield_pct", "q_roe", "q_npl", "q_netInterestMargin", "q_casaRatio", "q_cir", "q_ldrLoanDepositRatio",
           "q_loansLossReservesToNPLs", "q_debtToEquity", "last_q", "pbt_q_bn", "pbt_q_yoy", "pbt_6m_bn",
           "pbt_6m_yoy", "pbt_ttm_bn", "pbt_ttm_yoy", "rev_q_yoy", "rev_6m_yoy", "np_6m_yoy", "np_ttm_yoy",
           "prov_6m_yoy", "foreign_own", "foreign_max", "state_own", "adv_1m",
           "vci_rating", "vci_rating_date", "vci_target", "up_vci_target", "vci_tsr", "bbg_avg_tp"]
BT_KEYS = ["p_win6", "p_beat_dep6", "med6", "p10_6", "p_win12", "p_beat_dep12", "med12", "p_win6_dd", "med6_dd"]


def stock_dossier(sym, group):
    lines = [f"# {sym} ({group}) — dữ liệu xác minh đến phiên 02/10/2026 (giá: nghìn đồng)"]
    if sym in px.index:
        lines.append("GIÁ & KỸ THUẬT (đối chiếu 3 nguồn VNDirect/Vietcap/DNSE): " + fmt(px.loc[sym].to_dict(), PX_KEYS))
    if sym in fu.index:
        lines.append("ĐỊNH GIÁ & KQKD (VNDirect ratios, Vietcap IQ BCTC quý; *_yoy = % so cùng kỳ; pctile_5y = phân vị "
                     "trong 5 năm, 0 = rẻ nhất): " + fmt(fu.loc[sym].to_dict(), FU_KEYS))
    if sym in bt.index:
        lines.append("BACKTEST 5 NĂM (mua ngẫu nhiên giữ 6/12 tháng; p_beat_dep = % lần vượt lãi tiết kiệm 3,6%/6T, "
                     "7,3%/12T; *_dd = khi đang giảm 8–40% từ đỉnh 52 tuần): " + fmt(bt.loc[sym].to_dict(), BT_KEYS))
    rc = recs.get(sym) or []
    if rc:
        lines.append("KHUYẾN NGHỊ CTCK 12 THÁNG (nguồn VNDirect/Bloomberg; lưu ý giá có thể chưa điều chỉnh theo "
                     "cổ tức cổ phiếu/thưởng):")
        for x in rc[:14]:
            lines.append(f"  - {x.get('reportDate')} {x.get('firm')} {x.get('type')} giá lúc báo cáo={x.get('reportPrice')} "
                         f"mục tiêu={x.get('targetPrice')}")
    nw = [n for n in (news.get(sym) or []) if n.get("title")]
    if nw:
        lines.append("TIN 30 NGÀY (Google News):")
        for n in nw[:12]:
            lines.append(f"  - {(n.get('date') or '')[5:16]} | {n['title'][:170]}")
    return "\n".join(lines)


def etf_fund_dossier():
    lines = ["# ETF & QUỸ MỞ VIỆT NAM — dữ liệu 02/10/2026"]
    for s in ["E1VFVN30", "FUEVFVND", "FUESSVFL", "FUEKIV30", "FUEVN100", "FUESSV30", "FUEMAV30", "FUEDCMID",
              "VNINDEX", "VN30"]:
        if s in px.index:
            lines.append(f"{s}: " + fmt(px.loc[s].to_dict(), ["close", "ret_1m", "ret_3m", "ret_ytd", "ret_1y", "ret_3y",
                                                          "high_52w", "low_52w", "pct_from_52w_high", "pct_vs_ma200",
                                                          "rsi14", "vol_1y_ann_pct", "max_dd_1y_pct", "low_120d"]))
        if s in bt.index:
            lines.append(f"  backtest: " + fmt(bt.loc[s].to_dict(), BT_KEYS))
    cols = ["code", "issuer", "asset_type", "nav", "navTo1Months", "navTo6Months", "navTo12Months", "navTo36Months",
            "navTo60Months", "annualizedReturn36Months", "navToLastYear", "mgmt_fee"]
    lines.append("QUỸ MỞ (Fmarket, % thay đổi NAV):")
    lines.append(funds[cols].sort_values(["asset_type", "annualizedReturn36Months"], ascending=[True, False])
                 .to_csv(index=False, sep="|"))
    lines.append("TIN: " + " || ".join(n["title"][:120] for n in (news.get("_FTSE") or [])[:6] if n.get("title")))
    return "\n".join(lines)


def gold_dossier():
    g = json.load(open(f"{SNAP}/gold_fx.json"))
    lines = ["# VÀNG (SJC / nhẫn 9999) & BẠC — 02/10/2026"]
    for s in ["GC=F", "SI=F", "DX-Y.NYB", "^TNX", "BZ=F", "VND=X"]:
        if s in glob.index:
            lines.append(f"{s}: " + fmt(glob.loc[s].to_dict(), ["close", "ret_1m", "ret_3m", "ret_ytd", "ret_1y",
                                                             "high_52w", "high_52w_date", "low_52w", "low_52w_date",
                                                             "ma50", "ma200", "pct_vs_ma200", "rsi14",
                                                             "vol_1y_ann_pct", "max_dd_1y_pct", "low_120d"]))
    lines.append("PNJ bảng giá (đơn vị 10.000đ/chỉ → x10 = triệu/lượng): " + g.get("pnj", "")[:700])
    lines.append("Vietcombank USD: chuyển khoản 25.790, bán 26.170 (02/10/2026)")
    lines.append("Quy đổi: 1 lượng = 1,20565 oz. Vàng TG 4.183 USD/oz × 1,20565 × 26.170 ≈ 132,0 triệu/lượng; SJC bán "
                 "144,1 → chênh khoảng +12 triệu (~9%).")
    lines.append("TIN: " + " || ".join(n["title"][:120] for n in (news.get("_GOLD_VN") or [])[:8] if n.get("title")))
    return "\n".join(lines)


def crypto_dossier(sym):
    lines = [f"# {sym} — dữ liệu 02/10/2026 (USD)"]
    for s in ["BTC-USD", "ETH-USD", "SOL-USD", "BNB-USD", "XRP-USD", "LINK-USD"]:
        rows = px.loc[[s]] if s in px.index else None
    km = crypto.get("kraken_metrics", {})
    for s in ["BTC", "ETH", "SOL", "BNB"]:
        if s in km:
            lines.append(f"{s}: " + fmt(km[s], ["last_date", "close", "ret_1m", "ret_3m", "ret_ytd", "ret_1y",
                                               "high_52w", "high_52w_date", "low_52w", "low_52w_date", "ma50",
                                               "ma200", "pct_vs_ma200", "rsi14", "atr14_pct", "vol_1y_ann_pct",
                                               "max_dd_1y_pct", "low_60d", "low_120d", "high_120d"]))
    lines.append("Weekly MAs (Kraken): " + json.dumps(crypto.get("weekly", {}), ensure_ascii=False))
    fg = crypto.get("fear_greed") or []
    if fg:
        lines.append("Fear&Greed (alternative.me) 10 ngày gần nhất: " + ", ".join(f"{x.get('value')}" for x in fg[:10]))
    lines.append("Coinbase spot: " + json.dumps(crypto.get("coinbase_spot", {})))
    cg = crypto.get("coingecko_global") or {}
    if cg:
        lines.append("BTC dominance %: " + str((cg.get("market_cap_percentage") or {}).get("btc")))
    for s in ["^GSPC", "^NDX", "DX-Y.NYB", "^TNX"]:
        if s in glob.index:
            lines.append(f"{s}: " + fmt(glob.loc[s].to_dict(), ["close", "ret_1m", "ret_ytd", "pct_vs_ma200"]))
    lines.append("TIN crypto VN: " + " || ".join(n["title"][:120] for n in (news.get("_CRYPTO_VN") or [])[:8] if n.get("title")))
    lines.append("TIN BTC: " + " || ".join(n["title"][:120] for n in (news.get("_BTC") or [])[:8] if n.get("title")))
    return "\n".join(lines)


items = []
for group, syms in CANDIDATES.items():
    for s in syms:
        items.append({"id": s, "kind": "stock", "group": group, "dossier": stock_dossier(s, group)})
items.append({"id": "ETF_FUNDS", "kind": "fund", "group": "etf_fund", "dossier": etf_fund_dossier()})
items.append({"id": "GOLD", "kind": "gold", "group": "commodity", "dossier": gold_dossier()})
items.append({"id": "BTC", "kind": "crypto", "group": "crypto", "dossier": crypto_dossier("BTC")})
items.append({"id": "ETH", "kind": "crypto", "group": "crypto", "dossier": crypto_dossier("ETH")})
json.dump(items, open(f"{SNAP}/dossiers.json", "w"), ensure_ascii=False, indent=1)
print(len(items), "dossiers;", sum(len(i["dossier"]) for i in items), "chars")
