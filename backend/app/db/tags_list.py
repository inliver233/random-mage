from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.image_tags import ImageTag
from app.db.models.images import Image
from app.db.models.tags import Tag


@dataclass(frozen=True, slots=True)
class TagListItem:
    id: int
    name: str
    translated_name: str | None
    count_images: int


async def list_tags(
    session: AsyncSession,
    *,
    limit: int,
    cursor: str | None = None,
    q: str | None = None,
) -> tuple[list[TagListItem], str | None]:
    limit_i = int(limit)
    if limit_i < 1:
        raise ValueError("limit must be >= 1")

    cursor_name = (cursor or "").strip()
    cursor_name = cursor_name if cursor_name else ""

    q_norm = (q or "").strip()

    stmt = (
        select(
            Tag.id,
            Tag.name,
            Tag.translated_name,
            func.count(distinct(ImageTag.image_id)).label("count_images"),
        )
        .join(ImageTag, ImageTag.tag_id == Tag.id)
        .join(Image, Image.id == ImageTag.image_id)
        .where(Image.status == 1)
    )

    if q_norm:
        stmt = stmt.where(Tag.name.like(f"%{q_norm}%"))
    if cursor_name:
        stmt = stmt.where(Tag.name > cursor_name)

    stmt = stmt.group_by(Tag.id).order_by(Tag.name.asc()).limit(limit_i + 1)

    rows = (await session.execute(stmt)).all()
    next_cursor: str | None = None

    if len(rows) > limit_i:
        rows = rows[:limit_i]
        next_cursor = str(rows[-1][1] or "")

    items = [
        TagListItem(
            id=int(row[0]),
            name=str(row[1]),
            translated_name=str(row[2]) if row[2] is not None else None,
            count_images=int(row[3] or 0),
        )
        for row in rows
    ]

    return items, next_cursor

