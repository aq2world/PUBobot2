"""A configurable delay between the queue filling and the match starting, so last moment removes still count."""
import time

import pytest

import bot
from core.client import dc


@pytest.fixture
async def delayed(queue):
	await queue.cfg.update({"start_delay": "10s"})
	return queue


async def _fill(queue, ctx, players, count=4):
	responses = [await queue.add_member(ctx, p) for p in players[:count]]
	return responses[-1]


class TestDelayedStart:
	async def test_filling_schedules_instead_of_starting(self, delayed, ctx, players, match_counter):
		assert await _fill(delayed, ctx, players) is bot.Qr.Success
		assert bot.active_matches == [] and delayed.length == 4
		assert delayed.start_at is not None and delayed.start_at > time.time()
		assert any("is full, starting in" in n for n in ctx.notices)

	async def test_starts_when_the_delay_passes(self, delayed, ctx, players, match_counter):
		await _fill(delayed, ctx, players)
		await delayed.think(delayed.start_at - 1)
		assert bot.active_matches == []
		await delayed.think(delayed.start_at)
		assert len(bot.active_matches) == 1 and delayed.length == 0 and delayed.start_at is None
		assert set(bot.active_matches[0].players) == set(players[:4])

	async def test_leaving_cancels_the_start(self, delayed, ctx, players, match_counter):
		await _fill(delayed, ctx, players)
		start_at = delayed.start_at
		delayed.pop_members(players[0])
		assert delayed.start_at is None
		await delayed.think(start_at + 5)
		assert bot.active_matches == [] and delayed.length == 3

	async def test_refilling_after_a_leave_restarts_the_delay(self, delayed, ctx, players, match_counter):
		await _fill(delayed, ctx, players)
		delayed.pop_members(players[0])
		ctx.notices.clear()
		assert await delayed.add_member(ctx, players[4]) is bot.Qr.Success
		assert delayed.start_at is not None and len(ctx.notices) == 1
		await delayed.think(delayed.start_at)
		assert set(bot.active_matches[0].players) == {players[1], players[2], players[3], players[4]}

	async def test_extra_adds_while_pending_are_refused(self, delayed, ctx, players, match_counter):
		await _fill(delayed, ctx, players)
		assert await delayed.add_member(ctx, players[4]) is bot.Qr.QueueFull

	async def test_remove_command_during_delay(self, delayed, ctx, players, match_counter):
		await _fill(delayed, ctx, players)
		ctx.author = players[3]
		await bot.commands.remove(ctx)
		assert delayed.start_at is None and delayed.length == 3
		await delayed.think(time.time() + 60)
		assert bot.active_matches == []

	async def test_no_delay_keeps_immediate_start(self, queue, ctx, players, match_counter):
		assert await _fill(queue, ctx, players) is bot.Qr.QueueStarted
		assert len(bot.active_matches) == 1

	async def test_delay_limits(self, queue):
		for value in ("0s", "6m"):
			with pytest.raises(Exception):
				await queue.cfg.update({"start_delay": value})
		await queue.cfg.update({"start_delay": "5m"})
		assert queue.cfg.start_delay == 300


class TestTickRecovery:
	async def test_full_queue_is_started_by_the_tick(self, queue, ctx, players, match_counter):
		# e.g. restored from saved state, or the size was lowered below the queued count
		queue.queue = list(players[:5])
		bot.active_queues.append(queue)
		await queue.think(time.time())
		assert len(bot.active_matches) == 1
		assert set(bot.active_matches[0].players) == set(players[:4]), "only size players start"
		assert queue.queue == [players[4]]

	async def test_tick_ignores_manual_queues(self, queue, ctx, players):
		await queue.cfg.update({"autostart": "off"})
		queue.queue = list(players[:4])
		await queue.think(time.time())
		assert bot.active_matches == [] and queue.start_at is None

	async def test_tick_with_delay_waits(self, delayed, ctx, players, match_counter):
		delayed.queue = list(players[:4])
		now = time.time()
		await delayed.think(now)
		assert bot.active_matches == [] and delayed.start_at == now + 10
		await delayed.think(now + 10)
		assert len(bot.active_matches) == 1

	async def test_on_think_drives_queues(self, delayed, ctx, players, match_counter, monkeypatch):
		async def noop(frame_time):
			pass
		for target in (bot.expire, bot.noadds, bot.stats.jobs):
			monkeypatch.setattr(target, "think", noop)
		monkeypatch.setattr(bot, "expire_auto_ready", noop)
		await _fill(delayed, ctx, players)
		for handler in dc.events["on_think"]:
			await handler(delayed.start_at + 1)
		assert len(bot.active_matches) == 1


class TestRevertWithDelay:
	async def test_refill_after_abort_waits_for_the_delay(self, delayed, ctx, players, match_counter):
		await _fill(delayed, ctx, players)
		await delayed.think(delayed.start_at)
		match = bot.active_matches[0]
		await match.think(0)
		await delayed.add_member(ctx, players[4])
		await delayed.add_member(ctx, players[5])
		for p in players[1:4]:
			await match.check_in.set_ready(ctx, p, True)
		await match.check_in.set_ready(ctx, players[0], False)
		assert bot.active_matches == [], "no instant restart with a delay configured"
		assert delayed.queue == [players[1], players[2], players[3], players[4], players[5]]
		await delayed.think(delayed.start_at)
		assert set(bot.active_matches[0].players) == {players[1], players[2], players[3], players[4]}
		assert delayed.queue == [players[5]]
