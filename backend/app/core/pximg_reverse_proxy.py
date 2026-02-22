from __future__ import annotations

from urllib.parse import urlparse, urlunparse


PIXIV_CAT_I_HOST = "i.pixiv.cat"


def is_pximg_image_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
    except Exception:
        return False
    host = (parsed.hostname or "").strip().lower()
    if not host:
        return False
    # Pixiv original images are usually served from i.pximg.net (sometimes i-cf.pximg.net).
    if host == "i.pximg.net" or host == "i-cf.pximg.net":
        return True
    return host.endswith(".pximg.net") and host.startswith("i.")


def rewrite_pximg_to_pixiv_cat(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return url

    host = (parsed.hostname or "").strip().lower()
    if not host:
        return url
    if not is_pximg_image_url(url):
        return url

    # Preserve scheme/path/query/fragment. Replace netloc (and drop any port/userinfo if present).
    new = parsed._replace(netloc=PIXIV_CAT_I_HOST)
    return urlunparse(new)

