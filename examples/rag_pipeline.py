"""A traced RAG pipeline with the LLM call stubbed out.

    python examples/rag_pipeline.py && evalforge ingest && evalforge trace stats
"""

import random
import time

from evalforge import trace

DOCUMENTS = {
    "france": "Paris has been the capital of France since 987.",
    "japan": "Tokyo became the capital of Japan in 1868.",
    "brazil": "Brasilia was purpose-built as Brazil's capital in 1960.",
}


@trace(name="retrieve", type="retrieval")
def retrieve(question: str) -> list:
    time.sleep(random.uniform(0.01, 0.05))
    return [text for key, text in DOCUMENTS.items() if key in question.lower()]


@trace(type="llm")
def generate(question: str, context: list) -> dict:
    time.sleep(random.uniform(0.05, 0.2))
    if not context:
        raise LookupError(f"no context retrieved for {question!r}")
    return {
        "model": "gpt-4o-mini",
        "usage": {
            "prompt_tokens": 180 + len(" ".join(context)),
            "completion_tokens": random.randint(20, 60),
        },
        "choices": [{"message": {"content": context[0]}}],
    }


@trace(name="rag-pipeline")
def answer(question: str) -> str:
    response = generate(question, retrieve(question))
    return response["choices"][0]["message"]["content"]


def main() -> None:
    questions = [
        "What is the capital of France?",
        "And the capital of Japan?",
        "Which city is the capital of Brazil?",
        "What is the capital of Atlantis?",
    ]
    for question in questions:
        try:
            print(answer(question))
        except LookupError as error:
            print(f"failed: {error}")


if __name__ == "__main__":
    main()
