#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Public-preview -> Bot API relay. Source @Ms20260601, target @xiaotiancaixu.

Reuses the original config.yaml filters:
  filters.blacklist_region_categories / blacklist_genres / blacklist_genre_ids

Env:
  TELEGRAM_BOT_TOKEN, SOURCE_CHANNEL, TARGET_CHANNEL, POLL_SECONDS,
  CONFIG_PATH, DB_PATH, TMDB_API_KEY,
  ADD_HEADER=1, STRIP_BRANDING=1, PRESERVE_FORMATTING=1,
  KEEP_SOURCE_LINKS=0, KEEP_BUTTONS=0, DEDUPE_EPISODES=1
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import sqlite3
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

SOURCE = os.getenv("SOURCE_CHANNEL", "Ms20260601").lstrip("@")
TARGET = os.getenv("TARGET_CHANNEL", "@xiaotiancaixu")
POLL_SECONDS = int(os.getenv("POLL_SECONDS", "30"))
DB_PATH = Path(os.getenv("DB_PATH", "data/web_forwarder.sqlite3"))
CONFIG_PATH = Path(os.getenv("CONFIG_PATH", "config.yaml"))
MAX_CAPTION = int(os.getenv("MAX_CAPTION", "950"))
DEDUPE_EPISODES = os.getenv("DEDUPE_EPISODES", "1") != "0"
STRIP_BRANDING = os.getenv("STRIP_BRANDING", "1") != "0"
PRESERVE_FORMATTING = os.getenv("PRESERVE_FORMATTING", "1") != "0"
KEEP_SOURCE_LINKS = os.getenv("KEEP_SOURCE_LINKS", "0") != "0"
KEEP_BUTTONS = os.getenv("KEEP_BUTTONS", "0") != "0"
ADD_HEADER = os.getenv("ADD_HEADER", "1") != "0"
TMDB_API_KEY = os.getenv("TMDB_API_KEY", "")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
)

LABELS = (
    "资源名称|名称|标题|片名|影视|电影|影片|剧集|电视剧|美剧|英剧|日剧|韩剧|"
    "国剧|陆剧|动漫|动画|纪录片|综艺"
)
TITLE_RE = re.compile(
    rf"^\s*(?:[^\w\u4e00-\u9fff@#]+\s*)*({LABELS})\s*[:：\-\s]+(.+)$",
    re.IGNORECASE,
)
YEAR_RE = re.compile(r"(?:年份|上映|首播|发行)\s*[:：]\s*(19\d{2}|20\d{2})")
TMDB_RE = re.compile(
    r"(?:TMDB\s*(?:ID)?|tmdbid\s*=|(?<![A-Za-z])ID)\s*[:：=]\s*(\d+)",
    re.IGNORECASE,
)
TYPE_RE = re.compile(r"(?:影视类型|类型)\s*[:：]\s*([^\n]+)")
CATEGORY_RE = re.compile(r"分类\s*[:：]\s*([^\s｜|]+)")
EPISODE_RE = re.compile(r"季集\s*[:：]\s*([^\n]+)")

PROMO_MARKERS = (
    "hdhive", "开通vip", "永久vip", "免费开户", "群主自用机场", "守候网络",
    "阿里云盘播放神器", "vidhub", "9折活动", "本站发布的资源",
)
ALLOWED_TAGS = {
    "a", "b", "strong", "i", "em", "u", "ins", "s", "strike", "del",
    "code", "pre", "blockquote",
}
SAFE_SCHEMES = ("http://", "https://", "tg://")

CATEGORY_ALIASES = {
    "国产": {"国产剧", "华语电影"}, "国产剧": {"国产剧"},
    "华语": {"华语电影"}, "华语电影": {"华语电影"},
    "欧美": {"欧美剧", "欧美电影"}, "欧美剧": {"欧美剧"},
    "欧美电影": {"欧美电影"}, "日韩": {"日韩剧", "日韩电影"},
    "日韩剧": {"日韩剧"}, "日韩电影": {"日韩电影"},
    "日漫": {"日番"}, "日番": {"日番"}, "国漫": {"国漫"},
    "动漫": {"国漫", "日番", "动画电影"},
    "动画": {"国漫", "日番", "动画电影"},
    "动画电影": {"动画电影"}, "综艺": {"综艺"},
    "纪录": {"纪录片"}, "记录": {"纪录片"}, "纪录片": {"纪录片"},
    "儿童": {"儿童"}, "未分类": {"未分类"},
}
CATEGORY_MAP = {
    "国产剧": "国产剧", "港剧": "国产剧", "台剧": "国产剧",
    "华语电影": "华语电影",
    "美剧": "欧美剧", "欧美剧": "欧美剧", "海外剧": "欧美剧",
    "欧美电影": "欧美电影",
    "日剧": "日韩剧", "韩剧": "日韩剧", "日韩剧": "日韩剧",
    "日韩电影": "日韩电影",
    "国漫": "国漫", "日漫": "日番", "日番": "日番",
    "动画电影": "动画电影",
    "美综": "综艺", "国综": "综艺", "台综": "综艺", "综艺": "综艺",
    "纪录片": "纪录片", "法漫": "未分类", "未分类": "未分类",
}


def load_filters() -> dict:
    if not CONFIG_PATH.exists():
        return {"blacklist_genres": [], "blacklist_genre_ids": [],
                "blacklist_region_categories": []}
    data = yaml.safe_load(CONFIG_PATH.read_text("utf-8")) or {}
    f = data.get("filters", {}) or {}
    return {
        "blacklist_genres": [str(x) for x in f.get("blacklist_genres", [])],
        "blacklist_genre_ids": [int(x) for x in f.get("blacklist_genre_ids", [])],
        "blacklist_region_categories": [
            str(x) for x in f.get("blacklist_region_categories", [])
        ],
    }


FILTERS = load_filters()


def expand_categories(values: list[str]) -> set[str]:
    names: set[str] = set()
    for raw in values:
        name = raw.strip()
        if name:
            names.add(name)
            names.update(CATEGORY_ALIASES.get(name, set()))
    return names


BLACKLIST_CATEGORIES = expand_categories(FILTERS["blacklist_region_categories"])
BLACKLIST_GENRES = {g.casefold() for g in FILTERS["blacklist_genres"] if g}
BLACKLIST_GENRE_IDS = set(FILTERS["blacklist_genre_ids"])


@dataclass
class Meta:
    title: str
    year: int | None
    tmdb_id: int | None
    media_type: str
    category: str
    episode: str


@dataclass
class Post:
    mid: int
    published: str
    text: str
    html_text: str
    photo_url: str | None
    meta: Meta
    buttons: list[tuple[str, str]] = field(default_factory=list)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(*parts: object) -> None:
    print(datetime.now().strftime("%H:%M:%S"), *parts, flush=True)


def strip_tags(fragment: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", fragment))


def plain_text(fragment: str) -> str:
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = re.sub(r"</(?:p|div)\s*>", "\n", fragment, flags=re.I)
    return strip_tags(fragment).strip("\n")


EMOJI_RE = re.compile(r'<i[^>]*class="[^"]*emoji[^"]*"[^>]*>(.*?)</i>', re.S | re.I)
A_RE = re.compile(r"<a\s+([^>]*)>(.*?)</a>", re.S | re.I)
TAG_RE = re.compile(r"</?([a-zA-Z0-9]+)(?:\s[^>]*)?>")
HREF_RE = re.compile(r'href="([^"]+)"', re.I)


def format_html_fragment(fragment: str) -> str:
    if not PRESERVE_FORMATTING:
        return html.escape(plain_text(fragment), quote=False)

    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.I)
    fragment = EMOJI_RE.sub(r"\1", fragment)

    def link_repl(match: re.Match) -> str:
        attrs, inner = match.group(1), match.group(2)
        href_match = HREF_RE.search(attrs)
        if (
            KEEP_SOURCE_LINKS
            and href_match
            and href_match.group(1).lower().startswith(SAFE_SCHEMES)
        ):
            href = html.escape(href_match.group(1), quote=True)
            return f'<a href="{href}">{inner}</a>'
        return inner

    fragment = A_RE.sub(link_repl, fragment)

    def tag_repl(match: re.Match) -> str:
        tag = match.group(1).lower()
        return match.group(0) if tag in ALLOWED_TAGS else ""

    fragment = TAG_RE.sub(tag_repl, fragment)
    fragment = re.sub(
        r"&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)", "&amp;", fragment
    )
    fragment = re.sub(r"\n{3,}", "\n\n", fragment)
    return fragment.strip()


def parse_meta(text: str) -> Meta:
    title = ""
    for line in text.splitlines():
        match = TITLE_RE.match(line.strip())
        if match:
            title = match.group(2).strip()
            break
    if not title:
        for line in text.splitlines():
            line = line.strip()
            if line and not line.startswith(("http://", "https://", "ed2k://", "magnet:")):
                title = line
                break

    year = None
    year_match = YEAR_RE.search(text)
    if year_match:
        year = int(year_match.group(1))
    else:
        plain_title = re.sub(r"[*`~]+", "", title)
        match = re.search(r"\b(19\d{2}|20\d{2})\b", plain_title)
        if match:
            year = int(match.group(1))
            title = plain_title[: match.start()].strip()

    tmdb_match = TMDB_RE.search(text)
    tmdb_id = int(tmdb_match.group(1)) if tmdb_match else None

    media_type = "tv"
    type_match = TYPE_RE.search(text)
    if type_match and "电影" in type_match.group(1):
        media_type = "movie"

    category_match = CATEGORY_RE.search(text)
    category = category_match.group(1).strip() if category_match else "未分类"
    episode_match = EPISODE_RE.search(text)
    episode = episode_match.group(1).strip() if episode_match else ""

    title = re.sub(r"[*`~]+", "", title)
    title = re.sub(r"\s+", " ", title).strip(" -")
    return Meta(title, year, tmdb_id, media_type, category, episode)


def parse_buttons(block: str) -> list[tuple[str, str]]:
    if not KEEP_BUTTONS:
        return []
    buttons: list[tuple[str, str]] = []
    for match in re.finditer(
        r'<a[^>]*class="[^"]*tgme_widget_message_inline_button[^"]*"[^>]*>.*?</a>',
        block, re.S,
    ):
        tag = match.group(0)
        href = HREF_RE.search(tag)
        text = re.search(r"<span[^>]*>(.*?)</span>", tag, re.S)
        if not href or not text:
            continue
        url = html.unescape(href.group(1))
        if url.lower().startswith(SAFE_SCHEMES):
            label = strip_tags(text.group(1)).strip()
            if label:
                buttons.append((label, url))
    return buttons


def parse_posts(page: str, source: str) -> list[Post]:
    pattern = re.compile(
        r'(?=<div class="tgme_widget_message[^"]*"\s+data-post="%s/)' % re.escape(source)
    )
    posts: dict[int, Post] = {}
    for block in pattern.split(page):
        mid_match = re.search(r'data-post="%s/(\d+)"' % re.escape(source), block)
        if not mid_match:
            continue
        mid = int(mid_match.group(1))
        text_match = re.search(
            r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', block, re.S
        )
        raw_html = text_match.group(1) if text_match else ""
        text = plain_text(raw_html)
        html_text = format_html_fragment(raw_html)
        time_match = re.search(r'<time[^>]*datetime="([^"]+)"', block)
        published = time_match.group(1) if time_match else ""
        photo_match = re.search(r"background-image:url\('([^']+)'\)", block)
        photo_url = html.unescape(photo_match.group(1)) if photo_match else None
        if not text and not photo_url:
            continue
        posts[mid] = Post(
            mid, published, text, html_text, photo_url,
            parse_meta(text), parse_buttons(block),
        )
    return [posts[k] for k in sorted(posts)]


def fetch_posts(source: str) -> list[Post]:
    with httpx.Client(
        timeout=30, follow_redirects=True, headers={"User-Agent": UA}
    ) as client:
        response = client.get(f"https://t.me/s/{source}")
        response.raise_for_status()
    return parse_posts(response.text, source)


def clean_body(text_html: str) -> str:
    out: list[str] = []
    for raw in text_html.splitlines():
        plain = strip_tags(raw).strip()
        if not plain:
            out.append("")
            continue
        if STRIP_BRANDING:
            if plain.startswith("✅新片送达"):
                continue
            if plain.startswith("❤️RMGroup"):
                continue
            if re.match(r"^🕐", plain):
                continue
        if re.fullmatch(r"(?:#\S+\s*)+", plain):
            continue
        if plain.count("👀") >= 3 or plain.count("⬇") >= 2:
            continue
        if any(marker in plain.casefold() for marker in PROMO_MARKERS):
            continue
        out.append(raw)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out).strip())


def build_header(post: Post) -> str:
    meta = post.meta
    lines = [f"片名：{html.escape(meta.title or '未知')}"]
    if meta.year:
        lines.append(f"年份：{meta.year}")
    if meta.tmdb_id:
        path = f"{meta.media_type}/{meta.tmdb_id}"
        lines.append(f'TMDB：<a href="https://www.themoviedb.org/{path}">{path}</a>')
    lines.append(f"分类：{html.escape(meta.category or '未分类')}")
    return "\n".join(lines)


def build_caption(post: Post) -> str:
    body = clean_body(post.html_text)
    if not ADD_HEADER:
        return body
    return build_header(post) + ("\n\n" + body if body else "")


def visible_len(value: str) -> int:
    return len(strip_tags(value))


def split_caption(text: str, limit: int) -> tuple[str, str]:
    if visible_len(text) <= limit:
        return text, ""
    parts = text.split("\n\n", 1)
    if len(parts) == 2 and visible_len(parts[0]) <= limit:
        return parts[0], parts[1]
    plain = strip_tags(text)
    return html.escape(plain[:limit], quote=False), html.escape(plain[limit:], quote=False)


def episode_key(post: Post) -> str | None:
    if not DEDUPE_EPISODES or not post.meta.tmdb_id or not post.meta.episode:
        return None
    return f"{post.meta.tmdb_id}:{post.meta.episode}"


class Bot:
    def __init__(self, token: str):
        self.token = token
        self.client = httpx.Client(
            timeout=60, follow_redirects=True, headers={"User-Agent": UA}
        )

    def api(self, method: str, **kwargs):
        response = self.client.post(
            f"https://api.telegram.org/bot{self.token}/{method}", **kwargs
        )
        payload = response.json()
        if not payload.get("ok"):
            raise RuntimeError(f"{method}: {payload}")
        return payload["result"]

    def send_post(self, chat_id: str, caption: str, photo_url: str | None,
                  buttons: list[tuple[str, str]] | None = None) -> None:
        photo = None
        if photo_url:
            try:
                r = self.client.get(photo_url)
                if r.status_code == 200 and r.content:
                    photo = r.content
            except Exception as exc:
                log("photo download failed:", exc)

        markup = None
        if buttons:
            markup = json.dumps(
                {"inline_keyboard": [[{"text": t, "url": u}] for t, u in buttons]},
                ensure_ascii=False,
            )

        head, tail = split_caption(caption, MAX_CAPTION)
        if photo:
            data = {"chat_id": chat_id, "caption": head, "parse_mode": "HTML"}
            if markup:
                data["reply_markup"] = markup
            try:
                self.api("sendPhoto", data=data,
                         files={"photo": ("poster.jpg", photo, "image/jpeg")})
            except Exception as exc:
                log("sendPhoto failed, fallback to text:", exc)
                payload = {"chat_id": chat_id, "text": head, "parse_mode": "HTML",
                           "disable_web_page_preview": True}
                if markup:
                    payload["reply_markup"] = markup
                self.api("sendMessage", json=payload)
        else:
            payload = {"chat_id": chat_id, "text": head, "parse_mode": "HTML",
                       "disable_web_page_preview": True}
            if markup:
                payload["reply_markup"] = markup
            self.api("sendMessage", json=payload)
        if tail:
            self.api("sendMessage", json={"chat_id": chat_id, "text": tail,
                                          "parse_mode": "HTML",
                                          "disable_web_page_preview": True})


def init_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS sent (mid INTEGER PRIMARY KEY, sent_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS episodes (key TEXT PRIMARY KEY, mid INTEGER, sent_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS filtered (mid INTEGER PRIMARY KEY, reason TEXT, category TEXT, filtered_at TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS genres (key TEXT PRIMARY KEY, genres_json TEXT, fetched_at TEXT)")
    con.commit()
    return con


def already_sent(con: sqlite3.Connection, mid: int) -> bool:
    return con.execute("SELECT 1 FROM sent WHERE mid=?", (mid,)).fetchone() is not None


def mark_sent(con: sqlite3.Connection, post: Post, mark_episode: bool = True) -> None:
    stamp = now_iso()
    con.execute("INSERT OR IGNORE INTO sent(mid, sent_at) VALUES (?, ?)", (post.mid, stamp))
    key = episode_key(post)
    if mark_episode and key:
        con.execute("INSERT OR IGNORE INTO episodes(key, mid, sent_at) VALUES (?, ?, ?)",
                    (key, post.mid, stamp))
    con.commit()


def mark_filtered(con: sqlite3.Connection, post: Post, reason: str) -> None:
    con.execute("INSERT OR IGNORE INTO filtered(mid, reason, category, filtered_at) VALUES (?, ?, ?, ?)",
                (post.mid, reason, post.meta.category, now_iso()))
    mark_sent(con, post, mark_episode=False)


def episode_already_sent(con: sqlite3.Connection, post: Post) -> bool:
    key = episode_key(post)
    return bool(key and con.execute("SELECT 1 FROM episodes WHERE key=?", (key,)).fetchone())


def tmdb_genres(con: sqlite3.Connection, tmdb_id: int | None,
                media_type: str) -> list[tuple[int, str]]:
    if not tmdb_id or not TMDB_API_KEY:
        return []
    key = f"{media_type}:{tmdb_id}"
    row = con.execute("SELECT genres_json FROM genres WHERE key=?", (key,)).fetchone()
    if row:
        try:
            return [(int(g[0]), str(g[1])) for g in json.loads(row[0])]
        except Exception:
            pass
    try:
        r = httpx.get(f"https://api.themoviedb.org/3/{media_type}/{tmdb_id}",
                      params={"api_key": TMDB_API_KEY, "language": "zh-CN"},
                      timeout=20)
        r.raise_for_status()
        genres = [(int(g["id"]), str(g.get("name", g["id"])))
                  for g in r.json().get("genres", []) if "id" in g]
        con.execute("INSERT OR REPLACE INTO genres(key, genres_json, fetched_at) VALUES (?, ?, ?)",
                    (key, json.dumps(genres, ensure_ascii=False), now_iso()))
        con.commit()
        return genres
    except Exception as exc:
        log(f"tmdb genres failed {key}: {exc}")
        return []


def evaluate_post(con: sqlite3.Connection, post: Post) -> tuple[bool, str]:
    raw = post.meta.category or "未分类"
    mapped = CATEGORY_MAP.get(raw, raw)
    if raw in BLACKLIST_CATEGORIES or mapped in BLACKLIST_CATEGORIES:
        return False, f"blacklisted_region:{mapped}"
    if not TMDB_API_KEY and (BLACKLIST_GENRES or BLACKLIST_GENRE_IDS):
        return True, "allowed"
    for gid, gname in tmdb_genres(con, post.meta.tmdb_id, post.meta.media_type):
        if gid in BLACKLIST_GENRE_IDS:
            return False, f"blacklisted_genre_id:{gid}"
        if gname.casefold() in BLACKLIST_GENRES:
            return False, f"blacklisted_genre:{gname}"
    return True, "allowed"


def bootstrap(con: sqlite3.Connection, posts: list[Post]) -> None:
    stamp = now_iso()
    con.executemany("INSERT OR IGNORE INTO sent(mid, sent_at) VALUES (?, ?)",
                    [(p.mid, stamp) for p in posts])
    con.commit()


def log_filters() -> None:
    log("filters:", f"categories={sorted(BLACKLIST_CATEGORIES)}",
        f"genres={sorted(BLACKLIST_GENRES)}", f"genre_ids={sorted(BLACKLIST_GENRE_IDS)}")
    if not TMDB_API_KEY and (BLACKLIST_GENRES or BLACKLIST_GENRE_IDS):
        log("warning: TMDB_API_KEY missing, genre filters inactive")


def run_once(args, bot: Bot | None, con: sqlite3.Connection | None) -> None:
    posts = fetch_posts(SOURCE)
    if not posts:
        log("no posts found")
        return

    if args.dry_run:
        temp = sqlite3.connect(":memory:")
        temp.execute("CREATE TABLE genres (key TEXT PRIMARY KEY, genres_json TEXT, fetched_at TEXT)")
        selected = posts[-args.limit:] if args.limit else posts
        seen: set[str] = set()
        allowed = filtered = duplicate = 0
        for post in selected:
            key = episode_key(post)
            if key and key in seen:
                duplicate += 1
                log(f"[dry] {post.mid} skip duplicate episode {key}")
                continue
            ok, reason = evaluate_post(temp, post)
            if not ok:
                filtered += 1
                log(f"[dry] {post.mid} FILTER {reason} {post.meta.title} ({post.meta.category})")
                continue
            allowed += 1
            if key:
                seen.add(key)
            caption = build_caption(post)
            head, tail = split_caption(caption, MAX_CAPTION)
            log(f"[dry] {post.mid} SEND {post.meta.title} ({post.meta.category}) "
                f"visible={visible_len(caption)} raw={len(caption)} "
                f"tail={visible_len(tail)} buttons={len(post.buttons)}")
            print(head)
            if tail:
                print("--- tail ---")
                print(tail)
            print("-" * 70)
        log(f"dry summary: allowed={allowed} filtered={filtered} duplicates={duplicate}")
        temp.close()
        return

    assert bot is not None and con is not None

    if args.test_send:
        for post in reversed(posts):
            ok, reason = evaluate_post(con, post)
            if not ok:
                log(f"skip {post.mid} filter {reason}")
                continue
            caption = build_caption(post)
            log(f"test send {post.mid} {post.meta.title} ({post.meta.category}) -> {TARGET} "
                f"visible={visible_len(caption)} raw={len(caption)} buttons={len(post.buttons)}")
            bot.send_post(TARGET, caption, post.photo_url, post.buttons)
            mark_sent(con, post)
            return
        log("test send: no allowed post found")
        return

    if args.backfill is not None:
        pending = [p for p in posts[-args.backfill:] if not already_sent(con, p.mid)]
    else:
        pending = [p for p in posts if not already_sent(con, p.mid)]

    if not con.execute("SELECT 1 FROM sent LIMIT 1").fetchone() and args.backfill is None:
        bootstrap(con, posts)
        log(f"bootstrap: marked {len(posts)} existing posts as seen; waiting for new posts")
        return

    if args.limit:
        pending = pending[: args.limit]

    for post in pending:
        if episode_already_sent(con, post):
            log(f"skip {post.mid} duplicate episode {episode_key(post)}")
            mark_sent(con, post, mark_episode=False)
            continue
        caption = build_caption(post)
        if not post.meta.title:
            log(f"skip {post.mid} empty title")
            mark_sent(con, post, mark_episode=False)
            continue
        ok, reason = evaluate_post(con, post)
        if not ok:
            log(f"filter {post.mid} {reason} {post.meta.title} ({post.meta.category})")
            mark_filtered(con, post, reason)
            continue
        log(f"send {post.mid} {post.meta.title} ({post.meta.category}) -> {TARGET} "
            f"visible={visible_len(caption)} raw={len(caption)}")
        bot.send_post(TARGET, caption, post.photo_url, post.buttons)
        mark_sent(con, post)
        time.sleep(1.0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--token", default=os.getenv("TELEGRAM_BOT_TOKEN", ""))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--test-send", action="store_true")
    parser.add_argument("--backfill", type=int, default=None)
    parser.add_argument("--limit", type=int, default=0)
    args = parser.parse_args()

    log_filters()
    if args.dry_run:
        run_once(args, None, None)
        return
    if not args.token:
        print("ERROR: set TELEGRAM_BOT_TOKEN or pass --token", file=sys.stderr)
        sys.exit(2)

    bot = Bot(args.token)
    if args.test_send or args.backfill is not None:
        try:
            me = bot.api("getMe")
            log(f"bot: @{me.get('username')} id={me.get('id')}")
        except Exception as exc:
            print(f"ERROR: bot token invalid or api.telegram.org unreachable: {exc}",
                  file=sys.stderr)
            sys.exit(3)

    con = init_db()
    run_once(args, bot, con)
    if args.once or args.test_send:
        return

    log(f"loop: source=@{SOURCE} target={TARGET} interval={POLL_SECONDS}s")
    while True:
        time.sleep(POLL_SECONDS)
        try:
            run_once(args, bot, con)
        except Exception as exc:
            log("loop error:", exc)


if __name__ == "__main__":
    main()
