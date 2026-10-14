"""The redo command: a captain cancels the match and everyone goes back to the queue."""
import pytest

import bot
from bot.commands import matches as commands


async def _draft_match(queue, ctx, players):
	for p in players[:4]:
		await queue.add_member(ctx, p)
	if not bot.active_matches:  # autostart disabled or delayed
		await queue.start(ctx)
	match = bot.active_matches[-1]
	await match.think(0)
	for p in players[:4]:
		await match.check_in.set_ready(ctx, p, True)
	assert match.state == match.DRAFT
	return match


def _captain(match):
	return match.captains[0]


def _player_ctx(make_ctx, member):
	return make_ctx(author=member, level=bot.Context.Perms.MEMBER)


class TestPermissions:
	async def test_captain_can_redo(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		cap_ctx = _player_ctx(make_ctx, _captain(match))
		await commands.redo(cap_ctx)
		assert match not in bot.active_matches
		assert set(queue.queue) == set(players[:4])
		assert any("requested a redo" in n for n in cap_ctx.notices)

	async def test_regular_player_cannot(self, queue, ctx, make_ctx, players, match_counter):
		match = await _draft_match(queue, ctx, players)
		pleb = next(p for p in players[:4] if not match.is_captain(p))
		with pytest.raises(bot.Exc.PermissionError):
			await commands.redo(_player_ctx(make_ctx, pleb))
		assert match in bot.active_matches

	async def test_moderator_can(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		pleb = next(p for p in players[:4] if not match.is_captain(p))
		await commands.redo(make_ctx(author=pleb, level=bot.Context.Perms.MODERATOR))
		assert match not in bot.active_matches

	async def test_outsider_is_not_in_a_match(self, queue, ctx, make_ctx, players, match_counter):
		await _draft_match(queue, ctx, players)
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.redo(_player_ctx(make_ctx, players[7]))

	async def test_anyone_when_the_match_has_no_captains(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off", "pick_teams": "no teams", "pick_captains": "no captains"})
		for p in players[:4]:
			await queue.add_member(ctx, p)
		await queue.start(ctx)
		match = bot.active_matches[-1]
		assert not match.has_captains()
		await commands.redo(_player_ctx(make_ctx, players[2]))
		assert match not in bot.active_matches and queue.length == 4


class TestPlacement:
	async def test_autostart_rolls_a_new_match(self, queue, ctx, make_ctx, players, match_counter):
		match = await _draft_match(queue, ctx, players)
		await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert len(bot.active_matches) == 1 and bot.active_matches[0] is not match
		assert set(bot.active_matches[0].players) == set(players[:4]) and queue.length == 0

	async def test_start_delay_is_honoured(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"start_delay": "5s"})
		match = await _draft_match(queue, ctx, players)
		await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert bot.active_matches == [] and queue.length == 4 and queue.start_at is not None

	async def test_during_check_in(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off"})
		for p in players[:4]:
			await queue.add_member(ctx, p)
		await queue.start(ctx)
		match = bot.active_matches[-1]
		await match.think(0)
		message_id = match.check_in.message.id
		await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert match not in bot.active_matches and message_id not in bot.waiting_reactions
		assert queue.length == 4

	async def test_returned_players_go_in_front_of_waiting_ones(self, qc, ctx, make_ctx, players, match_counter):
		queue = await qc.new_queue(ctx, "big", 6, bot.PickupQueue)
		await queue.cfg.update({"autostart": "off"})
		for p in players[:4]:
			await queue.add_member(ctx, p)
		await queue.start(ctx)
		match = bot.active_matches[-1]
		await queue.add_member(ctx, players[4])
		await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert queue.queue == players[:4] + [players[4]]


class TestExplicitQueue:
	async def test_players_go_to_the_named_queue(self, qc, queue, ctx, make_ctx, players, match_counter):
		big = await qc.new_queue(ctx, "big", 10, bot.PickupQueue)
		await big.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		cap_ctx = _player_ctx(make_ctx, _captain(match))
		await commands.redo(cap_ctx, queue=" BIG ")
		assert match not in bot.active_matches
		assert set(big.queue) == set(players[:4]) and queue.length == 0
		assert any("**big**" in n for n in cap_ctx.notices)

	async def test_named_queue_must_exist(self, queue, ctx, make_ctx, players, match_counter):
		match = await _draft_match(queue, ctx, players)
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.redo(_player_ctx(make_ctx, _captain(match)), queue="nope")
		assert match in bot.active_matches

	async def test_named_queue_must_have_room(self, qc, queue, ctx, make_ctx, players, match_counter):
		small = await qc.new_queue(ctx, "small", 4, bot.PickupQueue)
		await small.add_member(ctx, players[4])
		match = await _draft_match(queue, ctx, players)
		with pytest.raises(bot.Exc.ValueError):
			await commands.redo(_player_ctx(make_ctx, _captain(match)), queue="small")
		assert match in bot.active_matches and small.queue == [players[4]]

	async def test_blank_name_means_default_behaviour(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		await commands.redo(_player_ctx(make_ctx, _captain(match)), queue="   ")
		assert set(queue.queue) == set(players[:4])


class TestOverflow:
	async def test_moves_everyone_to_the_redo_queue(self, qc, queue, ctx, make_ctx, players, match_counter):
		split = await qc.new_queue(ctx, "split", 10, bot.PickupQueue)
		await split.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		await queue.add_member(ctx, players[4])  # the original queue can take only 3 more now
		cap_ctx = _player_ctx(make_ctx, _captain(match))
		await commands.redo(cap_ctx)
		assert match not in bot.active_matches
		assert set(split.queue) == set(players[:4]) and queue.queue == [players[4]]
		assert any("**split**" in n for n in cap_ctx.notices)

	async def test_redo_queue_name_is_configurable(self, qc, queue, ctx, make_ctx, players, match_counter):
		big = await qc.new_queue(ctx, "big", 10, bot.PickupQueue)
		await big.cfg.update({"autostart": "off"})
		await queue.cfg.update({"redo_queue": "BIG"})
		match = await _draft_match(queue, ctx, players)
		await queue.add_member(ctx, players[4])
		await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert set(big.queue) == set(players[:4])

	async def test_missing_redo_queue_keeps_the_match(self, queue, ctx, make_ctx, players, match_counter):
		match = await _draft_match(queue, ctx, players)
		await queue.add_member(ctx, players[4])
		with pytest.raises(bot.Exc.NotFoundError) as exc:
			await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert "split" in str(exc.value)
		assert match in bot.active_matches and queue.queue == [players[4]]

	async def test_full_redo_queue_keeps_the_match(self, qc, queue, ctx, make_ctx, players, match_counter):
		split = await qc.new_queue(ctx, "split", 6, bot.PickupQueue)
		await split.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		await queue.add_member(ctx, players[4])
		for p in players[5:8]:
			await split.add_member(ctx, p)
		with pytest.raises(bot.Exc.ValueError):
			await commands.redo(_player_ctx(make_ctx, _captain(match)))
		assert match in bot.active_matches


class TestExclude:
	async def test_excluded_players_stay_out(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		cap_ctx = _player_ctx(make_ctx, _captain(match))
		left_out = [p for p in players[:4] if p != _captain(match)][:2]
		await commands.redo(cap_ctx, exclude=left_out)
		assert match not in bot.active_matches
		assert set(queue.queue) == set(players[:4]) - set(left_out)
		redo_notice = next(n for n in cap_ctx.notices if "Left out" in n)
		assert all(p.mention in redo_notice for p in left_out)

	async def test_excluding_everyone_still_cancels(self, queue, ctx, make_ctx, players, match_counter):
		match = await _draft_match(queue, ctx, players)
		await commands.redo(_player_ctx(make_ctx, _captain(match)), exclude=players[:4])
		assert bot.active_matches == [] and queue.length == 0

	async def test_excluded_must_be_in_the_match(self, queue, ctx, make_ctx, players, match_counter):
		match = await _draft_match(queue, ctx, players)
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.redo(_player_ctx(make_ctx, _captain(match)), exclude=[players[7]])
		assert match in bot.active_matches

	async def test_capacity_counts_only_returning_players(self, queue, ctx, make_ctx, players, match_counter):
		await queue.cfg.update({"autostart": "off"})
		match = await _draft_match(queue, ctx, players)
		await queue.add_member(ctx, players[4])  # only three spots left, but one player is excluded
		left_out = next(p for p in players[:4] if p != _captain(match))
		await commands.redo(_player_ctx(make_ctx, _captain(match)), exclude=[left_out])
		assert queue.length == 4 and left_out not in queue.queue

	async def test_text_argument_parsing(self, qc, ctx, queue, players):
		assert await commands.parse_redo_args(ctx, None) == (None, [])
		assert await commands.parse_redo_args(ctx, f" big  {players[0].mention} player2 ") == ("big", [players[0], players[1]])
		assert await commands.parse_redo_args(ctx, f"{players[2].mention} other") == ("other", [players[2]])
		with pytest.raises(bot.Exc.SyntaxError):
			await commands.parse_redo_args(ctx, "big nobody")
