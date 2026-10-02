#!/usr/bin/env python3
"""Second-pass fundamentals fetch (valuation, growth, ownership).

The first snapshot showed the legacy TCBS/VNDirect ratio endpoints are gone,
so this probes several current public endpoints with FPT, keeps a raw sample
of every response, and then runs each endpoint that worked across the whole
watchlist. Output: data/snapshot/fundamentals2.json and fundamentals_probe.json.
"""
import concurrent.futures as cf
import json
import subprocess
import sys
import time

import requests

sys.path.insert(0, "scripts")
from fetch_market_data import BANKS, BROKERS, OTHERS, ETFS  # noqa: E402

OUT = "data/snapshot"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
VCI_HDR = {"Referer": "https://trading.vietcap.com.vn/", "Origin": "https://trading.vietcap.com.vn"}
IQ_HDR = {"Referer": "https://iq.vietcap.com.vn/", "Origin": "https://iq.vietcap.com.vn"}
TICKERS = BANKS + BROKERS + OTHERS

GQL_RATIO = """query Query($ticker: String!, $period: String!) {
  CompanyFinancialRatio(ticker: $ticker, period: $period) {
    ratio { ticker yearReport lengthReport updateDate revenue revenueGrowth netProfit netProfitGrowth
      ebitMargin roe roic roa pe pb eps currentRatio cashRatio quickRatio interestCoverage ae
      netProfitMargin grossMargin ev issueShare ps pcf bvps evPerEbitda de le ebitda ebit dividend
      RTQ10 charterCapitalRatio RTQ4 epsTTM charterCapital RTQ17 CIRRatio __typename }
    period __typename } }"""

GQL_OVERVIEW = """query Query($ticker: String!, $lang: String!) {
  TickerPriceInfo(ticker: $ticker) { financialRatio { pe pb roe roa eps bvps dividend revenue netProfit
      revenueGrowth netProfitGrowth yearReport lengthReport __typename }
    ticker exchange matchPrice priceChange percentPriceChange totalVolume highestPrice1Year
    lowestPrice1Year foreignTotalRoom foreignHoldingRoom currentHoldingRatio maxHoldingRatio __typename }
  CompanyListingInfo(ticker: $ticker) { icbName2 icbName3 issueShare companyProfile __typename } }"""


def call(name, fn):
    t = time.time()
    try:
        r = fn()
        txt = r.text
        return {"name": name, "status": r.status_code, "ms": int((time.time() - t) * 1000), "body": txt[:4000]}
    except Exception as e:  # noqa: BLE001
        return {"name": name, "error": f"{type(e).__name__}: {str(e)[:200]}"}


def endpoints(sym):
    return {
        "vci_gql_ratio_Q": lambda: S.post("https://trading.vietcap.com.vn/data-mt/graphql", headers=VCI_HDR, timeout=25,
                                          json={"query": GQL_RATIO, "variables": {"ticker": sym, "period": "Q"}}),
        "vci_gql_ratio_Y": lambda: S.post("https://trading.vietcap.com.vn/data-mt/graphql", headers=VCI_HDR, timeout=25,
                                          json={"query": GQL_RATIO, "variables": {"ticker": sym, "period": "Y"}}),
        "vci_gql_overview": lambda: S.post("https://trading.vietcap.com.vn/data-mt/graphql", headers=VCI_HDR, timeout=25,
                                           json={"query": GQL_OVERVIEW, "variables": {"ticker": sym, "lang": "vi"}}),
        "iq_stats_fin": lambda: S.get(
            f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}/statistics-financial",
            headers=IQ_HDR, timeout=25),
        "iq_overview": lambda: S.get(f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}",
                                     headers=IQ_HDR, timeout=25),
        "iq_fin_ratio": lambda: S.get(
            f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}/financial-statement/metrics",
            headers=IQ_HDR, timeout=25),
        "iq_analysis": lambda: S.get(
            f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}/analysis-reports?page=0&size=10",
            headers=IQ_HDR, timeout=25),
        "vndirect_new": lambda: S.get(
            "https://api-finfo.vndirect.com.vn/v4/ratios/latest?filter=ratioCode:MARKETCAP,PRICE_TO_EARNINGS,"
            f"PRICE_TO_BOOK,DIVIDEND_YIELD,ROAE&where=code:{sym}&order=reportDate&fields=ratioCode,value", timeout=25),
        "vndirect_recs": lambda: S.get(
            f"https://api-finfo.vndirect.com.vn/v4/recommendations?q=code:{sym}&sort=reportDate:DESC&size=20",
            timeout=25),
        "vndirect_recs_old": lambda: S.get(
            f"https://finfo-api.vndirect.com.vn/v4/recommendations?q=code:{sym}&sort=reportDate:DESC&size=20",
            timeout=25),
        "ssi_fin": lambda: S.get(f"https://iboard-query.ssi.com.vn/v2/stock/{sym}", timeout=25),
        "ssi_ratio": lambda: S.get(
            f"https://fiin-fundamental.ssi.com.vn/FinancialAnalysis/GetFinancialRatioV2?language=vi&OrganCode={sym}"
            "&Timefilter=Quarter&NumberOfPeriod=4", timeout=25),
        "kbs_ratio": lambda: S.get(
            f"https://kbbuddywts.kbsec.com.vn/sas/kbsv-stock-data-store/stock/finance-info/{sym}?page=1&pageSize=8"
            "&type=CSTC&unit=1000&termtype=2&languageid=1", timeout=25),
        "kbs_profile": lambda: S.get(f"https://kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/profile/{sym}",
                                     timeout=25),
        "simplize_summary": lambda: S.get(f"https://api.simplize.vn/api/company/summary/{sym.lower()}", timeout=25),
        "simplize_ratio": lambda: S.get(
            f"https://api2.simplize.vn/api/company/fi/ratio?ticker={sym}&period=Q&size=8", timeout=25),
        "24h_info": lambda: S.get(
            f"https://api-finance-t19.24hmoney.vn/v1/ios/stock/statistic-investor-history?symbol={sym}", timeout=25),
        "cafef_ratio": lambda: S.get(
            f"https://s.cafef.vn/Ajax/PageNew/FinanceData/fi.ashx?symbol={sym}", timeout=25),
        "dnse_fin": lambda: S.get(f"https://services.entrade.com.vn/dnse-financial-product/securities/{sym}",
                                  timeout=25),
        "fireant_fund": lambda: S.get(f"https://restv2.fireant.vn/symbols/{sym}/fundamental", timeout=25),
    }


def good(res):
    if "error" in res or res.get("status") != 200:
        return False
    b = res.get("body", "")
    if len(b) < 60 or b.lstrip().startswith("<"):
        return False
    try:
        j = json.loads(b) if len(b) < 4000 else None
    except Exception:  # noqa: BLE001
        j = None
    if isinstance(j, dict) and j.get("errors"):
        return False
    return True


def full(name, sym):
    fn = endpoints(sym)[name]
    try:
        r = fn()
        r.raise_for_status()
        return r.json()
    except Exception as e:  # noqa: BLE001
        return {"_error": f"{type(e).__name__}: {str(e)[:150]}"}


def trim(name, j):
    """Keep payloads small: most recent periods only."""
    try:
        if name.startswith("vci_gql_ratio"):
            rows = j["data"]["CompanyFinancialRatio"]["ratio"]
            rows = sorted(rows, key=lambda r: (r.get("yearReport") or 0, r.get("lengthReport") or 0), reverse=True)
            return rows[:8 if name.endswith("Q") else 5]
        if isinstance(j, dict) and isinstance(j.get("data"), list):
            return {**{k: v for k, v in j.items() if k != "data"}, "data": j["data"][:12]}
        if isinstance(j, list):
            return j[:12]
    except Exception:  # noqa: BLE001
        pass
    return j


def main():
    probe = {}
    for sym in ("FPT", "VCB"):
        with cf.ThreadPoolExecutor(max_workers=8) as ex:
            futs = {ex.submit(call, n, f): n for n, f in endpoints(sym).items()}
            for fu in cf.as_completed(futs):
                res = fu.result()
                probe[f"{sym}:{res['name']}"] = res
                print(sym, res["name"], res.get("status"), res.get("error", "")[:100], (res.get("body") or "")[:160].replace("\n", " "))
    with open(f"{OUT}/fundamentals_probe.json", "w") as f:
        json.dump(probe, f, ensure_ascii=False, indent=1)
    working = sorted({k.split(":")[1] for k, v in probe.items() if good(v)})
    print("working endpoints:", working)

    out = {}
    jobs = [(n, s) for n in working for s in TICKERS]
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for (n, s), j in zip(jobs, ex.map(lambda a: full(*a), jobs)):
            out.setdefault(s, {})[n] = trim(n, j)
    with open(f"{OUT}/fundamentals2.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)

    # vnstock as an extra path; report why it fails if it does
    r = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "vnstock"], capture_output=True, text=True)
    print("pip vnstock rc", r.returncode, r.stderr[-800:])
    vs = {}
    try:
        from vnstock import Vnstock  # type: ignore
        for sym in TICKERS:
            try:
                st = Vnstock().stock(symbol=sym, source="VCI")
                df = st.finance.ratio(period="quarter", lang="en", dropna=True).head(6)
                df.columns = [" | ".join(map(str, c)) if isinstance(c, tuple) else str(c) for c in df.columns]
                vs[sym] = json.loads(df.to_json(orient="records", force_ascii=False))
            except Exception as e:  # noqa: BLE001
                vs[sym] = {"_error": f"{type(e).__name__}: {str(e)[:150]}"}
    except Exception as e:  # noqa: BLE001
        vs["_import_error"] = f"{type(e).__name__}: {str(e)[:300]}"
    with open(f"{OUT}/fundamentals_vnstock.json", "w") as f:
        json.dump(vs, f, ensure_ascii=False, indent=1, default=str)
    print("done", len(out), "tickers;", sum(1 for v in vs.values() if not (isinstance(v, dict) and "_error" in v)), "vnstock ok")


if __name__ == "__main__":
    main()
