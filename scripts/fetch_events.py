#!/usr/bin/env python3
"""Corporate-action calendar (ex-rights dates, ratios) for the shortlisted tickers.

Probes several public endpoints, keeps every non-empty response and also pulls
Google News headlines that mention record/ex-rights dates, so dates used in the
report can be cross-checked. Output: data/snapshot/events.json
"""
import concurrent.futures as cf
import json
import xml.etree.ElementTree as ET
from urllib.parse import quote_plus

import requests

OUT = "data/snapshot/events.json"
TICKERS = ["VCB", "CTG", "MBB", "BID", "HDB", "VPB", "TCB", "GMD", "BMP", "MWG", "NT2", "REE", "FRT", "VNM",
           "HPG", "FPT", "SSI", "IDC", "SIP", "DMX", "E1VFVN30"]
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
      "Chrome/126.0 Safari/537.36")
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept": "application/json, text/plain, */*"})
VCI_HDR = {"Referer": "https://trading.vietcap.com.vn/", "Origin": "https://trading.vietcap.com.vn"}
IQ_HDR = {"Referer": "https://iq.vietcap.com.vn/", "Origin": "https://iq.vietcap.com.vn"}

GQL_EVENTS = """query Query($ticker: String!, $lang: String!) {
  OrganizationEvents(ticker: $ticker) { id organCode ticker eventTitle publicDate issueDate sourceUrl
    eventListCode ratio value recordDate exrightDate eventListName en_EventListName __typename } }"""


def endpoints(sym):
    return {
        "vnd_events": lambda: S.get(f"https://api-finfo.vndirect.com.vn/v4/events?q=code:{sym}&sort=effectiveDate:desc&size=20", timeout=25),
        "vnd_events_locale": lambda: S.get(f"https://api-finfo.vndirect.com.vn/v4/events?q=code:{sym}~locale:VN&sort=disclosureDate:desc&size=20", timeout=25),
        "vci_gql_events": lambda: S.post("https://trading.vietcap.com.vn/data-mt/graphql", headers=VCI_HDR, timeout=25,
                                         json={"query": GQL_EVENTS, "variables": {"ticker": sym, "lang": "vi"}}),
        "iq_events": lambda: S.get(f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/events?ticker={sym}&page=0&size=20", headers=IQ_HDR, timeout=25),
        "iq_company_events": lambda: S.get(f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}/events?page=0&size=20", headers=IQ_HDR, timeout=25),
        "iq_news_events": lambda: S.get(f"https://iq.vietcap.com.vn/api/iq-insight-service/v1/company/{sym}/news-events?page=0&size=20", headers=IQ_HDR, timeout=25),
        "24h_events": lambda: S.get(f"https://api-finance-t19.24hmoney.vn/v1/ios/company/events?symbol={sym}&page=1&per_page=20", timeout=25),
        "24h_events2": lambda: S.get(f"https://api-finance-t19.24hmoney.vn/v1/web/company/events?symbol={sym}&page=1&per_page=20", timeout=25),
        "simplize_events": lambda: S.get(f"https://api.simplize.vn/api/company/events/{sym.lower()}?page=0&size=20", timeout=25),
        "kbs_events": lambda: S.get(f"https://kbbuddywts.kbsec.com.vn/iis-server/investment/stockinfo/event/{sym}?l=1&p=1&s=20", timeout=25),
        "cafef_events": lambda: S.get(f"https://s.cafef.vn/Ajax/Events_RelatedNews_New.aspx?symbol={sym}&floorID=0&configID=0&PageIndex=1&PageSize=20&Type=2", timeout=25),
    }


def body_ok(r):
    if r.status_code != 200:
        return False
    t = r.text.strip()
    return len(t) > 80 and not t.startswith("<!DOCTYPE") and '"data":[]' not in t and t not in ("{}", "[]")


def news(sym):
    out = []
    for q in (f'"{sym}" ngày đăng ký cuối cùng', f'"{sym}" giao dịch không hưởng quyền', f'"{sym}" cổ tức 2026'):
        url = f"https://news.google.com/rss/search?q={quote_plus(q + ' when:60d')}&hl=vi&gl=VN&ceid=VN:vi"
        try:
            root = ET.fromstring(S.get(url, timeout=20).content)
            for it in root.iter("item"):
                out.append({"q": q, "title": it.findtext("title"), "date": it.findtext("pubDate")})
        except Exception as e:  # noqa: BLE001
            out.append({"q": q, "error": str(e)[:100]})
    seen, uniq = set(), []
    for x in out:
        k = x.get("title")
        if k and k not in seen:
            seen.add(k)
            uniq.append(x)
    return uniq[:30]


def one(sym):
    res = {"api": {}, "status": {}}
    for name, fn in endpoints(sym).items():
        try:
            r = fn()
            res["status"][name] = r.status_code
            if body_ok(r):
                res["api"][name] = r.text[:12000]
        except Exception as e:  # noqa: BLE001
            res["status"][name] = f"ERR {type(e).__name__}"
    res["news"] = news(sym)
    return sym, res


def main():
    out = {}
    with cf.ThreadPoolExecutor(max_workers=5) as ex:
        for sym, res in ex.map(one, TICKERS):
            out[sym] = res
            print(sym, res["status"], "ok:", list(res["api"]), "news:", len(res["news"]))
    json.dump(out, open(OUT, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
