"""Celery application. Broker and result backend: Redis (PRICESCOPE_REDIS_URL).

Run a worker (Linux / Docker):
    celery -A pricescope_workers.celery_app worker --loglevel=INFO
On Windows, Celery's default pool is unsupported; for local debugging only:
    celery -A pricescope_workers.celery_app worker --pool=solo --loglevel=INFO
"""

import os

from celery import Celery

REDIS_URL = os.environ.get("PRICESCOPE_REDIS_URL", "redis://127.0.0.1:6379/0")

app = Celery(
    "pricescope", broker=REDIS_URL, backend=REDIS_URL, include=["pricescope_workers.tasks"]
)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    result_expires=3600,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # The fetch runner enforces its own 12 s deadline; these are hard backstops.
    task_soft_time_limit=20,
    task_time_limit=30,
    broker_connection_retry_on_startup=True,
    timezone="Asia/Kolkata",
    enable_utc=True,
)
