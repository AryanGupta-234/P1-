from concurrent.futures import ThreadPoolExecutor
import time

from sentinel import core


def test_insert_id_is_atomic_for_concurrent_writers():
    values = [f"proposal-{index}" for index in range(48)]

    def insert(value):
        return core.insert_id(
            "INSERT INTO events(ts,level,src,msg,data) VALUES(?,?,?,?,?)",
            (time.time(), "info", "insert-id-test", value, "{}"),
        )

    with ThreadPoolExecutor(max_workers=8) as pool:
        ids = list(pool.map(insert, values))

    try:
        assert len(ids) == len(values)
        assert len(set(ids)) == len(values)
        for value, row_id in zip(values, ids):
            rows = core.db("SELECT msg FROM events WHERE id=?", (row_id,))
            assert rows == [(value,)]
    finally:
        for row_id in ids:
            core.db("DELETE FROM events WHERE id=?", (row_id,))


def test_insert_id_rejects_non_insert_statements():
    try:
        core.insert_id("SELECT 1")
    except ValueError as exc:
        assert "INSERT" in str(exc)
    else:
        raise AssertionError("insert_id must reject non-INSERT statements")
