import time

from conftest import db


async def _player(qc, user_id, rating, last=None, wins=0, hidden=0):
	await db.insert("qc_players", dict(
		channel_id=qc.rating.channel_id, user_id=user_id, nick=f"p{user_id}", rating=rating, deviation=50,
		wins=wins, losses=0, draws=0, streak=0, is_hidden=hidden, last_ranked_match_at=last
	))


class TestLeaderboard:
	async def test_sorted_by_rating(self, qc):
		await _player(qc, 1, 1400)
		await _player(qc, 2, 1600)
		await _player(qc, 3, None)
		assert [p["user_id"] for p in await qc.get_lb()] == [2, 1]

	async def test_hidden_and_min_matches(self, qc):
		await _player(qc, 1, 1400, wins=5)
		await _player(qc, 2, 1600, hidden=1)
		await _player(qc, 3, 1500, wins=1)
		await qc.cfg.update({"lb_min_matches": "2"})
		assert [p["user_id"] for p in await qc.get_lb()] == [1]

	async def test_inactive_players_hidden(self, qc):
		now = int(time.time())
		await _player(qc, 1, 1400, last=now - 10 * 86400)
		await _player(qc, 2, 1600, last=now - 60 * 86400)
		await _player(qc, 3, 1500, last=None)
		assert [p["user_id"] for p in await qc.get_lb()] == [2, 3, 1], "no limit, everyone listed"

		await qc.cfg.update({"lb_last_match_limit": "30d"})
		assert [p["user_id"] for p in await qc.get_lb()] == [1], "old and never-played players hidden"

		await qc.cfg.update({"lb_last_match_limit": "90d"})
		assert [p["user_id"] for p in await qc.get_lb()] == [2, 1]
