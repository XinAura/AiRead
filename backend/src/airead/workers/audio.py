from celery.utils.log import get_task_logger  # type: ignore[import-untyped]

from airead.core.celery_app import celery_app
from airead.core.config import get_settings
from airead.core.database import SessionFactory
from airead.modules.audio.service import AudioService, RetryableAudioError
from airead.providers.limits import RedisSlotLimiter
from airead.providers.storage import build_storage
from airead.providers.tts import build_tts_provider

logger = get_task_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="airead.render_audio_part",
    autoretry_for=(ConnectionError, TimeoutError, RetryableAudioError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
)
def render_audio_part_task(self: object, part_id: str, run_id: str) -> str:
    del self
    settings = get_settings()
    tts_provider = build_tts_provider(settings)
    with SessionFactory() as session:
        service = AudioService(
            session,
            build_storage(settings),
            tts_provider,
            settings,
            render_limiter=RedisSlotLimiter(
                settings.redis_url, "audio-render", settings.audio_job_concurrency
            ),
            tts_limiter=RedisSlotLimiter(
                settings.redis_url, "tts", settings.tts_global_concurrency
            ),
            assemble_limiter=RedisSlotLimiter(
                settings.redis_url, "assemble", settings.assemble_concurrency
            ),
        )
        try:
            part = service.render_part(part_id, run_id)
        except Exception:
            _dispatch_next_batch(service, part_id, run_id)
            raise
        _dispatch_next_batch(service, part_id, run_id)
        if part.status == "canceled":
            logger.info(
                "audio part skipped because render was canceled",
                extra={"run_id": run_id, "audio_part_id": part_id},
            )
            return part.id
        logger.info(
            "audio part rendered provider=%s",
            tts_provider.name,
            extra={"run_id": run_id, "audio_part_id": part_id},
        )
        return part.id


def _dispatch_next_batch(service: AudioService, part_id: str, run_id: str) -> None:
    next_part_ids = service.claim_next_batch(part_id, run_id)
    if not next_part_ids:
        return
    logger.info(
        "dispatching next audio batch parts=%s",
        len(next_part_ids),
        extra={"run_id": run_id, "audio_part_id": part_id},
    )
    for next_part_id in next_part_ids:
        render_audio_part_task.delay(next_part_id, run_id)
