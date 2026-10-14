"""
The bot connects to MySQL and Discord at import time. These fixtures replace the config, console,
database and locale modules with in-memory fakes before the bot package is imported.
"""
import os
import sys
import types

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TESTS = os.path.join(ROOT, "tests")
for path in (ROOT, TESTS):
	if path not in sys.path:
		sys.path.insert(0, path)

from fakes import FakeDB, FakeLog, FakeGuild, FakeChannel  # noqa: E402


def _stub_module(name, **attrs):
	module = types.ModuleType(name)
	module.__dict__.update(attrs)
	sys.modules[name] = module
	return module


cfg = types.SimpleNamespace(
	DC_BOT_TOKEN="", DC_CLIENT_ID=0, DC_CLIENT_SECRET="", DC_INVITE_LINK="", DC_OWNER_ID=1,
	DC_SLASH_SERVERS=[], DB_URI="fake://", LOG_LEVEL="ERRORS", COMMANDS_URL="", HELP="", STATUS="",
)
db = FakeDB()
log = FakeLog()
_stub_module("core.config", cfg=cfg, __version__="test")
_stub_module("core.console", log=log)
_stub_module("core.database", db=db, DB_URI="fake://", init_db=lambda uri: db)
_stub_module("core.locales", locales={"en": lambda s: s})

import bot  # noqa: E402
from core.client import dc  # noqa: E402


class TestContext(bot.Context):
	""" Records every reply instead of sending it to Discord """

	def __init__(self, qc, channel, author, level=bot.Context.Perms.ADMIN):
		super().__init__(qc, channel, author)
		self.level = level
		self.replies, self.notices, self.successes, self.errors = [], [], [], []

	@property
	def access_level(self):
		return self.level

	async def reply(self, content=None, embed=None):
		self.replies.append(content)

	async def reply_dm(self, content=None, embed=None):
		self.replies.append(content)

	async def notice(self, content=None, embed=None, file=None):
		self.notices.append(content)

	async def ignore(self, content=None, embed=None):
		self.replies.append(content)

	async def error(self, content, title=None):
		self.errors.append(content)

	async def success(self, content, title=None):
		self.successes.append((content, title))


@pytest.fixture(autouse=True)
def clean_state():
	db.reset()
	log.lines.clear()
	bot.queue_channels.clear()
	bot.active_queues.clear()
	bot.active_matches.clear()
	bot.active_servers.clear()
	bot.waiting_reactions.clear()
	bot.allow_offline.clear()
	bot.auto_ready.clear()
	bot.expire.tasks.clear()
	yield


@pytest.fixture
def guild():
	return FakeGuild(100, "Guild")


@pytest.fixture
def channel(guild):
	return FakeChannel(200, "pickups", guild)


@pytest.fixture
def discord(monkeypatch, guild, channel):
	""" Point the Discord client at the fake guild and channel """
	monkeypatch.setattr(dc, "get_guild", lambda guild_id: guild if guild_id == guild.id else None)
	monkeypatch.setattr(dc, "get_channel", lambda channel_id: channel if channel_id == channel.id else None)
	monkeypatch.setattr(type(dc), "user", property(lambda self: guild.me))
	monkeypatch.setattr(bot.QueueChannel, "_dm_members", _no_dm)
	return dc


async def _no_dm(self, members, *args, **kwargs):
	pass


@pytest.fixture
def players(guild):
	return [guild.add_member(10 + i, f"player{i}") for i in range(1, 9)]


@pytest.fixture
async def qc(discord, channel):
	qc = await bot.QueueChannel.create(channel)
	bot.queue_channels[channel.id] = qc
	return qc


@pytest.fixture
def make_ctx(qc, channel, guild):
	def factory(author=None, level=bot.Context.Perms.ADMIN):
		return TestContext(qc, channel, author or guild.me, level)
	return factory


@pytest.fixture
def ctx(make_ctx):
	return make_ctx()


@pytest.fixture
async def queue(qc, ctx):
	return await qc.new_queue(ctx, "pickup", 4, bot.PickupQueue)


@pytest.fixture
async def match_counter():
	await db.insert("qc_match_id_counter", dict(next_id=1))


MAPS = ["urban", "city", "rok", "teroso", "cliff"]


@pytest.fixture
async def mapped_queue(queue):
	await queue.cfg.update({"maps": [dict(name=m) for m in MAPS]})
	return queue
