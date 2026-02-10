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


async def pick_random_image(
    session: AsyncSession,
    *,
    r: float,
    r18: int = 0,
    r18_strict: bool = True,
) -> Image | None:
    r = float(r)
    if r < 0.0:
        r = 0.0
    if r >= 1.0:
        r = 0.999999999

    r18_clause = _r18_where_clause(r18=r18, r18_strict=r18_strict)
    clauses = [Image.status == 1]
    if r18_clause is not None:
        clauses.append(r18_clause)

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
