from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.images import Image


@dataclass(frozen=True, slots=True)
class AuthorListItem:
    user_id: int
    user_name: str | None
    count_images: int


async def list_authors(
    session: AsyncSession,
    *,
    limit: int,
    cursor: int | None = None,
    q: str | None = None,
) -> tuple[list[AuthorListItem], int | None]:
    limit_i = int(limit)
    if limit_i < 1:
        raise ValueError("limit must be >= 1")

    clauses: list[object] = [Image.status == 1, Image.user_id.is_not(None)]

    if cursor is not None:
        cursor_i = int(cursor)
        if cursor_i <= 0:
            raise ValueError("cursor must be > 0")
        clauses.append(Image.user_id > cursor_i)

    q_norm = (q or "").strip()
    if q_norm:
        clauses.append(Image.user_name.like(f"%{q_norm}%"))

    stmt = (
        select(
            Image.user_id,
            func.max(Image.user_name).label("user_name"),
            func.count(Image.id).label("count_images"),
        )
        .where(*clauses)
        .group_by(Image.user_id)
        .order_by(Image.user_id.asc())
        .limit(limit_i + 1)
    )

    rows = (await session.execute(stmt)).all()
    next_cursor: int | None = None

    if len(rows) > limit_i:
        rows = rows[:limit_i]
        next_cursor = int(rows[-1][0] or 0)

    items = [
        AuthorListItem(
            user_id=int(row[0]),
            user_name=str(row[1]) if row[1] is not None else None,
            count_images=int(row[2] or 0),
        )
        for row in rows
    ]

    return items, next_cursor

