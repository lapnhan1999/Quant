#!/usr/bin/env python3
"""Snapshot of market data for a Vietnam-based multi-asset investment review.

Runs on a GitHub Actions runner (open internet) and writes everything under
data/snapshot/. Every block is wrapped so one dead source never kills the run.

Contents:
  prices_metrics.csv   per-symbol technical metrics (VN stocks/ETFs/indices,
                       global assets, crypto) with cross-checked last close
  history/*.csv        daily OHLCV used for the metrics
  fundamentals.json    valuation / profitability ratios per VN ticker
  funds.json           open-ended fund NAV + performance (Fmarket)
  crypto.json          market data, Fear & Greed, BTC 200-week MA
  gold_fx.json         domestic gold quotes and USD/VND
  news.json            last-30-day headlines per ticker (Google News RSS)
  summary.md           human-readable digest
"""
import concurrent.futures as cf
import datetime as dt
import json
import math
import os
import time
import traceback
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import numpy as np
import pandas as pd
import requests

OUT = "data/snapshot"
HIST = f"{OUT}/history"
os.makedirs(HIST, exist_ok=True)

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})

NOW = int(time.time())
START = NOW - 6 * 365 * 86400
TODAY = dt.datetime.utcfromtimestamp(NOW).strftime("%Y-%m-%d")

INDICES = ["VNINDEX", "VN30", "HNXINDEX", "UPCOMINDEX"]
ETFS = ["E1VFVN30", "FUEVFVND", "FUESSVFL", "FUEDCMID", "FUEKIV30", "FUEVN100", "FUESSV30", "FUEMAV30"]
BANKS = ["VCB", "BID", "CTG", "TCB", "MBB", "ACB", "VPB", "HDB", "STB", "VIB", "TPB", "LPB",
         "SHB", "SSB", "MSB", "OCB", "EIB", "NAB"]
BROKERS = ["SSI", "VCI", "HCM", "VND", "VIX", "SHS", "MBS", "FTS", "BSI", "CTS"]
OTHERS = [
    "FPT", "CMG", "MWG", "DMX", "FRT", "DGW", "PNJ", "MSN", "MCH", "VNM", "SAB", "QNS", "KDC",
    "HPG", "HSG", "NKG", "GMD", "HAH", "VSC", "DGC", "DCM", "DPM", "CSV", "REE", "PC1", "POW",
    "NT2", "GEG", "GAS", "PVS", "PVD", "PLX", "BSR", "PVT", "VHM", "VIC", "VRE", "KDH", "NLG",
    "DXG", "NVL", "PDR", "KBC", "IDC", "SZC", "BCM", "VTP", "CTR", "VGI", "VJC", "HVN", "ACV",
    "BMP", "CTD", "HHV", "VCG", "C4G", "GEX", "VGC", "SIP", "VHC", "ANV", "PTB", "DHG", "IMP",
    "GVR", "PHR", "DPR", "BAF", "DBC", "HAG", "VPI", "TCM", "MSR", "NTP", "TLG", "SCS",
]
VN_SYMBOLS = INDICES + ETFS + BANKS + BROKERS + OTHERS

YAHOO = {
    "GC=F": "Gold futures (USD/oz)",
    "SI=F": "Silver futures (USD/oz)",
    "^GSPC": "S&P 500",
    "^NDX": "Nasdaq 100",
    "DX-Y.NYB": "US Dollar Index",
    "^TNX": "US 10Y yield x10",
    "BZ=F": "Brent crude",
    "^VIX": "VIX",
    "VND=X": "USD/VND",
    "VNM": "VanEck Vietnam ETF (USD)",
    "BTC-USD": "Bitcoin (Yahoo)",
    "ETH-USD": "Ether (Yahoo)",
}

KRAKEN = {"BTC": "XBTUSD", "ETH": "ETHUSD", "SOL": "SOLUSD", "XRP": "XRPUSD", "LINK": "LINKUSD"}
COINGECKO_IDS = ["bitcoin", "ethereum", "solana", "binancecoin", "ripple", "chainlink"]

ERRORS = []


def log(msg):
    print(msg, flush=True)


def err(where, e):
    msg = f"{where}: {type(e).__name__}: {str(e)[:200]}"
    ERRORS.append(msg)
    log("  ! " + msg)


def get_json(url, **kw):
    kw.setdefault("timeout", 25)
    r = SESSION.get(url, **kw)
    r.raise_for_status()
    return r.json()


def post_json(url, payload, **kw):
    kw.setdefault("timeout", 25)
    r = SESSION.post(url, json=payload, **kw)
    r.raise_for_status()
    return r.json()


# --------------------------------------------------------------------------
# VN price sources. Each returns a DataFrame indexed by date with
# open/high/low/close/volume; prices are normalised to thousand VND for
# stocks/ETFs (index points for indices).
# --------------------------------------------------------------------------

def _frame(t, o, h, l, c, v):
    df = pd.DataFrame({"open": o, "high": h, "low": l, "close": c, "volume": v})
    df.index = pd.to_datetime(pd.Series(t).astype("int64"), unit="s").dt.tz_localize("UTC").dt.tz_convert(
        "Asia/Ho_Chi_Minh").dt.date.values
    df = df[~df.index.duplicated(keep="last")].sort_index()
    return df.astype(float)


def _normalise(df, sym):
    if sym in INDICES or df.empty:
        return df
    if df["close"].median() > 1000:  # raw VND -> thousand VND
        for col in ("open", "high", "low", "close"):
            df[col] = df[col] / 1000.0
    return df


def src_vndirect(sym):
    j = get_json(f"https://dchart-api.vndirect.com.vn/dchart/history?resolution=D&symbol={sym}&from={START}&to={NOW}")
    if j.get("s") != "ok" or not j.get("t"):
        raise ValueError(f"status {j.get('s')}")
    return _frame(j["t"], j["o"], j["h"], j["l"], j["c"], j["v"])


def src_vci(sym):
    hdr = {"Referer": "https://trading.vietcap.com.vn/", "Origin": "https://trading.vietcap.com.vn"}
    j = post_json("https://trading.vietcap.com.vn/api/chart/OHLCChart/gap-chart",
                  {"timeFrame": "ONE_DAY", "symbols": [sym], "to": NOW, "countBack": 1600}, headers=hdr)
    d = j[0] if isinstance(j, list) else j
    if not d.get("t"):
        raise ValueError("empty")
    return _frame([int(x) for x in d["t"]], d["o"], d["h"], d["l"], d["c"], d["v"])


def src_dnse(sym):
    kind = "index" if sym in INDICES else "stock"
    j = get_json(f"https://services.entrade.com.vn/chart-api/v2/ohlcs/{kind}?from={START}&to={NOW}&symbol={sym}&resolution=1D")
    if not j.get("t"):
        raise ValueError("empty")
    return _frame(j["t"], j["o"], j["h"], j["l"], j["c"], j["v"])


def src_ssi(sym):
    j = get_json(f"https://iboard-api.ssi.com.vn/statistics/charts/history?resolution=1D&symbol={sym}&from={START}&to={NOW}")
    d = j.get("data", j)
    if not d.get("t"):
        raise ValueError("empty")
    return _frame(d["t"], d["o"], d["h"], d["l"], d["c"], d["v"])


def src_tcbs(sym):
    kind = "index" if sym in INDICES else "stock"
    j = get_json(f"https://apipubaws.tcbs.com.vn/stock-insight/v2/stock/bars-long-term?ticker={sym}&type={kind}"
                 f"&resolution=D&to={NOW}&countBack=1600")
    rows = j.get("data") or []
    if not rows:
        raise ValueError("empty")
    df = pd.DataFrame(rows)
    df.index = pd.to_datetime(df["tradingDate"]).dt.date.values
    df = df[["open", "high", "low", "close", "volume"]].astype(float)
    return df[~df.index.duplicated(keep="last")].sort_index()


VN_SOURCES = [("vndirect", src_vndirect), ("vci", src_vci), ("dnse", src_dnse), ("ssi", src_ssi), ("tcbs", src_tcbs)]


def fetch_vn(sym):
    """Full history from the first working source, last close from every source for cross-checking."""
    best, closes, used = None, {}, None
    for name, fn in VN_SOURCES:
        try:
            df = _normalise(fn(sym), sym)
            if df.empty:
                continue
            closes[name] = (str(df.index[-1]), round(float(df["close"].iloc[-1]), 3))
            if best is None or df.index[-1] > best.index[-1] or (df.index[-1] == best.index[-1] and len(df) > len(best)):
                best, used = df, name
            if len(closes) >= 3:
                break
        except Exception as e:  # noqa: BLE001
            closes[name] = f"ERR {type(e).__name__}: {str(e)[:80]}"
        time.sleep(0.15)
    return sym, best, used, closes


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------

def rsi(series, n=14):
    delta = series.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / dn.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def metrics(df, bench=None):
    df = df.dropna(subset=["close"])
    c, h, l = df["close"], df["high"], df["low"]
    last = float(c.iloc[-1])
    idx = pd.to_datetime(pd.Index(df.index))
    cs = pd.Series(c.values, index=idx)

    def ret_days(days):
        target = idx[-1] - pd.Timedelta(days=days)
        prior = cs[cs.index <= target]
        return round((last / float(prior.iloc[-1]) - 1) * 100, 2) if len(prior) else None

    ytd_base = cs[cs.index < pd.Timestamp(idx[-1].year, 1, 1)]
    one_year = cs[cs.index > idx[-1] - pd.Timedelta(days=365)]
    hy = pd.Series(h.values, index=idx)[idx > idx[-1] - pd.Timedelta(days=365)]
    ly = pd.Series(l.values, index=idx)[idx > idx[-1] - pd.Timedelta(days=365)]
    tr = pd.concat([h - l, (h - c.shift()).abs(), (l - c.shift()).abs()], axis=1).max(axis=1)
    atr14 = float(tr.rolling(14).mean().iloc[-1]) if len(df) > 15 else None
    logret = np.log(one_year).diff().dropna()
    ann = 365 if bench == "crypto" else 252
    vol = float(logret.std() * math.sqrt(ann) * 100) if len(logret) > 20 else None
    roll_max = one_year.cummax()
    mdd = float(((one_year / roll_max) - 1).min() * 100) if len(one_year) else None
    ma = {n: (float(c.rolling(n).mean().iloc[-1]) if len(c) >= n else None) for n in (20, 50, 100, 200)}
    value20 = None
    if "volume" in df and df["volume"].notna().any():
        value20 = float((df["close"] * df["volume"]).tail(20).mean())
    out = {
        "last_date": str(df.index[-1]),
        "close": round(last, 4),
        "chg_1d_pct": round((last / float(c.iloc[-2]) - 1) * 100, 2) if len(c) > 1 else None,
        "ret_1w": ret_days(7), "ret_1m": ret_days(30), "ret_3m": ret_days(91), "ret_6m": ret_days(182),
        "ret_1y": ret_days(365), "ret_3y": ret_days(3 * 365),
        "ret_ytd": round((last / float(ytd_base.iloc[-1]) - 1) * 100, 2) if len(ytd_base) else None,
        "high_52w": round(float(hy.max()), 4) if len(hy) else None,
        "low_52w": round(float(ly.min()), 4) if len(ly) else None,
        "high_52w_date": str(hy.idxmax().date()) if len(hy) else None,
        "low_52w_date": str(ly.idxmin().date()) if len(ly) else None,
        "all_time_high_in_data": round(float(h.max()), 4),
        "ma20": ma[20], "ma50": ma[50], "ma100": ma[100], "ma200": ma[200],
        "rsi14": round(float(rsi(c).iloc[-1]), 1) if len(c) > 20 else None,
        "atr14": atr14, "atr14_pct": round(atr14 / last * 100, 2) if atr14 else None,
        "vol_1y_ann_pct": round(vol, 1) if vol else None,
        "max_dd_1y_pct": round(mdd, 1) if mdd is not None else None,
        "low_20d": round(float(l.tail(20).min()), 4), "high_20d": round(float(h.tail(20).max()), 4),
        "low_60d": round(float(l.tail(60).min()), 4), "high_60d": round(float(h.tail(60).max()), 4),
        "low_120d": round(float(l.tail(120).min()), 4), "high_120d": round(float(h.tail(120).max()), 4),
        "avg_value_20d": value20,
        "n_bars": int(len(df)),
    }
    for k in ("ma20", "ma50", "ma100", "ma200"):
        if out[k]:
            out[f"pct_vs_{k}"] = round((last / out[k] - 1) * 100, 2)
            out[k] = round(out[k], 4)
    if out["high_52w"]:
        out["pct_from_52w_high"] = round((last / out["high_52w"] - 1) * 100, 2)
        out["pct_from_52w_low"] = round((last / out["low_52w"] - 1) * 100, 2)
    return out


def beta_vs(df, bench_df):
    try:
        a = df["close"].pct_change()
        b = bench_df["close"].pct_change()
        j = pd.concat([a, b], axis=1, join="inner").dropna().tail(250)
        if len(j) < 60:
            return None
        cov = np.cov(j.iloc[:, 0], j.iloc[:, 1])
        return round(float(cov[0, 1] / cov[1, 1]), 2)
    except Exception:  # noqa: BLE001
        return None


# --------------------------------------------------------------------------
# Fundamentals
# --------------------------------------------------------------------------

def fundamentals(sym):
    res = {}
    try:  # VNDirect latest ratios
        url = ("https://finfo-api.vndirect.com.vn/v4/ratios/latest?filter=ratioCode:MARKETCAP,PRICE_TO_EARNINGS,"
               "PRICE_TO_BOOK,DIVIDEND_YIELD,ROAE,ROAA,BETA,PRICE_TO_SALES,EPS_TR,BVPS_CR,NETPROFIT_GROWTH_YOY"
               f"&where=code:{sym}&order=reportDate&fields=ratioCode,value,reportDate")
        j = get_json(url)
        res["vndirect_ratios"] = {d["ratioCode"]: [d.get("value"), d.get("reportDate")] for d in j.get("data", [])}
    except Exception as e:  # noqa: BLE001
        res["vndirect_ratios_err"] = str(e)[:150]
    try:  # TCBS overview + quarterly ratios
        res["tcbs_overview"] = get_json(f"https://apipubaws.tcbs.com.vn/tcanalysis/v1/ticker/{sym}/overview")
    except Exception as e:  # noqa: BLE001
        res["tcbs_overview_err"] = str(e)[:150]
    try:
        j = get_json(f"https://apipubaws.tcbs.com.vn/tcanalysis/v1/finance/{sym}/financialratio?yearly=0&isAll=false")
        res["tcbs_ratio_q"] = j[:6] if isinstance(j, list) else j
    except Exception as e:  # noqa: BLE001
        res["tcbs_ratio_err"] = str(e)[:150]
    try:
        j = get_json(f"https://apipubaws.tcbs.com.vn/tcanalysis/v1/finance/{sym}/incomestatement?yearly=0&isAll=false")
        res["tcbs_income_q"] = j[:8] if isinstance(j, list) else j
    except Exception as e:  # noqa: BLE001
        res["tcbs_income_err"] = str(e)[:150]
    try:  # vnstock (VCI source) ratios, if the library is installed and still works
        from vnstock import Vnstock  # type: ignore
        st = Vnstock().stock(symbol=sym, source="VCI")
        r = st.finance.ratio(period="quarter", lang="en", dropna=True)
        r = r.head(6)
        r.columns = [" | ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in r.columns]
        res["vnstock_ratio_q"] = json.loads(r.to_json(orient="records", force_ascii=False))
    except Exception as e:  # noqa: BLE001
        res["vnstock_ratio_err"] = f"{type(e).__name__}: {str(e)[:150]}"
    return sym, res


# --------------------------------------------------------------------------
# Other asset classes
# --------------------------------------------------------------------------

def fetch_yahoo():
    out, frames = {}, {}
    try:
        import yfinance as yf  # type: ignore
        for tk, name in YAHOO.items():
            try:
                df = yf.download(tk, period="6y", interval="1d", progress=False, auto_adjust=False)
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = df.columns.get_level_values(0)
                df = df.rename(columns=str.lower)[["open", "high", "low", "close", "volume"]].dropna(subset=["close"])
                df.index = pd.to_datetime(df.index).date
                frames[tk] = df
                m = metrics(df, "crypto" if tk.endswith("-USD") else None)
                m["name"] = name
                out[tk] = m
                log(f"  yahoo {tk}: {m['close']} ({m['last_date']})")
            except Exception as e:  # noqa: BLE001
                err(f"yahoo {tk}", e)
    except Exception as e:  # noqa: BLE001
        err("yfinance import", e)
    return out, frames


def fetch_crypto():
    res = {}
    try:
        res["coingecko_markets"] = get_json(
            "https://api.coingecko.com/api/v3/coins/markets?vs_currency=usd&ids=" + ",".join(COINGECKO_IDS)
            + "&price_change_percentage=7d,30d,200d,1y")
    except Exception as e:  # noqa: BLE001
        err("coingecko markets", e)
    try:
        res["coingecko_global"] = get_json("https://api.coingecko.com/api/v3/global").get("data", {})
        for k in ("market_cap_percentage", "total_market_cap", "total_volume"):
            v = res["coingecko_global"].get(k)
            if isinstance(v, dict):
                res["coingecko_global"][k] = {kk: v[kk] for kk in ("usd", "btc", "eth") if kk in v}
    except Exception as e:  # noqa: BLE001
        err("coingecko global", e)
    try:
        res["fear_greed"] = get_json("https://api.alternative.me/fng/?limit=60").get("data", [])[:60]
    except Exception as e:  # noqa: BLE001
        err("fear&greed", e)
    frames = {}
    for sym, pair in KRAKEN.items():
        try:
            j = get_json(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=1440")
            key = [k for k in j["result"] if k != "last"][0]
            rows = j["result"][key]
            df = pd.DataFrame(rows, columns=["t", "open", "high", "low", "close", "vwap", "volume", "count"])
            df.index = pd.to_datetime(df["t"].astype(int), unit="s").dt.date.values
            df = df[["open", "high", "low", "close", "volume"]].astype(float)
            frames[sym] = df
            res.setdefault("kraken_metrics", {})[sym] = metrics(df, "crypto")
            log(f"  kraken {sym}: {df['close'].iloc[-1]}")
        except Exception as e:  # noqa: BLE001
            err(f"kraken {sym}", e)
        try:
            j = get_json(f"https://api.kraken.com/0/public/OHLC?pair={pair}&interval=10080")
            key = [k for k in j["result"] if k != "last"][0]
            w = pd.DataFrame(j["result"][key]).iloc[:, [0, 4]]
            w.columns = ["t", "close"]
            w["close"] = w["close"].astype(float)
            res.setdefault("weekly", {})[sym] = {
                "weeks": int(len(w)),
                "ma200w": round(float(w["close"].tail(200).mean()), 2) if len(w) >= 200 else None,
                "ma100w": round(float(w["close"].tail(100).mean()), 2) if len(w) >= 100 else None,
                "ma50w": round(float(w["close"].tail(50).mean()), 2) if len(w) >= 50 else None,
                "last_weekly_close": float(w["close"].iloc[-1]),
                "max_weekly_close": float(w["close"].max()),
            }
        except Exception as e:  # noqa: BLE001
            err(f"kraken weekly {sym}", e)
    try:  # Coinbase as an independent cross-check of the latest close
        cb = {}
        for sym in ("BTC", "ETH", "SOL"):
            j = get_json(f"https://api.exchange.coinbase.com/products/{sym}-USD/ticker")
            cb[sym] = j.get("price")
        res["coinbase_spot"] = cb
    except Exception as e:  # noqa: BLE001
        err("coinbase", e)
    try:
        j = get_json("https://api.coingecko.com/api/v3/coins/binancecoin/market_chart?vs_currency=usd&days=365&interval=daily")
        p = pd.DataFrame(j["prices"], columns=["t", "close"])
        p.index = pd.to_datetime(p["t"], unit="ms").dt.date.values
        df = pd.DataFrame({"open": p["close"], "high": p["close"], "low": p["close"], "close": p["close"], "volume": 0.0})
        res.setdefault("kraken_metrics", {})["BNB"] = metrics(df, "crypto")
        frames["BNB"] = df
    except Exception as e:  # noqa: BLE001
        err("coingecko bnb history", e)
    for sym, df in frames.items():
        df.to_csv(f"{HIST}/CRYPTO_{sym}.csv")
    return res


def fetch_gold_fx():
    res = {}
    attempts = {
        "sjc": lambda: SESSION.post("https://sjc.com.vn/GoldPrice/Services/PriceService.ashx",
                                    data={"method": "GetCurrentGoldPricesByBranch", "BranchId": "1"}, timeout=25).text,
        "sjc_xml": lambda: SESSION.get("https://sjc.com.vn/xml/tygiavang.xml", timeout=25).text,
        "btmc": lambda: SESSION.get("http://api.btmc.vn/api/BTMCAPI/getpricebtmc?key=3kd8ub1llcg9t45hnoh8hmn7t5kc2v",
                                    timeout=25).text,
        "pnj": lambda: SESSION.get("https://edge-api.pnj.io/ecom-frontend/v1/get-gold-price?zone=00", timeout=25).text,
        "doji": lambda: SESSION.get("http://update.giavang.doji.vn/banggia/doji_92411/92411", timeout=25).text,
        "vcb_fx_xml": lambda: SESSION.get("https://portal.vietcombank.com.vn/Usercontrols/TVPortal.TyGia/pXML.aspx",
                                          timeout=25).text,
        "vcb_fx_api": lambda: SESSION.get(f"https://www.vietcombank.com.vn/api/exchangerates?date={TODAY}",
                                          timeout=25).text,
    }
    for name, fn in attempts.items():
        try:
            txt = fn()
            res[name] = txt[:6000]
            log(f"  {name}: {len(txt)} chars")
        except Exception as e:  # noqa: BLE001
            err(name, e)
    return res


def fetch_funds():
    payload = {"types": ["NEW_FUND", "TRADING_FUND"], "issuerIds": [], "sortOrder": "DESC",
               "sortField": "navTo12Months", "page": 1, "pageSize": 100, "isIpo": False, "fundAssetTypes": [],
               "bondRemainPeriods": [], "searchField": "", "isBuyByReward": False, "thirdAppIds": []}
    try:
        j = post_json("https://api.fmarket.vn/res/products/filter", payload,
                      headers={"Origin": "https://fmarket.vn", "Referer": "https://fmarket.vn/"})
        rows = j.get("data", {}).get("rows", [])
        out = []
        for r in rows:
            nav = r.get("productNavChange") or {}
            out.append({
                "code": r.get("shortName") or r.get("code"), "name": r.get("name"),
                "asset_type": (r.get("dataFundAssetType") or {}).get("name"),
                "nav": r.get("nav"), "nav_date": r.get("lastNAVDate") or r.get("navDate"),
                "issuer": (r.get("owner") or {}).get("shortName"),
                "mgmt_fee": r.get("managementFee"), "min_buy": r.get("buyMinValue"),
                **{k: nav.get(k) for k in ("navToPrevious", "navToLastYear", "navTo1Months", "navTo3Months",
                                           "navTo6Months", "navTo12Months", "navTo24Months", "navTo36Months",
                                           "navTo60Months", "annualizedReturn36Months", "updateAt") if k in nav},
            })
        log(f"  fmarket funds: {len(out)}")
        return out
    except Exception as e:  # noqa: BLE001
        err("fmarket", e)
        return []


def fetch_news(query, days=30, limit=12):
    url = f"https://news.google.com/rss/search?q={quote_plus(query + f' when:{days}d')}&hl=vi&gl=VN&ceid=VN:vi"
    r = SESSION.get(url, timeout=20)
    r.raise_for_status()
    root = ET.fromstring(r.content)
    items = []
    for it in root.iter("item"):
        items.append({"title": it.findtext("title"), "date": it.findtext("pubDate"),
                      "source": it.findtext("source")})
        if len(items) >= limit:
            break
    return items


# --------------------------------------------------------------------------

def main():
    t0 = time.time()
    log(f"Snapshot run at {dt.datetime.utcnow().isoformat()}Z")

    # VN prices
    log("== VN prices")
    frames, rows, xcheck = {}, [], {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for sym, df, used, closes in ex.map(fetch_vn, VN_SYMBOLS):
            xcheck[sym] = closes
            if df is None:
                log(f"  {sym}: NO DATA {closes}")
                continue
            frames[sym] = df
            df.to_csv(f"{HIST}/{sym}.csv")
            log(f"  {sym}: {df['close'].iloc[-1]} @ {df.index[-1]} via {used} | {closes}")
    bench = frames.get("VNINDEX")
    for sym, df in frames.items():
        try:
            m = metrics(df)
            m.update({"symbol": sym, "source": next((k for k, v in xcheck[sym].items() if isinstance(v, tuple)), None)})
            group = ("index" if sym in INDICES else "etf" if sym in ETFS else "bank" if sym in BANKS
                     else "broker" if sym in BROKERS else "stock")
            m["group"] = group
            m["beta_vs_vnindex"] = beta_vs(df, bench) if bench is not None and sym != "VNINDEX" else None
            vals = [v[1] for v in xcheck[sym].values() if isinstance(v, tuple) and v[0] == m["last_date"]]
            m["xcheck_sources"] = len(vals)
            m["xcheck_max_diff_pct"] = (round((max(vals) / min(vals) - 1) * 100, 3) if len(vals) > 1 and min(vals) else None)
            rows.append(m)
        except Exception as e:  # noqa: BLE001
            err(f"metrics {sym}", e)

    # Global / crypto
    log("== Yahoo")
    yahoo, yframes = fetch_yahoo()
    for tk, m in yahoo.items():
        rows.append({**m, "symbol": tk, "group": "global", "source": "yahoo"})
        yframes[tk].to_csv(f"{HIST}/Y_{tk.replace('^', '').replace('=', '_')}.csv")
    log("== Crypto")
    crypto = fetch_crypto()
    for sym, m in (crypto.get("kraken_metrics") or {}).items():
        rows.append({**m, "symbol": f"{sym}-USD", "group": "crypto", "source": "kraken" if sym != "BNB" else "coingecko"})

    pd.DataFrame(rows).to_csv(f"{OUT}/prices_metrics.csv", index=False)
    with open(f"{OUT}/price_crosscheck.json", "w") as f:
        json.dump(xcheck, f, ensure_ascii=False, indent=1, default=str)
    with open(f"{OUT}/crypto.json", "w") as f:
        json.dump(crypto, f, ensure_ascii=False, indent=1, default=str)

    log("== Gold / FX")
    with open(f"{OUT}/gold_fx.json", "w") as f:
        json.dump(fetch_gold_fx(), f, ensure_ascii=False, indent=1)

    log("== Funds")
    with open(f"{OUT}/funds.json", "w") as f:
        json.dump(fetch_funds(), f, ensure_ascii=False, indent=1)

    log("== Fundamentals")
    fund = {}
    stocks = BANKS + BROKERS + OTHERS
    with cf.ThreadPoolExecutor(max_workers=4) as ex:
        for sym, res in ex.map(fundamentals, stocks):
            fund[sym] = res
    ok = {k: [kk for kk in v if not kk.endswith("_err")] for k, v in fund.items()}
    log(f"  fundamentals sources per ticker (sample): {dict(list(ok.items())[:5])}")
    with open(f"{OUT}/fundamentals.json", "w") as f:
        json.dump(fund, f, ensure_ascii=False, indent=1, default=str)

    log("== News")
    news = {}
    topics = {s: f'"{s}" cổ phiếu' for s in stocks}
    topics.update({
        "_VNINDEX": "VN-Index nhận định", "_KHOINGOAI": "khối ngoại bán ròng", "_LAISUAT": "lãi suất huy động",
        "_GOLD_VN": "giá vàng SJC", "_BTC": "Bitcoin giá", "_FTSE": "FTSE nâng hạng Việt Nam",
        "_TYGIA": "tỷ giá USD VND", "_CRYPTO_VN": "sàn tài sản mã hóa cấp phép",
    })

    def _news(item):
        k, q = item
        try:
            return k, fetch_news(q)
        except Exception as e:  # noqa: BLE001
            return k, [{"error": str(e)[:120]}]

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for k, items in ex.map(_news, topics.items()):
            news[k] = items
    with open(f"{OUT}/news.json", "w") as f:
        json.dump(news, f, ensure_ascii=False, indent=1)

    # Summary
    df = pd.DataFrame(rows)
    cols = ["symbol", "group", "last_date", "close", "chg_1d_pct", "ret_1m", "ret_3m", "ret_ytd", "ret_1y",
            "high_52w", "low_52w", "pct_from_52w_high", "ma50", "ma200", "pct_vs_ma200", "rsi14", "atr14_pct",
            "vol_1y_ann_pct", "max_dd_1y_pct", "beta_vs_vnindex", "xcheck_sources", "xcheck_max_diff_pct"]
    cols = [c for c in cols if c in df.columns]
    with open(f"{OUT}/summary.md", "w") as f:
        f.write(f"# Market snapshot {TODAY}\n\nGenerated {dt.datetime.utcnow().isoformat()}Z in {time.time() - t0:.0f}s\n\n")
        for g in ("index", "etf", "bank", "broker", "stock", "global", "crypto"):
            sub = df[df["group"] == g][cols] if "group" in df else pd.DataFrame()
            if len(sub):
                f.write(f"## {g}\n\n{sub.to_markdown(index=False)}\n\n")
        f.write("## Errors\n\n" + "\n".join(f"- {e}" for e in ERRORS[:300]) + "\n")
    log(f"Done in {time.time() - t0:.0f}s; {len(rows)} rows; {len(ERRORS)} errors")
    if len(df):
        print(df[cols].to_string(max_rows=400, max_cols=40))


if __name__ == "__main__":
    try:
        main()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
        raise
