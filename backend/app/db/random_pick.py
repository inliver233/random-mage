from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.images import Image


def _r18_where_clause(*, r18: int, r18_strict: bool) -> object | None:
    r18_i = int(r18)
    if r18_i not in {0, 1, 2}:
        raise ValueError("r18 must be 0, 1, or 2")

    if r18_i == 2:
        return None

    if r18_i == 1:
        return Image.x_restrict == 1

    if bool(r18_strict):
        return Image.x_restrict == 0

    return (Image.x_restrict == 0) | (Image.x_restrict.is_(None))


def _orientation_where_clause(*, orientation: int | None) -> object | None:
    if orientation is None:
        return None
    orientation_i = int(orientation)
    if orientation_i not in {1, 2, 3}:
        raise ValueError("orientation must be 1, 2, or 3")
    return Image.orientation == orientation_i


async def pick_random_image(
    session: AsyncSession,
    *,
    r: float,
    r18: int = 0,
    r18_strict: bool = True,
    orientation: int | None = None,
    min_width: int = 0,
    min_height: int = 0,
    min_pixels: int = 0,
) -> Image | None:
    r = float(r)
    if r < 0.0:
        r = 0.0
    if r >= 1.0:
        r = 0.999999999

    r18_clause = _r18_where_clause(r18=r18, r18_strict=r18_strict)
    orientation_clause = _orientation_where_clause(orientation=orientation)

    min_width_i = int(min_width)
    min_height_i = int(min_height)
    min_pixels_i = int(min_pixels)
    if min_width_i < 0 or min_height_i < 0 or min_pixels_i < 0:
        raise ValueError("min_* must be >= 0")

    clauses = [Image.status == 1]
    if r18_clause is not None:
        clauses.append(r18_clause)
    if orientation_clause is not None:
        clauses.append(orientation_clause)
    if min_width_i > 0:
        clauses.append(Image.width >= min_width_i)
    if min_height_i > 0:
        clauses.append(Image.height >= min_height_i)
    if min_pixels_i > 0:
        clauses.append((Image.width * Image.height) >= min_pixels_i)

    stmt = (
        select(Image)
        .where(*clauses, Image.random_key >= r)
        .order_by(Image.random_key.asc())
        .limit(1)
    )
    image = (await session.execute(stmt)).scalars().first()
    if image is not None:
        return image

    stmt2 = (
        select(Image)
        .where(*clauses)
        .order_by(Image.random_key.asc())
        .limit(1)
    )
    return (await session.execute(stmt2)).scalars().first()
