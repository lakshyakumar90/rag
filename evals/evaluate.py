"""RAG evaluation harness.

Runs a fixed question set through the real chunker, retrieval repository, RRF
fusion, reranker hook and grounded-answer pipeline, then reports retrieval,
answer and citation metrics for a matrix of configurations.

Run from the repo root:
    .venv/Scripts/python.exe evals/evaluate.py

Everything runs locally on SQLite: no API keys, network calls or Docker needed.
The embedding and reranking implementations are deterministic stand-ins (see
evals/README.md); swap them for real providers to score a production stack.
"""

import argparse
import asyncio
import os
import hashlib
import json
import math
import re
import sys
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API_DIR = ROOT / "apps/api"
sys.path.insert(0, str(API_DIR))

from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

import services.chat as chat_module  # noqa: E402
from core.config import get_settings  # noqa: E402
from core.rrf import reciprocal_rank_fusion  # noqa: E402
from models import (  # noqa: E402
    Base,
    Document,
    DocumentChunk,
    DocumentStatus,
    MembershipRole,
    User,
    Workspace,
)
from providers.llm.types import ChatMessage, Completion, Usage  # noqa: E402
from providers.rerank import RerankScore  # noqa: E402
from repositories.retrieval import RetrievalRepository  # noqa: E402
from schemas import SearchResponse  # noqa: E402
from services.chat import ChatService  # noqa: E402
from services.retrieval import RetrievalService  # noqa: E402
from services.workspaces import WorkspaceContext  # noqa: E402
from workers.chunking import chunk_document  # noqa: E402
from workers.extraction import ExtractedPage, ExtractionResult  # noqa: E402

EVALS = Path(__file__).resolve().parent
PAGE_RE = re.compile(r"^===\s*PAGE\s+(\d+)\s*===\s*$", re.M)
TOKEN_RE = re.compile(r"[a-z0-9]+")
DIGIT_RE = re.compile(r"\d+")
SOURCE_RE = re.compile(
    r'<source number="(\d+)" document="([^"]+)"(?: page="([^"]+)")?>\s*(.*?)</source>',
    re.S,
)
SENT_RE = re.compile(r"(?<=[.!?])\s+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "at",
    "be",
    "by",
    "do",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "to",
    "was",
    "what",
    "when",
    "where",
    "which",
    "who",
    "with",
    "you",
    "your",
}
DIM = 768


def terms(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_RE.findall(text.lower())
        if len(token) > 1 and token not in STOPWORDS
    ]


def normalize(text: str) -> str:
    return " ".join(TOKEN_RE.findall(text.lower()))


def unit(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    return [value / norm for value in vector] if norm else vector


class HashingEmbedder:
    """Deterministic signed feature hashing — a fast local embedding stand-in."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim

    @property
    def name(self) -> str:
        return f"hashing-{self.dim}"

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        vector = [0.0] * self.dim
        for token in terms(text):
            digest = hashlib.blake2b(token.encode(), digest_size=8).digest()
            index = int.from_bytes(digest[:4], "big") % self.dim
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign
        return unit(vector)


class TfidfEmbedder:
    """Corpus-fitted TF-IDF vectors — a second, very different local model."""

    def __init__(self, dim: int = DIM) -> None:
        self.dim = dim
        self.idf: dict[str, float] = {}

    @property
    def name(self) -> str:
        return "tfidf-768"

    def fit(self, texts: list[str]) -> "TfidfEmbedder":
        document_freq: Counter[str] = Counter()
        for text in texts:
            document_freq.update(set(terms(text)))
        total = len(texts)
        self.idf = {
            token: 1.0 + math.log((1 + total) / (1 + count))
            for token, count in sorted(document_freq.items())[: self.dim]
        }
        return self

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self.embed_query(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        counts = Counter(terms(text))
        vector = [counts.get(token, 0) * weight for token, weight in self.idf.items()]
        vector.extend([0.0] * (self.dim - len(vector)))
        return unit(vector)


class LexicalReranker:
    """Deterministic term-overlap stand-in for a cross-encoder reranker."""

    enabled = True

    async def rerank(self, query: str, texts: list[str]) -> list[RerankScore]:
        query_terms = set(terms(query))
        digits = set(DIGIT_RE.findall(query))
        scores = []
        for index, text in enumerate(texts):
            overlap = len(query_terms & set(terms(text))) / max(1, len(query_terms))
            number_bonus = 0.1 * sum(1 for digit in digits if digit in text)
            scores.append(RerankScore(index=index, score=overlap + number_bonus))
        return scores


class ExtractiveLLM:
    """Pick the context sentence that best matches the question and cite it."""

    async def complete(self, messages: list[ChatMessage], **_opts) -> Completion:
        prompt = messages[-1].content
        question = prompt.split("\n\n", 1)[0].removeprefix("Question: ")
        query_terms = set(terms(question))
        digits = set(DIGIT_RE.findall(question))
        best: tuple[str, int] | None = None
        best_score = 0.0
        for match in SOURCE_RE.finditer(prompt):
            number = int(match.group(1))
            text = re.sub(r"<[^>]+>", "", match.group(4))
            for sentence in SENT_RE.split(text):
                sentence = sentence.strip()
                if not sentence:
                    continue
                score = len(query_terms & set(terms(sentence))) + 0.5 * sum(
                    1 for digit in digits if digit in sentence
                )
                if score > best_score:
                    best_score = score
                    best = (sentence, number)
        if best is None:
            return Completion("I don't know", "stop", Usage(1, 1))
        return Completion(f"{best[0]} [{best[1]}]", "stop", Usage(2, 2))

    async def close(self) -> None:
        return None


class FixedRetrieval:
    """Feed a precomputed search response through the real ChatService."""

    def __init__(self, response: SearchResponse) -> None:
        self.response = response

    async def search(self, *_args, **_kwargs) -> SearchResponse:
        return self.response


@dataclass(frozen=True)
class Variant:
    chunk_tokens: int
    embedding: str
    mode: str  # "vector" or "hybrid"
    rerank: bool

    @property
    def label(self) -> str:
        rerank = "rerank" if self.rerank else "plain"
        return f"chunk={self.chunk_tokens} {self.embedding} {self.mode} {rerank}"


def load_corpus() -> dict[str, ExtractionResult]:
    corpus: dict[str, ExtractionResult] = {}
    for path in sorted((EVALS / "corpus").glob("*.txt")):
        parts = PAGE_RE.split(path.read_text(encoding="utf-8"))
        pages = [
            ExtractedPage(int(parts[index]), parts[index + 1].strip())
            for index in range(1, len(parts), 2)
            if parts[index + 1].strip()
        ]
        corpus[path.name] = ExtractionResult(pages=pages, page_count=len(pages))
    return corpus


def load_questions() -> list[dict]:
    with (EVALS / "questions.jsonl").open(encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


async def build_workspace(
    variant: Variant,
    corpus: dict[str, ExtractionResult],
    embedder: HashingEmbedder | TfidfEmbedder,
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], WorkspaceContext]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        user = User(email="eval@example.com", password_hash="x")
        session.add(user)
        await session.flush()
        workspace = Workspace(name="Eval", slug="eval", created_by=user.id)
        session.add(workspace)
        await session.flush()
        for filename, extraction in corpus.items():
            document = Document(
                workspace_id=workspace.id,
                uploaded_by=user.id,
                filename=filename,
                mime_type="text/plain",
                size=sum(len(page.text) for page in extraction.pages),
                sha256=uuid.uuid4().hex + uuid.uuid4().hex,
                storage_key=f"{workspace.id}/{uuid.uuid4()}",
                status=DocumentStatus.READY,
                page_count=extraction.page_count,
                embedding_model=embedder.name,
                embedding_dim=embedder.dim,
            )
            session.add(document)
            await session.flush()
            chunks = chunk_document(
                extraction,
                strategy="paragraph",
                target_tokens=variant.chunk_tokens,
                overlap_tokens=max(0, variant.chunk_tokens // 5),
            )
            vectors = embedder.embed_documents([chunk.text for chunk in chunks])
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True)):
                session.add(
                    DocumentChunk(
                        document_id=document.id,
                        workspace_id=workspace.id,
                        chunk_index=chunk.index if chunk.index >= 0 else index,
                        page_number=chunk.page_number,
                        content=chunk.text,
                        token_count=chunk.token_count,
                        heading_path=list(chunk.heading_path) or None,
                        embedding=vector,
                    )
                )
        await session.commit()
        context = WorkspaceContext(
            user=user, workspace=workspace, role=MembershipRole.OWNER
        )
    return engine, factory, context


async def run_variant(
    variant: Variant,
    corpus: dict[str, ExtractionResult],
    questions: list[dict],
    settings,
) -> dict:
    embedder: HashingEmbedder | TfidfEmbedder
    if variant.embedding == "tfidf-768":
        all_text = " ".join(
            page.text for extraction in corpus.values() for page in extraction.pages
        )
        embedder = TfidfEmbedder().fit([all_text])
    else:
        embedder = HashingEmbedder(int(variant.embedding.split("-")[1]))

    engine, factory, context = await build_workspace(variant, corpus, embedder)
    original_factory = chat_module.create_llm_provider
    chat_module.create_llm_provider = lambda _name: ExtractiveLLM()
    hits: Counter[int] = Counter()
    correct = 0
    citation_correct = 0
    citation_present = 0
    idk_unanswerable = 0
    false_idk = 0
    try:
        async with factory() as session:
            repo = RetrievalRepository(session)
            reranker = LexicalReranker() if variant.rerank else None
            service = RetrievalService(session, embedder, reranker)
            for question in questions:
                vector = embedder.embed_query(question["question"])
                vector_hits = await repo.vector_search(
                    context.workspace.id, vector, settings.retrieval_candidate_k
                )
                keyword_hits = (
                    await repo.keyword_search(
                        context.workspace.id,
                        question["question"],
                        settings.retrieval_candidate_k,
                    )
                    if variant.mode == "hybrid"
                    else []
                )
                fused = reciprocal_rank_fusion(
                    vector_hits, keyword_hits, k=settings.rrf_k
                )
                ranked, _ = await service._rerank(question["question"], fused)
                top = ranked[: settings.retrieval_top_k]
                answerable = bool(top) and (
                    top[0].score >= settings.retrieval_score_threshold
                )
                search = SearchResponse(
                    answer=None if answerable else "I don't know",
                    answerable=answerable,
                    threshold=settings.retrieval_score_threshold,
                    items=[RetrievalService._to_result(item) for item in top],
                )
                response = await ChatService(FixedRetrieval(search)).answer(
                    context, question["question"]
                )
                answer = response.answer
                expected = normalize(question["expected_answer"])
                if question["answerable"]:
                    for k in (1, 3, 5):
                        if any(
                            item.filename == question["expected_doc"]
                            and item.page_number in question["expected_pages"]
                            for item in top[:k]
                        ):
                            hits[k] += 1
                    if expected in normalize(answer):
                        correct += 1
                    if response.citations:
                        citation_present += 1
                        if any(
                            citation.filename == question["expected_doc"]
                            and citation.page_number in question["expected_pages"]
                            for citation in response.citations
                        ):
                            citation_correct += 1
                    if answer == "I don't know":
                        false_idk += 1
                elif answer == "I don't know":
                    idk_unanswerable += 1
    finally:
        chat_module.create_llm_provider = original_factory
        await engine.dispose()

    answerable_count = sum(1 for question in questions if question["answerable"])
    unanswerable_count = len(questions) - answerable_count
    return {
        "variant": variant.label,
        "chunk_tokens": variant.chunk_tokens,
        "embedding": variant.embedding,
        "mode": variant.mode,
        "rerank": variant.rerank,
        "hit@1": hits[1] / answerable_count,
        "hit@3": hits[3] / answerable_count,
        "hit@5": hits[5] / answerable_count,
        "answer_correctness": correct / answerable_count,
        "citation_accuracy": citation_correct / answerable_count,
        "citation_presence": citation_present / answerable_count,
        "idk_accuracy": idk_unanswerable / unanswerable_count,
        "false_idk_rate": false_idk / answerable_count,
    }


def format_markdown_table(rows: list[dict]) -> str:
    lines = [
        "| Variant | Recall@1 | Recall@3 | Recall@5 | Faithfulness | Citation Acc | IDK Acc |",
        "| :--- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            f"| `{row['variant']}` | {row['hit@1']:.2f} | {row['hit@3']:.2f} "
            f"| {row['hit@5']:.2f} | {row['answer_correctness']:.2f} "
            f"| {row['citation_accuracy']:.2f} | {row['idk_accuracy']:.2f} |"
        )
    return "\n".join(lines)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RAG Workspace Evaluation CLI")
    parser.add_argument(
        "--fast",
        action="store_true",
        help="Run only the primary hybrid+rerank production variant.",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print a Markdown summary table (also written to GITHUB_STEP_SUMMARY).",
    )
    parser.add_argument(
        "--fail-under-recall",
        type=float,
        default=0.0,
        help="Exit non-zero if best Recall@5 drops below this floor.",
    )
    parser.add_argument(
        "--fail-under-faithfulness",
        type=float,
        default=0.0,
        help="Exit non-zero if best Faithfulness/Answer accuracy drops below this floor.",
    )
    parser.add_argument(
        "--fail-under-citation",
        type=float,
        default=0.0,
        help="Exit non-zero if best Citation Accuracy drops below this floor.",
    )
    return parser.parse_args(argv)


async def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = get_settings()
    settings.retrieval_candidate_k = 20
    settings.retrieval_top_k = 5
    settings.retrieval_score_threshold = 0.15
    settings.rrf_k = 60
    corpus = load_corpus()
    questions = load_questions()
    if args.fast:
        variants = [
            Variant(
                chunk_tokens=256, embedding="tfidf-768", mode="hybrid", rerank=True
            )
        ]
    else:
        variants = [
            Variant(chunk_tokens=size, embedding=embedding, mode=mode, rerank=rerank)
            for size in (128, 256, 512)
            for embedding in ("hashing-256", "hashing-768", "tfidf-768")
            for mode in ("vector", "hybrid")
            for rerank in (False, True)
        ]
    rows = []
    for index, variant in enumerate(variants, start=1):
        rows.append(await run_variant(variant, corpus, questions, settings))
        print(f"[{index:02d}/{len(variants)}] {variant.label}", flush=True)

    result = {
        "generated_at": datetime.now(UTC).isoformat(),
        "documents": len(corpus),
        "questions": len(questions),
        "answerable_questions": sum(1 for q in questions if q["answerable"]),
        "unanswerable_questions": sum(1 for q in questions if not q["answerable"]),
        "settings": {
            "candidate_k": settings.retrieval_candidate_k,
            "top_k": settings.retrieval_top_k,
            "score_threshold": settings.retrieval_score_threshold,
            "rrf_k": settings.rrf_k,
        },
        "rows": rows,
    }
    target = EVALS / "results.json"
    target.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(f"\nWrote {target}")

    md_table = format_markdown_table(rows)
    if args.markdown:
        print("\n" + md_table)
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write("## RAG Evaluation Summary\n\n" + md_table + "\n")
    else:
        header = ("variant", "hit@1", "hit@3", "hit@5", "answer", "citation", "idk")
        print(
            f"{header[0]:<48} {header[1]:>7} {header[2]:>7} {header[3]:>7} "
            f"{header[4]:>7} {header[5]:>9} {header[6]:>7}"
        )
        for row in rows:
            print(
                f"{row['variant']:<48} {row['hit@1']:>7.2f} {row['hit@3']:>7.2f} "
                f"{row['hit@5']:>7.2f} {row['answer_correctness']:>7.2f} "
                f"{row['citation_accuracy']:>9.2f} {row['idk_accuracy']:>7.2f}"
            )

    best_recall = max(row["hit@5"] for row in rows)
    best_faith = max(row["answer_correctness"] for row in rows)
    best_cite = max(row["citation_accuracy"] for row in rows)

    failures: list[str] = []
    if best_recall < args.fail_under_recall:
        failures.append(
            f"Recall@5 {best_recall:.3f} < floor {args.fail_under_recall:.3f}"
        )
    if best_faith < args.fail_under_faithfulness:
        failures.append(
            f"Faithfulness {best_faith:.3f} < floor {args.fail_under_faithfulness:.3f}"
        )
    if best_cite < args.fail_under_citation:
        failures.append(
            f"Citation Accuracy {best_cite:.3f} < floor {args.fail_under_citation:.3f}"
        )

    if failures:
        print("\nREGRESSION GATE FAILED:", file=sys.stderr)
        for msg in failures:
            print(f"  - {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
