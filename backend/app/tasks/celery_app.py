from celery import Celery
from celery.schedules import crontab

from app.config import get_settings

settings = get_settings()
celery_app = Celery(
    "solarshepherd",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.tasks.jobs"],
)
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    broker_connection_retry_on_startup=False,
    broker_connection_max_retries=1,
    broker_connection_timeout=1.0,
    task_publish_retry=False,
    task_publish_retry_policy={"max_retries": 0},
    beat_schedule={
        "conduit-hourly": {
            "task": "app.tasks.jobs.run_conduit_ingestion",
            "schedule": crontab(minute=8),
        },
        "satellite-daily": {
            "task": "app.tasks.jobs.run_satellite_ingestion",
            "schedule": crontab(hour=2, minute=20),
            "args": ("jkuat",),
        },
        "satellite-garissa-daily": {
            "task": "app.tasks.jobs.run_satellite_ingestion",
            "schedule": crontab(hour=2, minute=30),
            "args": ("garissa",),
        },
        "satellite-lodwar-daily": {
            "task": "app.tasks.jobs.run_satellite_ingestion",
            "schedule": crontab(hour=2, minute=40),
            "args": ("lodwar",),
        },
        "forecast-every-three-hours": {
            "task": "app.tasks.jobs.run_forecast_ingestion",
            "schedule": crontab(minute=18, hour="*/3"),
            "args": ("jkuat",),
        },
        "forecast-garissa-every-three-hours": {
            "task": "app.tasks.jobs.run_forecast_ingestion",
            "schedule": crontab(minute=23, hour="*/3"),
            "args": ("garissa",),
        },
        "forecast-lodwar-every-three-hours": {
            "task": "app.tasks.jobs.run_forecast_ingestion",
            "schedule": crontab(minute=28, hour="*/3"),
            "args": ("lodwar",),
        },
        "public-observations-every-fifteen-minutes": {
            "task": "app.tasks.jobs.run_public_observation_ingestion",
            "schedule": crontab(minute="*/15"),
        },
        "osm-weekly": {
            "task": "app.tasks.jobs.run_osm_ingestion",
            "schedule": crontab(day_of_week="monday", hour=3, minute=10),
            "args": ("jkuat",),
        },
        "osm-garissa-weekly": {
            "task": "app.tasks.jobs.run_osm_ingestion",
            "schedule": crontab(day_of_week="monday", hour=3, minute=20),
            "args": ("garissa",),
        },
        "osm-lodwar-weekly": {
            "task": "app.tasks.jobs.run_osm_ingestion",
            "schedule": crontab(day_of_week="monday", hour=3, minute=30),
            "args": ("lodwar",),
        },
        "worker-heartbeat": {
            "task": "app.tasks.jobs.worker_heartbeat",
            "schedule": 60.0,
        },
        "evaluate-user-alerts": {
            "task": "app.tasks.jobs.evaluate_alerts",
            "schedule": 900.0,
        },
    },
)
