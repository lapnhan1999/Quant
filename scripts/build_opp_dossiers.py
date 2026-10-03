#!/usr/bin/env python3
"""Fact sheets for the opportunity deep-dive (scout evidence + whole-market screen + snapshot)."""
import json
import os

import pandas as pd

D = "data/opportunity"
S = "data/snapshot"
scouts = json.load(open(f"{D}/scouts.json"))
scr = pd.read_csv(f"{D}/screen_liquid.csv").set_index("symbol")
uni = pd.read_csv(f"{D}/universe.csv").set_index("symbol")
px = pd.read_csv(f"{S}/prices_metrics.csv")
px = px[~px["group"].isin(["global", "crypto"])].set_index("symbol")
cr = pd.read_csv(f"{S}/prices_metrics.csv")
cr = cr[cr["group"] == "crypto"].set_index("symbol")
news = json.load(open(f"{S}/news.json"))
cnews = json.load(open(f"{D}/catalyst_news.json"))
bt = pd.read_csv(f"{S}/backtest_holding_winrates.csv").set_index("sym")
cu = json.load(open(f"{D}/crypto_universe.json"))
cmk = pd.DataFrame(cu.get("markets", [])).set_index("symbol")

CANDS = {
    # id: (kind, tickers, keywords for scout matching, news keys)
    "DEPOSIT_LOCK": ("fixed", [], ["lãi suất", "tiền gửi", "Khóa đỉnh"], ["lãi suất huy động", "lãi suất cho vay giảm"]),
    "MSN": ("stock", ["MSN"], ["MSN"], []),
    "VPB": ("stock", ["VPB"], ["VPB"], []),
    "ACV": ("stock", ["ACV"], ["ACV", "Long Thành"], ["sân bay Long Thành khai thác"]),
    "HPG": ("stock", ["HPG"], ["HPG"], ["giá thép xây dựng"]),
    "PHR": ("stock", ["PHR"], ["PHR"], ["giá cao su"]),
    "FTSE_FRONTRUN": ("stock", ["MCH", "VJC", "VIC"], ["FTSE đợt", "Đón trước dòng tiền FTSE"], ["FTSE bổ sung cổ phiếu Việt Nam", "ETF cơ cấu danh mục quý 4 2026"]),
    "PVS": ("stock", ["PVS", "IDC"], ["PVS", "IDC"], ["chuyển toàn bộ cổ phiếu HNX sang HOSE"]),
    "NTP": ("stock", ["NTP"], ["NTP", "SCIC"], ["SCIC thoái vốn", "thoái vốn nhà nước 2026"]),
    "VEA_QTP_VTO": ("stock", ["VEA", "QTP", "VTO"], ["VEA", "QTP", "VTO"], ["thoái vốn nhà nước 2026"]),
    "BROKERS": ("stock", ["SSI", "VCI", "MBS"], ["Công ty chứng khoán", "chứng khoán bị bán tháo", "SSI", "MBS"], ["MSCI nâng hạng Việt Nam 2027"]),
    "VIX": ("stock", ["VIX"], ["VIX"], ["sàn tài sản mã hóa được cấp phép"]),
    "RE_TURNAROUND": ("stock", ["KDH", "NLG", "DXG"], ["KDH", "NLG", "BĐS dân cư"], ["gỡ vướng pháp lý dự án bất động sản 2026"]),
    "INFRA_CONTRACTORS": ("stock", ["HHV", "VCG", "C4G"], ["HHV", "VCG", "nhà thầu hạ tầng"], ["đường sắt tốc độ cao Bắc Nam", "đầu tư công giải ngân 2026"]),
    "NVL_RIGHTS": ("stock", ["NVL"], ["NVL"], ["tái cơ cấu nợ trái phiếu"]),
    "AGRI_DBC_HAG": ("stock", ["DBC", "HAG"], ["DBC", "HAG"], ["giá heo hơi"]),
    "PNJ_TURNAROUND": ("stock", ["PNJ"], ["PNJ"], []),
    "OIL_SHIPPING": ("stock", ["PVT", "PVP", "VOS"], ["PVT", "PVP", "VOS", "dầu"], ["giá dầu Brent"]),
    "BTC": ("crypto", ["BTC"], ["BTC"], ["sàn tài sản mã hóa được cấp phép"]),
    "ETH": ("crypto", ["ETH"], ["ETH"], []),
    "SOL": ("crypto", ["SOL"], ["SOL"], []),
    "ALT_BASKET_LINK_HYPE": ("crypto", ["LINK", "HYPE"], ["LINK", "HYPE"], []),
    "SILVER": ("commodity", [], ["Bạc", "bạc"], ["giá bạc"]),
    "SKILLS_BUSINESS": ("other", [], ["kỹ năng", "kinh doanh nhỏ"], []),
}

SCR_COLS = ["floor", "close", "adv20_bn", "mcap_bn", "pe", "pb", "dy", "pbt_q_yoy", "pbt_6m_yoy", "pbt_ttm_yoy",
            "np_ttm_bn", "fin_inc_share_6m", "net_cash_bn", "net_cash_to_mcap", "debt_to_equity", "ret_1m", "ret_3m",
            "ret_6m", "ret_1y", "ret_2y", "hi52", "lo52", "from_hi52", "from_lo52", "ma50_gap", "ma200_gap", "vol_1y",
            "vci_rating", "vci_tp", "up_vci_tp", "recs_tp_median", "state_pct", "foreign_pct", "foreign_max", "sector",
            "events"]
PX_COLS = ["ma20", "ma50", "ma100", "ma200", "rsi14", "atr14", "atr14_pct", "low_20d", "low_60d", "low_120d",
           "high_60d", "high_120d", "beta_vs_vnindex"]


def fmt(d, keys):
    out = []
    for k in keys:
        v = d.get(k)
        if v is None or (isinstance(v, float) and pd.isna(v)) or v == "":
            continue
        out.append(f"{k}={round(v, 3) if isinstance(v, float) else v}")
    return ", ".join(out)


def scout_matches(keys, tickers):
    out = []
    for t in scouts:
        for o in t["opportunities"]:
            blob = o["name"] + " " + " ".join(o["instruments"])
            if any(k in blob for k in keys) or any(tk in o["instruments"][0][:12] for tk in tickers if tickers):
                out.append(f"### [scout: {t['theme'][:60]}] {o['name']}\n- Công cụ: {', '.join(o['instruments'])}\n"
                           f"- Chất xúc tác: {o['catalyst']}\n- Thời điểm: {o['catalyst_date']}\n"
                           f"- Vì sao bị định giá thấp: {o['why_underpriced']}\n- Kịch bản tốt: {o['upside_case']}\n"
                           f"- Kịch bản xấu: {o['downside_case']}\n- Xác suất: {o['probability_note']}\n"
                           f"- Pháp lý: {o['legality']} | tự tin scout {o['confidence_1_10']}/10\n- Bằng chứng: "
                           + " || ".join(o["evidence"][:8]))
    return out


for cid, (kind, tickers, keys, nkeys) in CANDS.items():
    L = [f"# {cid} ({kind}) — dữ liệu đến 02/10/2026 (giá cổ phiếu: nghìn đồng)"]
    for tk in tickers:
        if kind == "stock":
            if tk in scr.index:
                L.append(f"## {tk} — sàng lọc toàn thị trường: " + fmt(scr.loc[tk].to_dict(), SCR_COLS))
            elif tk in uni.index:
                L.append(f"## {tk} — giá: " + fmt(uni.loc[tk].to_dict(), list(uni.columns)))
            if tk in px.index:
                L.append(f"   kỹ thuật (snapshot 3 nguồn): " + fmt(px.loc[tk].to_dict(), PX_COLS))
            if tk in bt.index:
                L.append(f"   backtest 5 năm: " + fmt(bt.loc[tk].to_dict(), ["p_win6", "p_beat_dep6", "med6", "p10_6",
                                                                          "p_win12", "p_beat_dep12", "med12",
                                                                          "p_win6_dd", "med6_dd"]))
            nw = [n for n in (news.get(tk) or []) if n.get("title")][:8]
            if nw:
                L.append("   tin 30 ngày: " + " || ".join(f"{(n.get('date') or '')[5:16]} {n['title'][:120]}" for n in nw))
        elif kind == "crypto":
            sym = f"{tk}-USD"
            if sym in cr.index:
                L.append(f"## {tk} — " + fmt(cr.loc[sym].to_dict(), ["close", "ret_1m", "ret_3m", "ret_ytd", "ret_1y",
                                                                     "high_52w", "low_52w", "ma50", "ma200",
                                                                     "pct_vs_ma200", "rsi14", "atr14_pct",
                                                                     "vol_1y_ann_pct", "max_dd_1y_pct", "low_60d",
                                                                     "low_120d", "high_120d"]))
            low = tk.lower()
            if low in cmk.index:
                m = cmk.loc[low]
                if isinstance(m, pd.DataFrame):
                    m = m.iloc[0]
                L.append(f"   coingecko: " + fmt(m.to_dict(), ["current_price", "market_cap", "market_cap_rank",
                                                              "fully_diluted_valuation", "circulating_supply",
                                                              "total_supply", "ath", "ath_change_percentage",
                                                              "ath_date", "price_change_percentage_30d_in_currency",
                                                              "price_change_percentage_1y_in_currency"]))
    if kind == "commodity":
        L.append(open(f"{D}/commodities.csv").read())
    L.append("\n## Bằng chứng từ vòng trinh sát web (7 agent, 03/10/2026)")
    L += scout_matches(keys, tickers) or ["(không có mục khớp)"]
    for nk in nkeys:
        items = [n for n in (cnews.get(nk) or []) if n.get("title")][:10]
        if items:
            L.append(f"\n## Tin 60 ngày '{nk}': " + " || ".join(f"{(n.get('date') or '')[5:16]} {n['title'][:110]}" for n in items))
    open(f"{D}/dossiers/{cid}.md", "w").write("\n".join(L))
print(len(CANDS), "dossiers written")
