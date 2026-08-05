import asyncio
from dataclasses import dataclass

import tiktoken

from app.services.openai_client import create_openai_client

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536
MAX_TOKENS_PER_REQUEST = 300000
SAFETY_MARGIN = 50000
BATCH_TOKEN_LIMIT = MAX_TOKENS_PER_REQUEST - SAFETY_MARGIN

# Local embedding servers usually ignore the key but the OpenAI SDK still requires one.
CUSTOM_ENDPOINT_API_KEY_PLACEHOLDER = "not-needed"


@dataclass
class EmbeddingResult:
    text: str
    embedding: list[float]


def as_bool(value: object) -> bool:
    """Read a flag that may arrive as a bool from JSON or a string from a form."""
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in ("true", "1", "yes")


@dataclass(frozen=True)
class EmbeddingConfig:
    """Where embeddings come from: OpenAI by default, any compatible endpoint by URL."""

    api_key: str | None = None
    base_url: str | None = None
    model: str = EMBEDDING_MODEL
    dimensions: int = EMBEDDING_DIMENSIONS
    request_dimensions: bool = False

    @property
    def is_custom_endpoint(self) -> bool:
        return bool(self.base_url)


def embedding_config_from_credential(config: dict) -> EmbeddingConfig:
    """Build an embedding config from a decrypted `rag` credential config."""
    dimensions = int(config.get("embedding_dimensions") or EMBEDDING_DIMENSIONS)
    return EmbeddingConfig(
        api_key=(config.get("embedding_api_key") or None),
        base_url=(str(config.get("embedding_base_url") or "").strip() or None),
        model=(str(config.get("embedding_model") or "").strip() or EMBEDDING_MODEL),
        dimensions=dimensions,
        request_dimensions=as_bool(config.get("embedding_request_dimensions")),
    )


class EmbeddingService:
    def __init__(self, config: EmbeddingConfig | str):
        if isinstance(config, str):
            config = EmbeddingConfig(api_key=config)
        self.config = config

        client_kwargs: dict = {"api_key": config.api_key or CUSTOM_ENDPOINT_API_KEY_PLACEHOLDER}
        if config.base_url:
            client_kwargs["base_url"] = config.base_url
        self.client = create_openai_client(**client_kwargs)

        try:
            self.encoding = tiktoken.encoding_for_model(config.model)
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

    def _request_kwargs(self) -> dict:
        """Extra embedding request parameters.

        OpenAI accepts a `dimensions` parameter for text-embedding-3-*, but most
        OpenAI-compatible servers reject unknown parameters, so custom endpoints
        only get it when the credential opts in. Otherwise they use their model's
        native width, which `_check_dimensions` verifies against the credential.
        """
        if self.config.request_dimensions or not self.config.is_custom_endpoint:
            return {"dimensions": self.config.dimensions}
        return {}

    def _check_dimensions(self, embedding: list[float]) -> list[float]:
        if len(embedding) == self.config.dimensions:
            return embedding

        problem = (
            f"Embedding model '{self.config.model}' returned {len(embedding)} "
            f"dimensions, but the credential expects {self.config.dimensions}."
        )
        if self.config.request_dimensions:
            # The endpoint accepted the request but ignored the requested width,
            # which only Matryoshka-capable models honour.
            fix = (
                "The endpoint accepted the request but did not shorten the output, "
                "so this model cannot produce the requested width. Use Qdrant with "
                "the model's native dimensions instead."
            )
        else:
            fix = (
                "Set the credential's dimensions to match the model, or enable "
                "'Ask the endpoint to return N dimensions' if the model can shorten "
                "its output."
            )
        raise ValueError(f"{problem} {fix}")

    def _count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def _split_large_text(self, text: str, max_tokens: int) -> list[str]:
        tokens = self.encoding.encode(text)
        if len(tokens) <= max_tokens:
            return [text]

        parts = []
        for i in range(0, len(tokens), max_tokens):
            part_tokens = tokens[i : i + max_tokens]
            part_text = self.encoding.decode(part_tokens)
            parts.append(part_text)

        return parts

    def _batch_texts_by_tokens(
        self, texts: list[str], max_tokens: int = BATCH_TOKEN_LIMIT
    ) -> list[list[str]]:
        batches = []
        current_batch = []
        current_tokens = 0

        for text in texts:
            text_tokens = self._count_tokens(text)

            if text_tokens > max_tokens:
                if current_batch:
                    batches.append(current_batch)
                    current_batch = []
                    current_tokens = 0

                split_parts = self._split_large_text(text, max_tokens)
                for part in split_parts:
                    batches.append([part])
                continue

            if current_tokens + text_tokens > max_tokens:
                if current_batch:
                    batches.append(current_batch)
                current_batch = [text]
                current_tokens = text_tokens
            else:
                current_batch.append(text)
                current_tokens += text_tokens

        if current_batch:
            batches.append(current_batch)

        return batches

    def embed_text(self, text: str) -> list[float]:
        text_tokens = self._count_tokens(text)
        if text_tokens > MAX_TOKENS_PER_REQUEST:
            raise ValueError(
                f"Text exceeds token limit: {text_tokens} > {MAX_TOKENS_PER_REQUEST}. "
                f"Please split the text into smaller chunks."
            )

        response = self.client.embeddings.create(
            model=self.config.model,
            input=text,
            **self._request_kwargs(),
        )
        return self._check_dimensions(response.data[0].embedding)

    def embed_texts(self, texts: list[str]) -> list[EmbeddingResult]:
        if not texts:
            return []

        batches = self._batch_texts_by_tokens(texts)
        all_results = []

        for batch in batches:
            batch_tokens = sum(self._count_tokens(text) for text in batch)
            if batch_tokens > MAX_TOKENS_PER_REQUEST:
                raise ValueError(
                    f"Batch exceeds token limit: {batch_tokens} > {MAX_TOKENS_PER_REQUEST}. "
                    f"This should not happen. Please check batching logic."
                )

            response = self.client.embeddings.create(
                model=self.config.model,
                input=batch,
                **self._request_kwargs(),
            )

            for embedding_data in response.data:
                all_results.append(
                    EmbeddingResult(
                        text=batch[embedding_data.index],
                        embedding=self._check_dimensions(embedding_data.embedding),
                    )
                )

        return all_results

    async def embed_text_async(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)

    async def embed_texts_async(self, texts: list[str]) -> list[EmbeddingResult]:
        return await asyncio.to_thread(self.embed_texts, texts)
