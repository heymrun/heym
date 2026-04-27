import asyncio
from dataclasses import dataclass

import tiktoken
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-large"
EMBEDDING_DIMENSIONS = 1536
MAX_TOKENS_PER_REQUEST = 300000
SAFETY_MARGIN = 50000
BATCH_TOKEN_LIMIT = MAX_TOKENS_PER_REQUEST - SAFETY_MARGIN


@dataclass
class EmbeddingResult:
    text: str
    embedding: list[float]


class EmbeddingService:
    def __init__(self, openai_api_key: str):
        self.client = OpenAI(api_key=openai_api_key)
        try:
            self.encoding = tiktoken.encoding_for_model("text-embedding-3-large")
        except KeyError:
            self.encoding = tiktoken.get_encoding("cl100k_base")

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
            model=EMBEDDING_MODEL,
            input=text,
            dimensions=EMBEDDING_DIMENSIONS,
        )
        return response.data[0].embedding

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
                model=EMBEDDING_MODEL,
                input=batch,
                dimensions=EMBEDDING_DIMENSIONS,
            )

            for embedding_data in response.data:
                all_results.append(
                    EmbeddingResult(
                        text=batch[embedding_data.index],
                        embedding=embedding_data.embedding,
                    )
                )

        return all_results

    async def embed_text_async(self, text: str) -> list[float]:
        return await asyncio.to_thread(self.embed_text, text)

    async def embed_texts_async(self, texts: list[str]) -> list[EmbeddingResult]:
        return await asyncio.to_thread(self.embed_texts, texts)
