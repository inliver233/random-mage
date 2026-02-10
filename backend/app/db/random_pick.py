from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.images import Image


async def pick_random_image(session: AsyncSession, *, r: float) -> Image | None:
    r = float(r)
    if r < 0.0:
        r = 0.0
    if r >= 1.0:
        r = 0.999999999

    stmt = (
        select(Image)
        .where(Image.status == 1, Image.random_key >= r)
        .order_by(Image.random_key.asc())
        .limit(1)
    )
    image = (await session.execute(stmt)).scalars().first()
    if image is not None:
        return image

    stmt2 = (
        select(Image)
        .where(Image.status == 1)
        .order_by(Image.random_key.asc())
        .limit(1)
    )
    return (await session.execute(stmt2)).scalars().first()

