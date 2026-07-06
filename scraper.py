# -*- coding: utf-8 -*-
"""新聞爬蟲核心：從 CLAUDE.md 指定的資料來源抓取各主題新聞。

資料來源：自由時報、聯合新聞網、報導者、ETtoday、Yahoo新聞、天下雜誌。
（頂五 basketballtop5.com 依規定禁止使用，未納入。）
"""
import calendar
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone, timedelta

import feedparser
import requests
from bs4 import BeautifulSoup

TAIPEI = timezone(timedelta(hours=8))
TIMEOUT = 12
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "zh-TW,zh;q=0.9",
}
CACHE_TTL = 300  # 各來源頁面快取 5 分鐘，避免重複請求對方網站

TOPICS = {
    "current": "時事",
    "hot": "熱門話題",
    "politics": "政治（國內外）",
    "finance": "財經（國內外）",
    "weather": "天氣",
    "sports": "體育（棒球）",
    "society": "社會",
    "tech": "3C",
}

WEATHER_RE = re.compile(
    r"天氣|氣象|颱風|豪雨|大雨|降雨|雷陣雨|鋒面|梅雨|寒流|冷氣團|低溫|高溫|熱浪|"
    r"焚風|東北季風|西南風|紫外線|降溫|回溫|海警|陸警|海上警報|陸上警報|悶熱|轉涼"
)
BASEBALL_RE = re.compile(
    r"棒球|中職|中華職棒|CPBL|MLB|大聯盟|日職|日本職棒|世界大賽|經典賽|12強|"
    r"中信兄弟|富邦悍將|樂天桃猿|統一獅|味全龍|台鋼雄鷹|投手|打擊|全壘打|洋將"
)
# 部分來源的分類 feed（尤其 Yahoo）會混入其他類別的新聞，
# 對這類 feed 以政治關鍵字做二次過濾，確保顯示內容與勾選主題一致。
POLITICS_RE = re.compile(
    r"政治|總統|副總統|行政院|立法院|立委|議員|選舉|大選|罷免|公投|修憲|憲法|"
    r"法案|草案|三讀|政黨|民進黨|國民黨|民眾黨|內閣|部長|首長|外交|邦交|國防|"
    r"軍|兩岸|中共|白宮|川普|國會|參議院|眾議院|首相|總理|普丁|習近平|澤倫斯基|"
    r"制裁|條約|峰會|G7|G20|北約|聯合國|歐盟|市長|縣長|參選|候選人|執政|在野|"
    r"藍營|綠營|政見|政府|官員"
)

_cache = {}
_cache_lock = threading.Lock()


def _fetch_url(url):
    """抓取原始內容，帶 TTL 快取。"""
    now = time.time()
    with _cache_lock:
        hit = _cache.get(url)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
    resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    resp.raise_for_status()
    content = resp.content
    with _cache_lock:
        _cache[url] = (now, content)
    return content


def _clean(text):
    return re.sub(r"\s+", " ", BeautifulSoup(text or "", "html.parser").get_text()).strip()


def _item(title, url, source, ts=None, summary=""):
    return {
        "title": title.strip(),
        "url": url,
        "source": source,
        "ts": int(ts) if ts else None,
        "summary": summary.strip()[:150],
    }


# ---------------------------------------------------------------- 各來源爬蟲

def _rss(url, source):
    feed = feedparser.parse(_fetch_url(url))
    items = []
    for e in feed.entries[:40]:
        ts = None
        for attr in ("published_parsed", "updated_parsed"):
            t = getattr(e, attr, None)
            if t:
                ts = calendar.timegm(t)
                break
        it = _item(_clean(e.get("title", "")), e.get("link", ""), source, ts,
                   _clean(e.get("summary", "")))
        if it["title"] and it["url"]:
            items.append(it)
    return items


def _udn(cate_id):
    """聯合新聞網即時新聞 API（官方 RSS 內容已清空，改用 breaknews API）。"""
    raw = _fetch_url(
        f"https://udn.com/api/more?page=1&channelId=1&cate_id={cate_id}&type=breaknews"
    )
    data = json.loads(raw)
    items = []
    for it in data.get("lists", [])[:40]:
        link = it.get("titleLink", "")
        if link.startswith("/"):
            link = "https://udn.com" + link
        ts = None
        t = (it.get("time") or {}).get("date", "") if isinstance(it.get("time"), dict) else ""
        if t:
            try:
                ts = datetime.strptime(t[:16], "%Y-%m-%d %H:%M").replace(tzinfo=TAIPEI).timestamp()
            except ValueError:
                pass
        item = _item(it.get("title", ""), link, "聯合新聞網", ts, it.get("paragraph", ""))
        if item["title"] and item["url"]:
            items.append(item)
    return items


def _ettoday(categories=None):
    """ETtoday 即時新聞列表，可依分類名稱（子字串）過濾。"""
    soup = BeautifulSoup(_fetch_url("https://www.ettoday.net/news/news-list.htm"), "html.parser")
    items = []
    for h3 in soup.select("div.part_list_2 h3"):
        a = h3.find("a")
        if not a or not a.get("href"):
            continue
        tag = h3.find("em")
        cat = tag.get_text(strip=True) if tag else ""
        if categories and not any(c in cat for c in categories):
            continue
        ts = None
        date = h3.find("span", class_="date")
        if date:
            try:
                ts = datetime.strptime(
                    date.get_text(strip=True), "%Y/%m/%d %H:%M"
                ).replace(tzinfo=TAIPEI).timestamp()
            except ValueError:
                pass
        items.append(_item(a.get_text(strip=True), a["href"], "ETtoday", ts,
                           f"分類：{cat}" if cat else ""))
    return items


_ETTODAY_ARTICLE_RE = re.compile(r"ettoday\.net/(news/\d{8}/\d+|article/\d+|news/\d+)")


def _ettoday_hot():
    """ETtoday 熱門新聞頁。"""
    soup = BeautifulSoup(_fetch_url("https://www.ettoday.net/news/hot-news.htm"), "html.parser")
    items, seen = [], set()
    for a in soup.select("h3 a[href]"):
        href = a["href"]
        title = a.get_text(strip=True)
        if not _ETTODAY_ARTICLE_RE.search(href) or len(title) < 6 or href in seen:
            continue
        seen.add(href)
        items.append(_item(title, href, "ETtoday", None, "熱門新聞"))
    return items[:20]


def _ltn_popular():
    """自由時報熱門新聞排行（ajax API，回應開頭帶 BOM）。"""
    raw = _fetch_url("https://news.ltn.com.tw/ajax/breakingnews/popular/1")
    data = json.loads(raw.decode("utf-8-sig"))
    rows = data.get("data", [])
    if isinstance(rows, dict):
        rows = list(rows.values())
    items = []
    for it in rows[:20]:
        item = _item(it.get("title", ""), it.get("url", ""), "自由時報",
                     None, it.get("summary", ""))
        if item["title"] and item["url"]:
            items.append(item)
    return items


def _cw():
    """天下雜誌首頁。該站以 WAF 阻擋自動化流量（403），失敗時由上層回報來源異常。"""
    soup = BeautifulSoup(_fetch_url("https://www.cw.com.tw/"), "html.parser")
    items, seen = [], set()
    for a in soup.select("a[href*='/article/']"):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if href.startswith("/"):
            href = "https://www.cw.com.tw" + href
        if len(title) < 8 or href in seen:
            continue
        seen.add(href)
        items.append(_item(title, href, "天下雜誌"))
    return items[:20]


# ---------------------------------------------------------------- 主題與來源對應

LTN = "https://news.ltn.com.tw/rss/{}.xml"
YAHOO = "https://tw.news.yahoo.com/rss/{}"
TWREPORTER = "https://public.twreporter.org/rss/twreporter-rss.xml"

TOPIC_SOURCES = {
    "current": [
        ("自由時報", lambda: _rss(LTN.format("all"), "自由時報")),
        ("聯合新聞網", lambda: _udn(1)),
        ("ETtoday", lambda: _ettoday()),
        ("Yahoo新聞", lambda: _rss("https://tw.news.yahoo.com/rss", "Yahoo新聞")),
        ("報導者", lambda: _rss(TWREPORTER, "報導者")),
        ("天下雜誌", _cw),
    ],
    "hot": [
        ("ETtoday 熱門", _ettoday_hot),
        ("自由時報 熱門", _ltn_popular),
    ],
    "politics": [
        ("自由時報 政治", lambda: _rss(LTN.format("politics"), "自由時報")),
        ("自由時報 國際", lambda: _rss(LTN.format("world"), "自由時報"), POLITICS_RE),
        ("聯合新聞網 要聞", lambda: _udn(1), POLITICS_RE),
        ("聯合新聞網 國際", lambda: _udn(5), POLITICS_RE),
        ("Yahoo新聞 政治", lambda: _rss(YAHOO.format("politics"), "Yahoo新聞"), POLITICS_RE),
        ("Yahoo新聞 國際", lambda: _rss(YAHOO.format("world"), "Yahoo新聞"), POLITICS_RE),
        ("ETtoday 政治", lambda: _ettoday(["政治"])),
    ],
    "finance": [
        ("自由時報 財經", lambda: _rss(LTN.format("business"), "自由時報")),
        ("聯合新聞網 財經", lambda: _udn(6)),
        ("聯合新聞網 股市", lambda: _udn(11)),
        ("Yahoo新聞 財經", lambda: _rss(YAHOO.format("finance"), "Yahoo新聞")),
        ("ETtoday 財經", lambda: _ettoday(["財經"])),
    ],
    "weather": [
        ("自由時報 即時", lambda: _rss(LTN.format("all"), "自由時報")),
        ("自由時報 生活", lambda: _rss(LTN.format("life"), "自由時報")),
        ("聯合新聞網 生活", lambda: _udn(9)),
        ("ETtoday 即時", lambda: _ettoday()),
    ],
    "sports": [
        ("自由時報 體育", lambda: _rss(LTN.format("sports"), "自由時報")),
        ("聯合新聞網 運動", lambda: _udn(7)),
        ("Yahoo新聞 運動", lambda: _rss(YAHOO.format("sports"), "Yahoo新聞")),
        ("ETtoday 體育", lambda: _ettoday(["體育", "運動"])),
    ],
    "society": [
        ("自由時報 社會", lambda: _rss(LTN.format("society"), "自由時報")),
        ("聯合新聞網 社會", lambda: _udn(2)),
        ("Yahoo新聞 社會", lambda: _rss(YAHOO.format("society"), "Yahoo新聞")),
        ("ETtoday 社會", lambda: _ettoday(["社會"])),
    ],
    "tech": [
        ("Yahoo新聞 科技", lambda: _rss(YAHOO.format("technology"), "Yahoo新聞")),
        ("聯合新聞網 科技", lambda: _udn(13)),
        ("ETtoday 3C", lambda: _ettoday(["3C", "科技"])),
    ],
}


# ---------------------------------------------------------------- 彙整

def _interleave_by_source(items, limit):
    """依來源輪流取件，避免單一來源洗版；各來源內部依時間新到舊。"""
    by_source = {}
    for it in items:
        by_source.setdefault(it["source"], []).append(it)
    for lst in by_source.values():
        lst.sort(key=lambda i: i["ts"] or 0, reverse=True)
    result, queues = [], list(by_source.values())
    while queues and len(result) < limit:
        for q in list(queues):
            if not q:
                queues.remove(q)
                continue
            result.append(q.pop(0))
            if len(result) >= limit:
                break
    return result


def fetch_news(topics, per_topic=10):
    """抓取多個主題的新聞。回傳 {"topics": {...}, "generated_at": ts}。"""
    jobs = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for topic in topics:
            for entry in TOPIC_SOURCES[topic]:
                label, fn = entry[0], entry[1]
                source_filter = entry[2] if len(entry) > 2 else None
                jobs.append((topic, label, source_filter, pool.submit(fn)))

        results = {t: {"name": TOPICS[t], "items": [], "errors": []} for t in topics}
        for topic, label, source_filter, fut in jobs:
            try:
                items = fut.result()
                if source_filter:
                    items = [i for i in items
                             if source_filter.search(i["title"] + " " + i["summary"])]
                results[topic]["items"].extend(items)
            except Exception as exc:
                results[topic]["errors"].append(f"{label}：無法取得（{exc.__class__.__name__}）")

    for topic in topics:
        items = results[topic]["items"]
        # 主題層級過濾，確保顯示內容與勾選主題一致
        if topic == "weather":
            items = [i for i in items if WEATHER_RE.search(i["title"])]
        elif topic == "sports":
            # CLAUDE.md 指定體育主題聚焦棒球
            items = [i for i in items if BASEBALL_RE.search(i["title"])]
        # 以網址與標題去除重複
        seen, deduped = set(), []
        for it in items:
            if it["url"] in seen or it["title"] in seen:
                continue
            seen.add(it["url"])
            seen.add(it["title"])
            deduped.append(it)
        results[topic]["items"] = _interleave_by_source(deduped, per_topic)

    return {"topics": results, "generated_at": int(time.time())}
