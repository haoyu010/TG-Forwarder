from __future__ import annotations

from dataclasses import dataclass

from app.models import TmdbMatch


@dataclass(frozen=True)
class CategoryRule:
    name: str
    genre_ids: tuple[int, ...] = ()
    original_language: tuple[str, ...] = ()
    origin_country: tuple[str, ...] = ()
    release_year: str | None = None


MOVIE_RULES = (
    CategoryRule(name="动画电影", genre_ids=(16,)),
    CategoryRule(name="华语电影", original_language=("zh", "cn", "bo", "za")),
    CategoryRule(name="日韩电影", original_language=("ja", "ko")),
    CategoryRule(name="欧美电影", original_language=("en", "fr", "de", "es", "it", "pt", "nl", "ru")),
    CategoryRule(name="其他电影"),
)

TV_RULES = (
    CategoryRule(name="国漫", genre_ids=(16,), origin_country=("CN", "TW", "HK")),
    CategoryRule(name="日番", genre_ids=(16,), origin_country=("JP",)),
    CategoryRule(name="纪录片", genre_ids=(99,)),
    CategoryRule(name="儿童", genre_ids=(10762,)),
    CategoryRule(name="综艺", genre_ids=(10764, 10767)),
    CategoryRule(name="国产剧", origin_country=("CN", "TW", "HK")),
    CategoryRule(name="欧美剧", origin_country=("US", "FR", "GB", "DE", "ES", "IT", "NL", "PT", "RU", "UK")),
    CategoryRule(name="日韩剧", origin_country=("JP", "KP", "KR", "TH", "IN", "SG")),
    CategoryRule(name="未分类"),
)


def classify_tmdb_match(match: TmdbMatch) -> str:
    if match.media_type == "movie":
        return _classify(MOVIE_RULES, match)
    if match.media_type == "tv":
        return _classify(TV_RULES, match)
    return "未分类"


def _classify(rules: tuple[CategoryRule, ...], match: TmdbMatch) -> str:
    fallback = "未分类"
    ordered_rules = sorted(enumerate(rules), key=lambda item: (-_specificity(item[1]), item[0]))

    for _, rule in ordered_rules:
        if _specificity(rule) == 0:
            fallback = rule.name
            continue
        if _matches(rule, match):
            return rule.name

    return fallback


def _specificity(rule: CategoryRule) -> int:
    return sum(
        bool(value)
        for value in (
            rule.genre_ids,
            rule.original_language,
            rule.origin_country,
            rule.release_year,
        )
    )


def _matches(rule: CategoryRule, match: TmdbMatch) -> bool:
    if rule.genre_ids and not set(rule.genre_ids).intersection({genre.id for genre in match.genres}):
        return False
    if rule.original_language and (match.original_language or "").casefold() not in {
        language.casefold() for language in rule.original_language
    }:
        return False
    if rule.origin_country and not {country.upper() for country in match.origin_country or []}.intersection(
        {country.upper() for country in rule.origin_country}
    ):
        return False
    if rule.release_year and not _matches_year(rule.release_year, match.year):
        return False
    return True


def _matches_year(rule: str, year: int | None) -> bool:
    if year is None:
        return False
    if "-" not in rule:
        return year == int(rule)
    start, end = rule.split("-", 1)
    return int(start) <= year <= int(end)
