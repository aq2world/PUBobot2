import pytest

from conftest import db
from core import cfg_factory


class TestListTable:
	async def test_normalises_strings(self):
		table = cfg_factory.ListTable("maps")
		assert await table.validate(' ["urban", " city ", "", 3, "urban"] ', None) == ["urban", "city", "3"]

	async def test_rejects_nested_values(self):
		table = cfg_factory.ListTable("maps")
		with pytest.raises(ValueError):
			await table.validate([{"name": "urban"}], None)
		with pytest.raises(ValueError):
			await table.validate("not a list", None)


def test_verify_error_carries_message():
	assert str(cfg_factory.VerifyError("too big")) == "too big"
	assert str(cfg_factory.VerifyError()) == "Verification failed."


class TestConfigUpdate:
	async def test_writes_database_and_applies(self, queue):
		data = {"size": "6"}
		await queue.cfg.update(data)
		assert queue.cfg.size == 6
		assert data == {"size": "6"}, "caller's dict must not be mutated"
		row = await db.select_one(["cfg_data"], "pq_configs", where={"pq_id": queue.id})
		assert '"size": 6' in row["cfg_data"]

	async def test_verify_failure_changes_nothing(self, queue):
		before = len(db.update_calls)
		with pytest.raises(cfg_factory.VerifyError) as exc:
			await queue.cfg.update({"size": "500"})
		assert "between 2 and 100" in str(exc.value)
		assert queue.cfg.size == 4
		assert len(db.update_calls) == before

	async def test_failed_write_keeps_memory_untouched(self, queue):
		db.fail_updates = True
		with pytest.raises(RuntimeError):
			await queue.cfg.update({"size": "6"})
		assert queue.cfg.size == 4

	async def test_unknown_variable(self, queue):
		with pytest.raises(KeyError):
			await queue.cfg.update({"nope": "1"})

	async def test_duration_variable(self, qc):
		await qc.cfg.update({"lb_last_match_limit": "30d"})
		assert qc.cfg.lb_last_match_limit == 30 * 86400
		await qc.cfg.update({"lb_last_match_limit": None})
		assert qc.cfg.lb_last_match_limit is None

	async def test_table_rows_need_exact_columns(self, queue):
		with pytest.raises(ValueError):
			await queue.cfg.update({"maps": [{"name": "urban", "extra": 1}]})
