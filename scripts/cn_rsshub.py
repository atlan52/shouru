"""CN 通过 RSSHub 公开实例绕过反爬抓中文本地母语收入帖。

知乎/微博/雪球/36kr/虎嗅/少数派/简书/V2EX 直抓全 0 cookie 强依赖；
RSSHub 提供 RSS 镜像免 cookie。多 fallback 实例容错。

输出: data/raw/cn_rsshub_native_<DAY>.jsonl
schema 同 r_mexico_native (id / raw_id / platform / lang / title / body /
author / url / country_hint / matched_keyword / engagement / crawled_at)
"""
import json, hashlib, time, random, re, sys
from datetime import datetime, timezone
from pathlib import Path
import requests
from bs4 import BeautifulSoup

DAY = datetime.now().strftime("%Y%m%d")
OUT = Path(f"data/raw/cn_rsshub_native_{DAY}.jsonl")
UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
HDR = {
    "User-Agent": UA,
    "Accept": "application/rss+xml, application/xml, text/xml, */*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.5",
}
HDR_HTML = {**HDR, "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
TIMEOUT = 25
SLEEP = (1.3, 1.7)

# 中文收入/谋生关键词
KW_RE = re.compile(
    r"工资|月薪|年薪|月入|年入|收入|赚到|挣到|副业|自由职业|存款|裸辞|"
    r"FIRE|财务自由|被动收入|分红|租金|股息|奖金|提成|创业|月薪过万|"
    r"年薪百万|时薪|薪资|薪水|年终奖|加班费|涨薪|跳槽|外包|接单|"
    r"包月|包年|月收入|年收入|稿费|版税|房租|股票|理财"
)

# RSSHub 实例 fallback 顺序
RSSHUB_HOSTS = [
    "https://rsshub.app",
    "https://rsshub.rssforever.com",
    "https://rss.shab.fun",
]

# 选定 10 个产出预期最好的 feed
# (label, path, body_selectors_for_link_fetch)
FEEDS = [
    # 知乎热榜 + 程序员/创业 topic
    ("rsshub_zhihu_hotlist",   "/zhihu/hotlist",
     [".RichText", ".QuestionAnswer-content", "article", ".content"]),
    ("rsshub_zhihu_programmer","/zhihu/topic/19551147",
     [".RichText", ".QuestionAnswer-content", "article", ".content"]),
    ("rsshub_zhihu_startup",   "/zhihu/topic/19553298",
     [".RichText", ".QuestionAnswer-content", "article", ".content"]),
    # 微博收入相关 keyword
    ("rsshub_weibo_yueru",     "/weibo/keyword/月入十万",
     [".weibo-text", "article", ".content"]),
    ("rsshub_weibo_nianxin",   "/weibo/keyword/年薪百万",
     [".weibo-text", "article", ".content"]),
    ("rsshub_weibo_fuye",      "/weibo/keyword/副业收入",
     [".weibo-text", "article", ".content"]),
    # 雪球 — 投资/分红/股息原文
    ("rsshub_xueqiu_today",    "/xueqiu/today",
     [".article__bd__detail", ".status-content", "article", ".content"]),
    # 36kr 创业财经
    ("rsshub_36kr_latest",     "/36kr/news/latest",
     [".articleDetailContent", "article", ".content", "main"]),
    # 虎嗅
    ("rsshub_huxiu_article",   "/huxiu/article",
     [".article-content-wrap", "article", ".content"]),
    # 少数派
    ("rsshub_sspai_index",     "/sspai/index",
     [".content", "article", ".article__main"]),
    # 简书
    ("rsshub_jianshu_home",    "/jianshu/home",
     [".show-content", "article", ".content"]),
    # V2EX 招聘 / 最新
    ("rsshub_v2ex_jobs",       "/v2ex/tab/jobs",
     [".topic_content", ".cell.markdown_body", "article"]),
    ("rsshub_v2ex_latest",     "/v2ex/topics/latest",
     [".topic_content", ".cell.markdown_body", "article"]),
]


def md5_16(*p): return hashlib.md5("|".join(map(str, p)).encode()).hexdigest()[:16]
def now_iso(): return datetime.now(timezone.utc).isoformat(timespec="seconds")
def polite(): time.sleep(random.uniform(*SLEEP))


def append(obj):
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def load_seen():
    seen = set()
    if OUT.exists():
        for line in OUT.open(encoding="utf-8"):
            try: seen.add(json.loads(line)["id"])
            except Exception: pass
    return seen


def fetch(url: str, label: str = "", retried: bool = False) -> str | None:
    try:
        r = requests.get(url, headers=HDR, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [{label}] req err: {e}", file=sys.stderr)
        return None
    if r.status_code == 429 and not retried:
        print(f"  [{label}] 429 rate-limited, sleep 5s and retry once", file=sys.stderr)
        time.sleep(5.0)
        return fetch(url, label, retried=True)
    if r.status_code != 200:
        print(f"  [{label}] status={r.status_code} url={url}", file=sys.stderr)
        return None
    if len(r.text) < 80:
        print(f"  [{label}] body too short ({len(r.text)}b)", file=sys.stderr)
        return None
    return r.text


def fetch_feed(path: str, label: str) -> str | None:
    """轮询 RSSHub 实例直到拿到内容。"""
    for host in RSSHUB_HOSTS:
        url = host + path
        xml = fetch(url, f"{label}@{host}")
        if xml and ("<item" in xml or "<entry" in xml):
            return xml
        time.sleep(0.5)
    return None


def parse_rss(xml: str):
    soup = BeautifulSoup(xml, "xml")
    items = soup.find_all("item") or soup.find_all("entry")
    out = []
    for it in items:
        t = it.find("title")
        l = it.find("link")
        g = it.find("guid") or it.find("id")
        d = it.find("description") or it.find("summary") or it.find("content")
        a = it.find("author") or it.find("dc:creator")
        p = it.find("pubDate") or it.find("published") or it.find("updated")
        title = t.get_text(" ", strip=True) if t else ""
        # link 处理 (rss <link>text</link> 或 atom <link href="">)
        link = ""
        if l is not None:
            link = (l.get("href") or l.get_text(strip=True) or "")
        guid = g.get_text(strip=True) if g else (link or title)
        desc_html = d.get_text(" ", strip=True) if d else ""
        # description 内通常含 <p>/<img>，再 strip 一次取纯文本
        if desc_html:
            try:
                desc_text = BeautifulSoup(desc_html, "html.parser").get_text(" ", strip=True)
            except Exception:
                desc_text = desc_html
        else:
            desc_text = ""
        author = a.get_text(" ", strip=True) if a else ""
        pub = p.get_text(strip=True) if p else ""
        out.append({
            "title": title, "link": link, "guid": guid,
            "desc": desc_text, "author": author, "pub": pub,
        })
    return out


def fetch_article_body(url: str, selectors: list[str], label: str) -> str:
    """正文页 fallback —— 仅当 RSS desc 太短才用。"""
    if not url or not url.startswith("http"):
        return ""
    try:
        r = requests.get(url, headers=HDR_HTML, timeout=TIMEOUT)
    except Exception as e:
        print(f"  [{label}] body req err: {e}", file=sys.stderr)
        return ""
    if r.status_code != 200:
        return ""
    soup = BeautifulSoup(r.text, "html.parser")
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            if len(txt) > 100:
                return txt[:6000]
    # fallback: 拼接 <p>
    ps = soup.select("p")
    if ps:
        joined = " ".join(p.get_text(" ", strip=True) for p in ps if p.get_text(strip=True))
        if len(joined) > 100:
            return joined[:6000]
    return ""


def crawl_feed(label: str, path: str, body_selectors: list[str], seen: set) -> tuple[int, int, int]:
    """Return (items, matched, written)."""
    xml = fetch_feed(path, label)
    if xml is None:
        print(f"[{label}] FEED FAIL", file=sys.stderr)
        return 0, 0, 0
    items = parse_rss(xml)
    n_items = len(items)
    matched = 0
    written = 0
    for it in items:
        title = it["title"] or ""
        desc = it["desc"] or ""
        haystack = f"{title}\n{desc}"
        if not KW_RE.search(haystack):
            continue
        matched += 1
        link = it["link"] or ""
        guid = it["guid"] or link or title
        rid = md5_16(label, guid)
        if rid in seen:
            continue
        body = desc
        # 描述太短再 GET 正文
        if len(body) < 200 and link:
            extra = fetch_article_body(link, body_selectors, label)
            polite()
            if extra and len(extra) > len(body):
                body = extra
        if not body or len(body) < 30:
            continue
        # 二次确认 body 含中文 + KW (有些纯英文 RSS 会被标题误命中)
        if not KW_RE.search(body) and not KW_RE.search(title):
            continue
        # matched_keyword 取首个命中关键词
        mkw = KW_RE.search(haystack)
        kw_str = mkw.group(0) if mkw else ""
        obj = {
            "id": rid,
            "raw_id": guid[:200],
            "platform": label,
            "lang": "zh",
            "title": title[:500],
            "body": body[:6000],
            "author": (it.get("author") or "")[:200],
            "url": link,
            "country_hint": "CN",
            "matched_keyword": kw_str,
            "engagement": {"score": 0, "comments": 0, "views": None},
            "pub_date": it.get("pub", ""),
            "crawled_at": now_iso(),
        }
        append(obj)
        seen.add(rid)
        written += 1
    return n_items, matched, written


def main():
    seen = load_seen()
    totals = {"items": 0, "matched": 0, "written": 0}
    per_feed = []
    for label, path, sels in FEEDS:
        try:
            it_n, m_n, w_n = crawl_feed(label, path, sels, seen)
        except Exception as e:
            print(f"[{label}] CRAWL ERR: {e}", file=sys.stderr)
            it_n = m_n = w_n = 0
        per_feed.append((label, it_n, m_n, w_n))
        totals["items"] += it_n
        totals["matched"] += m_n
        totals["written"] += w_n
        print(f"[{label}] items={it_n} matched={m_n} written={w_n}",
              file=sys.stderr)
        polite()
    # 末尾汇总
    print("\n=== cn_rsshub summary ===")
    for label, it_n, m_n, w_n in per_feed:
        print(f"  {label:32s} items={it_n:4d} matched={m_n:4d} written={w_n:4d}")
    total_lines = 0
    if OUT.exists():
        total_lines = sum(1 for _ in OUT.open(encoding="utf-8"))
    print(f"\nTOTAL  items={totals['items']}  matched={totals['matched']}  "
          f"written={totals['written']}  file_lines={total_lines}")
    print(f"OUT: {OUT}")


if __name__ == "__main__":
    main()
