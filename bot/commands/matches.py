__all__ = [
	'show_matches', 'show_teams', 'set_ready', 'sub_me', 'sub_for', 'put',
	'sub_force', 'cap_me', 'cap_for', 'pick', 'report_admin', 'report', 'report_manual', 'redo', 'parse_redo_args'
]

from nextcord import Member
from typing import List
from functools import wraps

from core.utils import get, find

import bot


def author_match(coro):
	@wraps(coro)
	async def wrapper(ctx, *args, **kwargs):
		if (match := find(lambda m: m.qc == ctx.qc and ctx.author in m.players, bot.active_matches)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt("You are not in an active match."))
		return await coro(ctx, match, *args, **kwargs)
	return wrapper


async def show_matches(ctx):
	matches = [m for m in bot.active_matches if m.qc.id == ctx.qc.id]
	if len(matches):
		await ctx.reply("\n".join((m.print() for m in matches)))
	else:
		await ctx.reply(ctx.qc.gt("> no active matches"))


@author_match
async def show_teams(ctx, match: bot.Match):
	if match.state not in [bot.Match.DRAFT, bot.Match.WAITING_REPORT]:
		raise bot.Exc.MatchStateError('Match must be on draft or waiting report state.')
	await match.draft.print(ctx)


@author_match
async def set_ready(ctx, match: bot.Match, is_ready=True):
	await match.check_in.set_ready(ctx, ctx.author, is_ready)


@author_match
async def sub_me(ctx, match: bot.Match):
	await match.draft.sub_me(ctx, ctx.author)


async def sub_for(ctx, player: Member):
	if (match := find(lambda m: m.qc == ctx.qc and player in m.players, bot.active_matches)) is None:
		raise bot.Exc.NotInMatchError(ctx.qc.gt("Specified user is not in a match."))
	await ctx.qc.check_allowed_to_add(ctx, ctx.author, queue=match.queue)
	await match.draft.sub_for(ctx, player, ctx.author)


async def sub_force(ctx, player1: Member, player2: Member):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and player1 in m.players, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Specified user is not in a match."))
	if any((player2 in m.players for m in bot.active_matches)):
		raise bot.Exc.InMatchError(ctx.qc.gt("Specified user is in an active match."))

	await match.draft.sub_for(ctx, player1, player2, force=True)


@author_match
async def cap_me(ctx, match: bot.Match):
	await match.draft.cap_me(ctx, ctx.author)


@author_match
async def cap_for(ctx, match: bot.Match, team_name: str):
	await match.draft.cap_for(ctx, ctx.author, team_name)


@author_match
async def pick(ctx, match: bot.Match, players: List[Member]):
	await match.draft.pick(ctx, ctx.author, players)


async def put(ctx, match_id: int, player: Member, team_name: str):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and m.id == match_id, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Could not find match with specified id. Check `/matches`."))
	await match.draft.put(ctx, player, team_name)


@author_match
async def redo(ctx, match: bot.Match, queue: str = None, exclude: List[Member] = None):
	"""
	Cancel the match and put its players back into a queue, captains and moderators only.
	The players go to the named queue, or to the match queue, or to its redo queue when they do not fit any more.
	Excluded players are left out of the queue.
	"""
	try:
		ctx.check_perms(ctx.Perms.MODERATOR)
	except bot.Exc.PermissionError:
		if match.has_captains() and not match.is_captain(ctx.author):
			raise bot.Exc.PermissionError(ctx.qc.gt("Only captains or moderators can redo the match."))

	exclude = list(exclude or [])
	if outsiders := [p for p in exclude if p not in match.players]:
		raise bot.Exc.NotFoundError(ctx.qc.gt("{players} are not in the match.").format(
			players=", ".join((p.mention for p in outsiders))
		))
	players = [p for p in match.players if p not in exclude]
	if queue and queue.strip():
		name = queue.strip()
		if (target := find(lambda q: q.name.lower() == name.lower(), ctx.qc.queues)) is None:
			raise bot.Exc.NotFoundError(f"Queue '{name}' not found on the channel.")
		if not target.fits(players):
			raise bot.Exc.ValueError(ctx.qc.gt("Not enough room in **{queue}** to redo the match.").format(queue=target.name))
	elif match.queue.fits(players):
		target = match.queue
	else:
		name = match.queue.cfg.redo_queue or ''
		if (target := find(lambda q: q.name.lower() == name.lower(), ctx.qc.queues)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt(
				"The players do not fit into **{queue}** any more and the redo queue '{redo}' does not exist."
			).format(queue=match.queue.name, redo=name))
		if not target.fits(players):
			raise bot.Exc.ValueError(ctx.qc.gt("Not enough room in **{queue}** to redo the match.").format(queue=target.name))

	await match.cancel(ctx)
	text = ctx.qc.gt("{member} requested a redo, the players were put back into **{queue}**.").format(
		member=ctx.author.mention, queue=target.name
	)
	if len(exclude):
		text += " " + ctx.qc.gt("Left out: {players}.").format(players=", ".join((p.mention for p in exclude)))
	await ctx.notice(text)
	await target.readd(ctx, players)


async def parse_redo_args(ctx, args: str):
	""" Split '!redo [queue] [players...]' into a queue name and excluded members, in any order """
	queue, exclude = None, []
	for token in (args or '').split():
		if (member := await ctx.get_member(token)) is not None:
			exclude.append(member)
		elif queue is None:
			queue = token
		else:
			raise bot.Exc.SyntaxError(ctx.qc.gt("Player '{name}' not found.").format(name=token))
	return queue, exclude


async def report_admin(ctx, match_id: int, winner_team=None, draw=False, abort=False):
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (match := find(lambda m: m.qc == ctx.qc and m.id == match_id, bot.active_matches)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Could not find match with specified id. Check `/matches`."))
	if winner_team is None and not draw and not abort:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Please specify a team name or draw."))

	if abort:
		await match.cancel(ctx)
	else:
		await match.report_win(ctx, winner_team, draw)


@author_match
async def report(ctx, match: bot.Match, result):
	if result == 'loss':
		await match.report_loss(ctx, ctx.author, draw_flag=False)
	elif result == 'draw':
		await match.report_loss(ctx, ctx.author, draw_flag=1)
	elif result == 'abort':
		await match.report_loss(ctx, ctx.author, draw_flag=2)
	else:
		raise bot.Exc.ValueError("Invalid result value.")


async def report_manual(ctx, queue: str, winners: List[Member], losers: List[Member], draw: bool = False):
	""" Report a fake match """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	if any((winners.count(p) != 1 or p in losers for p in winners)):
		raise bot.Exc.ValueError(f"Teams can not contain duplicate players.")
	if any((losers.count(p) != 1 or p in winners for p in losers)):
		raise bot.Exc.ValueError(f"Teams can not contain duplicate players.")
	if not len(winners) or not len(losers):
		raise bot.Exc.ValueError(f"Teams can not be empty.")
	await q.fake_ranked_match(ctx, winners, losers, draw=draw)
