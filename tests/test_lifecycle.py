"""Queue start through check-in to a finished or reverted match, driven the way the bot's tick does it."""
import pytest

import bot
from conftest import db


async def _start_match(queue, ctx, players, count=4):
	for p in players[:count]:
		await queue.add_member(ctx, p)
	if not bot.active_matches:  # autostart disabled
		await queue.start(ctx)
	match = bot.active_matches[-1]
	await match.think(0)  # the bot's tick moves INIT -> CHECK_IN
	return match


class TestCheckIn:
	async def test_tick_posts_check_in_message(self, queue, ctx, players, channel, match_counter):
		match = await _start_match(queue, ctx, players)
		assert match.state == match.CHECK_IN
		message = match.check_in.message
		assert message in channel.sent
		assert match.check_in.READY_EMOJI in message.reactions
		assert bot.waiting_reactions[message.id] == match.check_in.process_reaction
		assert message.edits and message.edits[-1]["embed"] is not None

	async def test_all_ready_moves_to_draft(self, queue, ctx, players, match_counter):
		match = await _start_match(queue, ctx, players)
		for p in players[:4]:
			await match.check_in.set_ready(ctx, p, True)
		assert match in bot.active_matches and match.state == match.DRAFT
		assert match.check_in.message.deleted

	async def test_all_ready_finishes_unranked_match(self, queue, ctx, players, match_counter):
		await queue.cfg.update({"map_count": "0", "pick_teams": "random teams"})
		match = await _start_match(queue, ctx, players)
		for p in players[:4]:
			await match.check_in.set_ready(ctx, p, True)
		assert match not in bot.active_matches
		assert match.check_in.message.deleted
		assert len(await db.select(["match_id"], "qc_matches")) == 1
		assert queue.length == 0

	async def test_timeout_reverts_to_queue(self, queue, ctx, players, channel, match_counter):
		await queue.cfg.update({"autostart": "off"})
		match = await _start_match(queue, ctx, players)
		await match.check_in.set_ready(ctx, players[0], True)
		await match.check_in.think(match.start_time + match.check_in.timeout + 1)  # the bot's tick on timeout
		assert match not in bot.active_matches
		assert set(queue.queue) == {players[0]}, "only the ready player keeps the spot"
		assert any("not ready in time" in (m.content or "") for m in channel.sent)

	async def test_abort_refills_from_waiting_players(self, queue, ctx, players, match_counter):
		match = await _start_match(queue, ctx, players)
		await queue.add_member(ctx, players[4])  # joins while the match is checking in
		assert queue.queue == [players[4]]
		for p in players[1:4]:
			await match.check_in.set_ready(ctx, p, True)
		await match.check_in.set_ready(ctx, players[0], False)  # immediate discard aborts
		assert match not in bot.active_matches
		assert len(bot.active_matches) == 1, "ready players plus the waiting one start a new match"
		assert set(bot.active_matches[0].players) == set(players[1:5])
		assert queue.length == 0

	async def test_soft_discard_waits_for_everyone(self, queue, ctx, players, match_counter):
		await queue.cfg.update({"check_in_discard_immediately": "off", "autostart": "off"})
		match = await _start_match(queue, ctx, players)
		await match.check_in.set_ready(ctx, players[0], False)
		assert match in bot.active_matches
		for p in players[1:3]:
			await match.check_in.set_ready(ctx, p, True)
		await match.check_in.set_ready(ctx, players[3], False)
		assert match not in bot.active_matches, "every unready player discarded"
		assert set(queue.queue) == {players[1], players[2]}

	async def test_set_ready_outside_check_in(self, queue, ctx, players, match_counter):
		for p in players[:4]:
			await queue.add_member(ctx, p)
		match = bot.active_matches[-1]
		with pytest.raises(bot.Exc.MatchStateError):
			await match.check_in.set_ready(ctx, players[0], True)

	async def test_history_recorded_on_finish(self, mapped_queue, ctx, players, match_counter, monkeypatch):
		async def no_image(maps):
			return None
		monkeypatch.setattr("bot.match.match.map_stitch_async", no_image)  # no thumbnail downloads
		await mapped_queue.cfg.update({"pick_teams": "random teams"})
		match = await _start_match(mapped_queue, ctx, players)
		assert len(match.maps) == 1
		for p in players[:4]:
			await match.check_in.set_ready(ctx, p, True)
		assert match not in bot.active_matches
		assert mapped_queue.recent_maps() == match.maps
