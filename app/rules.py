from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import ExtractedTitle, FilterDecision, TmdbMatch


NOISE_TOKENS = {
    "2160p",
    "1080p",
    "720p",
    "web",
    "webdl",
    "web-dl",
    "bluray",
    "bdrip",
    "hdr",
    "dv",
    "h264",
    "h265",
    "x264",
    "x265",
    "hevc",
    "aac",
    "ddp",
    "atmos",
    "nf",
    "netflix",
    "amzn",
    "disney",
    "hulu",
    "hbo",
}

PREFIX_PATTERN = re.compile(
    r"^\s*(?:[^\w\u4e00-\u9fff@#]+[\s]*)*(资源名称|名称|标题|片名|影视|电影|影片|剧集|电视剧|美剧|英剧|日剧|韩剧|国剧|陆剧|动漫|动画|纪录片|综艺)\s*[:：\-\s]+",
    flags=re.IGNORECASE,
)

LABELED_TITLE_PATTERN = re.compile(
    r"^\s*(?:[^\w\u4e00-\u9fff@#]+[\s]*)*(资源名称|名称|标题|片名|影视|电影|影片|剧集|电视剧|美剧|英剧|日剧|韩剧|国剧|陆剧|动漫|动画|纪录片|综艺)\s*[:：\-\s]+(.+)$",
    flags=re.IGNORECASE,
)

LABELED_YEAR_PATTERN = re.compile(r"(?:年份|上映|首播|发行)\s*[:：]\s*(19\d{2}|20\d{2})")

MEDIA_TYPE_TAGS = {
    "movie": "#电影",
    "tv": "#剧集",
}

GENRE_TAGS = {
    "Action": "#动作",
    "Adventure": "#冒险",
    "Animation": "#动画",
    "Comedy": "#喜剧",
    "Crime": "#犯罪",
    "Documentary": "#纪录片",
    "Drama": "#剧情",
    "Family": "#家庭",
    "Fantasy": "#奇幻",
    "History": "#历史",
    "Horror": "#恐怖",
    "Music": "#音乐",
    "Mystery": "#悬疑",
    "Romance": "#爱情",
    "Science Fiction": "#科幻",
    "TV Movie": "#电视电影",
    "Thriller": "#惊悚",
    "War": "#战争",
    "Western": "#西部",
    "Action & Adventure": "#动作冒险",
    "Kids": "#儿童",
    "News": "#新闻",
    "Reality": "#真人秀",
    "Sci-Fi & Fantasy": "#科幻奇幻",
    "Soap": "#肥皂剧",
    "Talk": "#脱口秀",
    "War & Politics": "#战争政治",
}

CATEGORY_ALIASES = {
    "国产": {"国产剧", "华语电影"},
    "国产剧": {"国产剧"},
    "华语": {"华语电影"},
    "华语电影": {"华语电影"},
    "欧美": {"欧美剧", "欧美电影"},
    "欧美剧": {"欧美剧"},
    "欧美电影": {"欧美电影"},
    "日韩": {"日韩剧", "日韩电影"},
    "日韩剧": {"日韩剧"},
    "日韩电影": {"日韩电影"},
    "日漫": {"日番"},
    "日番": {"日番"},
    "国漫": {"国漫"},
    "动漫": {"国漫", "日番", "动画电影"},
    "动画": {"国漫", "日番", "动画电影"},
    "动画电影": {"动画电影"},
    "综艺": {"综艺"},
    "纪录": {"纪录片"},
    "记录": {"纪录片"},
    "纪录片": {"纪录片"},
    "儿童": {"儿童"},
    "未分类": {"未分类"},
}


@dataclass(frozen=True)
class FilterConfig:
    blacklist_genres: list[str] = field(default_factory=list)
    blacklist_genre_ids: list[int] = field(default_factory=list)
    blacklist_region_categories: list[str] = field(default_factory=list)


def extract_title(text: str) -> ExtractedTitle:
    line = _labeled_title_line(text) or _first_useful_line(text)
    line = _strip_markdown_noise(line)
    tmdb_id = _extract_tmdb_id(text)
    media_type_hint = _extract_media_type_hint(text)
    line = re.sub(r"[\._\[\]\(\)【】]+", " ", line)
    line = re.sub(r"\s+", " ", line).strip()
    for _ in range(3):
        next_line = PREFIX_PATTERN.sub("", line)
        if next_line == line:
            break
        line = next_line
    line = re.sub(r"\s+", " ", line).strip()

    year_match = re.search(r"\b(19\d{2}|20\d{2})\b", line)
    year = int(year_match.group(1)) if year_match else _extract_labeled_year(text)
    if year_match:
        line = line[: year_match.start()].strip()

    parts = [part for part in line.split(" ") if part and part.lower() not in NOISE_TOKENS]
    name = " ".join(parts).strip(" -")
    return ExtractedTitle(name=name, year=year, tmdb_id=tmdb_id, media_type_hint=media_type_hint)


def _labeled_title_line(text: str) -> str | None:
    for raw_line in text.splitlines():
        match = LABELED_TITLE_PATTERN.match(raw_line.strip())
        if match:
            return match.group(2).strip()
    return None


def _extract_labeled_year(text: str) -> int | None:
    match = LABELED_YEAR_PATTERN.search(text)
    return int(match.group(1)) if match else None


def _strip_markdown_noise(text: str) -> str:
    return re.sub(r"[*`~]+", "", text)


def _extract_tmdb_id(text: str) -> int | None:
    match = re.search(r"(?:TMDB\s*(?:ID)?|tmdbid\s*=|\bID)\s*[:：=]\s*(\d+)", text, flags=re.IGNORECASE)
    if not match:
        return None
    return int(match.group(1))


def _extract_media_type_hint(text: str) -> str | None:
    labeled_type = re.search(r"(?:影视类型|类型)\s*[:：]\s*([^\n]+)", text)
    if labeled_type:
        value = labeled_type.group(1)
        if re.search(r"(电影|影片)", value):
            return "movie"
        if re.search(r"(剧集|电视剧|番剧|动漫|综艺|纪录片)", value):
            return "tv"
    first_line = _strip_markdown_noise(_first_useful_line(text))
    if re.search(r"(电影|影片|🎬)", first_line):
        return "movie"
    if re.search(r"(剧集|电视剧|番剧|动漫|📺)", first_line):
        return "tv"
    return None


def evaluate_blacklist(match: TmdbMatch, config: FilterConfig) -> FilterDecision:
    names = {name.casefold() for name in config.blacklist_genres}
    ids = set(config.blacklist_genre_ids)
    regions = _expanded_category_names(config.blacklist_region_categories + config.blacklist_genres)

    if match.region_category and match.region_category.casefold() in {region.casefold() for region in regions}:
        return FilterDecision(False, f"blacklisted_region:{match.region_category}")

    for genre in match.genres:
        if genre.name.casefold() in names:
            return FilterDecision(False, f"blacklisted_genre:{genre.name}")
        if genre.id in ids:
            return FilterDecision(False, f"blacklisted_genre_id:{genre.id}")

    return FilterDecision(True, "allowed")


def _expanded_category_names(values: list[str]) -> set[str]:
    names: set[str] = set()
    for raw_name in values:
        name = raw_name.strip()
        if not name:
            continue
        names.add(name)
        names.update(CATEGORY_ALIASES.get(name, set()))
    return names


def genre_tags(match: TmdbMatch) -> list[str]:
    tags: list[str] = []
    if match.region_category:
        tags.append("#" + match.region_category)
    media_tag = MEDIA_TYPE_TAGS.get(match.media_type)
    if media_tag:
        tags.append(media_tag)

    for genre in match.genres:
        tags.append(GENRE_TAGS.get(genre.name, "#" + re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", genre.name)))

    return _dedupe(tags)


def build_forward_header(match: TmdbMatch) -> str:
    original = match.original_title or match.title
    title_line = match.title if original == match.title else f"{match.title} / {original}"
    year = str(match.year) if match.year else "未知"
    link = f"https://www.themoviedb.org/{match.media_type}/{match.tmdb_id}"

    return "\n".join(
        [
            f"片名：{title_line}",
            f"年份：{year}",
            f"TMDB：{match.media_type}/{match.tmdb_id}",
            f"分类：{match.region_category or '未分类'}",
            f"链接：{link}",
        ]
    )


def _first_useful_line(text: str) -> str:
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith(("http://", "https://", "magnet:")):
            continue
        return line
    return text.strip()


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result
