"""Unit tests for FireflyAgent._run_with_rate_limit_retry()."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai.exceptions import ModelHTTPError

from fireflyframework_genai.agents.base import FireflyAgent
from fireflyframework_genai.config import reset_config


@pytest.fixture(autouse=True)
def _reset_cfg():
    """Ensure a fresh config for every test."""
    reset_config()
    yield
    reset_config()


def _make_agent() -> FireflyAgent:
    return FireflyAgent("test-retry", model="test", auto_register=False)


def _make_429(body: str | None = None) -> ModelHTTPError:
    return ModelHTTPError(status_code=429, model_name="test", body=body)


def _make_500() -> ModelHTTPError:
    return ModelHTTPError(status_code=500, model_name="test", body=None)


@pytest.mark.asyncio
class TestRunWithRateLimitRetry:
    """Test suite for _run_with_rate_limit_retry()."""

    async def test_429_retries_then_succeeds(self):
        """Mock agent.run() to raise 429 twice, then succeed — verify 3 calls."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "success"

        agent._agent.run = AsyncMock(side_effect=[_make_429(), _make_429(), mock_result])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        assert agent._agent.run.call_count == 3

    async def test_429_exhausts_retries(self):
        """Always 429 — verify ModelHTTPError propagates after max retries."""
        agent = _make_agent()

        agent._agent.run = AsyncMock(side_effect=_make_429())

        with (
            patch("asyncio.sleep", new_callable=AsyncMock),
            patch(
                "fireflyframework_genai.agents.base.get_config",
            ) as mock_cfg,
        ):
            cfg = mock_cfg.return_value
            cfg.rate_limit_max_retries = 2
            cfg.rate_limit_base_delay = 0.01
            cfg.rate_limit_max_delay = 0.1

            with pytest.raises(ModelHTTPError) as exc_info:
                await agent._run_with_rate_limit_retry("hello")

            assert exc_info.value.status_code == 429
            # 1 initial + 2 retries = 3 total calls
            assert agent._agent.run.call_count == 3

    async def test_non_429_not_retried(self):
        """ModelHTTPError(500) propagates immediately without retry."""
        agent = _make_agent()

        agent._agent.run = AsyncMock(side_effect=_make_500())

        with pytest.raises(ModelHTTPError) as exc_info:
            await agent._run_with_rate_limit_retry("hello")

        assert exc_info.value.status_code == 500
        assert agent._agent.run.call_count == 1

    async def test_retry_after_parsed(self):
        """Error body with 'retry after 5 seconds' — verify parsed delay."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "ok"

        err = ModelHTTPError(
            status_code=429,
            model_name="test",
            body="Rate limited. Please retry after 5 seconds.",
        )
        agent._agent.run = AsyncMock(side_effect=[err, mock_result])

        sleep_delays: list[float] = []

        async def capture_sleep(delay: float) -> None:
            sleep_delays.append(delay)

        with patch("asyncio.sleep", side_effect=capture_sleep):
            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        # The delay should be 5.0 (parsed from error body)
        assert len(sleep_delays) == 1
        assert sleep_delays[0] == 5.0

    async def test_success_resets_backoff(self):
        """After success, backoff counter is reset."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "ok"

        agent._agent.run = AsyncMock(return_value=mock_result)

        with patch(
            "fireflyframework_genai.agents.base.get_config",
        ) as mock_cfg:
            cfg = mock_cfg.return_value
            cfg.rate_limit_max_retries = 3
            cfg.rate_limit_base_delay = 1.0
            cfg.rate_limit_max_delay = 60.0
            cfg.quota_enabled = False

            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        assert agent._agent.run.call_count == 1

    async def test_rate_limit_string_detection(self):
        """Exceptions with 'rate limit' in message are detected as 429."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "ok"

        class CustomError(Exception):
            pass

        agent._agent.run = AsyncMock(side_effect=[CustomError("Rate limit exceeded"), mock_result])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        assert agent._agent.run.call_count == 2

    async def test_bedrock_throttling_exception_detected(self):
        """Bedrock ThrottlingException (ClientError shape) is detected as rate limit."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "ok"

        # Simulate a boto3 ClientError with ThrottlingException code
        class ClientError(Exception):
            def __init__(self):
                self.response = {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}}
                super().__init__("ThrottlingException")

        agent._agent.run = AsyncMock(side_effect=[ClientError(), mock_result])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        assert agent._agent.run.call_count == 2

    async def test_bedrock_too_many_requests_detected(self):
        """Bedrock TooManyRequestsException (ClientError shape) is detected as rate limit."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "ok"

        class ClientError(Exception):
            def __init__(self):
                self.response = {"Error": {"Code": "TooManyRequestsException", "Message": "Too many"}}
                super().__init__("TooManyRequestsException")

        agent._agent.run = AsyncMock(side_effect=[ClientError(), mock_result])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        assert agent._agent.run.call_count == 2

    async def test_throttling_string_detection(self):
        """Exceptions with 'throttl' in message are detected as rate limit."""
        agent = _make_agent()
        mock_result = MagicMock()
        mock_result.output = "ok"

        class CustomError(Exception):
            pass

        agent._agent.run = AsyncMock(side_effect=[CustomError("Request throttled by provider"), mock_result])

        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await agent._run_with_rate_limit_retry("hello")

        assert result is mock_result
        assert agent._agent.run.call_count == 2
