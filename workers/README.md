# pricescope-workers

Celery tasks that fetch marketplaces concurrently. Workers do **adapter I/O only**: each task
returns a JSON `FetchResult`, and the API process matches, prices and stores it (one writer,
which keeps Google Sheets storage safe).

Enabled with `PRICESCOPE_TASK_EXECUTOR=celery` (default `threads` needs no Redis).

```powershell
docker compose up -d redis worker
```

Windows has no supported Celery pool; for debugging only:
`celery -A pricescope_workers.celery_app worker --pool=solo`.
