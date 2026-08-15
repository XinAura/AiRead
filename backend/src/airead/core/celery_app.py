from celery import Celery  # type: ignore[import-untyped]

from airead.core.config import get_settings

settings = get_settings()
celery_app = Celery(
    "airead",
    broker=settings.redis_url,
    include=["airead.workers.parsing", "airead.workers.audio"],
)
celery_app.conf.update(
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_routes={
        "airead.parse_source": {"queue": "parsing"},
        "airead.render_audio_part": {"queue": "audio"},
    },
)
