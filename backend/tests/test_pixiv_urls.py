from __future__ import annotations

import pytest

from app.core.pixiv_urls import parse_pixiv_original_url


def test_parse_pixiv_original_url_ok() -> None:
    u = "https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p0.jpg"
    parsed = parse_pixiv_original_url(u)
    assert parsed.illust_id == 12345678
    assert parsed.page_index == 0
    assert parsed.ext == "jpg"


def test_parse_pixiv_original_url_ignores_query_and_whitespace() -> None:
    u = "  https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678_p12.PNG?foo=bar  \n"
    parsed = parse_pixiv_original_url(u)
    assert parsed.illust_id == 12345678
    assert parsed.page_index == 12
    assert parsed.ext == "png"


def test_parse_pixiv_original_url_rejects_non_pximg() -> None:
    with pytest.raises(ValueError, match="unsupported host"):
        parse_pixiv_original_url("https://www.pixiv.net/artworks/12345678")


def test_parse_pixiv_original_url_rejects_wrong_pattern() -> None:
    with pytest.raises(ValueError, match="unsupported pixiv original url"):
        parse_pixiv_original_url("https://i.pximg.net/img-original/img/2023/01/01/00/00/00/12345678.jpg")

