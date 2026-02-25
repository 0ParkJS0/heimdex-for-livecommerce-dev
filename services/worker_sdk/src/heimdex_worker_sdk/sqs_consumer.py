"""
SQS consumer loop for Heimdex workers (Phase 2: Dual-Read Consumer).

Provides a generic ``SQSConsumerLoop`` that long-polls an SQS queue in a
background thread, dispatches messages to a user-supplied callback, and
manages visibility heartbeats for long-running tasks.

Design constraints:
  - Both the SQS consumer and legacy HTTP poll share the same
    ``threading.Semaphore`` to enforce concurrency limits.
  - When ``SQS_CONSUMER_ENABLED=false`` this module is never instantiated.
  - Graceful shutdown: stops accepting new messages, drains in-flight work.
"""

import logging
import threading
import time
from typing import Callable, Optional

from heimdex_worker_sdk.sqs_client import SQSJobClient, SQSMessage

logger = logging.getLogger(__name__)


class InvalidMessageError(Exception):
    """Raised when an SQS message body cannot be parsed.

    Messages that raise this are treated as *poison pills*: they are deleted
    immediately from the queue to prevent infinite retry loops.
    """


# ── Visibility Heartbeat ──────────────────────────────────────────────


class VisibilityHeartbeat:
    """Context manager that extends SQS message visibility in a daemon thread.

    Usage::

        with VisibilityHeartbeat(sqs_client, receipt_handle, interval=40, timeout=60):
            do_work()  # heartbeat runs in background until block exits

    The daemon thread calls ``extend_visibility`` every *interval* seconds,
    resetting the visibility timeout to *timeout* seconds.  If the thread
    fails to extend (network error, receipt handle expired), it logs a
    warning and stops — the message will become visible again after the
    current visibility window expires.
    """

    def __init__(
        self,
        sqs_client: SQSJobClient,
        receipt_handle: str,
        interval: int = 40,
        timeout: int = 60,
    ) -> None:
        self._sqs = sqs_client
        self._handle = receipt_handle
        self._interval = interval
        self._timeout = timeout
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def __enter__(self) -> "VisibilityHeartbeat":
        self._thread = threading.Thread(
            target=self._heartbeat_loop, daemon=True, name="sqs-heartbeat"
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _heartbeat_loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._sqs.extend_visibility(self._handle, self._timeout)
                logger.debug(
                    "sqs_heartbeat_extended",
                    extra={"timeout": self._timeout},
                )
            except Exception:
                logger.warning(
                    "sqs_heartbeat_failed",
                    exc_info=True,
                )
                break  # Stop heartbeat; visibility will expire naturally


# ── Consumer Loop ─────────────────────────────────────────────────────


class SQSConsumerLoop:
    """Background thread that long-polls SQS and dispatches to a callback.

    The consumer acquires a slot from the shared ``semaphore`` *before*
    calling ``receive_jobs``, ensuring it never pulls a message it cannot
    immediately begin processing.

    Each received message is processed in its own thread with a dedicated
    ``VisibilityHeartbeat``.  On success the message is deleted; on failure
    it is left for SQS to redeliver (and eventually land in the DLQ).

    Args:
        sqs_client: Configured ``SQSJobClient`` for the target queue.
        process_callback: ``(SQSMessage) -> None``.  Must be synchronous.
            Raise ``InvalidMessageError`` for poison pills (auto-deleted).
        semaphore: Shared ``threading.Semaphore`` — same instance used by
            the legacy HTTP poll path.
        visibility_timeout: Seconds to set on each ``receive_message`` call.
        heartbeat_interval: Seconds between heartbeat extensions.
        worker_name: Label for log messages.
    """

    def __init__(
        self,
        sqs_client: SQSJobClient,
        process_callback: Callable[[SQSMessage], None],
        semaphore: threading.Semaphore,
        visibility_timeout: int = 60,
        heartbeat_interval: int = 40,
        worker_name: str = "worker",
    ) -> None:
        self._sqs = sqs_client
        self._callback = process_callback
        self._semaphore = semaphore
        self._visibility_timeout = visibility_timeout
        self._heartbeat_interval = heartbeat_interval
        self._worker_name = worker_name

        self._shutdown = threading.Event()
        self._loop_thread: Optional[threading.Thread] = None
        self._active_lock = threading.Lock()
        self._active_threads: list[threading.Thread] = []

    # ── Lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Start the consumer loop in a daemon thread."""
        self._loop_thread = threading.Thread(
            target=self._run_loop,
            daemon=True,
            name=f"sqs-consumer-{self._worker_name}",
        )
        self._loop_thread.start()
        logger.info(
            "sqs_consumer_started",
            extra={
                "worker": self._worker_name,
                "visibility_timeout": self._visibility_timeout,
                "heartbeat_interval": self._heartbeat_interval,
            },
        )

    def stop(self, timeout: float = 30.0) -> None:
        """Signal shutdown and wait for in-flight messages to drain.

        The main loop stops calling ``receive_jobs``.  Active processing
        threads are given up to *timeout* seconds to finish.  Heartbeats
        continue running during the drain period.
        """
        self._shutdown.set()

        # Wait for the polling loop thread to exit
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5.0)

        # Drain active processing threads
        deadline = time.monotonic() + timeout
        with self._active_lock:
            threads = list(self._active_threads)

        for t in threads:
            remaining = deadline - time.monotonic()
            if remaining > 0:
                t.join(timeout=remaining)

        logger.info(
            "sqs_consumer_stopped",
            extra={"worker": self._worker_name},
        )

    # ── Main loop ─────────────────────────────────────────────────

    def _run_loop(self) -> None:
        """Main consumer loop — runs in background thread."""
        while not self._shutdown.is_set():
            # Backpressure: block until a concurrency slot opens
            acquired = self._semaphore.acquire(timeout=1.0)
            if not acquired:
                continue

            try:
                messages = self._sqs.receive_jobs(
                    max_messages=1,
                    wait_time=20,
                    visibility_timeout=self._visibility_timeout,
                )

                if not messages:
                    self._semaphore.release()
                    continue

                msg = messages[0]
                logger.info(
                    "sqs_message_received",
                    extra={
                        "worker": self._worker_name,
                        "message_id": msg.message_id,
                        "file_id": msg.body.get("file_id", ""),
                        "receive_count": msg.receive_count,
                    },
                )

                # Spawn processing thread (semaphore released inside)
                t = threading.Thread(
                    target=self._process_with_heartbeat,
                    args=(msg,),
                    daemon=True,
                    name=f"sqs-proc-{msg.message_id[:8]}",
                )
                with self._active_lock:
                    self._active_threads.append(t)
                t.start()

                # Housekeeping: prune finished threads
                self._prune_finished_threads()

            except Exception:
                self._semaphore.release()
                logger.exception(
                    "sqs_receive_error",
                    extra={"worker": self._worker_name},
                )
                # Back off before retrying
                self._shutdown.wait(5.0)

    # ── Per-message processing ────────────────────────────────────

    def _process_with_heartbeat(self, message: SQSMessage) -> None:
        """Process a single message with heartbeat.  Runs in its own thread."""
        started = time.monotonic()
        with VisibilityHeartbeat(
            self._sqs,
            message.receipt_handle,
            interval=self._heartbeat_interval,
            timeout=self._visibility_timeout,
        ):
            try:
                self._callback(message)

                # Success → delete from queue
                self._sqs.complete_job(message.receipt_handle)
                duration_ms = int((time.monotonic() - started) * 1000)
                logger.info(
                    "sqs_message_processed",
                    extra={
                        "worker": self._worker_name,
                        "message_id": message.message_id,
                        "file_id": message.body.get("file_id", ""),
                        "duration_ms": duration_ms,
                    },
                )

            except InvalidMessageError:
                # Poison pill → delete immediately to prevent retry loops
                self._sqs.complete_job(message.receipt_handle)
                logger.warning(
                    "sqs_invalid_message_deleted",
                    extra={
                        "worker": self._worker_name,
                        "message_id": message.message_id,
                        "receive_count": message.receive_count,
                    },
                    exc_info=True,
                )

            except Exception:
                # Processing failure → let visibility timeout expire
                # SQS will redeliver; DLQ catches poison pills
                duration_ms = int((time.monotonic() - started) * 1000)
                logger.exception(
                    "sqs_message_failed",
                    extra={
                        "worker": self._worker_name,
                        "message_id": message.message_id,
                        "file_id": message.body.get("file_id", ""),
                        "receive_count": message.receive_count,
                        "duration_ms": duration_ms,
                    },
                )

            finally:
                self._semaphore.release()

    # ── Helpers ───────────────────────────────────────────────────

    def _prune_finished_threads(self) -> None:
        with self._active_lock:
            self._active_threads = [
                t for t in self._active_threads if t.is_alive()
            ]
