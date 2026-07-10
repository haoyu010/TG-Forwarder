from app.models import Genre, TmdbMatch
from app.rules import (
    FilterConfig,
    build_forward_header,
    evaluate_blacklist,
    extract_title,
    genre_tags,
)


def test_extract_title_keeps_name_and_year_from_noisy_release_line():
    title = extract_title("Dune.Part.Two.2024.2160p.WEB-DL.H265\\n大小 18GB")

    assert title.name == "Dune Part Two"
    assert title.year == 2024


def test_extract_title_uses_first_useful_line():
    title = extract_title("\n\n资源名称：沙丘2 2024 1080p\n链接：https://example.invalid")

    assert title.name == "沙丘2"
    assert title.year == 2024


def test_extract_title_removes_media_category_prefixes():
    title = extract_title("剧集 少年法庭 2022 NF 1080p")

    assert title.name == "少年法庭"
    assert title.year == 2022


def test_extract_title_removes_bracketed_media_category_prefixes():
    title = extract_title("【剧集】少年法庭 2022 NF 1080p")

    assert title.name == "少年法庭"
    assert title.year == 2022


def test_extract_title_removes_common_chinese_noise_prefixes():
    title = extract_title("电影：沙丘2 Dune Part Two 2024 2160p")

    assert title.name == "沙丘2 Dune Part Two"
    assert title.year == 2024


def test_extract_title_handles_emoji_prefix_and_markdown_bold_tv_title():
    title = extract_title("📺 电视剧：**云秀行 (2026) 更新至36集 4K**\n🍿 TMDB ID：239901")

    assert title.name == "云秀行"
    assert title.year == 2026
    assert title.tmdb_id == 239901
    assert title.media_type_hint == "tv"


def test_extract_title_handles_emoji_prefix_and_markdown_bold_movie_title():
    title = extract_title("🎬 电影：**入凶宅 (2026) 4K HDR10**\n🍿 TMDB ID：1726224")

    assert title.name == "入凶宅"
    assert title.year == 2026
    assert title.tmdb_id == 1726224
    assert title.media_type_hint == "movie"


def test_evaluate_blacklist_matches_genre_name_case_insensitively():
    match = TmdbMatch(
        tmdb_id=693134,
        media_type="movie",
        title="Dune: Part Two",
        original_title="Dune: Part Two",
        year=2024,
        genres=[Genre(id=27, name="Horror")],
    )

    decision = evaluate_blacklist(match, FilterConfig(blacklist_genres=["horror"]))

    assert decision.allowed is False
    assert decision.reason == "blacklisted_genre:Horror"


def test_evaluate_blacklist_matches_genre_id():
    match = TmdbMatch(
        tmdb_id=1,
        media_type="tv",
        title="Planet Earth",
        original_title="Planet Earth",
        year=2006,
        genres=[Genre(id=99, name="Documentary")],
    )

    decision = evaluate_blacklist(match, FilterConfig(blacklist_genre_ids=[99]))

    assert decision.allowed is False
    assert decision.reason == "blacklisted_genre_id:99"


def test_evaluate_blacklist_matches_region_category():
    match = TmdbMatch(
        tmdb_id=112833,
        media_type="tv",
        title="\u5c11\u5e74\u6cd5\u5ead",
        original_title="Juvenile Justice",
        year=2022,
        genres=[Genre(id=18, name="Drama")],
        origin_country=["KR"],
        region_category="\u97e9\u5267",
    )

    decision = evaluate_blacklist(match, FilterConfig(blacklist_region_categories=["\u97e9\u5267"]))

    assert decision.allowed is False
    assert decision.reason == "blacklisted_region:\u97e9\u5267"


def test_evaluate_blacklist_treats_common_category_aliases_as_region_blacklist():
    match = TmdbMatch(
        tmdb_id=1,
        media_type="tv",
        title="\u6b27\u7f8e\u5267\u793a\u4f8b",
        original_title="Example",
        year=2024,
        genres=[Genre(id=18, name="Drama")],
        region_category="\u6b27\u7f8e\u5267",
    )

    decision = evaluate_blacklist(match, FilterConfig(blacklist_genres=["\u6b27\u7f8e"]))

    assert decision.allowed is False
    assert decision.reason == "blacklisted_region:\u6b27\u7f8e\u5267"


def test_build_forward_header_includes_tmdb_number_category_and_link_without_tag_line():
    match = TmdbMatch(
        tmdb_id=693134,
        media_type="movie",
        title="沙丘2",
        original_title="Dune: Part Two",
        year=2024,
        genres=[Genre(id=28, name="Action"), Genre(id=878, name="Science Fiction")],
        region_category="\u6b27\u7f8e\u7535\u5f71",
    )

    header = build_forward_header(match)

    assert "#\u6b27\u7f8e\u7535\u5f71" not in header
    assert "#电影" not in header
    assert "#动作" not in header
    assert "#科幻" not in header
    assert "片名：沙丘2 / Dune: Part Two" in header
    assert "年份：2024" in header
    assert "TMDB：movie/693134" in header
    assert "分类：\u6b27\u7f8e\u7535\u5f71" in header
    assert "https://www.themoviedb.org/movie/693134" in header


def test_genre_tags_falls_back_to_normalized_genre_names():
    match = TmdbMatch(
        tmdb_id=2,
        media_type="tv",
        title="Example",
        original_title="Example",
        year=None,
        genres=[Genre(id=12345, name="Made For TV")],
    )

    assert genre_tags(match) == ["#剧集", "#MadeForTV"]
