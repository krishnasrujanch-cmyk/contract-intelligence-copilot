"""
Celery worker configuration and task registration.

Two queues:
  document_processing  — contract upload and analysis pipeline
  alerts               — obligation deadline notification scheduler

Tasks are idempotent — safe to retry on failure (Celery retry policy).
All tasks use task_id as the contract processing_job_id for status tracking.
"""
from celery import Celery
from app.core.config import settings

worker = Celery(
    "clm_worker",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

worker.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,           # Ack after task completes — prevents data loss on crash
    worker_prefetch_multiplier=1,  # One task at a time per worker — prevents OOM on LLM tasks
    task_routes={
        "app.tasks.document.*": {"queue": "document_processing"},
        "app.tasks.alerts.*":   {"queue": "alerts"},
    },
    beat_schedule={
        # Check obligation deadlines daily at 08:00 UTC
        "daily-obligation-alerts": {
            "task":     "app.tasks.alerts.check_upcoming_deadlines",
            "schedule": 86400,
        },
    },
)

worker.autodiscover_tasks(["app.tasks"])
