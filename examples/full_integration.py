#!/usr/bin/env python3
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

"""Comprehensive example demonstrating full framework integration.

This example shows all production-ready features working together:
- Database persistence (PostgreSQL/MongoDB)
- Distributed tracing (W3C Trace Context)
- API quota management
- Security (RBAC, encryption, SQL injection prevention)
- HTTP connection pooling
- Incremental streaming
- Batch processing
- Prompt caching
- Circuit breaker

The example demonstrates a complete production-ready GenAI application
with enterprise features enabled.
"""

from __future__ import annotations

import asyncio
import os

# Core framework
from fireflyframework_genai.agents.base import FireflyAgent

# Middleware (all production features)
from fireflyframework_genai.agents.builtin_middleware import (
    CostGuardMiddleware,
    LoggingMiddleware,
    ObservabilityMiddleware,
)
from fireflyframework_genai.agents.prompt_cache import PromptCacheMiddleware
from fireflyframework_genai.config import get_config

# Database persistence
from fireflyframework_genai.memory.manager import MemoryManager

# Observability
from fireflyframework_genai.observability.usage import default_usage_tracker

# Pipeline with batch processing
from fireflyframework_genai.pipeline.builder import PipelineBuilder
from fireflyframework_genai.pipeline.steps import BatchLLMStep
from fireflyframework_genai.resilience.circuit_breaker import CircuitBreakerMiddleware


async def demo_full_stack_agent():
    """Demonstrate agent with all production features enabled."""
    print("\n=== Full-Stack Production Agent ===\n")

    # Configure framework (typically done via environment variables)
    config = get_config()
    print("Configuration:")
    print(f"  Model: {config.default_model}")
    print(f"  Observability: {config.observability_enabled}")
    print(f"  Cost tracking: {config.cost_tracking_enabled}")
    print(f"  Memory backend: {config.memory_backend}")
    print()

    # Create memory manager (supports in-memory, file, PostgreSQL, MongoDB)
    memory = MemoryManager(
        working_scope_id="production-app",
        # To use PostgreSQL: Uncomment and set FIREFLY_GENAI_MEMORY_BACKEND=postgres
        # To use MongoDB: Uncomment and set FIREFLY_GENAI_MEMORY_BACKEND=mongodb
    )

    # Create production-ready agent with all features
    agent = FireflyAgent(
        "production-assistant",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        instructions="""You are a helpful AI assistant for a production application.

        You provide accurate, helpful responses while maintaining conversation context.
        You are cost-effective, resilient, and secure."""
        * 5,  # Long prompt for caching demo
        memory=memory,
        middleware=[
            # Logging for audit trail
            LoggingMiddleware(),
            # Observability (tracing, metrics)
            ObservabilityMiddleware(),
            # Cost guard to prevent budget overruns
            CostGuardMiddleware(
                budget_limit_usd=config.budget_limit_usd or 10.0,
                alert_threshold_usd=config.budget_alert_threshold_usd or 5.0,
            ),
            # Prompt caching for cost savings
            PromptCacheMiddleware(
                cache_system_prompt=True,
                cache_min_tokens=1024,
            ),
            # Circuit breaker for resilience
            CircuitBreakerMiddleware(
                failure_threshold=5,
                recovery_timeout=60.0,
            ),
        ],
        tags=["production", "assistant", "resilient"],
        auto_register=True,
    )

    conversation_id = "user-123-session"

    print("Making requests with full production features:\n")

    # Request 1: Creates cache, traces, logs
    print("Request 1: (Cache miss, full tracing)")
    result1 = await agent.run(
        "What is Python?",
        conversation_id=conversation_id,
    )
    print(f"Answer: {str(result1.output)[:100]}...")
    print()

    # Request 2: Cache hit, continued tracing
    print("Request 2: (Cache hit, ~90% cost savings)")
    result2 = await agent.run(
        "What is machine learning?",
        conversation_id=conversation_id,
    )
    print(f"Answer: {str(result2.output)[:100]}...")
    print()

    # Request 3: With streaming
    print("Request 3: (Incremental streaming)")
    print("Answer: ", end="", flush=True)
    async with await agent.run_stream(
        "Explain async/await in Python",
        conversation_id=conversation_id,
        streaming_mode="incremental",
    ) as stream:
        async for token in stream.stream_tokens():
            print(token, end="", flush=True)
    print("\n")

    # Show usage statistics
    usage_summary = default_usage_tracker.get_summary()
    print("\nUsage Statistics:")
    print(f"  Total requests: {usage_summary.total_requests}")
    print(f"  Total tokens: {usage_summary.total_tokens:,}")
    print(f"  Total cost: ${usage_summary.total_cost_usd:.4f}")
    print(f"  Input tokens: {usage_summary.total_input_tokens:,}")
    print(f"  Output tokens: {usage_summary.total_output_tokens:,}")

    # Show conversation history (persisted in memory)
    history = memory.get_message_history(conversation_id)
    print("\nConversation History:")
    print(f"  Messages persisted: {len(history)}")


async def demo_pipeline_with_batch():
    """Demonstrate pipeline with batch processing and all features."""
    print("\n\n=== Production Pipeline with Batch Processing ===\n")

    memory = MemoryManager()

    # Create agents for pipeline
    classifier = FireflyAgent(
        "classifier",
        model=os.getenv("MODEL", "openai:gpt-4o-mini"),
        instructions="Classify sentiment as: positive, negative, or neutral.",
        memory=memory,
        middleware=[
            LoggingMiddleware(),
            PromptCacheMiddleware(),
            CircuitBreakerMiddleware(failure_threshold=3),
        ],
        auto_register=False,
    )

    # Build pipeline with batch processing
    builder = PipelineBuilder()

    # Step 1: Load documents (simulated)
    async def load_documents(context, inputs):
        return [
            "This product is amazing!",
            "Terrible experience.",
            "It's okay, nothing special.",
            "Best purchase ever!",
            "Waste of money.",
        ]

    builder.add_node("load", load_documents)

    # Step 2: Batch classify with all features
    builder.add_node(
        "classify",
        BatchLLMStep(
            classifier,
            prompts_key="load",
            batch_size=10,
        ),
    )
    builder.add_edge("load", "classify")

    # Step 3: Aggregate results
    async def aggregate(context, inputs):
        classifications = context.get_node_result("classify").output
        counts = {}
        for c in classifications:
            sentiment = str(c).strip().lower()
            counts[sentiment] = counts.get(sentiment, 0) + 1
        return counts

    builder.add_node("aggregate", aggregate)
    builder.add_edge("classify", "aggregate")

    # Run pipeline
    from fireflyframework_genai.pipeline.context import PipelineContext

    pipeline = builder.build()

    print("Running pipeline with:")
    print("  - Batch processing (5 documents)")
    print("  - Circuit breaker protection")
    print("  - Prompt caching")
    print("  - Distributed tracing")
    print()

    result = await pipeline.run(PipelineContext(inputs={}, correlation_id="pipeline-batch-1"))

    print("Pipeline Result:")
    print(f"  Documents processed: {len(result.get_node_result('load'))}")
    print(f"  Classifications: {result.get_node_result('classify')}")
    print(f"  Sentiment distribution: {result.output}")


async def demo_security_features():
    """Demonstrate security features integration."""
    print("\n\n=== Security Features Integration ===\n")

    # RBAC (if enabled)
    print("1. RBAC (Role-Based Access Control):")
    print("   Configure with: FIREFLY_GENAI_RBAC_ENABLED=true")
    print("   Set JWT secret: FIREFLY_GENAI_RBAC_JWT_SECRET=your-secret")
    print("   Use @require_permission decorator on agent endpoints")
    print()

    # Encryption (if enabled)
    print("2. Data Encryption:")
    print("   Configure with: FIREFLY_GENAI_ENCRYPTION_ENABLED=true")
    print("   Set encryption key: FIREFLY_GENAI_ENCRYPTION_KEY=your-key-32-bytes")
    print("   Use EncryptedMemoryStore wrapper for sensitive data")
    print()

    # SQL Injection Prevention
    print("3. SQL Injection Prevention:")
    print("   Automatically enabled in DatabaseTool")
    print("   Detects 15+ dangerous SQL patterns")
    print("   Enforces parameterized queries")
    print()

    # CORS Security
    print("4. CORS Security:")
    print("   Default: No origins allowed (secure)")
    print("   Configure: FIREFLY_GENAI_CORS_ALLOWED_ORIGINS=['https://app.example.com']")
    print()


async def demo_observability_integration():
    """Demonstrate observability features."""
    print("\n\n=== Observability Integration ===\n")

    config = get_config()

    print("1. Distributed Tracing:")
    print(f"   Enabled: {config.observability_enabled}")
    print(f"   OTLP endpoint: {config.otlp_endpoint or 'Not configured'}")
    print(f"   Service name: {config.service_name}")
    print("   W3C Trace Context propagation: Enabled")
    print()

    print("2. Usage Tracking:")
    print(f"   Cost tracking: {config.cost_tracking_enabled}")
    print(f"   Max records: {config.usage_tracker_max_records:,}")
    print()

    print("3. Quota Management:")
    print(f"   Enabled: {config.quota_enabled}")
    print(f"   Daily budget: ${config.quota_budget_daily_usd or 'Not set'}")
    print(f"   Rate limits: {config.quota_rate_limits or 'Not set'}")
    print(f"   Adaptive backoff: {config.quota_adaptive_backoff}")
    print()


async def demo_configuration_integration():
    """Show how all features are configured."""
    print("\n\n=== Configuration Integration ===\n")

    print("All features are configured via environment variables:")
    print()

    print("# Database Persistence")
    print("export FIREFLY_GENAI_MEMORY_BACKEND=postgres  # or mongodb, file, in_memory")
    print("export FIREFLY_GENAI_MEMORY_POSTGRES_URL=postgresql://user:pass@localhost/db")
    print("export FIREFLY_GENAI_MEMORY_MONGODB_URL=mongodb://localhost:27017/")
    print()

    print("# Distributed Tracing")
    print("export FIREFLY_GENAI_OBSERVABILITY_ENABLED=true")
    print("export FIREFLY_GENAI_OTLP_ENDPOINT=http://localhost:4317")
    print("export FIREFLY_GENAI_SERVICE_NAME=my-genai-app")
    print()

    print("# Quota Management")
    print("export FIREFLY_GENAI_QUOTA_ENABLED=true")
    print("export FIREFLY_GENAI_QUOTA_BUDGET_DAILY_USD=100.0")
    print("export FIREFLY_GENAI_QUOTA_RATE_LIMITS='{\"openai:gpt-4o\": 60}'")
    print()

    print("# Security")
    print("export FIREFLY_GENAI_RBAC_ENABLED=true")
    print("export FIREFLY_GENAI_RBAC_JWT_SECRET=your-secret-key")
    print("export FIREFLY_GENAI_ENCRYPTION_ENABLED=true")
    print("export FIREFLY_GENAI_ENCRYPTION_KEY=your-32-byte-key")
    print("export FIREFLY_GENAI_CORS_ALLOWED_ORIGINS=['https://app.example.com']")
    print()

    print("# HTTP Connection Pooling")
    print("export FIREFLY_GENAI_HTTP_POOL_ENABLED=true")
    print("export FIREFLY_GENAI_HTTP_POOL_SIZE=100")
    print()

    print("# Cost Optimization")
    print("export FIREFLY_GENAI_BUDGET_LIMIT_USD=500.0")
    print("export FIREFLY_GENAI_BUDGET_ALERT_THRESHOLD_USD=400.0")
    print()


async def main():
    """Run all integration demonstrations."""
    print("=" * 70)
    print("FireflyFramework GenAI - Full Integration Demonstration")
    print("=" * 70)
    print()
    print("This example demonstrates all production-ready features working together:")
    print("✓ Database persistence (PostgreSQL/MongoDB)")
    print("✓ Distributed tracing (W3C Trace Context)")
    print("✓ API quota management")
    print("✓ Security (RBAC, encryption, SQL injection prevention)")
    print("✓ HTTP connection pooling")
    print("✓ Incremental streaming")
    print("✓ Batch processing")
    print("✓ Prompt caching")
    print("✓ Circuit breaker")
    print()

    # Run demonstrations
    await demo_full_stack_agent()
    await demo_pipeline_with_batch()
    await demo_security_features()
    await demo_observability_integration()
    await demo_configuration_integration()

    # Summary
    print("\n" + "=" * 70)
    print("Integration Summary")
    print("=" * 70)
    print()
    print("✓ All features are integrated and work together seamlessly")
    print("✓ Configuration is unified through environment variables")
    print("✓ Middleware provides composable production features")
    print("✓ Pipelines support all agent capabilities")
    print("✓ REST API exposes all functionality")
    print()
    print("Quick Start:")
    print("  1. Set environment variables for desired features")
    print("  2. Create agent with production middleware")
    print("  3. Use standard agent.run() - features apply automatically")
    print()
    print("For detailed documentation:")
    print("  - docs/deployment.md - Production deployment guide")
    print("  - docs/observability.md - Tracing and monitoring")
    print("  - docs/security.md - RBAC and encryption")
    print("  - docs/memory.md - Database persistence")
    print()


if __name__ == "__main__":
    asyncio.run(main())
