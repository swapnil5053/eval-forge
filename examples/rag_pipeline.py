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


@trace(name="rag-item")
def answer_item(item: dict) -> dict:
    """Entry point for `evalforge eval run`: one dataset item in, one trace out."""
    question = item["question"]
    context = retrieve(question)
    response = generate(question, context)
    return {"output": response["choices"][0]["message"]["content"], "context": context}


def build_dataset() -> None:
    """Create the 'capitals' dataset that examples/experiment.yaml evaluates against."""
    from evalforge.eval import dataset
    from evalforge.storage.duckdb_store import Store

    with Store() as store:
        if dataset.get(store, "capitals") is None:
            dataset.create(
                store,
                "capitals",
                [
                    {"input": {"question": f"What is the capital of {country}?"},
                     "expected_output": text.split()[0]}
                    for country, text in DOCUMENTS.items()
                ],
                description="One question per document in the toy corpus.",
            )


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
