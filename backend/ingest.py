import re
import hashlib
import datetime as dt
from typing import List, Dict

import requests
from bs4 import BeautifulSoup

from .config import (
    ENABLE_TWITTER,
    MAX_TWEETS_PER_SOURCE,
    TWITTER_SOURCES,
    NEWS_FEEDS,
    KEYWORDS,
)

# ==================================================
# Helpers
# ==================================================
UA = {"User-Agent": "ofac-social-monitor/1.0"}

def normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def hash_item(*parts: str) -> str:
    h = hashlib.sha256()
    for p in parts:
        h.update((p or "").encode("utf-8", errors="ignore"))
        h.update(b"|")
    return h.hexdigest()

def text_matches_keywords(text: str) -> bool:
    txt = (text or "").lower()
    # whitelist dura: si no hay KEYWORDS, no devuelve nada (evita “todo pasa”)
    if not KEYWORDS:
        return False
    return any((kw or "").lower() in txt for kw in KEYWORDS if kw)

# ==================================================
# RSS
# ==================================================
def fetch_rss_articles(feed_url: str, timeout: int = 15) -> List[Dict[str, str]]:
    """
    Devuelve items RSS como dict:
    {title, description, link, published}
    """
    try:
        resp = requests.get(feed_url, timeout=timeout, headers=UA)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.content, "xml")

        items = soup.find_all("item") or []
        out: List[Dict[str, str]] = []

        for it in items:
            title = normalize_text(getattr(it.title, "text", "") if it.title else "")
            desc  = normalize_text(getattr(it.description, "text", "") if it.description else "")
            link  = normalize_text(getattr(it.link, "text", "") if it.link else "")
            pub   = normalize_text(getattr(it.pubDate, "text", "") if it.pubDate else "")

            # validación dura: sin texto, no sirve
            if not title and not desc:
                continue

            out.append({
                "title": title,
                "description": desc,
                "link": link,
                "published": pub,
            })

        return out
    except Exception:
        return []

# ==================================================
# Twitter/X (OPCIONAL)
# ==================================================
def fetch_tweets_from_user(username: str, max_count: int = 100) -> List[str]:
    """
    Usa snscrape (scraping). Puede fallar por cambios/bloqueos de X.
    """
    import snscrape.modules.twitter as sntwitter

    tweets: List[str] = []
    for i, tweet in enumerate(sntwitter.TwitterUserScraper(username).get_items()):
        if i >= max_count:
            break
        txt = normalize_text(getattr(tweet, "content", "") or "")
        if txt:
            tweets.append(txt)
    return tweets

# ==================================================
# Pipeline (menciones crudas)
# ==================================================
def collect_mentions() -> List[Dict]:
    """
    Produce una lista de 'menciones crudas' (sin NER) con:
    id, source, kind, text, ts_utc, link?, published?
    """
    now = dt.datetime.utcnow().isoformat() + "Z"
    out: List[Dict] = []

    # --------------------------
    # 1) RSS
    # --------------------------
    for feed in (NEWS_FEEDS or []):
        items = fetch_rss_articles(feed)
        for it in items:
            blob = normalize_text(f"{it.get('title', '')} {it.get('description', '')}")

            if not text_matches_keywords(blob):
                continue

            link = it.get("link", "") or ""
            published = it.get("published", "") or ""

            out.append({
                "id": hash_item("rss", feed, link, blob[:300]),
                "source": feed,
                "kind": "news",
                "text": blob[:400],
                "link": link,
                "published": published,
                "ts_utc": now,
            })

    # --------------------------
    # 2) Twitter/X (opcional)
    # --------------------------
    if ENABLE_TWITTER:
        for user in (TWITTER_SOURCES or []):
            user = normalize_text(user).lstrip("@")
            if not user:
                continue

            try:
                tweets = fetch_tweets_from_user(user, MAX_TWEETS_PER_SOURCE)
            except Exception:
                continue

            for tw in tweets:
                if not text_matches_keywords(tw):
                    continue

                out.append({
                    "id": hash_item("twitter", user, tw[:200]),
                    "source": f"X @{user}",
                    "kind": "x",
                    "text": tw[:400],
                    "link": "",
                    "published": "",
                    "ts_utc": now,
                })

    return out
