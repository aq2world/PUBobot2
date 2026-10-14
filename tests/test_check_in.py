import pytest

import bot
from conftest import MAPS
from fakes import FakeMessage


def _ratings(players):
	return {p.id: 1500 for p in players}


async def _voting_match(queue, players):
	await queue.cfg.update({"vote_maps": "3", "servers": [dict(name="srv1"), dict(name="srv2")], "vote_server": "on"})
	return bot.Match(1, queue, queue.qc, players[:4], _ratings(players), team_size=2, **queue._match_cfg())


class TestVoteSetup:
	async def test_vote_maps_sampled_from_active_maps(self, mapped_queue, players):
		match = await _voting_match(mapped_queue, players)
		assert len(match.check_in.maps) == 3 and set(match.check_in.maps) <= set(MAPS)
		assert match.check_in.map_votes == [set(), set(), set()]
		assert match.maps == [], "maps are decided by the vote, not pre-rolled"

	async def test_no_vote_without_check_in(self, mapped_queue, players):
		await mapped_queue.cfg.update({"vote_maps": "3", "check_in_timeout": None})
		match = bot.Match(1, mapped_queue, mapped_queue.qc, players[:4], _ratings(players), **mapped_queue._match_cfg())
		assert match.check_in.maps == [] and match.check_in.timeout == 0

	async def test_new_match_rolls_maps_when_not_voting(self, mapped_queue, ctx, players, match_counter):
		await mapped_queue.cfg.update({"map_count": "2"})
		await bot.Match.new(ctx, mapped_queue, players[:4], team_size=2, **mapped_queue._match_cfg())
		match = bot.active_matches[0]
		assert len(match.maps) == 2 and set(match.maps) <= set(MAPS)
		assert match.check_in.maps == []


class TestSerialize:
	async def test_round_trip(self, mapped_queue, players):
		match = await _voting_match(mapped_queue, players)
		ci = match.check_in
		ci.map_votes[0].add(players[0].id)
		ci.map_votes[2].update({players[1].id, players[2].id})
		ci.server_votes[1].add(players[3].id)
		ci.discarded_players.add(players[1])

		data = ci.serialize()
		assert data["maps"] == ci.maps
		assert data["discarded_players"] == [players[1].id]

		fresh = (await _voting_match(mapped_queue, players)).check_in
		fresh.restore(data, players[:4])
		assert fresh.maps == ci.maps
		assert fresh.map_votes == ci.map_votes
		assert fresh.server_votes == ci.server_votes
		assert fresh.discarded_players == {players[1]}

	async def test_restore_is_defensive(self, mapped_queue, players):
		ci = (await _voting_match(mapped_queue, players)).check_in
		original_maps = list(ci.maps)
		ci.restore(None, players[:4])
		assert ci.maps == original_maps

		ci.restore({"maps": ["a", "b"], "map_votes": [[1]], "server_votes": [[2]], "discarded_players": [999]}, players[:4])
		assert ci.maps == ["a", "b"]
		assert ci.map_votes == [{1}, set()], "vote slots are padded to the maps"
		assert ci.server_votes == [set(), set()], "mismatching server votes are ignored"
		assert ci.discarded_players == set(), "unknown players are dropped"

	async def test_match_serialize_includes_check_in(self, mapped_queue, players):
		match = await _voting_match(mapped_queue, players)
		assert match.serialize()["check_in"]["maps"] == match.check_in.maps


class TestReactions:
	async def _check_in_match(self, queue, players):
		match = await _voting_match(queue, players)
		match.state = match.CHECK_IN
		match.check_in.message = FakeMessage()
		return match

	async def test_vote_index_guards(self, mapped_queue, players):
		match = await self._check_in_match(mapped_queue, players)
		ci = match.check_in
		await ci.process_reaction(ci.INT_EMOJIS[2], players[0].id)
		assert ci.map_votes[2] == {players[0].id} and players[0] in ci.ready_players
		await ci.process_reaction(ci.INT_EMOJIS[3], players[1].id)  # beyond the three vote maps
		await ci.process_reaction(ci.ABC_EMOJIS[2], players[1].id)  # beyond the two servers
		assert players[1] not in ci.ready_players
		assert all(len(v) == 0 for v in ci.server_votes)
		await ci.process_reaction(ci.ABC_EMOJIS[1], players[1].id)
		assert ci.server_votes[1] == {players[1].id}

	async def test_outsiders_are_ignored(self, mapped_queue, players):
		match = await self._check_in_match(mapped_queue, players)
		ci = match.check_in
		await ci.process_reaction(ci.INT_EMOJIS[0], players[7].id)
		assert ci.map_votes[0] == set()

	async def test_discard_and_ready_again(self, mapped_queue, players):
		await mapped_queue.cfg.update({"check_in_discard_immediately": "off"})
		match = await self._check_in_match(mapped_queue, players)
		ci = match.check_in
		bot.active_matches.append(match)
		await ci.process_reaction(ci.NOT_READY_EMOJI, players[0].id)
		assert ci.discarded_players == {players[0]}
		assert match in bot.active_matches, "a soft discard must not abort the match"
		await ci.process_reaction(ci.READY_EMOJI, players[0].id)
		assert ci.discarded_players == set() and players[0] in ci.ready_players
