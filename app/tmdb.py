from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import httpx

from app.category import classify_tmdb_match
from app.models import Genre, TmdbMatch


@dataclass
class TmdbClient:
    api_key: str
    language: str = "zh-CN"
    fallback_language: str = "en-US"
    base_url: str = "https://api.themoviedb.org/3"

    async def search(self, title: str, year: int | None = None) -> TmdbMatch | None:
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
            genres = await self._genres(client)
            params: dict[str, Any] = {
                "api_key": self.api_key,
                "language": self.language,
                "query": title,
                "include_adult": "false",
            }
            if year:
                params["year"] = year
            response = await client.get("/search/multi", params=params)
            response.raise_for_status()
            for item in response.json().get("results", []):
                match = parse_tmdb_search_result(item, genres)
                if match:
                    return match
        return None

    async def lookup(self, tmdb_id: int, media_type: str | None = None) -> TmdbMatch | None:
        media_types = [media_type] if media_type in {"movie", "tv"} else ["tv", "movie"]
        async with httpx.AsyncClient(base_url=self.base_url, timeout=20) as client:
            for candidate in media_types:
                response = await client.get(
                    f"/{candidate}/{tmdb_id}",
                    params={"api_key": self.api_key, "language": self.language},
                )
                if response.status_code == 404:
                    continue
                response.raise_for_status()
                match = parse_tmdb_detail_result(response.json(), str(candidate))
                if match:
                    return match
        return None

    async def _genres(self, client: httpx.AsyncClient) -> dict[int, str]:
        genre_map: dict[int, str] = {}
        for media_type in ("movie", "tv"):
            response = await client.get(
                f"/genre/{media_type}/list",
                params={"api_key": self.api_key, "language": self.language},
            )
            response.raise_for_status()
            for genre in response.json().get("genres", []):
                genre_map[int(genre["id"])] = str(genre["name"])
        return genre_map


def parse_tmdb_search_result(payload: dict[str, Any], genres: dict[int, str]) -> TmdbMatch | None:
    media_type = payload.get("media_type")
    if media_type not in {"movie", "tv"}:
        return None

    if media_type == "movie":
        title = payload.get("title") or payload.get("original_title") or ""
        original_title = payload.get("original_title")
        date = payload.get("release_date")
        origin_country = [str(code).upper() for code in payload.get("origin_country", [])]
    else:
        title = payload.get("name") or payload.get("original_name") or ""
        original_title = payload.get("original_name")
        date = payload.get("first_air_date")
        origin_country = [str(code).upper() for code in payload.get("origin_country", [])]

    if not title:
        return None

    match = TmdbMatch(
        tmdb_id=int(payload["id"]),
        media_type=str(media_type),
        title=str(title),
        original_title=str(original_title) if original_title else None,
        year=_year_from_date(str(date or "")),
        genres=[Genre(id=int(genre_id), name=genres.get(int(genre_id), str(genre_id))) for genre_id in payload.get("genre_ids", [])],
        original_language=str(payload.get("original_language") or "") or None,
        origin_country=origin_country,
    )
    return _with_region_category(match)


def parse_tmdb_detail_result(payload: dict[str, Any], media_type: str) -> TmdbMatch | None:
    if media_type not in {"movie", "tv"}:
        return None

    if media_type == "movie":
        title = payload.get("title") or payload.get("original_title") or ""
        original_title = payload.get("original_title")
        date = payload.get("release_date")
        origin_country = [
            str(country.get("iso_3166_1", "")).upper()
            for country in payload.get("production_countries", [])
            if country.get("iso_3166_1")
        ]
    else:
        title = payload.get("name") or payload.get("original_name") or ""
        original_title = payload.get("original_name")
        date = payload.get("first_air_date")
        origin_country = [str(code).upper() for code in payload.get("origin_country", [])]

    if not title:
        return None

    match = TmdbMatch(
        tmdb_id=int(payload["id"]),
        media_type=media_type,
        title=str(title),
        original_title=str(original_title) if original_title else None,
        year=_year_from_date(str(date or "")),
        genres=[
            Genre(id=int(genre["id"]), name=str(genre.get("name", genre["id"])))
            for genre in payload.get("genres", [])
            if "id" in genre
        ],
        original_language=str(payload.get("original_language") or "") or None,
        origin_country=origin_country,
    )
    return _with_region_category(match)


def _with_region_category(match: TmdbMatch) -> TmdbMatch:
    return TmdbMatch(
        tmdb_id=match.tmdb_id,
        media_type=match.media_type,
        title=match.title,
        original_title=match.original_title,
        year=match.year,
        genres=match.genres,
        original_language=match.original_language,
        origin_country=match.origin_country,
        region_category=classify_tmdb_match(match),
    )


def _year_from_date(value: str) -> int | None:
    if len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def classify_region(media_type: str, countries: list[str]) -> str:
    country_set = {country.upper() for country in countries}
    if media_type == "movie":
        if country_set & {"CN", "HK", "TW", "MO"}:
            return "华语电影"
        if country_set & {"JP", "KR"}:
            return "日韩电影"
        if country_set & {"US", "FR", "GB", "DE", "ES", "IT", "NL", "PT", "RU", "UK"}:
            return "欧美电影"
        return "其他电影"
    if country_set & {"CN", "HK", "TW", "MO"}:
        return "国产剧"
    if country_set & {"US", "FR", "GB", "DE", "ES", "IT", "NL", "PT", "RU", "UK"}:
        return "欧美剧"
    if country_set & {"JP", "KP", "KR", "TH", "IN", "SG"}:
        return "日韩剧"
    return "未分类"
