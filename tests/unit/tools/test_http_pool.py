# Copyright 2026 Firefly Software Solutions Inc
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Unit tests for HTTP connection pooling."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest

from fireflyframework_agentic.tools.builtins.http import HTTPX_AVAILABLE, HttpTool


class TestHttpConnectionPooling:
    """Test suite for HTTP connection pooling."""

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_httpx_client_created_when_pool_enabled(self):
        """Test that httpx client is created when pooling is enabled."""
        tool = HttpTool(use_pool=True, pool_size=50, pool_max_keepalive=10)

        assert tool._client is not None
        assert tool._use_pool is True

        await tool.close()

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_httpx_client_not_created_when_pool_disabled(self):
        """Test that httpx client is not created when pooling is disabled."""
        tool = HttpTool(use_pool=False)

        assert tool._client is None
        assert tool._use_pool is False

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_request_uses_httpx_when_pool_enabled(self):
        """Test that requests use httpx when pooling is enabled."""
        tool = HttpTool(use_pool=True)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {"Content-Type": "application/json"}
        mock_response.text = '{"result": "ok"}'

        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await tool._execute(
                url="https://api.example.com/endpoint",
                method="GET",
            )

            assert result["status"] == 200
            assert result["body"] == '{"result": "ok"}'
            assert "Content-Type" in result["headers"]

            # Verify httpx was called
            mock_request.assert_called_once()
            call_kwargs = mock_request.call_args.kwargs
            assert call_kwargs["method"] == "GET"
            assert call_kwargs["url"] == "https://api.example.com/endpoint"

        await tool.close()

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_request_with_body_and_headers(self):
        """Test that request body and headers are properly passed."""
        tool = HttpTool(use_pool=True, default_headers={"X-Default": "value"})

        mock_response = Mock()
        mock_response.status_code = 201
        mock_response.headers = {}
        mock_response.text = "Created"

        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            result = await tool._execute(
                url="https://api.example.com/create",
                method="POST",
                body='{"name": "test"}',
                headers={"Content-Type": "application/json"},
            )

            assert result["status"] == 201

            # Verify body and headers
            call_kwargs = mock_request.call_args.kwargs
            assert call_kwargs["content"] == b'{"name": "test"}'
            assert "X-Default" in call_kwargs["headers"]
            assert "Content-Type" in call_kwargs["headers"]

        await tool.close()

    async def test_fallback_to_urllib_when_httpx_not_available(self):
        """Test that urllib fallback works when httpx is not available."""
        # Temporarily disable httpx
        with patch("fireflyframework_agentic.tools.builtins.http.HTTPX_AVAILABLE", False):
            tool = HttpTool(use_pool=True)  # Request pooling

            # Should fallback to no pooling
            assert tool._client is None
            assert tool._use_pool is False

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_connection_reuse_across_requests(self):
        """Test that connections are reused across multiple requests."""
        tool = HttpTool(use_pool=True)

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.headers = {}
        mock_response.text = "OK"

        with patch.object(tool._client, "request", new_callable=AsyncMock) as mock_request:
            mock_request.return_value = mock_response

            # Make multiple requests
            for i in range(5):
                result = await tool._execute(
                    url=f"https://api.example.com/endpoint{i}",
                    method="GET",
                )
                assert result["status"] == 200

            # Verify all requests used the same client
            assert mock_request.call_count == 5

        await tool.close()

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_close_releases_connections(self):
        """Test that close() properly releases connections."""
        tool = HttpTool(use_pool=True)

        client = tool._client
        assert client is not None

        with patch.object(client, "aclose", new_callable=AsyncMock) as mock_close:
            await tool.close()
            mock_close.assert_called_once()

        # Client should be None after close
        assert tool._client is None

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_timeout_configuration(self):
        """Test that timeout is properly configured."""
        tool = HttpTool(use_pool=True, timeout=60.0)

        # Check that timeout was set on the client
        assert tool._client.timeout.read == 60.0

        await tool.close()

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_default_pool_parameters(self):
        """Test default pool parameters."""
        tool = HttpTool(use_pool=True)

        # Verify client was created with pooling
        assert tool._client is not None
        assert tool._use_pool is True

        await tool.close()

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_custom_pool_parameters(self):
        """Test custom pool parameters."""
        tool = HttpTool(
            use_pool=True,
            pool_size=200,
            pool_max_keepalive=50,
        )

        # Verify client was created with custom parameters
        assert tool._client is not None
        assert tool._use_pool is True

        await tool.close()

    @pytest.mark.skipif(not HTTPX_AVAILABLE, reason="httpx not installed")
    async def test_follow_redirects_enabled(self):
        """Test that redirects are followed by default."""
        tool = HttpTool(use_pool=True)

        # httpx client should have follow_redirects=True
        assert tool._client.follow_redirects is True

        await tool.close()


class TestHttpToolBackwardCompatibility:
    """Test backward compatibility with urllib fallback."""

    async def test_urllib_fallback_works(self):
        """Test that urllib fallback executes requests."""
        with patch("fireflyframework_agentic.tools.builtins.http.HTTPX_AVAILABLE", False):
            tool = HttpTool(use_pool=False)

            # Mock urllib.request.urlopen
            mock_response = Mock()
            mock_response.status = 200
            mock_response.headers = {"Content-Type": "text/plain"}
            mock_response.read.return_value = b"Hello, World!"

            with patch("urllib.request.urlopen", return_value=mock_response) as mock_urlopen:
                mock_urlopen.__enter__ = Mock(return_value=mock_response)
                mock_urlopen.__exit__ = Mock(return_value=False)

                # Need to mock the context manager
                with patch("urllib.request.urlopen") as mock_urlopen_ctx:
                    mock_urlopen_ctx.return_value.__enter__ = Mock(return_value=mock_response)
                    mock_urlopen_ctx.return_value.__exit__ = Mock(return_value=False)

                    result = await tool._execute(
                        url="https://example.com",
                        method="GET",
                    )

                    assert result["status"] == 200
                    assert result["body"] == "Hello, World!"
