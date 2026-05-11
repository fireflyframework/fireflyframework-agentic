"""Embedding provider implementations."""

from fireflyframework_agentic.embeddings.providers.azure import AzureEmbedder
from fireflyframework_agentic.embeddings.providers.bedrock import BedrockEmbedder
from fireflyframework_agentic.embeddings.providers.cohere import CohereEmbedder
from fireflyframework_agentic.embeddings.providers.google import GoogleEmbedder
from fireflyframework_agentic.embeddings.providers.mistral import MistralEmbedder
from fireflyframework_agentic.embeddings.providers.ollama import OllamaEmbedder
from fireflyframework_agentic.embeddings.providers.openai import OpenAIEmbedder
from fireflyframework_agentic.embeddings.providers.voyage import VoyageEmbedder

__all__ = [
    "AzureEmbedder",
    "BedrockEmbedder",
    "CohereEmbedder",
    "GoogleEmbedder",
    "MistralEmbedder",
    "OllamaEmbedder",
    "OpenAIEmbedder",
    "VoyageEmbedder",
]
