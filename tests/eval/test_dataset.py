import pytest

from evalforge.eval import dataset
from evalforge.storage.duckdb_store import Store

ITEMS = [
    {"input": {"question": "capital of France?"}, "expected_output": "Paris"},
    {"input": {"question": "capital of Japan?"}, "expected_output": "Tokyo"},
]


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "evalforge.db") as opened:
        yield opened


def test_create_and_read_back(store):
    created = dataset.create(store, "capitals", ITEMS, description="geography")

    assert dataset.get(store, "capitals").id == created.id
    items = dataset.items(store, created.id)
    assert len(items) == 2
    assert {item.input["question"] for item in items} == {
        "capital of France?",
        "capital of Japan?",
    }
    assert {item.expected_output for item in items} == {"Paris", "Tokyo"}
    assert all(item.dataset_id == created.id for item in items)


def test_duplicate_names_are_rejected(store):
    dataset.create(store, "capitals", ITEMS)
    with pytest.raises(ValueError, match="already exists"):
        dataset.create(store, "capitals", ITEMS)


def test_missing_dataset_says_how_to_make_one(store):
    with pytest.raises(LookupError, match="dataset.create"):
        dataset.resolve(store, "absent")


def test_resolve_accepts_raw_dicts(store):
    found, items = dataset.resolve(store, [{"input": {"question": "q"}}])

    assert found is None
    assert items[0].input == {"question": "q"}
    assert items[0].dataset_id is None


def test_a_bare_input_becomes_the_whole_item(store):
    _, items = dataset.resolve(store, [{"question": "q", "difficulty": "easy"}])
    assert items[0].input == {"question": "q", "difficulty": "easy"}


def test_a_scalar_input_is_wrapped(store):
    _, items = dataset.resolve(store, [{"input": "just a string"}])
    assert items[0].input == {"input": "just a string"}


def test_non_dict_items_are_rejected(store):
    with pytest.raises(TypeError, match="must be dicts"):
        dataset.resolve(store, ["nope"])


def test_listing_counts_items(store):
    dataset.create(store, "capitals", ITEMS)
    assert dataset.listing(store)[0] == {
        "name": "capitals",
        "description": None,
        "items": 2,
        "created_at": dataset.get(store, "capitals").created_at,
    }
