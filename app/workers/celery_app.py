from celery import Celery
from celery.schedules import crontab

from app.config import settings

celery = Celery(
    "hyperseek",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "reindex-nightly": {
            "task": "app.workers.reindex_tasks.full_reindex",
            "schedule": crontab(hour=3, minute=0),  # 3 AM UTC
        },
    },
)

# Auto-discover tasks in workers package
celery.autodiscover_tasks(["app.workers"])
