"""Embedding provider implementations."""

from fireflyframework_genai.embeddings.providers.azure import AzureEmbedder
from fireflyframework_genai.embeddings.providers.bedrock import BedrockEmbedder
from fireflyframework_genai.embeddings.providers.cohere import CohereEmbedder
from fireflyframework_genai.embeddings.providers.google import GoogleEmbedder
from fireflyframework_genai.embeddings.providers.mistral import MistralEmbedder
from fireflyframework_genai.embeddings.providers.ollama import OllamaEmbedder
from fireflyframework_genai.embeddings.providers.openai import OpenAIEmbedder
from fireflyframework_genai.embeddings.providers.voyage import VoyageEmbedder

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
