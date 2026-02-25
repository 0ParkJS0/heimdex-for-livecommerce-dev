import os
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from heimdex_worker_sdk.settings import WorkerSettings
from heimdex_worker_sdk.sqs_client import SQSJobClient, SQSMessage
from heimdex_worker_sdk.sqs_consumer import (
    InvalidMessageError,
    SQSConsumerLoop,
    VisibilityHeartbeat,
)


class _NoopHeartbeat:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None


@pytest.fixture
def mock_sqs_client():
    return MagicMock(spec=SQSJobClient)


@pytest.fixture
def semaphore():
    return threading.Semaphore(1)


@pytest.fixture
def sqs_message():
    return SQSMessage(
        message_id="msg-001",
        receipt_handle="receipt-001",
        body={"file_id": "file-001", "job_type": "caption"},
        receive_count=1,
    )


class TestInvalidMessageError:
    def test_is_exception_subclass(self):
        assert issubclass(InvalidMessageError, Exception)


class TestVisibilityHeartbeat:
    def test_extends_visibility_on_interval_and_stops_on_exit(self, mock_sqs_client):
        heartbeat_called = threading.Event()

        def _extend(receipt_handle, timeout):
            assert receipt_handle == "receipt-123"
            assert timeout == 33
            heartbeat_called.set()

        mock_sqs_client.extend_visibility.side_effect = _extend

        with VisibilityHeartbeat(
            mock_sqs_client,
            "receipt-123",
            interval=0,
            timeout=33,
        ):
            assert heartbeat_called.wait(0.3)

        call_count_after_exit = mock_sqs_client.extend_visibility.call_count
        time.sleep(0.05)
        assert mock_sqs_client.extend_visibility.call_count == call_count_after_exit

    def test_stops_heartbeat_loop_when_extend_fails(self, mock_sqs_client):
        failed = threading.Event()

        def _fail(*_args, **_kwargs):
            failed.set()
            raise RuntimeError("network down")

        mock_sqs_client.extend_visibility.side_effect = _fail
        heartbeat = VisibilityHeartbeat(mock_sqs_client, "receipt-123", interval=0)

        with heartbeat:
            assert failed.wait(0.3)
            assert heartbeat._thread is not None
            heartbeat._thread.join(timeout=0.2)
            assert not heartbeat._thread.is_alive()

        assert mock_sqs_client.extend_visibility.call_count == 1


class TestSQSConsumerLoopLifecycle:
    def test_start_and_stop(self, mock_sqs_client, semaphore):
        mock_sqs_client.receive_jobs.return_value = []
        consumer = SQSConsumerLoop(
            mock_sqs_client,
            process_callback=lambda _msg: None,
            semaphore=semaphore,
            worker_name="caption",
        )

        consumer.start()
        assert consumer._loop_thread is not None
        assert consumer._loop_thread.is_alive()

        time.sleep(0.05)
        consumer.stop(timeout=0.5)

        assert not consumer._loop_thread.is_alive()
        assert mock_sqs_client.receive_jobs.called


class TestSQSConsumerLoopProcessing:
    def test_processes_message_and_completes_job(self, mock_sqs_client, semaphore, sqs_message):
        callback_called = threading.Event()
        state = {"sent": False}

        def _receive_jobs(**_kwargs):
            if not state["sent"]:
                state["sent"] = True
                return [sqs_message]
            return []

        def _callback(msg):
            assert msg == sqs_message
            callback_called.set()

        mock_sqs_client.receive_jobs.side_effect = _receive_jobs
        consumer = SQSConsumerLoop(
            mock_sqs_client,
            process_callback=_callback,
            semaphore=semaphore,
            heartbeat_interval=1,
            worker_name="caption",
        )

        with patch("heimdex_worker_sdk.sqs_consumer.VisibilityHeartbeat", return_value=_NoopHeartbeat()):
            consumer.start()
            assert callback_called.wait(0.5)
            consumer.stop(timeout=0.5)

        mock_sqs_client.complete_job.assert_called_once_with(sqs_message.receipt_handle)

    @pytest.mark.parametrize(
        "callback_side_effect,should_delete",
        [
            (None, True),
            (InvalidMessageError("bad payload"), True),
            (RuntimeError("processing failed"), False),
        ],
    )
    def test_releases_semaphore_in_all_code_paths(
        self,
        mock_sqs_client,
        sqs_message,
        callback_side_effect,
        should_delete,
    ):
        sem = threading.Semaphore(0)
        callback = MagicMock()
        if callback_side_effect is not None:
            callback.side_effect = callback_side_effect

        consumer = SQSConsumerLoop(
            mock_sqs_client,
            process_callback=callback,
            semaphore=sem,
            worker_name="caption",
        )

        with patch("heimdex_worker_sdk.sqs_consumer.VisibilityHeartbeat", return_value=_NoopHeartbeat()):
            consumer._process_with_heartbeat(sqs_message)

        assert sem.acquire(blocking=False) is True
        assert sem.acquire(blocking=False) is False

        if should_delete:
            mock_sqs_client.complete_job.assert_called_once_with(sqs_message.receipt_handle)
        else:
            mock_sqs_client.complete_job.assert_not_called()

    def test_backpressure_waits_for_semaphore_slot(self, mock_sqs_client, sqs_message):
        sem = threading.Semaphore(0)
        receive_called = threading.Event()
        state = {"sent": False}

        def _receive_jobs(**_kwargs):
            receive_called.set()
            if not state["sent"]:
                state["sent"] = True
                return [sqs_message]
            return []

        mock_sqs_client.receive_jobs.side_effect = _receive_jobs
        consumer = SQSConsumerLoop(
            mock_sqs_client,
            process_callback=lambda _msg: None,
            semaphore=sem,
            worker_name="caption",
        )

        with patch("heimdex_worker_sdk.sqs_consumer.VisibilityHeartbeat", return_value=_NoopHeartbeat()):
            consumer.start()
            assert not receive_called.wait(0.15)

            sem.release()
            assert receive_called.wait(0.5)

            consumer.stop(timeout=0.5)

    def test_receive_error_uses_backoff_and_retries(self, mock_sqs_client, semaphore):
        backoff_wait_called = threading.Event()
        retried_after_error = threading.Event()
        state = {"calls": 0}

        def _receive_jobs(**_kwargs):
            state["calls"] += 1
            if state["calls"] == 1:
                raise RuntimeError("sqs unavailable")
            retried_after_error.set()
            return []

        mock_sqs_client.receive_jobs.side_effect = _receive_jobs
        consumer = SQSConsumerLoop(
            mock_sqs_client,
            process_callback=lambda _msg: None,
            semaphore=semaphore,
            worker_name="caption",
        )

        def _fake_wait(timeout):
            if timeout == 5.0:
                backoff_wait_called.set()
            return False

        with patch.object(consumer._shutdown, "wait", side_effect=_fake_wait):
            consumer.start()
            assert backoff_wait_called.wait(0.5)
            assert retried_after_error.wait(0.5)
            consumer.stop(timeout=0.5)


class TestSQSConsumerEnabledSetting:
    def test_default_false(self):
        settings = WorkerSettings()
        assert settings.sqs_consumer_enabled is False

    def test_env_override_true(self):
        with patch.dict(os.environ, {"SQS_CONSUMER_ENABLED": "true"}):
            settings = WorkerSettings()
            assert settings.sqs_consumer_enabled is True
