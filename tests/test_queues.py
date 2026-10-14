import json
import types

import pytest

import bot
from bot.commands import config as config_commands
from bot.commands import queues as queues_commands
from conftest import db, MAPS
from fakes import FakeRole


class TestCreateQueue:
	@pytest.mark.parametrize("size", [1, 101, 0])
	async def test_size_range(self, qc, ctx, size):
		with pytest.raises(ValueError):
			await qc.new_queue(ctx, "pickup", size, bot.PickupQueue)
		assert qc.queues == []
		assert await db.select(["pq_id"], "pq_configs") == []

	@pytest.mark.parametrize("name", ["", "two words", "a:b"])
	async def test_invalid_names(self, qc, ctx, name):
		with pytest.raises(ValueError):
			await qc.new_queue(ctx, name, 4, bot.PickupQueue)

	async def test_duplicate_name_is_case_insensitive(self, qc, ctx, queue):
		with pytest.raises(ValueError):
			await qc.new_queue(ctx, "PICKUP", 4, bot.PickupQueue)
		assert len(qc.queues) == 1

	async def test_failed_setup_leaves_no_row(self, qc, ctx):
		db.fail_updates = True
		with pytest.raises(RuntimeError):
			await qc.new_queue(ctx, "pickup", 4, bot.PickupQueue)
		assert qc.queues == []
		assert await db.select(["pq_id"], "pq_configs") == []

	async def test_command_reports_errors(self, qc, ctx):
		await config_commands.create_pickup(ctx, "pickup", 4)
		assert ctx.successes[-1][0] == "[**pickup** (0/4)]"
		with pytest.raises(bot.Exc.ValueError):
			await config_commands.create_pickup(ctx, "pickup", 4)
		ctx.level = bot.Context.Perms.MEMBER
		with pytest.raises(bot.Exc.PermissionError):
			await config_commands.create_pickup(ctx, "other", 4)

	async def test_config_size_limits_match_creation(self, queue):
		for size in ("1", "101"):
			with pytest.raises(Exception):
				await queue.cfg.update({"size": size})
		await queue.cfg.update({"size": "100"})
		assert queue.cfg.size == 100


class TestAddMember:
	async def test_add_and_duplicate(self, queue, ctx, players):
		assert await queue.add_member(ctx, players[0]) is bot.Qr.Success
		assert await queue.add_member(ctx, players[0]) is bot.Qr.Duplicate
		assert queue.status == "1/4" and queue in bot.active_queues

	async def test_queue_full(self, queue, ctx, players):
		await queue.cfg.update({"autostart": "off"})
		for p in players[:4]:
			assert await queue.add_member(ctx, p) is bot.Qr.Success
		assert await queue.add_member(ctx, players[4]) is bot.Qr.QueueFull
		assert queue.length == 4

	async def test_blacklisted(self, queue, ctx, players, guild):
		role = FakeRole(300, "banned")
		players[0].roles.append(role)
		queue.cfg.blacklist_role = role
		assert await queue.add_member(ctx, players[0]) is bot.Qr.NotAllowed
		assert await queue.add_member(ctx, players[1]) is bot.Qr.Success

	async def test_autostart_creates_match(self, mapped_queue, ctx, players, match_counter):
		for p in players[:3]:
			assert await mapped_queue.add_member(ctx, p) is bot.Qr.Success
		assert await mapped_queue.add_member(ctx, players[3]) is bot.Qr.QueueStarted
		assert mapped_queue.length == 0
		assert len(bot.active_matches) == 1
		match = bot.active_matches[0]
		assert set(match.players) == set(players[:4])
		assert len(match.maps) == 1 and match.maps[0] in MAPS

	async def test_pop_members(self, queue, ctx, players):
		for p in players[:3]:
			await queue.add_member(ctx, p)
		assert queue.pop_members(players[0], players[5]) == [players[0]]
		assert queue.queue == players[1:3]


class TestDeleteQueue:
	async def test_not_found(self, queue, ctx):
		with pytest.raises(bot.Exc.NotFoundError):
			await config_commands.delete_queue(ctx, "nope")

	async def test_blocked_by_active_match(self, queue, ctx):
		bot.active_matches.append(types.SimpleNamespace(queue=queue))
		with pytest.raises(bot.Exc.PermissionError):
			await config_commands.delete_queue(ctx, "pickup")
		assert queue in ctx.qc.queues

	async def test_removes_queue_and_players(self, qc, queue, ctx, players):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await queue.add_member(ctx, players[0])
		await queue.add_member(ctx, players[1])
		await other.add_member(ctx, players[1])
		bot.expire.set(qc, players[0], 600)
		bot.expire.set(qc, players[1], 600)

		await config_commands.delete_queue(ctx, "PICKUP")

		assert qc.queues == [other]
		assert queue not in bot.active_queues and other in bot.active_queues
		assert await db.select(["pq_id"], "pq_configs", where={"pq_id": queue.id}) == []
		assert bot.expire.get(qc, players[0]) is None, "no longer in any queue"
		assert bot.expire.get(qc, players[1]) is not None, "still in the other queue"
		assert players[0].mention in ctx.notices[0] and players[1].mention in ctx.notices[0]
		assert ctx.replies[-1] == "> [**other** (1/4)]"


class TestMapCooldown:
	async def test_random_maps_avoid_recent(self):
		pool = ["a", "b", "c", "d"]
		for _ in range(20):
			assert set(bot.Match.random_maps(pool, 2, ["a", "b"])) == {"c", "d"}
		assert pool == ["a", "b", "c", "d"], "input must not be mutated"
		assert len(bot.Match.random_maps(pool, 3, ["a", "b"])) == 3, "cooldown yields when too few maps remain"
		assert bot.Match.random_maps([], 2) == []

	async def test_private_history_per_queue(self, qc, ctx, queue):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		queue.record_maps(["urban"])
		assert queue.recent_maps() == ["urban"]
		assert other.recent_maps() == []
		assert set(qc.map_history) == {f"queue:{queue.id}"}

	async def test_shared_group_with_own_cooldowns(self, qc, ctx, queue):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await queue.cfg.update({"map_cooldown_group": "Main", "map_cooldown": "1"})
		await other.cfg.update({"map_cooldown_group": "main", "map_cooldown": "2"})
		queue.record_maps(["urban"])
		other.record_maps(["rok", "city"])
		assert queue.recent_maps() == ["rok", "city"]
		assert other.recent_maps() == ["urban", "rok", "city"]
		assert qc.map_history == {"group:main": [["urban"], ["rok", "city"]]}

	async def test_cooldown_zero_and_cap(self, queue):
		await queue.cfg.update({"map_cooldown": "0"})
		queue.record_maps(["urban"])
		assert queue.recent_maps() == []
		await queue.cfg.update({"map_cooldown": "3"})
		for i in range(150):
			queue.record_maps([str(i)])
		queue.record_maps([])
		assert len(queue.map_history) == bot.PickupQueue.MAP_HISTORY_LIMIT
		assert queue.recent_maps() == ["147", "148", "149"]

	async def test_group_name_must_be_one_word(self, queue):
		with pytest.raises(Exception):
			await queue.cfg.update({"map_cooldown_group": "two words"})

	async def test_match_records_history(self, mapped_queue, ctx, players, match_counter):
		await bot.Match.new(ctx, mapped_queue, players[:4], team_size=2, **mapped_queue._match_cfg())
		match = bot.active_matches[0]
		match.maps = ["urban"]
		await match.finish_match(ctx)
		assert mapped_queue.recent_maps() == ["urban"]
		assert bot.active_matches == []


class TestSavedState:
	async def test_round_trip(self, qc, ctx, queue, players, tmp_path, monkeypatch):
		monkeypatch.chdir(tmp_path)
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await other.cfg.update({"map_cooldown_group": "main"})
		await queue.add_member(ctx, players[0])
		queue.record_maps(["urban", "city"])
		other.record_maps(["rok"])

		bot.save_state()
		saved = json.loads((tmp_path / "saved_state.json").read_text())
		assert [q["players"] for q in saved["queues"]] == [[players[0].id]]
		assert sorted(saved["map_history"], key=lambda h: h["key"]) == [
			dict(channel_id=qc.id, key="group:main", history=[["rok"]]),
			dict(channel_id=qc.id, key=f"queue:{queue.id}", history=[["urban", "city"]]),
		]

		queue.queue.clear()
		bot.active_queues.clear()
		qc.map_history.clear()
		await bot.load_state()
		assert queue.queue == [players[0]] and queue in bot.active_queues
		assert queue.recent_maps() == ["urban", "city"]
		assert other.recent_maps() == ["rok"]

	async def test_missing_file(self, tmp_path, monkeypatch):
		monkeypatch.chdir(tmp_path)
		await bot.load_state()


class TestStartCommand:
	async def test_picks_most_populated_queue(self, qc, ctx, queue, players, match_counter):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await queue.add_member(ctx, players[0])
		for p in players[1:4]:
			await other.add_member(ctx, p)
		await queues_commands.start(ctx)
		assert len(bot.active_matches) == 1 and bot.active_matches[0].queue is other
		assert other.length == 0 and queue.length == 1

	async def test_nothing_to_start(self, queue, ctx):
		with pytest.raises(bot.Exc.NotFoundError):
			await queues_commands.start(ctx)
		with pytest.raises(bot.Exc.NotFoundError):
			await queues_commands.start(ctx, "   ")

	async def test_too_few_players(self, queue, ctx, players):
		await queue.add_member(ctx, players[0])
		with pytest.raises(bot.Exc.PubobotException):
			await queues_commands.start(ctx, "pickup")
		assert queue.length == 1

	async def test_requires_moderator(self, queue, make_ctx):
		with pytest.raises(bot.Exc.PermissionError):
			await queues_commands.start(make_ctx(level=bot.Context.Perms.MEMBER), "pickup")

	async def test_failed_match_creation_keeps_players(self, queue, ctx, players, monkeypatch):
		async def boom(*args, **kwargs):
			raise RuntimeError("database down")
		monkeypatch.setattr(bot.Match, "new", boom)
		for p in players[:2]:
			await queue.add_member(ctx, p)
		with pytest.raises(RuntimeError):
			await queues_commands.start(ctx, "pickup")
		assert queue.queue == players[:2]


class TestAddRemoveCommands:
	async def test_add_to_named_queue(self, qc, ctx, queue, players):
		ctx.author = players[0]
		assert await queues_commands.add(ctx, " PICKUP ") is True
		assert queue.queue == [players[0]]
		assert ctx.notices[-1] == qc.topic

	async def test_add_unknown_queue(self, queue, ctx, players):
		ctx.author = players[0]
		with pytest.raises(bot.Exc.NotFoundError):
			await queues_commands.add(ctx, "nope")

	async def test_add_defaults_to_only_queue(self, queue, ctx, players):
		ctx.author = players[0]
		await queues_commands.add(ctx)
		assert queue.queue == [players[0]]

	async def test_add_while_in_match(self, queue, ctx, players):
		bot.active_matches.append(types.SimpleNamespace(queue=queue, players=[players[0]]))
		ctx.author = players[0]
		with pytest.raises(bot.Exc.InMatchError):
			await queues_commands.add(ctx, "pickup")

	async def test_duplicate_add_has_no_effect(self, queue, ctx, players):
		ctx.author = players[0]
		await queues_commands.add(ctx, "pickup")
		assert await queues_commands.add(ctx, "pickup") is None
		assert queue.length == 1

	async def test_remove_cancels_expire(self, qc, ctx, queue, players):
		ctx.author = players[0]
		await queues_commands.add(ctx, "pickup")
		bot.expire.set(qc, players[0], 600)
		await queues_commands.remove(ctx)
		assert queue.length == 0 and bot.expire.get(qc, players[0]) is None

	async def test_add_player_messages(self, queue, ctx, players):
		await queue.cfg.update({"autostart": "off"})
		await queues_commands.add_player(ctx, players[0].mention, "pickup")
		assert queue.queue == [players[0]]
		with pytest.raises(bot.Exc.NoEffect):
			await queues_commands.add_player(ctx, players[0].mention, "pickup")
		for p in players[1:4]:
			await queues_commands.add_player(ctx, p.mention, "pickup")
		with pytest.raises(bot.Exc.ValueError) as exc:
			await queues_commands.add_player(ctx, players[4].mention, "pickup")
		assert "full" in str(exc.value)

	async def test_remove_player(self, queue, ctx, players):
		await queue.add_member(ctx, players[0])
		await queues_commands.remove_player(ctx, players[0].mention)
		assert queue.length == 0


class TestResetAndSplit:
	async def test_reset_clears_and_notifies(self, qc, ctx, queue, players):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await queue.add_member(ctx, players[0])
		await queue.add_member(ctx, players[1])
		await other.add_member(ctx, players[1])
		bot.expire.set(qc, players[0], 600)
		bot.expire.set(qc, players[1], 600)
		await queues_commands.reset(ctx, "pickup")
		assert queue.length == 0 and queue not in bot.active_queues
		assert bot.expire.get(qc, players[0]) is None
		assert bot.expire.get(qc, players[1]) is not None, "still queued elsewhere"
		assert "pickup" in players[0].sent[-1][1]["content"]

	async def test_reset_all(self, qc, ctx, queue, players):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await queue.add_member(ctx, players[0])
		await other.add_member(ctx, players[1])
		await queues_commands.reset(ctx)
		assert queue.length == 0 and other.length == 0 and bot.active_queues == []

	async def test_split_into_matches(self, qc, ctx, players, match_counter):
		queue = await qc.new_queue(ctx, "big", 10, bot.PickupQueue)
		for p in players:
			await queue.add_member(ctx, p)
		await queues_commands.split(ctx, "big", group_size=4)
		assert len(bot.active_matches) == 2 and queue.length == 0
		assert set(bot.active_matches[0].players) == set(players[:4])

	async def test_split_remainder_stays(self, qc, ctx, players, match_counter):
		queue = await qc.new_queue(ctx, "big", 10, bot.PickupQueue)
		for p in players[:5]:
			await queue.add_member(ctx, p)
		await queues_commands.split(ctx, "big", group_size=4)
		assert len(bot.active_matches) == 1 and queue.queue == [players[4]]

	async def test_split_needs_enough_players(self, queue, ctx, players):
		await queue.add_member(ctx, players[0])
		with pytest.raises(bot.Exc.PubobotException):
			await queues_commands.split(ctx, "pickup", group_size=2)
		with pytest.raises(bot.Exc.PubobotException):
			await queues_commands.split(ctx, "pickup", group_size=1)


class TestMatchConfig:
	async def test_team_names_tolerate_extra_spaces(self, queue):
		await queue.cfg.update({"team_names": "Red   Blue", "team_emojis": "🔴  🔵"})
		cfg = queue._match_cfg()
		assert cfg["team_names"] == ["Red", "Blue"] and cfg["team_emojis"] == ["🔴", "🔵"]

	async def test_restore_drops_missing_members(self, qc, queue, players):
		await bot.PickupQueue.from_json(dict(
			queue_type="PickupQueue", queue_id=queue.id, channel_id=qc.id, players=[players[0].id, 999]
		))
		assert queue.queue == [players[0]] and queue in bot.active_queues


class TestCooldownCommand:
	async def test_disabled(self, queue, ctx):
		await queue.cfg.update({"map_cooldown": "0"})
		with pytest.raises(bot.Exc.NotFoundError):
			await queues_commands.map_cooldown(ctx, "pickup")

	async def test_nothing_on_cooldown(self, queue, ctx):
		await queues_commands.map_cooldown(ctx, " PICKUP ")
		content, title = ctx.successes[-1]
		assert "No maps" in content and "1 matches" in title

	async def test_lists_maps_with_matches_left(self, qc, ctx, queue):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await queue.cfg.update({"map_cooldown": "2", "map_cooldown_group": "main"})
		await other.cfg.update({"map_cooldown_group": "main"})
		queue.record_maps(["urban", "city"])
		other.record_maps(["rok", "urban"])
		queue.record_maps(["cliff"])
		assert queue.cooldown_maps() == [("cliff", 2), ("rok", 1), ("urban", 1)]
		assert other.cooldown_maps() == [("cliff", 1)], "the other queue only looks one match back"

		await queues_commands.map_cooldown(ctx, "pickup")
		content, title = ctx.successes[-1]
		assert content.splitlines() == ["`cliff` - 2 matches left", "`rok` - 1 matches left", "`urban` - 1 matches left"]
		assert "2 matches" in title and "main" in title

	async def test_unknown_queue(self, queue, ctx):
		with pytest.raises(bot.Exc.SyntaxError):
			await queues_commands.map_cooldown(ctx, "nope")
		with pytest.raises(bot.Exc.SyntaxError):
			await queues_commands.map_cooldown(ctx, None)
