import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from evalforge.core import spool  # noqa: E402
from evalforge.eval import judge  # noqa: E402


@pytest.fixture
def spool_dir(tmp_path):
    """Point the process-wide spool writer at a temporary directory."""
    directory = tmp_path / "spool"
    writer = spool.SpoolWriter(directory, rotate_seconds=0.0)
    spool.set_writer(writer)
    yield directory
    writer.close()
    spool.set_writer(None)


@pytest.fixture
def read_spool(spool_dir):
    def read():
        spool.get_writer().flush()
        records = []
        for path in sorted(spool_dir.iterdir()):
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    records.append(json.loads(line))
        return records

    return read


@pytest.fixture
def judge_stub(monkeypatch):
    """Replace the judge with a scripted responder and record what it was asked."""
    calls = []

    def responder(system, user, model=judge.DEFAULT_MODEL, temperature=0.0):
        calls.append({"system": system, "user": user, "model": model})
        for match, payload in responder.script:
            if match in system or match in user:
                return payload if isinstance(payload, str) else json.dumps(payload)
        return json.dumps(responder.default)

    responder.script = []
    responder.default = {"score": 0.75, "reason": "looks fine"}
    responder.calls = calls
    monkeypatch.setattr(judge, "complete", responder)
    return responder
