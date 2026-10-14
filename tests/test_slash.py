import asyncio
import time
import types

import pytest

import bot
from bot.context.slash.commands import run_slash
from conftest import log


def _snowflake(age=0.0):
	return int((time.time() - age) * 1000 - 1420070400000) << 22


class FakeResponse:
	def __init__(self):
		self.sent = []
		self.deferred = False

	def is_done(self):
		return bool(self.sent) or self.deferred

	async def send_message(self, *args, **kwargs):
		self.sent.append((args, kwargs))

	async def defer(self):
		self.deferred = True


def _interaction(channel, user, age=0.0):
	return types.SimpleNamespace(
		id=_snowflake(age), channel_id=channel.id, channel=channel, user=user,
		response=FakeResponse(), followup=types.SimpleNamespace(send=channel.send)
	)


@pytest.fixture
def ready(monkeypatch):
	monkeypatch.setattr(bot, "bot_ready", True)


async def test_outdated_interaction_is_skipped(qc, channel, guild, ready):
	interaction = _interaction(channel, guild.me, age=4)
	called = []
	async def cmd(ctx):
		called.append(1)
	await run_slash(cmd, interaction)
	assert not called and not interaction.response.sent


async def test_not_ready_and_not_queue_channel(qc, channel, guild, monkeypatch):
	monkeypatch.setattr(bot, "bot_ready", False)
	interaction = _interaction(channel, guild.me)
	await run_slash(bot.commands.show_queues, interaction)
	assert "under connection" in interaction.response.sent[0][1]["embed"].description

	monkeypatch.setattr(bot, "bot_ready", True)
	bot.queue_channels.clear()
	interaction = _interaction(channel, guild.me)
	await run_slash(bot.commands.show_queues, interaction)
	assert "Not in a queue channel" in interaction.response.sent[0][1]["embed"].description


async def test_command_runs_and_replies(qc, queue, channel, guild, ready):
	interaction = _interaction(channel, guild.me)
	await run_slash(bot.commands.show_queues, interaction)
	assert interaction.response.sent[0][0][0] == "> [**pickup** (0/4)]"


async def test_bot_errors_become_ephemeral_embeds(qc, channel, guild, ready):
	interaction = _interaction(channel, guild.me)
	await run_slash(bot.commands.maps, interaction, queue="nope")
	args, kwargs = interaction.response.sent[0]
	assert kwargs["ephemeral"] and kwargs["embed"].title == "SyntaxError"
	assert "nope" in kwargs["embed"].description


async def test_unexpected_errors_are_reported_and_logged(qc, channel, guild, ready):
	async def broken(ctx):
		raise RuntimeError("kaboom")
	interaction = _interaction(channel, guild.me)
	await run_slash(broken, interaction)
	args, kwargs = interaction.response.sent[0]
	assert kwargs["embed"].title == "RuntimeError" and "kaboom" in kwargs["embed"].description
	assert any("kaboom" in line for level, line in log.lines if level == "error")


async def test_slow_command_is_deferred(qc, channel, guild, ready):
	finished = []
	async def slow(ctx):
		await asyncio.sleep(0.2)
		finished.append(1)
	interaction = _interaction(channel, guild.me, age=2.45)
	await run_slash(slow, interaction)
	assert interaction.response.deferred
	await asyncio.sleep(0.3)
	assert finished, "the shielded command still completes after deferring"
