from __future__ import annotations

import random
import os
import math
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.responses import RedirectResponse

from app.core.errors import ApiError, ErrorCode
from app.core.http_stream import stream_url
from app.core.imgproxy import build_signed_processing_url, load_imgproxy_config_from_settings
from app.core.proxy_routing import select_proxy_uri_for_url
from app.core.runtime_settings import load_runtime_config
from app.core.time import iso_utc_ms
from app.db.images_mark import mark_image_failure, mark_image_ok
from app.db.tags_get import get_tag_names_for_image
from app.db.random_pick import pick_random_image
from app.db.session import create_sessionmaker
from app.jobs.enqueue import enqueue_opportunistic_hydrate_metadata

router = APIRouter()

_MAX_TAG_FILTERS = 50


def _as_nonneg_int(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, bool):
        return 0
    try:
        i = int(value)
    except Exception:
        return 0
    return i if i > 0 else 0


_DEFAULT_SCORE_WEIGHTS: dict[str, float] = {
    "bookmark": 4.0,
    "view": 0.5,
    "comment": 2.0,
    "pixels": 1.0,
    "bookmark_rate": 3.0,
}

_DEFAULT_RECOMMENDATION: dict[str, Any] = {
    "pick_mode": "weighted",
    "temperature": 1.0,
    "score_weights": dict(_DEFAULT_SCORE_WEIGHTS),
    "multipliers": {
        "ai": 1.0,
        "non_ai": 1.0,
        "unknown_ai": 1.0,
        "illust": 1.0,
        "manga": 1.0,
        "ugoira": 1.0,
        "unknown_illust_type": 1.0,
    },
}


def _as_float(value: Any, *, default: float) -> float:
    if value is None:
        return float(default)
    if isinstance(value, bool):
        return float(default)
    try:
        return float(value)
    except Exception:
        return float(default)


def _quality_score(image: Any, *, weights: dict[str, float] | None = None) -> float:
    w = weights or _DEFAULT_SCORE_WEIGHTS
    w_bookmark = float(w.get("bookmark", _DEFAULT_SCORE_WEIGHTS["bookmark"]))
    w_view = float(w.get("view", _DEFAULT_SCORE_WEIGHTS["view"]))
    w_comment = float(w.get("comment", _DEFAULT_SCORE_WEIGHTS["comment"]))
    w_pixels = float(w.get("pixels", _DEFAULT_SCORE_WEIGHTS["pixels"]))
    w_bookmark_rate = float(w.get("bookmark_rate", _DEFAULT_SCORE_WEIGHTS["bookmark_rate"]))

    bookmark_count = _as_nonneg_int(getattr(image, "bookmark_count", None))
    view_count = _as_nonneg_int(getattr(image, "view_count", None))
    comment_count = _as_nonneg_int(getattr(image, "comment_count", None))

    width = _as_nonneg_int(getattr(image, "width", None))
    height = _as_nonneg_int(getattr(image, "height", None))
    pixels = width * height if width > 0 and height > 0 else 0

    rate_term = 0.0
    if view_count > 0:
        bookmark_rate_per_mille = (float(bookmark_count) / float(view_count)) * 1000.0
        rate_term = math.log1p(max(0.0, bookmark_rate_per_mille))

    score = (
        float(w_bookmark) * math.log1p(bookmark_count)
        + float(w_view) * math.log1p(view_count)
        + float(w_comment) * math.log1p(comment_count)
        + float(w_pixels) * math.log1p(float(pixels) / 1_000_000.0)
        + float(w_bookmark_rate) * rate_term
    )
    return float(score)


@router.get("/random")
async def random_image(
    request: Request,
    format: str = "image",
    redirect: int = 0,
    attempts: int | None = None,
    seed: str | None = None,
    strategy: str | None = None,
    quality_samples: int | None = None,
    r18: int = 0,
    r18_strict: int | None = None,
    ai_type: str = "any",
    orientation: str = "any",
    min_width: int = 0,
    min_height: int = 0,
    min_pixels: int = 0,
    included_tags: list[str] | None = Query(default=None),
    excluded_tags: list[str] | None = Query(default=None),
    user_id: int | None = None,
    illust_id: int | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
) -> Any:
    if format not in {"image", "json", "simple_json"}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported format", status_code=400)
    if redirect not in {0, 1}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported redirect", status_code=400)
    seed_norm = (seed or "").strip()
    if seed is not None and not seed_norm:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported seed", status_code=400)
    if seed_norm and len(seed_norm) > 128:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported seed", status_code=400)

    ai_type_raw = (ai_type or "any").strip().lower()
    ai_type_i: int | None = None
    if ai_type_raw in {"", "any"}:
        ai_type_i = None
    elif ai_type_raw in {"0", "1"}:
        ai_type_i = int(ai_type_raw)
    else:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported ai_type", status_code=400)

    if r18 not in {0, 1, 2}:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported r18", status_code=400)
    orientation = (orientation or "").strip().lower()
    orientation_map = {"any": None, "portrait": 1, "landscape": 2, "square": 3}
    if orientation not in orientation_map:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported orientation", status_code=400)
    if min_width < 0 or min_height < 0 or min_pixels < 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported min_*", status_code=400)

    def _parse_tags(values: list[str] | None) -> list[str]:
        out: list[str] = []
        seen: set[str] = set()
        for raw in values or []:
            for part in str(raw).split("|"):
                name = part.strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                out.append(name)
        return out

    included = _parse_tags(included_tags)
    excluded = _parse_tags(excluded_tags)
    if len(included) > _MAX_TAG_FILTERS or len(excluded) > _MAX_TAG_FILTERS:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Too many tag filters", status_code=400)
    if user_id is not None and int(user_id) <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported user_id", status_code=400)
    if illust_id is not None and int(illust_id) <= 0:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported illust_id", status_code=400)

    def _normalize_iso_utc(value: str) -> str:
        raw = (value or "").strip()
        if not raw:
            raise ValueError("empty datetime")
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(timezone.utc).replace(microsecond=0)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    created_from_norm: str | None = None
    created_to_norm: str | None = None
    try:
        if created_from is not None:
            created_from_norm = _normalize_iso_utc(created_from)
        if created_to is not None:
            created_to_norm = _normalize_iso_utc(created_to)
    except Exception:
        raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported created_*", status_code=400)

    if created_from_norm is not None and created_to_norm is not None:
        if created_from_norm > created_to_norm:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="created_from > created_to", status_code=400)

    def _no_match_error() -> ApiError:
        applied_filters: dict[str, Any] = {
            "r18": r18,
            "r18_strict": int(r18_strict),
            "orientation": orientation,
            "min_width": int(min_width),
            "min_height": int(min_height),
            "min_pixels": int(min_pixels),
        }
        if included:
            applied_filters["included_tags"] = included
        if excluded:
            applied_filters["excluded_tags"] = excluded
        if user_id is not None:
            applied_filters["user_id"] = int(user_id)
        if illust_id is not None:
            applied_filters["illust_id"] = int(illust_id)
        if created_from_norm is not None:
            applied_filters["created_from"] = created_from_norm
        if created_to_norm is not None:
            applied_filters["created_to"] = created_to_norm

        suggestions: list[str] = ["运行元数据补全任务以提升元数据覆盖率"]
        if r18 == 0 and int(r18_strict) == 1:
            suggestions.append("将 r18_strict=0 以允许未知 x_restrict（冷启动阶段更容易命中）")
        if orientation != "any":
            suggestions.append("将 orientation=any（取消方向限制）")
        if int(min_width) > 0 or int(min_height) > 0 or int(min_pixels) > 0:
            suggestions.append("降低 min_width/min_height/min_pixels（放宽分辨率门槛）")
        if included:
            suggestions.append("放宽 included_tags（减少必须包含的标签）")
        if excluded:
            suggestions.append("放宽 excluded_tags（减少必须排除的标签）")
        if user_id is not None:
            suggestions.append("移除 user_id 过滤")
        if illust_id is not None:
            suggestions.append("移除 illust_id 过滤")
        if created_from_norm is not None or created_to_norm is not None:
            suggestions.append("扩大 created_from/created_to 时间范围")

        return ApiError(
            code=ErrorCode.NO_MATCH,
            message="没有匹配的图片。",
            status_code=404,
            details={"hints": {"applied_filters": applied_filters, "suggestions": suggestions}},
        )

    engine = request.app.state.engine
    Session = create_sessionmaker(engine)
    runtime = await load_runtime_config(engine)

    random_defaults = runtime.random_defaults if isinstance(runtime.random_defaults, dict) else {}

    attempts_source = "query"
    attempts_i = 3
    if attempts is not None:
        try:
            attempts_i = int(attempts)
        except Exception as exc:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported attempts", status_code=400) from exc
    else:
        raw = random_defaults.get("default_attempts")
        if raw is None:
            attempts_source = "fallback"
            attempts_i = 3
        else:
            attempts_source = "runtime"
            try:
                attempts_i = int(raw)
            except Exception:
                attempts_i = 3
    if attempts_i < 1 or attempts_i > 10:
        if attempts_source == "query":
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported attempts", status_code=400)
        attempts_source = "fallback"
        attempts_i = 3
    attempts = int(attempts_i)

    r18_strict_source = "query"
    r18_strict_i = 1
    if r18_strict is not None:
        try:
            r18_strict_i = int(r18_strict)
        except Exception as exc:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported r18_strict", status_code=400) from exc
    else:
        raw = random_defaults.get("default_r18_strict")
        if raw is None:
            r18_strict_source = "fallback"
            r18_strict_i = 1
        elif isinstance(raw, bool):
            r18_strict_source = "runtime"
            r18_strict_i = 1 if raw else 0
        else:
            r18_strict_source = "runtime"
            try:
                r18_strict_i = int(raw)
            except Exception:
                r18_strict_i = 1
    if r18_strict_i not in {0, 1}:
        if r18_strict_source == "query":
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported r18_strict", status_code=400)
        r18_strict_source = "fallback"
        r18_strict_i = 1
    r18_strict = int(r18_strict_i)

    fail_cooldown_source = "runtime"
    fail_cooldown_ms = random_defaults.get("fail_cooldown_ms")
    try:
        fail_cooldown_ms_i = int(fail_cooldown_ms) if fail_cooldown_ms is not None else None
    except Exception:
        fail_cooldown_ms_i = None

    if fail_cooldown_ms_i is None:
        fail_cooldown_source = "fallback"
        cooldown_s_raw = (os.environ.get("RANDOM_FAIL_COOLDOWN_SECONDS") or "600").strip()
        try:
            cooldown_s = int(cooldown_s_raw)
        except Exception:
            cooldown_s = 600
        cooldown_s = max(0, min(int(cooldown_s), 24 * 60 * 60))
        fail_cooldown_ms_i = int(cooldown_s) * 1000
    fail_cooldown_ms_i = max(0, min(int(fail_cooldown_ms_i), 24 * 60 * 60 * 1000))

    request_now = datetime.now(timezone.utc)
    fail_cooldown_before = (
        iso_utc_ms(request_now - timedelta(milliseconds=int(fail_cooldown_ms_i)))
        if int(fail_cooldown_ms_i) > 0
        else None
    )

    pick_kwargs: dict[str, Any] = {
        "r18": r18,
        "r18_strict": bool(r18_strict),
        "ai_type": ai_type_i,
        "orientation": orientation_map[orientation],
        "min_width": min_width,
        "min_height": min_height,
        "min_pixels": min_pixels,
        "included_tags": included,
        "excluded_tags": excluded,
        "user_id": user_id,
        "illust_id": illust_id,
        "created_from": created_from_norm,
        "created_to": created_to_norm,
        "fail_cooldown_before": fail_cooldown_before,
    }

    rng = random.Random(seed_norm) if seed_norm else random

    strategy_raw = (strategy or "").strip().lower()
    strategy_source = "query"
    if not strategy_raw:
        strategy_source = "runtime"
        strategy_raw = str(random_defaults.get("strategy") or "").strip().lower()
    if not strategy_raw:
        strategy_source = "fallback"
        strategy_raw = "quality"
    if strategy_raw not in {"quality", "random"}:
        if strategy_source == "query":
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported strategy", status_code=400)
        strategy_source = "fallback"
        strategy_raw = "quality"

    strategy_norm = strategy_raw

    quality_samples_i: int
    quality_samples_source = "query"
    if quality_samples is not None:
        try:
            quality_samples_i = int(quality_samples)
        except Exception as exc:
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported quality_samples", status_code=400) from exc
    else:
        raw = random_defaults.get("quality_samples")
        if raw is None:
            quality_samples_source = "fallback"
            quality_samples_i = 5
        else:
            quality_samples_source = "runtime"
            try:
                quality_samples_i = int(raw)
            except Exception:
                quality_samples_i = 5
    if quality_samples_i < 1 or quality_samples_i > 20:
        if quality_samples_source == "query":
            raise ApiError(code=ErrorCode.BAD_REQUEST, message="Unsupported quality_samples", status_code=400)
        quality_samples_source = "fallback"
        quality_samples_i = 5

    recommendation_raw = random_defaults.get("recommendation")
    recommendation_source = "fallback"
    recommendation_obj: dict[str, Any] = {}
    if isinstance(recommendation_raw, dict):
        recommendation_source = "runtime"
        recommendation_obj = dict(recommendation_raw)

    pick_mode_raw = str(recommendation_obj.get("pick_mode") or _DEFAULT_RECOMMENDATION["pick_mode"]).strip().lower()
    if pick_mode_raw not in {"best", "weighted"}:
        pick_mode_raw = str(_DEFAULT_RECOMMENDATION["pick_mode"])

    temperature_raw = _as_float(recommendation_obj.get("temperature"), default=float(_DEFAULT_RECOMMENDATION["temperature"]))
    temperature = float(max(0.05, min(float(temperature_raw), 100.0)))

    score_weights_raw = recommendation_obj.get("score_weights")
    score_weights_obj = score_weights_raw if isinstance(score_weights_raw, dict) else {}
    score_weights: dict[str, float] = {}
    for key, default_value in _DEFAULT_SCORE_WEIGHTS.items():
        v = _as_float(score_weights_obj.get(key), default=float(default_value))
        score_weights[key] = float(max(-100.0, min(float(v), 100.0)))

    multipliers_default = _DEFAULT_RECOMMENDATION["multipliers"]
    multipliers_raw = recommendation_obj.get("multipliers")
    multipliers_obj = multipliers_raw if isinstance(multipliers_raw, dict) else {}
    multipliers: dict[str, float] = {}
    for key, default_value in multipliers_default.items():
        v = _as_float(multipliers_obj.get(key), default=float(default_value))
        multipliers[key] = float(max(0.0, min(float(v), 100.0)))

    debug_base = {
        "attempts": int(attempts_i),
        "attempts_source": attempts_source,
        "r18_strict": int(r18_strict_i),
        "r18_strict_source": r18_strict_source,
        "fail_cooldown_ms": int(fail_cooldown_ms_i),
        "fail_cooldown_source": fail_cooldown_source,
        "strategy": strategy_norm,
        "strategy_source": strategy_source,
        "quality_samples": int(quality_samples_i),
        "quality_samples_source": quality_samples_source,
        "recommendation_source": recommendation_source,
    }

    async def _pick_with_strategy(
        *,
        session: Any,
        exclude_image_ids: list[int] | None = None,
    ) -> tuple[Any, dict[str, Any]] | tuple[None, dict[str, Any]]:
        if strategy_norm == "random":
            image = await pick_random_image(session, r=rng.random(), exclude_image_ids=exclude_image_ids, **pick_kwargs)
            if image is None:
                return None, {**debug_base, "attempts_used": 1, "picked_by": "random_key"}
            return image, {**debug_base, "attempts_used": 1, "picked_by": "random_key"}

        def _multiplier_for_image(image: Any) -> float:
            m = 1.0

            ai = getattr(image, "ai_type", None)
            if ai == 1:
                m *= float(multipliers.get("ai", 1.0))
            elif ai == 0:
                m *= float(multipliers.get("non_ai", 1.0))
            else:
                m *= float(multipliers.get("unknown_ai", 1.0))

            it = getattr(image, "illust_type", None)
            if it == 0:
                m *= float(multipliers.get("illust", 1.0))
            elif it == 1:
                m *= float(multipliers.get("manga", 1.0))
            elif it == 2:
                m *= float(multipliers.get("ugoira", 1.0))
            else:
                m *= float(multipliers.get("unknown_illust_type", 1.0))

            if not math.isfinite(float(m)) or float(m) <= 0.0:
                return 0.0
            return float(m)

        exclude_set: set[int] = set(int(x) for x in exclude_image_ids or [])
        drawn = 0
        accepted = 0

        candidates: list[tuple[Any, float, float, float]] = []
        max_draws = max(int(quality_samples_i) * 5, 20)

        for _ in range(int(max_draws)):
            image = await pick_random_image(
                session,
                r=rng.random(),
                exclude_image_ids=list(exclude_set),
                **pick_kwargs,
            )
            if image is None:
                break
            exclude_set.add(int(image.id))
            drawn += 1
            score = _quality_score(image, weights=score_weights)
            multiplier = _multiplier_for_image(image)
            if multiplier <= 0.0:
                continue

            logit = float(score) / float(temperature) + math.log(float(multiplier))
            candidates.append((image, float(score), float(multiplier), float(logit)))
            accepted += 1
            if accepted >= int(quality_samples_i):
                break

        if not candidates:
            return None, {
                **debug_base,
                "attempts_used": 1,
                "picked_by": "quality_weighted" if pick_mode_raw == "weighted" else "quality_best",
                "candidates_drawn": int(drawn),
                "candidates_accepted": int(accepted),
                "quality_pick_mode": pick_mode_raw,
                "quality_temperature": float(temperature),
            }

        if pick_mode_raw == "best":
            picked = max(candidates, key=lambda x: x[3])
            picked_by = "quality_best"
        else:
            max_logit = max(x[3] for x in candidates)
            weights = [math.exp(float(x[3]) - float(max_logit)) for x in candidates]
            total = float(sum(weights))
            if not math.isfinite(total) or total <= 0.0:
                picked = max(candidates, key=lambda x: x[3])
                picked_by = "quality_best"
            else:
                r = float(rng.random()) * total
                idx = 0
                for i, w in enumerate(weights):
                    r -= float(w)
                    if r <= 0:
                        idx = i
                        break
                picked = candidates[int(max(0, min(idx, len(candidates) - 1)))]
                picked_by = "quality_weighted"

        best_image, best_score, best_multiplier, _best_logit = picked

        return (
            best_image,
            {
                **debug_base,
                "attempts_used": 1,
                "picked_by": picked_by,
                "candidates_drawn": int(drawn),
                "candidates_accepted": int(accepted),
                "quality_pick_mode": pick_mode_raw,
                "quality_temperature": float(temperature),
                "quality_score": float(best_score),
                "quality_multiplier": float(best_multiplier),
            },
        )

    def _needs_opportunistic_hydrate(image: Any) -> bool:
        return (
            getattr(image, "width", None) is None
            or getattr(image, "height", None) is None
            or getattr(image, "x_restrict", None) is None
            or getattr(image, "ai_type", None) is None
            or getattr(image, "illust_type", None) is None
            or getattr(image, "user_id", None) is None
            or getattr(image, "bookmark_count", None) is None
            or getattr(image, "view_count", None) is None
            or getattr(image, "comment_count", None) is None
        )

    if format in {"json", "simple_json"} or (format == "image" and redirect == 1):
        tags: list[str] = []
        debug: dict[str, Any] = {}
        async with Session() as session:
            image, debug = await _pick_with_strategy(session=session)
            if image is None:
                raise _no_match_error()
            if format == "json":
                tags = await get_tag_names_for_image(session, image_id=image.id)

        if _needs_opportunistic_hydrate(image):
            try:
                await enqueue_opportunistic_hydrate_metadata(engine, illust_id=int(image.illust_id), reason="random")
            except Exception:
                pass

        if format == "image" and redirect == 1:
            return RedirectResponse(
                url=f"/i/{image.id}.{image.ext}",
                status_code=302,
                headers={"Cache-Control": "no-store"},
            )

        origin_url = None if runtime.hide_origin_url_in_public_json else image.original_url

        imgproxy_url = None
        try:
            cfg = load_imgproxy_config_from_settings(request.app.state.settings)
        except Exception:
            cfg = None
        if cfg is not None:
            try:
                if runtime.hide_origin_url_in_public_json:
                    base = str(getattr(request, "base_url", "") or "").rstrip("/")
                    source_url = f"{base}/i/{image.id}.{image.ext}"
                else:
                    source_url = str(image.original_url)
                imgproxy_url = build_signed_processing_url(cfg, source_url=source_url, extension=str(image.ext))
            except Exception:
                imgproxy_url = None

        if format == "simple_json":
            return {
                "ok": True,
                "code": "OK",
                "request_id": getattr(getattr(request, "state", None), "request_id", None) or "req_unknown",
                "data": {
                    "image": {
                        "id": str(image.id),
                        "illust_id": str(image.illust_id),
                        "page_index": image.page_index,
                        "ext": image.ext,
                        "width": image.width,
                        "height": image.height,
                        "x_restrict": image.x_restrict,
                        "ai_type": image.ai_type,
                        "illust_type": getattr(image, "illust_type", None),
                        "bookmark_count": getattr(image, "bookmark_count", None),
                        "view_count": getattr(image, "view_count", None),
                        "comment_count": getattr(image, "comment_count", None),
                    },
                    "urls": {
                        "proxy": f"/i/{image.id}.{image.ext}",
                        "origin": origin_url,
                        "imgproxy": imgproxy_url,
                    },
                    "debug": {
                        **debug,
                    },
                },
            }

        return {
            "ok": True,
            "code": "OK",
            "request_id": getattr(getattr(request, "state", None), "request_id", None) or "req_unknown",
            "data": {
                "image": {
                    "id": str(image.id),
                    "illust_id": str(image.illust_id),
                    "page_index": image.page_index,
                    "ext": image.ext,
                    "width": image.width,
                    "height": image.height,
                    "x_restrict": image.x_restrict,
                    "ai_type": image.ai_type,
                    "illust_type": getattr(image, "illust_type", None),
                    "bookmark_count": getattr(image, "bookmark_count", None),
                    "view_count": getattr(image, "view_count", None),
                    "comment_count": getattr(image, "comment_count", None),
                    "user": {
                        "id": str(image.user_id) if image.user_id is not None else None,
                        "name": image.user_name,
                    },
                    "title": image.title,
                    "created_at_pixiv": image.created_at_pixiv,
                },
                "tags": tags,
                "urls": {
                    "proxy": f"/i/{image.id}.{image.ext}",
                    "origin": origin_url,
                    "imgproxy": imgproxy_url,
                    "legacy_single": f"/{image.illust_id}.{image.ext}",
                    "legacy_multi": f"/{image.illust_id}-{image.page_index + 1}.{image.ext}",
                },
                "debug": {
                    **debug,
                },
            },
        }

    tried_ids: set[int] = set()
    last_error: ApiError | None = None
    attempts_i = int(attempts)
    runtime_stream = runtime

    for _ in range(attempts_i):
        async with Session() as session:
            image, _debug = await _pick_with_strategy(session=session, exclude_image_ids=list(tried_ids))
            if image is None:
                break
            image_id = int(image.id)
            origin_url = str(image.original_url)
            illust_id_for_hydrate = int(image.illust_id)
            needs_hydrate = _needs_opportunistic_hydrate(image)

        transport = getattr(request.app.state, "httpx_transport", None)
        proxy_uri = None
        picked = await select_proxy_uri_for_url(
            engine,
            request.app.state.settings,
            runtime_stream,
            url=origin_url,
        )
        if picked is not None:
            proxy_uri = picked.uri
        try:
            resp = await stream_url(
                origin_url,
                transport=transport,
                proxy=proxy_uri,
                cache_control="no-store",
                range_header=request.headers.get("Range"),
            )
            await mark_image_ok(engine, image_id=image_id, now=iso_utc_ms())
            if needs_hydrate:
                try:
                    await enqueue_opportunistic_hydrate_metadata(
                        engine,
                        illust_id=illust_id_for_hydrate,
                        reason="random",
                    )
                except Exception:
                    pass
            return resp
        except ApiError as exc:
            if exc.code in {
                ErrorCode.UPSTREAM_STREAM_ERROR,
                ErrorCode.UPSTREAM_403,
                ErrorCode.UPSTREAM_404,
                ErrorCode.UPSTREAM_RATE_LIMIT,
            }:
                await mark_image_failure(
                    engine,
                    image_id=image_id,
                    now=iso_utc_ms(),
                    error_code=exc.code.value,
                    error_message=exc.message,
                )
                tried_ids.add(image_id)
                last_error = exc
                continue
            raise

    if last_error is None:
        raise _no_match_error()

    raise ApiError(
        code=ErrorCode.UPSTREAM_STREAM_ERROR,
        message="多次尝试后上游请求仍失败。",
        status_code=502,
        details={
            "attempts_used": len(tried_ids),
            "last_upstream_code": last_error.code.value,
        },
    )
