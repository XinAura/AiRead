from celery.utils.log import get_task_logger  # type: ignore[import-untyped]

from airead.core.celery_app import celery_app
from airead.core.database import SessionFactory
from airead.modules.editions.service import EditionService
from airead.modules.parsing.service import ParsingService
from airead.providers.storage import build_storage

logger = get_task_logger(__name__)


@celery_app.task(  # type: ignore[untyped-decorator]
    bind=True,
    name="airead.parse_source",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=3,
)
def parse_source_task(self: object, source_id: str, run_id: str) -> str:
    del self
    with SessionFactory() as session:
        document = ParsingService(session, build_storage()).parse(source_id, run_id)
        edition = EditionService(session).create_original(document.id)
        logger.info("source parsed", extra={"run_id": run_id, "source_id": source_id})
        return edition.id
