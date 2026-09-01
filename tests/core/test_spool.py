import json
import threading

from evalforge.core.spool import ACTIVE_SUFFIX, SEALED_SUFFIX, SpoolWriter


def test_writes_valid_ndjson(tmp_path):
    writer = SpoolWriter(tmp_path)
    writer.write({"type": "span_end", "id": "a"})
    writer.write({"type": "span_end", "id": "b"})
    writer.close()

    files = list(tmp_path.glob(f"*{SEALED_SUFFIX}"))
    assert len(files) == 1
    records = [json.loads(line) for line in files[0].read_text().splitlines()]
    assert [record["id"] for record in records] == ["a", "b"]


def test_active_file_is_sealed_only_on_close(tmp_path):
    writer = SpoolWriter(tmp_path, flush_lines=1)
    writer.write({"type": "span_end", "id": "a"})

    assert writer.path.name.endswith(ACTIVE_SUFFIX)
    assert not list(tmp_path.glob(f"*{SEALED_SUFFIX}"))

    writer.close()
    assert list(tmp_path.glob(f"*{SEALED_SUFFIX}"))


def test_rotation_seals_and_reopens(tmp_path):
    writer = SpoolWriter(tmp_path, flush_lines=1, rotate_lines=2, rotate_seconds=1e9)
    for index in range(5):
        writer.write({"type": "span_end", "id": str(index)})
    writer.close()

    sealed = sorted(tmp_path.glob(f"*{SEALED_SUFFIX}"))
    assert len(sealed) == 3
    ids = [
        json.loads(line)["id"]
        for path in sealed
        for line in path.read_text().splitlines()
    ]
    assert sorted(ids) == ["0", "1", "2", "3", "4"]


def test_concurrent_writes_lose_nothing(tmp_path):
    writer = SpoolWriter(tmp_path, flush_lines=7)
    barrier = threading.Barrier(8)

    def worker(worker_id):
        barrier.wait()
        for index in range(50):
            writer.write({"type": "span_end", "id": f"{worker_id}-{index}"})

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    writer.close()

    ids = [
        json.loads(line)["id"]
        for path in tmp_path.glob(f"*{SEALED_SUFFIX}")
        for line in path.read_text().splitlines()
    ]
    assert len(ids) == 400
    assert len(set(ids)) == 400


def test_empty_file_is_not_left_behind(tmp_path):
    SpoolWriter(tmp_path).close()
    assert list(tmp_path.iterdir()) == []


def test_write_after_close_is_dropped(tmp_path):
    writer = SpoolWriter(tmp_path)
    writer.close()
    writer.write({"type": "span_end", "id": "a"})
    assert list(tmp_path.iterdir()) == []
