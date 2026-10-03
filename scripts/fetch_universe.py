#!/usr/bin/env python3
"""Whole-market data pull for the "asymmetric / event-driven opportunity" screen.

Runs on GitHub Actions (open internet). Writes to data/opportunity/:
  universe.csv            every listed stock with price/liquidity metrics (HOSE, HNX, UPCOM)
  fundamentals_liquid.json  ratios, quarterly P&L, balance sheet, ratings for the liquid subset
  catalyst_news.json      60-day headlines for catalyst / special-situation keywords
  crypto_universe.json    top-500 coins (CoinGecko) + categories + global
  commodities.csv         10-year context for commodities and thematic ETFs
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import time
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import requests

OUT = "data/opportunity"
os.makedirs(OUT, exist_ok=True)
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
IQ_HDR = {"Referer": "https://iq.vietcap.com.vn/", "Origin": "https://iq.vietcap.com.vn"}
VCI_HDR = {"Referer": "https://trading.vietcap.com.vn/", "Origin": "https://trading.vietcap.com.vn"}
NOW = int(time.time())
START = NOW - 3 * 365 * 86400
LOG = []


def log(m):
    print(m, flush=True)
    LOG.append(str(m))


def jget(url, **kw):
    kw.setdefault("timeout", 25)
    r = S.get(url, **kw)
    r.raise_for_status()
    return r.json()


# ---------------------------------------------------------------- universe
def universe():
    syms = {}
    tries = [
        "https://api-finfo.vndirect.com.vn/v4/stocks?q=type:STOCK~status:LISTED&fields=code,companyName,floor,listedDate,industryName&size=3000",
        "https://api-finfo.vndirect.com.vn/v4/stocks?q=type:STOCK&size=3000",
    ]
    for u in tries:
        try:
            for d in jget(u).get("data", []):
                c = d.get("code")
                if c and len(c) == 3 and (d.get("status") in (None, "LISTED")):
                    syms[c] = {"floor": d.get("floor"), "name": d.get("companyName"), "industry": d.get("industryName")}
            if len(syms) > 500:
                log(f"universe from vndirect: {len(syms)}")
                break
        except Exception as e:  # noqa: BLE001
            log(f"universe vndirect fail {e}")
    if len(syms) < 500:
        try:
            for d in jget("https://trading.vietcap.com.vn/api/price/symbols/getAll", headers=VCI_HDR):
                c = d.get("symbol")
                if c and len(c) == 3 and d.get("type") in (None, "STOCK"):
                    syms.setdefault(c, {"floor": d.get("board"), "name": d.get("organName")})
            log(f"universe after vietcap: {len(syms)}")
        except Exception as e:  # noqa: BLE001
            log(f"universe vietcap fail {e}")
    return syms


# ---------------------------------------------------------------- prices
def history(sym):
    try:
        j = jget(f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={sym}&from={START}&to={NOW}")
        if j.get("s") != "ok" or not j.get("t"):
            return sym, None
        df = pd.DataFrame({"t": j["t"], "o": j["o"], "h": j["h"], "l": j["l"], "c": j["c"], "v": j["v"]})
        df["d"] = pd.to_datetime(df["t"], unit="s")
        return sym, df
    except Exception:  # noqa: BLE001
        return sym, None


def pmetrics(df):
    c = df["c"].astype(float)
    h, lo, v = df["h"].astype(float), df["l"].astype(float), df["v"].astype(float)
    last = float(c.iloc[-1])
    d = df["d"]

    def back(days):
        p = c[d <= d.iloc[-1] - pd.Timedelta(days=days)]
        return round((last / float(p.iloc[-1]) - 1) * 100, 1) if len(p) else None

    y1 = d > d.iloc[-1] - pd.Timedelta(days=365)
    val20 = float((c * v).tail(20).mean()) * 1000 / 1e9  # price in thousand VND -> bn VND
    return {
        "last_date": str(d.iloc[-1].date()), "close": last, "adv20_bn": round(val20, 2),
        "adv60_bn": round(float((c * v).tail(60).mean()) * 1000 / 1e9, 2),
        "ret_1m": back(30), "ret_3m": back(91), "ret_6m": back(182), "ret_1y": back(365), "ret_2y": back(730),
        "hi52": round(float(h[y1].max()), 3), "lo52": round(float(lo[y1].min()), 3),
        "from_hi52": round((last / float(h[y1].max()) - 1) * 100, 1),
        "from_lo52": round((last / float(lo[y1].min()) - 1) * 100, 1),
        "ma50_gap": round((last / float(c.tail(50).mean()) - 1) * 100, 1) if len(c) >= 50 else None,
        "ma200_gap": round((last / float(c.tail(200).mean()) - 1) * 100, 1) if len(c) >= 200 else None,
        "vol_1y": round(float(np.log(c[y1]).diff().std() * math.sqrt(252) * 100), 1) if y1.sum() > 30 else None,
        "vol_ratio_20_120": round(float(v.tail(20).mean() / max(v.tail(120).mean(), 1)), 2),
        "n_bars": int(len(df)),
    }


# ---------------------------------------------------------------- fundamentals (liquid subset)
def fundamentals(sym):
    out = {}
    try:
        j = jget("https://api-finfo.vndirect.com.vn/v4/ratios/latest?filter=ratioCode:MARKETCAP,PRICE_TO_EARNINGS,"
                 f"PRICE_TO_BOOK,DIVIDEND_YIELD,ROAE&where=code:{sym}&order=reportDate&fields=ratioCode,value")
        out["ratios"] = {d["ratioCode"]: d["value"] for d in j.get("data", [])}
    except Exception as e:  # noqa: BLE001
        out["ratios_err"] = str(e)[:80]
    for sec in ("INCOME_STATEMENT", "BALANCE_SHEET"):
        try:
            j = jget(f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}/financial-statement?section={sec}",
                     headers=IQ_HDR)
            q = (j.get("data") or {}).get("quarters") or []
            q = [x for x in q if 1 <= (x.get("lengthReport") or 0) <= 4]
            q.sort(key=lambda r: (r.get("yearReport") or 0, r.get("lengthReport") or 0))
            keep = q[-9:] if sec == "INCOME_STATEMENT" else q[-2:]
            fields = (["yearReport", "lengthReport", "isa1", "isa3", "isa5", "isa11", "isa16", "isa20", "isa22",
                       "isb27", "isb38", "isb41", "isa102", "isa6"] if sec == "INCOME_STATEMENT" else
                      ["yearReport", "lengthReport", "bsa2", "bsa5", "bsb108", "bsa15", "bsa53", "bsa54", "bsa56",
                       "bsa71", "bsa78", "bsa80", "bsa90", "bsa210", "bsa58", "bsa170"])
            out[sec] = [{k: x.get(k) for k in fields} for x in keep]
        except Exception as e:  # noqa: BLE001
            out[f"{sec}_err"] = str(e)[:80]
    try:
        d = (jget(f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}", headers=IQ_HDR).get("data") or {})
        out["overview"] = {k: d.get(k) for k in ("rating", "ratingAsOf", "targetPrice", "upsideToTargetPercent",
                                                  "foreignerPercentage", "maximumForeignPercentage", "statePercentage",
                                                  "sector", "sectorVn", "issueShare", "marketCap",
                                                  "averageMatchValue1Month", "enOrganShortName", "viOrganShortName")}
    except Exception as e:  # noqa: BLE001
        out["overview_err"] = str(e)[:80]
    try:
        rc = jget(f"https://api-finfo.vndirect.com.vn/v4/recommendations?q=code:{sym}&sort=reportDate:DESC&size=10").get("data", [])
        out["recs"] = [x for x in rc if (x.get("reportDate") or "") >= "2026-01-01"]
    except Exception as e:  # noqa: BLE001
        out["recs_err"] = str(e)[:80]
    try:
        ev = jget(f"https://api-finfo.vndirect.com.vn/v4/events?q=code:{sym}~locale:VN&sort=disclosureDate:desc&size=12").get("data", [])
        out["events"] = [{k: x.get(k) for k in ("type", "typeDesc", "note", "disclosureDate", "effectiveDate", "ratio",
                                                 "dividend", "numberOfShares")}
                         for x in ev if x.get("type") not in ("LISTED", "updateListed")
                         and (x.get("disclosureDate") or "") >= "2026-04-01"]
    except Exception as e:  # noqa: BLE001
        out["events_err"] = str(e)[:80]
    return sym, out


# ---------------------------------------------------------------- news
def rss(query, days=60, limit=20):
    url = f"https://news.google.com/rss/search?q={quote_plus(query + f' when:{days}d')}&hl=vi&gl=VN&ceid=VN:vi"
    try:
        root = ET.fromstring(S.get(url, timeout=20).content)
        items = []
        for it in root.iter("item"):
            items.append({"title": it.findtext("title"), "date": it.findtext("pubDate"), "link": it.findtext("link")})
            if len(items) >= limit:
                break
        return items
    except Exception as e:  # noqa: BLE001
        return [{"error": str(e)[:100]}]


CATALYST_QUERIES = [
    "chào mua công khai cổ phiếu", "thoái vốn nhà nước 2026", "SCIC thoái vốn", "đấu giá cổ phần 2026",
    "niêm yết HOSE chào sàn tháng 10", "IPO 2026 cổ phiếu", "chuyển toàn bộ cổ phiếu HNX sang HOSE",
    "MSCI nâng hạng Việt Nam 2027", "FTSE bổ sung cổ phiếu Việt Nam", "ETF cơ cấu danh mục quý 4 2026",
    "VN30 dự báo thay đổi rổ", "cổ tức đặc biệt 2026", "mua cổ phiếu quỹ 2026", "lãnh đạo đăng ký mua cổ phiếu",
    "cổ đông lớn đăng ký mua", "sáp nhập M&A doanh nghiệp 2026", "dự báo lợi nhuận quý 3 2026 tăng mạnh",
    "lợi nhuận quý 3 2026 đột biến", "gỡ vướng pháp lý dự án bất động sản 2026", "sân bay Long Thành khai thác",
    "đường sắt tốc độ cao Bắc Nam", "đầu tư công giải ngân 2026", "Nghị quyết 68 kinh tế tư nhân",
    "sàn tài sản mã hóa được cấp phép", "giá cà phê", "giá thép xây dựng", "giá phân bón urê", "giá cao su",
    "giá gạo xuất khẩu", "giá bạc", "giá heo hơi", "giá dầu Brent", "hoàn nhập dự phòng", "tái cơ cấu nợ trái phiếu",
    "trung tâm tài chính quốc tế Việt Nam", "khu thương mại tự do", "điện hạt nhân Ninh Thuận", "LNG điện khí",
    "data center Việt Nam", "bán dẫn Việt Nam", "cổ phiếu cơ bản tốt bị bỏ quên", "doanh nghiệp tiền mặt ròng lớn",
    "phát hành quyền mua giá thấp", "cổ phiếu tăng trần nhiều phiên", "phím hàng chứng khoán xử phạt",
    "thao túng giá cổ phiếu 2026", "sử dụng thông tin nội bộ xử phạt", "lừa đảo đầu tư tài chính 2026",
    "dự án lừa đảo tiền số 2026", "kinh tế Việt Nam quý 3 2026", "lãi suất cho vay giảm", "Fed hạ lãi suất",
]


# ---------------------------------------------------------------- crypto / commodities
def crypto():
    res = {}
    coins = []
    for page in (1, 2):
        try:
            coins += jget("https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&order=market_cap_desc"
                          f"&per_page=250&page={page}&price_change_percentage=7d,30d,1y")
            time.sleep(3)
        except Exception as e:  # noqa: BLE001
            log(f"coingecko page {page} fail {e}")
    res["markets"] = [{k: c.get(k) for k in ("id", "symbol", "name", "current_price", "market_cap", "market_cap_rank",
                                             "fully_diluted_valuation", "total_volume", "circulating_supply",
                                             "total_supply", "max_supply", "ath", "ath_change_percentage", "ath_date",
                                             "atl", "price_change_percentage_30d_in_currency",
                                             "price_change_percentage_1y_in_currency")} for c in coins]
    for name, url in (("categories", "https://api.coingecko.com/api/v3/coins/categories"),
                      ("global", "https://api.coingecko.com/api/v3/global"),
                      ("trending", "https://api.coingecko.com/api/v3/search/trending")):
        try:
            res[name] = jget(url)
            time.sleep(3)
        except Exception as e:  # noqa: BLE001
            log(f"coingecko {name} fail {e}")
    if isinstance(res.get("categories"), list):
        res["categories"] = [{k: c.get(k) for k in ("name", "market_cap", "market_cap_change_24h", "volume_24h")}
                             for c in res["categories"][:150]]
    return res


COMMOD = {"SI=F": "Silver", "GC=F": "Gold", "HG=F": "Copper", "PL=F": "Platinum", "PA=F": "Palladium",
          "CL=F": "WTI", "BZ=F": "Brent", "NG=F": "NatGas", "KC=F": "Coffee Arabica", "SB=F": "Sugar",
          "CT=F": "Cotton", "ZW=F": "Wheat", "ZR=F": "Rough Rice", "ZC=F": "Corn", "URA": "Uranium ETF",
          "GDX": "Gold miners ETF", "SIL": "Silver miners ETF", "COPX": "Copper miners ETF",
          "VNM": "VanEck Vietnam ETF", "^GSPC": "S&P500", "BTC-USD": "Bitcoin", "ETH-USD": "Ether",
          "SOL-USD": "Solana", "TLT": "US 20Y Treasury ETF", "DX-Y.NYB": "DXY"}


def commodities():
    rows = []
    try:
        import yfinance as yf  # type: ignore
        for tk, name in COMMOD.items():
            try:
                df = yf.download(tk, period="10y", interval="1wk", progress=False, auto_adjust=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                c = df["Close"].dropna()
                last = float(c.iloc[-1])
                rows.append({"ticker": tk, "name": name, "last": round(last, 4),
                             "ret_1y": round((last / float(c.iloc[-53]) - 1) * 100, 1) if len(c) > 53 else None,
                             "ret_3y": round((last / float(c.iloc[-157]) - 1) * 100, 1) if len(c) > 157 else None,
                             "max_10y": round(float(c.max()), 4), "min_10y": round(float(c.min()), 4),
                             "pctile_10y": round(float((c < last).mean() * 100), 1),
                             "from_max_10y": round((last / float(c.max()) - 1) * 100, 1),
                             "ma200w_gap": round((last / float(c.tail(200).mean()) - 1) * 100, 1) if len(c) >= 200 else None})
            except Exception as e:  # noqa: BLE001
                log(f"yf {tk} fail {e}")
    except Exception as e:  # noqa: BLE001
        log(f"yfinance import fail {e}")
    return pd.DataFrame(rows)


# ---------------------------------------------------------------- main
def main():
    t0 = time.time()
    syms = universe()
    rows = []
    with cf.ThreadPoolExecutor(max_workers=10) as ex:
        for sym, df in ex.map(history, sorted(syms)):
            if df is None or len(df) < 30:
                continue
            try:
                m = pmetrics(df)
                m.update({"symbol": sym, **{k: syms[sym].get(k) for k in ("floor", "name", "industry")}})
                rows.append(m)
            except Exception as e:  # noqa: BLE001
                log(f"metrics {sym} fail {e}")
    uni = pd.DataFrame(rows)
    uni.to_csv(f"{OUT}/universe.csv", index=False)
    log(f"prices: {len(uni)} symbols in {time.time() - t0:.0f}s")

    liquid = uni[(uni["adv20_bn"] >= 0.5) | (uni["adv60_bn"] >= 0.8)]["symbol"].tolist()
    log(f"liquid subset: {len(liquid)}")
    fund = {}
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        for sym, res in ex.map(fundamentals, liquid):
            fund[sym] = res
    json.dump(fund, open(f"{OUT}/fundamentals_liquid.json", "w"), ensure_ascii=False, default=str)
    log(f"fundamentals done in {time.time() - t0:.0f}s")

    news = {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for q, items in zip(CATALYST_QUERIES, ex.map(rss, CATALYST_QUERIES)):
            news[q] = items
    json.dump(news, open(f"{OUT}/catalyst_news.json", "w"), ensure_ascii=False, indent=1)

    json.dump(crypto(), open(f"{OUT}/crypto_universe.json", "w"), ensure_ascii=False, default=str)
    commodities().to_csv(f"{OUT}/commodities.csv", index=False)
    open(f"{OUT}/run_log.txt", "w").write("\n".join(LOG))
    log(f"done in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
