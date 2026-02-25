import asyncio
import importlib
import logging
import signal
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# Shared concurrency semaphore — acquired by both SQS consumer and HTTP poll.
_semaphore: Optional[threading.Semaphore] = None


def _init_semaphore(max_concurrent: int) -> threading.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = threading.Semaphore(max_concurrent)
    return _semaphore


def _acquire_slot(settings) -> bool:
    sem = _init_semaphore(settings.drive_stt_concurrency)
    return sem.acquire(blocking=False)


def _release_slot() -> None:
    if _semaphore is not None:
        _semaphore.release()


async def poll_and_process(api_client, stt_processor=None) -> None:
    get_settings = importlib.import_module("heimdex_worker_sdk.settings").get_worker_settings
    process_stt_pending_files = importlib.import_module("src.tasks.stt").process_stt_pending_files

    settings = get_settings()

    if not settings.drive_stt_enabled:
        return

    if not _acquire_slot(settings):
        return

    try:
        await process_stt_pending_files(
            api_client=api_client, settings=settings, stt_processor=stt_processor,
        )
    except Exception:
        logger.exception("stt_poll_cycle_failed")
    finally:
        _release_slot()


def _make_sqs_callback(api_client, settings, stt_processor):
    """Create the SQS message callback for STT processing."""
    from heimdex_worker_sdk.message_adapters import sqs_to_claimed_file
    _process_single_stt = importlib.import_module("src.tasks.stt")._process_single_stt

    def callback(message):
        claimed_file = sqs_to_claimed_file(message)
        _process_single_stt(
            api_client=api_client,
            settings=settings,
            claimed_file=claimed_file,
            stt_processor=stt_processor,
        )

    return callback


def main() -> None:
    get_settings = importlib.import_module("heimdex_worker_sdk.settings").get_worker_settings
    AsyncIOScheduler = importlib.import_module("apscheduler.schedulers.asyncio").AsyncIOScheduler
    InternalAPIClient = importlib.import_module("heimdex_worker_sdk.internal_api").InternalAPIClient

    settings = get_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    if not settings.drive_stt_enabled:
        logger.info("drive_stt_disabled")
        signal.pause()
        return

    api_client = InternalAPIClient(
        base_url=settings.drive_api_base_url,
        api_key=settings.drive_internal_api_key,
    )

    stt_mod = importlib.import_module("heimdex_media_pipelines.speech.stt")
    stt_processor = stt_mod.create_stt_processor(
        backend=settings.drive_stt_backend,
        model_name=settings.drive_stt_model,
        language=settings.drive_stt_language,
        device="cpu",
        compute_type="int8",
        beam_size=1,
        best_of=1,
    )
    logger.info("stt_processor_loaded_once", extra={"model": settings.drive_stt_model})

    # Initialize shared semaphore before starting any consumers
    semaphore = _init_semaphore(settings.drive_stt_concurrency)

    # ── SQS Consumer (Phase 2) ──────────────────────────────────────
    sqs_consumer = None
    if settings.sqs_consumer_enabled and settings.sqs_stt_queue_url:
        from heimdex_worker_sdk.sqs_client import SQSJobClient
        from heimdex_worker_sdk.sqs_consumer import SQSConsumerLoop

        sqs_client = SQSJobClient(
            queue_url=settings.sqs_stt_queue_url,
            region=settings.sqs_region,
            endpoint_url=settings.sqs_endpoint_url or None,
        )
        sqs_consumer = SQSConsumerLoop(
            sqs_client=sqs_client,
            process_callback=_make_sqs_callback(api_client, settings, stt_processor),
            semaphore=semaphore,
            visibility_timeout=60,
            heartbeat_interval=40,
            worker_name="stt",
        )
        sqs_consumer.start()
    elif settings.sqs_consumer_enabled:
        logger.warning("sqs_consumer_enabled_but_no_queue_url", extra={"queue": "stt"})

    # ── Legacy HTTP Poll (always active during Phase 2) ─────────────
    scheduler = AsyncIOScheduler()
    scheduler.add_job(
        poll_and_process,
        "interval",
        seconds=settings.drive_stt_poll_interval_seconds,
        args=[api_client, stt_processor],
        max_instances=1,
        id="stt_poll",
    )

    async def _run() -> None:
        stop_event = asyncio.Event()
        loop = asyncio.get_running_loop()

        def shutdown(*_: object) -> None:
            logger.info("shutdown_signal_received")
            scheduler.shutdown(wait=False)
            if sqs_consumer is not None:
                sqs_consumer.stop(timeout=30.0)
            stop_event.set()

        loop.add_signal_handler(signal.SIGTERM, shutdown)
        loop.add_signal_handler(signal.SIGINT, shutdown)

        scheduler.start()
        logger.info(
            "stt_worker_started",
            extra={
                "poll_interval": settings.drive_stt_poll_interval_seconds,
                "concurrency": settings.drive_stt_concurrency,
                "model": settings.drive_stt_model,
                "language": settings.drive_stt_language,
                "backend": settings.drive_stt_backend,
                "max_audio_seconds": settings.drive_stt_max_audio_seconds,
                "sqs_consumer_enabled": settings.sqs_consumer_enabled,
            },
        )
        await stop_event.wait()

    asyncio.run(_run())


if __name__ == "__main__":
    main()
