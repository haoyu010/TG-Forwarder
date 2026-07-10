from fastapi.testclient import TestClient

from app.api import create_app
from app.config import AppConfig, DashboardConfig, FilterSettings, TelegramConfig, TmdbConfig
from app.models import Genre, PipelineEvent, TmdbMatch
from app.storage import EventRepository
from app.tmdb import classify_region, parse_tmdb_detail_result, parse_tmdb_search_result


class RuntimeSettingsWorker:
    running = True

    def __init__(self):
        self.applied_filters = None
        self.applied_target_channel = None

    def apply_runtime_settings(self, filters, target_channel):
        self.applied_filters = filters
        self.applied_target_channel = target_channel


def test_parse_tmdb_search_result_prefers_title_year_and_genres():
    payload = {
        "id": 693134,
        "media_type": "movie",
        "title": "沙丘2",
        "original_title": "Dune: Part Two",
        "release_date": "2024-02-27",
        "original_language": "en",
        "genre_ids": [28, 878],
        "origin_country": ["US"],
    }
    genres = {28: "Action", 878: "Science Fiction"}

    match = parse_tmdb_search_result(payload, genres)

    assert match.tmdb_id == 693134
    assert match.media_type == "movie"
    assert match.title == "沙丘2"
    assert match.original_title == "Dune: Part Two"
    assert match.year == 2024
    assert match.region_category == "\u6b27\u7f8e\u7535\u5f71"
    assert match.genres == [Genre(id=28, name="Action"), Genre(id=878, name="Science Fiction")]


def test_parse_tmdb_search_result_supports_tv_fields():
    payload = {
        "id": 123,
        "media_type": "tv",
        "name": "绝命毒师",
        "original_name": "Breaking Bad",
        "first_air_date": "2008-01-20",
        "original_language": "en",
        "genre_ids": [18],
        "origin_country": ["US"],
    }

    match = parse_tmdb_search_result(payload, {18: "Drama"})

    assert match.media_type == "tv"
    assert match.title == "绝命毒师"
    assert match.original_title == "Breaking Bad"
    assert match.year == 2008
    assert match.region_category == "\u6b27\u7f8e\u5267"


def test_parse_tmdb_detail_result_supports_tv_details_from_id_lookup():
    payload = {
        "id": 239901,
        "name": "云秀行",
        "original_name": "云秀行",
        "first_air_date": "2026-01-01",
        "original_language": "zh",
        "origin_country": ["CN"],
        "genres": [{"id": 18, "name": "剧情"}, {"id": 35, "name": "喜剧"}],
    }

    match = parse_tmdb_detail_result(payload, "tv")

    assert match.tmdb_id == 239901
    assert match.media_type == "tv"
    assert match.title == "云秀行"
    assert match.year == 2026
    assert match.region_category == "国产剧"
    assert match.genres == [Genre(id=18, name="剧情"), Genre(id=35, name="喜剧")]


def test_parse_tmdb_detail_result_supports_movie_details_from_id_lookup():
    payload = {
        "id": 1726224,
        "title": "入凶宅",
        "original_title": "入凶宅",
        "release_date": "2026-01-01",
        "original_language": "zh",
        "production_countries": [{"iso_3166_1": "CN", "name": "China"}],
        "genres": [{"id": 9648, "name": "悬疑"}],
    }

    match = parse_tmdb_detail_result(payload, "movie")

    assert match.tmdb_id == 1726224
    assert match.media_type == "movie"
    assert match.title == "入凶宅"
    assert match.year == 2026
    assert match.region_category == "华语电影"


def test_parse_tmdb_search_result_ignores_people():
    assert parse_tmdb_search_result({"media_type": "person"}, {}) is None


def test_classify_region_common_categories():
    assert classify_region("tv", ["CN"]) == "\u56fd\u4ea7\u5267"
    assert classify_region("tv", ["KR"]) == "\u65e5\u97e9\u5267"
    assert classify_region("tv", ["JP"]) == "\u65e5\u97e9\u5267"
    assert classify_region("movie", ["US"]) == "\u6b27\u7f8e\u7535\u5f71"


def test_parse_tmdb_search_result_uses_organizer_style_specific_categories():
    chinese_animation = parse_tmdb_search_result(
        {
            "id": 1,
            "media_type": "tv",
            "name": "\u4e2d\u56fd\u5947\u8c2d",
            "first_air_date": "2023-01-01",
            "original_language": "zh",
            "genre_ids": [16],
            "origin_country": ["CN"],
        },
        {16: "Animation"},
    )
    korean_drama = parse_tmdb_search_result(
        {
            "id": 2,
            "media_type": "tv",
            "name": "\u5c11\u5e74\u6cd5\u5ead",
            "first_air_date": "2022-01-01",
            "original_language": "ko",
            "genre_ids": [18],
            "origin_country": ["KR"],
        },
        {18: "Drama"},
    )
    animation_movie = parse_tmdb_search_result(
        {
            "id": 3,
            "media_type": "movie",
            "title": "\u54ea\u5412\u4e4b\u9b54\u7ae5\u95f9\u6d77",
            "release_date": "2025-01-29",
            "original_language": "zh",
            "genre_ids": [16],
        },
        {16: "Animation"},
    )

    assert chinese_animation.region_category == "\u56fd\u6f2b"
    assert korean_drama.region_category == "\u65e5\u97e9\u5267"
    assert animation_movie.region_category == "\u52a8\u753b\u7535\u5f71"


def test_api_returns_status_records_and_preview(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    config = AppConfig(
        telegram=TelegramConfig(
            api_id=1,
            api_hash="hash",
            source_channels=["@source"],
            target_channel="@target",
        ),
        tmdb=TmdbConfig(api_key="tmdb"),
        filters=FilterSettings(blacklist_genres=["Horror"], blacklist_genre_ids=[99]),
        dashboard=DashboardConfig(port=8000),
        database_path=str(tmp_path / "events.sqlite3"),
    )
    app = create_app(config=config, repository=repo, worker=None)

    with TestClient(app) as client:
        match = TmdbMatch(
            tmdb_id=693134,
            media_type="movie",
            title="沙丘2",
            original_title="Dune: Part Two",
            year=2024,
            genres=[Genre(id=28, name="Action")],
        )
        import anyio

        anyio.run(
            repo.record_event,
            PipelineEvent(
                telegram_message_id=1,
                source_channel="@source",
                title="Dune Part Two 2024",
                tmdb_match=match,
                decision="forwarded",
                reason="allowed",
            ),
        )

        status = client.get("/api/status").json()
        records = client.get("/api/records").json()
        settings = client.get("/api/settings").json()

    assert status["telegram"]["source_count"] == 1
    assert status["telegram"]["target_channel"] == "@target"
    assert status["tmdb"]["configured"] is True
    assert status["stats"]["forwarded"] == 1
    assert records["items"][0]["tmdb_id"] == 693134
    assert settings["filters"]["blacklist_genres"] == ["Horror"]


def test_api_updates_settings_and_persists_config_yaml(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    config_path = tmp_path / "config.yaml"
    config = AppConfig(
        telegram=TelegramConfig(
            api_id=1,
            api_hash="hash",
            source_channels=["@old"],
            target_channel="@old_target",
        ),
        tmdb=TmdbConfig(api_key="tmdb"),
        filters=FilterSettings(blacklist_genres=["Horror"], blacklist_genre_ids=[99]),
        dashboard=DashboardConfig(port=8000),
        database_path=str(tmp_path / "events.sqlite3"),
    )
    app = create_app(config=config, repository=repo, worker=None, config_path=config_path)

    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "telegram": {
                    "source_channels": ["@movies", "-100123456"],
                    "target_channel": "@target",
                },
                "filters": {
                    "blacklist_region_categories": ["国产剧", "欧美剧"],
                    "blacklist_genres": ["Reality", "Talk"],
                    "blacklist_genre_ids": [10764, 10767],
                },
            },
        )
        settings = client.get("/api/settings").json()
        status = client.get("/api/status").json()

    assert response.status_code == 200
    assert settings["telegram"]["source_channels"] == ["@movies", "-100123456"]
    assert settings["telegram"]["target_channel"] == "@target"
    assert settings["filters"]["blacklist_region_categories"] == ["国产剧", "欧美剧"]
    assert settings["filters"]["blacklist_genre_ids"] == [10764, 10767]
    assert status["telegram"]["source_count"] == 2
    text = config_path.read_text(encoding="utf-8")
    assert "@movies" in text
    assert "TELEGRAM_API_HASH" not in text


def test_api_applies_updated_filters_to_running_worker(tmp_path):
    repo = EventRepository(tmp_path / "events.sqlite3")
    config_path = tmp_path / "config.yaml"
    worker = RuntimeSettingsWorker()
    config = AppConfig(
        telegram=TelegramConfig(
            api_id=1,
            api_hash="hash",
            source_channels=["@old"],
            target_channel="@old_target",
        ),
        tmdb=TmdbConfig(api_key="tmdb"),
        filters=FilterSettings(),
        dashboard=DashboardConfig(port=8000),
        database_path=str(tmp_path / "events.sqlite3"),
    )
    app = create_app(config=config, repository=repo, worker=worker, config_path=config_path)

    with TestClient(app) as client:
        response = client.put(
            "/api/settings",
            json={
                "telegram": {
                    "source_channels": ["@oneonefivewpfx"],
                    "target_channel": "@xiaotiancaixu",
                },
                "filters": {
                    "blacklist_region_categories": ["日韩剧"],
                    "blacklist_genres": ["真人秀"],
                    "blacklist_genre_ids": [99],
                },
            },
        )

    assert response.status_code == 200
    assert worker.applied_target_channel == "@xiaotiancaixu"
    assert worker.applied_filters.blacklist_region_categories == ["日韩剧"]
