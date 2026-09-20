from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from operator import ge, gt, le, lt

import httpx
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import (
    Alert,
    AlertRule,
    ForecastPoint,
    ForecastRun,
    Mission,
    NotificationDelivery,
    TelemetryObservation,
    UserProfile,
)

COMPARATORS: dict[str, Callable[[float, float], bool]] = {">": gt, ">=": ge, "<": lt, "<=": le}


async def evaluate_alert_rules(session: AsyncSession, settings: Settings) -> int:
    now = datetime.now(UTC)
    rules = list(
        (
            await session.execute(
                select(AlertRule).where(AlertRule.enabled.is_(True)).order_by(AlertRule.created_at)
            )
        ).scalars()
    )
    created = 0
    for rule in rules:
        if rule.last_triggered_at and now - rule.last_triggered_at < timedelta(
            minutes=rule.cooldown_minutes
        ):
            continue
        result = await _evaluate_rule(session, rule, now)
        if result is None:
            continue
        title, message, payload, bucket = result
        dedupe_key = f"{rule.id}:{bucket}"
        alert_id = (
            await session.execute(
                insert(Alert)
                .values(
                    pilot_slug=rule.pilot_slug,
                    owner_user_id=rule.owner_user_id,
                    rule_id=rule.id,
                    kind=rule.kind,
                    title=title,
                    message=message,
                    severity="warning",
                    payload=payload,
                    dedupe_key=dedupe_key,
                )
                .on_conflict_do_nothing(index_elements=[Alert.dedupe_key])
                .returning(Alert.id)
            )
        ).scalar_one_or_none()
        if alert_id is None:
            continue
        rule.last_triggered_at = now
        created += 1
        if "email" in rule.channels:
            session.add(NotificationDelivery(alert_id=alert_id, channel="email", status="pending"))
    await session.commit()
    await deliver_pending_emails(session, settings)
    return created


async def _evaluate_rule(
    session: AsyncSession, rule: AlertRule, now: datetime
) -> tuple[str, str, dict[str, object], str] | None:
    comparator = COMPARATORS.get(rule.comparator or "")
    if (
        rule.kind == "forecast_threshold"
        and rule.metric
        and comparator
        and rule.threshold is not None
    ):
        latest_run = (
            await session.execute(
                select(ForecastRun)
                .where(ForecastRun.pilot_slug == rule.pilot_slug)
                .order_by(ForecastRun.fetched_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest_run is None:
            return None
        points = list(
            (
                await session.execute(
                    select(ForecastPoint).where(
                        ForecastPoint.forecast_run_id == latest_run.id,
                        ForecastPoint.valid_at >= now,
                        ForecastPoint.valid_at <= now + timedelta(hours=rule.lookahead_hours),
                    )
                )
            ).scalars()
        )
        matches = [
            (point, getattr(point, rule.metric))
            for point in points
            if getattr(point, rule.metric, None) is not None
            and comparator(float(getattr(point, rule.metric)), rule.threshold)
        ]
        if not matches:
            return None
        point, value = matches[0]
        return (
            rule.name,
            f"{rule.metric} is forecast at {value} for {point.valid_at.isoformat()}.",
            {"metric": rule.metric, "value": value, "valid_at": point.valid_at.isoformat()},
            point.valid_at.strftime("%Y%m%d%H"),
        )
    if rule.kind == "telemetry_stale" and comparator and rule.threshold is not None:
        observed_at = (
            await session.execute(
                select(func.max(TelemetryObservation.observed_at)).where(
                    TelemetryObservation.pilot_slug == rule.pilot_slug
                )
            )
        ).scalar_one_or_none()
        age_hours = (
            (now - observed_at.astimezone(UTC)).total_seconds() / 3600 if observed_at else 1e9
        )
        if not comparator(age_hours, rule.threshold):
            return None
        return (
            rule.name,
            f"Latest station observation is {age_hours:.1f} hours old.",
            {
                "age_hours": age_hours,
                "observed_at": observed_at.isoformat() if observed_at else None,
            },
            now.strftime("%Y%m%d%H"),
        )
    if rule.kind == "mission_reminder":
        mission = (
            await session.execute(
                select(Mission)
                .where(
                    Mission.owner_user_id == rule.owner_user_id,
                    Mission.pilot_slug == rule.pilot_slug,
                    Mission.status.in_(["draft", "planned"]),
                    Mission.scheduled_start >= now,
                    Mission.scheduled_start <= now + timedelta(hours=rule.lookahead_hours),
                )
                .order_by(Mission.scheduled_start)
                .limit(1)
            )
        ).scalar_one_or_none()
        if mission is None:
            return None
        return (
            rule.name,
            f"Mission '{mission.title}' starts at {mission.scheduled_start.isoformat()}.",
            {"mission_id": str(mission.id), "scheduled_start": mission.scheduled_start.isoformat()},
            str(mission.id),
        )
    return None


async def deliver_pending_emails(session: AsyncSession, settings: Settings) -> int:
    if not settings.resend_api_key:
        return 0
    deliveries = list(
        (
            await session.execute(
                select(NotificationDelivery, Alert, UserProfile)
                .join(Alert, Alert.id == NotificationDelivery.alert_id)
                .join(UserProfile, UserProfile.auth_user_id == Alert.owner_user_id)
                .where(
                    NotificationDelivery.status == "pending",
                    UserProfile.email.is_not(None),
                    (
                        NotificationDelivery.next_attempt_at.is_(None)
                        | (NotificationDelivery.next_attempt_at <= datetime.now(UTC))
                    ),
                )
                .limit(50)
            )
        ).all()
    )
    sent = 0
    async with httpx.AsyncClient(timeout=15) as client:
        for delivery, alert, profile in deliveries:
            if not profile.notification_preferences.get("email", True):
                delivery.status = "skipped"
                continue
            delivery.attempts += 1
            try:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": settings.email_from,
                        "to": [profile.email],
                        "subject": f"SolarShepherd · {alert.title}",
                        "text": f"{alert.message}\n\nOpen SolarShepherd to review the evidence.",
                    },
                )
            except httpx.HTTPError as exc:
                delivery.last_error = type(exc).__name__
                delivery.status = "failed" if delivery.attempts >= 3 else "pending"
                delivery.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
                continue
            if response.is_success:
                delivery.status = "sent"
                delivery.provider_id = response.json().get("id")
                delivery.sent_at = datetime.now(UTC)
                sent += 1
            else:
                delivery.last_error = f"Resend returned {response.status_code}"
                delivery.status = "failed" if delivery.attempts >= 3 else "pending"
                delivery.next_attempt_at = datetime.now(UTC) + timedelta(minutes=15)
    await session.commit()
    return sent
