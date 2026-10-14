import types

import pytest

import bot
from bot.commands import queues as commands
from bot.context.message.commands import _pool_args
from bot.context.slash import autocomplete
from conftest import MAPS


async def test_maps_list_is_the_default_pool(mapped_queue):
	assert mapped_queue.active_pool() is None
	assert mapped_queue.active_maps() == MAPS
	assert mapped_queue._match_cfg()["maps"] == MAPS


class TestPoolAdd:
	async def test_creates_pool_and_dedupes(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", " rok, city ,, rok ")
		assert mapped_queue.cfg.map_pools == [{"name": "ctf", "maps": ["rok", "city"]}]
		content, title = ctx.successes[-1]
		assert "`rok`" in content and "ctf" in title

	async def test_appends_case_insensitively(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.map_pool_add(ctx, "PICKUP", "CTF", "city,rok")
		assert mapped_queue.cfg.map_pools == [{"name": "ctf", "maps": ["rok", "city"]}]

	@pytest.mark.parametrize("name", ["none", "null", "my pool", "a,b", ""])
	async def test_rejects_bad_new_names(self, mapped_queue, ctx, name):
		with pytest.raises(bot.Exc.SyntaxError):
			await commands.map_pool_add(ctx, "pickup", name, "rok")
		assert mapped_queue.cfg.map_pools == []

	async def test_requires_maps(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.SyntaxError):
			await commands.map_pool_add(ctx, "pickup", "ctf", " , ")

	async def test_unknown_queue(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.SyntaxError):
			await commands.map_pool_add(ctx, "nope", "ctf", "rok")

	async def test_requires_moderator(self, mapped_queue, make_ctx):
		with pytest.raises(bot.Exc.PermissionError):
			await commands.map_pool_add(make_ctx(level=bot.Context.Perms.MEMBER), "pickup", "ctf", "rok")


class TestSetPool:
	async def test_selects_pool_case_insensitively(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "Ctf", "rok,city")
		await commands.set_map_pool(ctx, "pickup", "CTF")
		assert mapped_queue.cfg.map_current_pool == "Ctf"
		assert mapped_queue.active_maps() == ["rok", "city"]
		assert mapped_queue._match_cfg()["maps"] == ["rok", "city"]

	@pytest.mark.parametrize("keyword", ["none", "default", "NULL"])
	async def test_keywords_select_maps_list(self, mapped_queue, ctx, keyword):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.set_map_pool(ctx, "pickup", "ctf")
		await commands.set_map_pool(ctx, "pickup", keyword)
		assert mapped_queue.cfg.map_current_pool is None
		assert mapped_queue.active_maps() == MAPS

	async def test_pool_named_default_wins_over_keyword(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "default", "rok")
		await commands.set_map_pool(ctx, "pickup", "default")
		assert mapped_queue.cfg.map_current_pool == "default"
		assert mapped_queue.active_maps() == ["rok"]

	async def test_unknown_pool(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.set_map_pool(ctx, "pickup", "ctf")

	async def test_missing_pool_falls_back_to_maps_list(self, mapped_queue):
		# a pool name left behind by an older configuration
		await mapped_queue.cfg.update({"map_current_pool": "gone"})
		assert mapped_queue.active_maps() == MAPS

	async def test_empty_pool_falls_back_and_warns(self, mapped_queue, ctx):
		await mapped_queue.cfg.update({"map_pools": [{"name": "ctf", "maps": []}]})
		await commands.set_map_pool(ctx, "pickup", "ctf")
		assert mapped_queue.active_pool() is None
		assert mapped_queue.active_maps() == MAPS
		assert "empty" in ctx.successes[-1][0]


class TestRemoveAndDestroy:
	async def test_remove_maps(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok,city,cliff")
		await commands.map_pool_remove(ctx, "pickup", "ctf", "city, cliff")
		assert mapped_queue.cfg.map_pools == [{"name": "ctf", "maps": ["rok"]}]

	async def test_remove_reports_missing_maps(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok,city")
		with pytest.raises(bot.Exc.NotFoundError) as exc:
			await commands.map_pool_remove(ctx, "pickup", "ctf", "city,nope")
		assert "nope" in str(exc.value)
		assert mapped_queue.cfg.map_pools == [{"name": "ctf", "maps": ["rok", "city"]}]

	async def test_emptying_active_pool_notifies(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.set_map_pool(ctx, "pickup", "ctf")
		await commands.map_pool_remove(ctx, "pickup", "ctf", "rok")
		assert any("empty" in n for n in ctx.notices)
		assert mapped_queue.active_maps() == MAPS

	async def test_destroy_resets_current_pool(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.map_pool_add(ctx, "pickup", "dm", "city")
		await commands.set_map_pool(ctx, "pickup", "ctf")
		await commands.map_pool_destroy(ctx, "pickup", "CTF")
		assert mapped_queue.cfg.map_pools == [{"name": "dm", "maps": ["city"]}]
		assert mapped_queue.cfg.map_current_pool is None

	async def test_destroy_keeps_other_selection(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.map_pool_add(ctx, "pickup", "dm", "city")
		await commands.set_map_pool(ctx, "pickup", "dm")
		await commands.map_pool_destroy(ctx, "pickup", "ctf")
		assert mapped_queue.cfg.map_current_pool == "dm"

	async def test_destroy_unknown(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.map_pool_destroy(ctx, "pickup", "ctf")


class TestShowPools:
	async def test_no_pools(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.show_map_pools(ctx, "pickup")

	async def test_requires_queue(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.SyntaxError):
			await commands.show_map_pools(ctx, None)

	async def test_lists_pools_with_active_one(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.map_pool_add(ctx, "pickup", "dm", "city")
		await commands.set_map_pool(ctx, "pickup", "dm")
		await commands.show_map_pools(ctx, "pickup")
		content, title = ctx.successes[-1]
		assert "`ctf`" in content and "`dm`" in content
		assert "Active pool: dm" in title

	async def test_marks_empty_active_pool(self, mapped_queue, ctx):
		await mapped_queue.cfg.update({"map_pools": [{"name": "ctf", "maps": []}], "map_current_pool": "ctf"})
		await commands.show_map_pools(ctx, "pickup")
		assert "empty" in ctx.successes[-1][1]

	async def test_shows_one_pool(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok,city")
		await commands.show_map_pools(ctx, "pickup", "ctf")
		assert ctx.successes[-1][0] == "`rok`, `city`"

	async def test_unknown_pool(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.show_map_pools(ctx, "pickup", "dm")


class TestMapsCommand:
	async def test_shows_maps_list(self, mapped_queue, ctx):
		await commands.maps(ctx, "pickup")
		content, title = ctx.successes[-1]
		assert content == ", ".join(f"`{m}`" for m in MAPS)
		assert "pool" not in title

	async def test_honours_active_pool(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok,city")
		await commands.set_map_pool(ctx, "pickup", "ctf")
		await commands.maps(ctx, "pickup")
		content, title = ctx.successes[-1]
		assert content == "`rok`, `city`" and "ctf" in title
		for _ in range(10):
			await commands.maps(ctx, "pickup", one=True)
			assert ctx.successes[-1][0] in ("`rok`", "`city`")

	async def test_no_maps(self, queue, ctx):
		with pytest.raises(bot.Exc.NotFoundError):
			await commands.maps(ctx, "pickup")


def test_text_command_argument_splitting():
	assert _pool_args("pickup ctf rok, city", 3) == ["pickup", "ctf", "rok, city"]
	assert _pool_args("pickup", 3) == ["pickup", None, None]
	assert _pool_args(None, 2) == [None, None]
	assert _pool_args("  pickup   ctf  ", 2) == ["pickup", "ctf"]


class TestAutocomplete:
	def _interaction(self, channel_id, queue=None):
		options = [{"name": "pool", "value": "c"}]
		if queue:
			options.insert(0, {"name": "queue", "value": queue})
		return types.SimpleNamespace(channel_id=channel_id, data={"options": options})

	async def test_lists_pools_of_queue(self, mapped_queue, ctx, channel):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.map_pool_add(ctx, "pickup", "Clan", "rok")
		await commands.map_pool_add(ctx, "pickup", "dm", "rok")
		assert await autocomplete.map_pools(self._interaction(channel.id, "Pickup"), "c") == ["ctf", "Clan"]

	async def test_without_queue_or_channel(self, mapped_queue, channel):
		assert await autocomplete.map_pools(self._interaction(channel.id), "c") == []
		assert await autocomplete.map_pools(self._interaction(999, "pickup"), "c") == []

	async def test_subcommand_options(self, mapped_queue, ctx, channel):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		interaction = types.SimpleNamespace(channel_id=channel.id, data={"options": [
			{"name": "sub", "options": [{"name": "queue", "value": "pickup"}]}
		]})
		assert await autocomplete.map_pools(interaction, "") == ["ctf"]


class TestWhitespace:
	""" Padded arguments and config values must behave like their trimmed form """

	async def test_pool_commands_trim_arguments(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, " pickup ", " ctf ", " rok , city ")
		assert mapped_queue.cfg.map_pools == [{"name": "ctf", "maps": ["rok", "city"]}]
		await commands.map_pool_add(ctx, "pickup", " CTF", "cliff")
		assert mapped_queue.cfg.map_pools[0]["maps"] == ["rok", "city", "cliff"]
		await commands.set_map_pool(ctx, "pickup ", " Ctf ")
		assert mapped_queue.cfg.map_current_pool == "ctf"
		await commands.show_map_pools(ctx, " pickup", " ctf ")
		assert ctx.successes[-1][0] == "`rok`, `city`, `cliff`"
		await commands.map_pool_remove(ctx, "pickup", " ctf ", " cliff ")
		assert mapped_queue.cfg.map_pools[0]["maps"] == ["rok", "city"]
		await commands.set_map_pool(ctx, "pickup", " none ")
		assert mapped_queue.cfg.map_current_pool is None
		await commands.map_pool_destroy(ctx, "pickup", " ctf ")
		assert mapped_queue.cfg.map_pools == []

	async def test_blank_pool_argument_lists_pools(self, mapped_queue, ctx):
		await commands.map_pool_add(ctx, "pickup", "ctf", "rok")
		await commands.show_map_pools(ctx, "pickup", "  ")
		assert "Map pools for" in ctx.successes[-1][1]

	async def test_blank_queue_argument(self, mapped_queue, ctx):
		with pytest.raises(bot.Exc.SyntaxError):
			await commands.show_map_pools(ctx, "   ")

	async def test_raw_config_values_are_trimmed(self, mapped_queue):
		await mapped_queue.cfg.update({
			"map_pools": [{"name": " ctf ", "maps": [" rok "]}],
			"map_current_pool": " CTF ",
			"maps": [{"name": " urban "}],
			"aliases": [{"alias": " dm "}],
			"map_cooldown_group": " main ",
		})
		assert mapped_queue.cfg.map_pools == [{"name": "ctf", "maps": ["rok"]}]
		assert mapped_queue.cfg.map_current_pool == "CTF"
		assert mapped_queue.active_maps() == ["rok"]
		assert mapped_queue.cfg.maps == [{"name": "urban"}]
		assert mapped_queue.cfg.aliases == [{"alias": "dm"}]
		assert mapped_queue.map_history_key == "group:main"

	async def test_blank_string_config_is_null(self, mapped_queue):
		await mapped_queue.cfg.update({"map_current_pool": "   "})
		assert mapped_queue.cfg.map_current_pool is None
		with pytest.raises(ValueError):
			await mapped_queue.cfg.update({"name": "   "})


class TestQueueTargets:
	async def test_names_and_aliases_with_odd_spacing(self, qc, ctx, queue):
		other = await qc.new_queue(ctx, "other", 4, bot.PickupQueue)
		await other.cfg.update({"aliases": [{"alias": "dm"}]})
		assert commands._target_queues(ctx, "  PICKUP   dm ") == [queue, other]
		assert commands._target_queues(ctx, "nope") == []
		assert commands._target_queues(ctx, None) == []

	async def test_who_with_blank_argument_lists_populated(self, qc, ctx, queue, players):
		await queue.add_member(ctx, players[0])
		await commands.who(ctx, "   ")
		assert "pickup" in ctx.replies[-1] and players[0].name in ctx.replies[-1]
		await commands.who(ctx, " other ")
		assert ctx.replies[-1] == "> no players"
