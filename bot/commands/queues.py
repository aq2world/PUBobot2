__all__ = [
	'add', 'remove', 'who', 'add_player', 'remove_player', 'promote', 'start', 'split',
	'reset', 'subscribe', 'server', 'maps', 'map_cooldown',
	'show_map_pools', 'set_map_pool', 'map_pool_add', 'map_pool_remove', 'map_pool_destroy'
]

from core.console import log
import time
from random import choice
from nextcord import Member
from core.utils import error_embed, join_and, find, seconds_to_str
import bot


def _target_queues(ctx, queues: str):
	""" Queues matching the space separated names or aliases in the queues string, case-insensitively """
	targets = queues.lower().split() if queues else []
	return [q for q in ctx.qc.queues if any(
		(t == q.name.lower() or t in (a["alias"].lower() for a in q.cfg.aliases) for t in targets)
	)]


async def add(ctx, queues: str = None):
	""" add author to channel queues """
	phrase = await ctx.qc.check_allowed_to_add(ctx, ctx.author)

	targets = queues.split() if queues else []
	# select the only one queue on the channel
	if not len(targets) and len(ctx.qc.queues) == 1:
		t_queues = ctx.qc.queues

	# select queues requested by user
	elif len(targets):
		if not len(t_queues := _target_queues(ctx, queues)):
			raise bot.Exc.NotFoundError(ctx.qc.gt("Queue '{queue}' not found on the channel.").format(queue=queues.strip()))

	# select active queues or default queues if no active queues
	else:
		t_queues = [q for q in ctx.qc.queues if len(q.queue) and q.cfg.is_default]
		if not len(t_queues):
			t_queues = [q for q in ctx.qc.queues if q.cfg.is_default]

	qr = dict()  # get queue responses
	for q in t_queues:
		qr[q] = await q.add_member(ctx, ctx.author)
		if qr[q] == bot.Qr.QueueStarted:
			await ctx.notice(ctx.qc.topic)
			return

	if len(not_allowed := [q for q in qr.keys() if qr[q] == bot.Qr.NotAllowed]):
		await ctx.error(ctx.qc.gt("You are not allowed to add to {queues} queues.".format(
			queues=join_and([f"**{q.name}**" for q in not_allowed])
		)))

	if bot.Qr.Success in qr.values():
		await ctx.qc.update_expire(ctx.author)
		if phrase:
			await ctx.reply(phrase)
		await ctx.notice(ctx.qc.topic)
		return True
	else:  # have to give some response for slash commands
		await ctx.ignore(content=ctx.qc.topic, embed=error_embed(ctx.qc.gt("Action had no effect."), title=None))

async def remove(ctx, queues: str = None):
	""" add author from channel queues """
	if not (queues or '').strip():
		t_queues = [q for q in ctx.qc.queues if q.is_added(ctx.author)]
	else:
		t_queues = [q for q in _target_queues(ctx, queues) if q.is_added(ctx.author)]

	if len(t_queues):
		for q in t_queues:
			q.pop_members(ctx.author)

		if not any((q.is_added(ctx.author) for q in ctx.qc.queues)):
			bot.expire.cancel(ctx.qc, ctx.author)

		await ctx.notice(ctx.qc.topic)
	else:
		await ctx.ignore(content=ctx.qc.topic, embed=error_embed(ctx.qc.gt("Action had no effect."), title=None))


async def who(ctx, queues: str = None):
	""" List added players """
	if (queues or '').strip():
		t_queues = _target_queues(ctx, queues)
	else:
		t_queues = [q for q in ctx.qc.queues if len(q.queue)]

	if not len(t_queues):
		await ctx.reply(f"> {ctx.qc.gt('no players')}")
	else:
		await ctx.reply("\n".join([f"> **{q.name}** ({q.status}) | {q.who}" for q in t_queues]))


async def add_player(ctx, player: Member, queue: str):
	""" Add a player to a queue """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (p := await ctx.get_member(player)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")

	resp = await q.add_member(ctx, p)
	if resp == bot.Qr.Success:
		await ctx.qc.update_expire(p)
		await ctx.reply(ctx.qc.topic)
	elif resp == bot.Qr.QueueStarted:
		await ctx.reply(ctx.qc.topic)
	elif resp == bot.Qr.Duplicate:
		raise bot.Exc.NoEffect(ctx.qc.gt("{member} is already added to **{queue}**.").format(member=p.mention, queue=q.name))
	elif resp == bot.Qr.QueueFull:
		raise bot.Exc.ValueError(ctx.qc.gt("Queue **{queue}** is full.").format(queue=q.name))
	elif resp == bot.Qr.NotAllowed:
		raise bot.Exc.PermissionError(ctx.qc.gt("{member} is not allowed to add to **{queue}**.").format(
			member=p.mention, queue=q.name
		))
	else:
		await ctx.error(f"Got bad queue response: {resp.__name__}.")


async def remove_player(ctx, player: Member, queues: str = None):
	""" Remove a player from queues """
	ctx.check_perms(ctx.Perms.MODERATOR)

	if (p := await ctx.get_member(player)) is None:
		raise bot.Exc.SyntaxError(ctx.qc.gt("Specified user not found."))
	ctx.author = p
	await remove(ctx, queues=queues)


async def promote(ctx, queue: str = None):
	""" Promote a queue """
	if not queue:
		if (q := next(iter(sorted(
			(i for i in ctx.qc.queues if i.length),
			key=lambda i: i.length, reverse=True
		)), None)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt("Nothing to promote."))
	else:
		if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
			raise bot.Exc.NotFoundError(ctx.qc.gt("Specified queue not found."))

	now = int(time.time())
	if ctx.qc.cfg.promotion_delay and ctx.qc.cfg.promotion_delay+ctx.qc.last_promote > now:
		raise bot.Exc.PermissionError(ctx.qc.gt("You're promoting too often, please wait `{delay}` until next promote.".format(
			delay=seconds_to_str((ctx.qc.cfg.promotion_delay+ctx.qc.last_promote)-now)
		)))

	await q.promote(ctx)
	ctx.qc.last_promote = now


async def start(ctx, queue: str = None):
	""" Manually start a queue, the most populated one if no name is given """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue and queue.strip():
		q = _find_queue(ctx, queue)
	elif (q := max((i for i in ctx.qc.queues if i.length), key=lambda i: i.length, default=None)) is None:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Nothing to start."))
	await q.start(ctx)
	await ctx.reply(ctx.qc.topic)


async def split(ctx, queue: str, group_size: int = None, sort_by_rating: bool = False):
	""" Split queue players into X separate matches """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	await q.split(ctx, group_size=group_size, sort_by_rating=sort_by_rating)
	await ctx.reply(ctx.qc.topic)


async def reset(ctx, queue: str = None):
	""" Reset all or specified queue """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue:
		if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
			raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
		await q.reset()
	else:
		for q in ctx.qc.queues:
			await q.reset()
	await ctx.reply(ctx.qc.topic)


async def subscribe(ctx, queues: str = None, unsub: bool = False):
	if not queues:
		roles = [ctx.qc.cfg.promotion_role] if ctx.qc.cfg.promotion_role else []
	else:
		roles = (q.cfg.promotion_role for q in _target_queues(ctx, queues) if q.cfg.promotion_role)

	if unsub:
		roles = [r for r in roles if r in ctx.author.roles]
		if not len(roles):
			raise bot.Exc.ValueError(ctx.qc.gt("No changes to apply."))
		await ctx.author.remove_roles(*roles, reason="subscribe command")
		await ctx.success(ctx.qc.gt("Removed `{count}` roles from you.").format(
			count=len(roles)
		))

	else:
		roles = [r for r in roles if r not in ctx.author.roles]
		if not len(roles):
			raise bot.Exc.ValueError(ctx.qc.gt("No changes to apply."))
		await ctx.author.add_roles(*roles, reason="subscribe command")
		await ctx.success(ctx.qc.gt("Added `{count}` roles to you.").format(
			count=len(roles)
		))


async def server(ctx, queue: str):
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	if not q.cfg.server:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Server for **{queue}** is not set.").format(
			queue=q.name
		))
	await ctx.success(q.cfg.server, title=ctx.qc.gt("Server for **{queue}**").format(
		queue=q.name
	))

async def maps(ctx, queue: str, one: bool = False):
	""" Show the maps matches will be played on, taking the active map pool into account """
	if (q := find(lambda i: i.name.lower() == queue.lower(), ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	if not len(active := q.active_maps()):
		raise bot.Exc.NotFoundError(ctx.qc.gt("No maps is set for **{queue}**.").format(
			queue=q.name
		))

	if one:
		await ctx.success(f"`{choice(active)}`")
	else:
		if (pool := q.active_pool()) is not None:
			title = ctx.qc.gt("Maps for **{queue}** (pool **{pool}**)").format(queue=q.name, pool=pool['name'])
		else:
			title = ctx.qc.gt("Maps for **{queue}**").format(queue=q.name)
		await ctx.success(", ".join((f"`{i}`" for i in active)), title=title)

async def map_cooldown(ctx, queue: str):
	""" Show the maps on cooldown for a queue and how long the cooldown is """
	q = _find_queue(ctx, queue)
	if not q.cfg.map_cooldown:
		raise bot.Exc.NotFoundError(ctx.qc.gt("Map cooldown is disabled for **{queue}**.").format(queue=q.name))

	title = ctx.qc.gt("Map cooldown for **{queue}**: {matches} matches").format(queue=q.name, matches=q.cfg.map_cooldown)
	if q.cfg.map_cooldown_group:
		title += " " + ctx.qc.gt("(shared with group **{group}**)").format(group=q.cfg.map_cooldown_group)

	if not len(on_cooldown := q.cooldown_maps()):
		await ctx.success(ctx.qc.gt("No maps are on cooldown."), title=title)
		return
	await ctx.success(
		"\n".join((
			ctx.qc.gt("`{map}` - {left} matches left").format(map=m, left=left) for m, left in on_cooldown
		)),
		title=title
	)


def _find_pool(pools, name):
	name = name.strip().lower()
	return find(lambda p: p['name'].lower() == name, pools)


def _find_queue(ctx, queue):
	if not (queue or '').strip():
		raise bot.Exc.SyntaxError("Please provide a queue name.")
	queue = queue.strip().lower()
	if (q := find(lambda i: i.name.lower() == queue, ctx.qc.queues)) is None:
		raise bot.Exc.SyntaxError(f"Queue '{queue}' not found on the channel.")
	return q


async def _save_pools(q, data):
	""" Save pool changes, turning validation errors into user facing errors """
	try:
		await q.cfg.update(data)
	except Exception as e:
		raise bot.Exc.ValueError(str(e))


def _copy_pools(q):
	""" Copy the queue map pools so they can be edited before saving """
	return [dict(name=p['name'], maps=list(p['maps'])) for p in q.cfg.map_pools]


def _split_maps(maps: str):
	""" Parse a comma separated maps string, dropping blanks and duplicates """
	return list(dict.fromkeys(m.strip() for m in maps.split(',') if m.strip()))


async def _show_pool(ctx, q, pool):
	await ctx.success(
		", ".join((f"`{i}`" for i in pool['maps'])) or ctx.qc.gt("no maps"),
		title=ctx.qc.gt("Maps for pool **{pool}** in {queue}.").format(pool=pool['name'], queue=q.name)
	)


async def show_map_pools(ctx, queue: str, pool: str = None):
	""" List the pools of a queue, or the maps of one pool """
	if queue is None:
		raise bot.Exc.SyntaxError("\n".join((
			"Please provide a queue to list its pools. Example: *!pools pickup*",
			"Provide a queue and a pool to list the maps of that pool. Example: *!pools pickup ctf*"
		)))
	q = _find_queue(ctx, queue)
	if not len(q.cfg.map_pools):
		raise bot.Exc.NotFoundError(ctx.qc.gt("No map pools is set for **{queue}**.").format(
			queue=q.name
		))

	if pool and pool.strip():
		if (p := _find_pool(q.cfg.map_pools, pool)) is None:
			raise bot.Exc.NotFoundError(f"Map pool '{pool}' not found on the channel.")
		await _show_pool(ctx, q, p)
	else:
		if (cur := q.find_pool(q.cfg.map_current_pool)) is None:
			cur_pool = "none"
		elif not len(cur['maps']):
			cur_pool = cur['name'] + " " + ctx.qc.gt("(empty, the maps list is used)")
		else:
			cur_pool = cur['name']
		await ctx.success(
			", ".join((f"`{i['name']}`" for i in q.cfg.map_pools)),
			title=ctx.qc.gt("Map pools for **{queue}**.  Active pool: {cur_pool}").format(
				queue=q.name, cur_pool=cur_pool)
		)


async def set_map_pool(ctx, queue: str, pool: str):
	""" Select the queue map pool, 'none' to use the queue maps list """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue is None or pool is None:
		raise bot.Exc.SyntaxError("Please provide queue and pool to set a new pool. Example: *!pool pickup ctf*")
	q = _find_queue(ctx, queue)

	if (p := _find_pool(q.cfg.map_pools, pool)) is not None:
		name = p['name']
	elif pool.strip().lower() in bot.PickupQueue.MAPS_LIST_KEYWORDS:
		name = None
	else:
		raise bot.Exc.NotFoundError(f"Map pool '{pool}' not found on the channel.")

	await _save_pools(q, {"map_current_pool": name})
	text = ctx.qc.gt("Changed map pool for queue **{queue}**. New active pool is **{cur_pool}**").format(
		queue=q.name, cur_pool=name or "none")
	if p is not None and not len(p['maps']):
		text += "\n" + ctx.qc.gt("The pool is empty, the maps list is used until maps are added to it.")
	await ctx.success(text, title=ctx.qc.gt("Map pool changed."))


async def map_pool_add(ctx, queue: str, pool: str, maps: str):
	""" Add maps to a pool, creating the pool if it does not exist """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue is None or pool is None or maps is None:
		raise bot.Exc.SyntaxError("Please provide queue, pool and maps to add. Example: *!pooladd pickup ctf rok,bwcity2*")
	q = _find_queue(ctx, queue)
	if not (new_maps := _split_maps(maps)):
		raise bot.Exc.SyntaxError("Please provide at least one map, separated by commas.")

	pools = _copy_pools(q)
	if (p := _find_pool(pools, pool)) is None:
		try:
			p = dict(name=bot.PickupQueue.validate_pool_name(pool.strip()), maps=[])
		except ValueError as e:
			raise bot.Exc.SyntaxError(str(e))
		pools.append(p)
	p['maps'] += [m for m in new_maps if m not in p['maps']]

	await _save_pools(q, {"map_pools": pools})
	await _show_pool(ctx, q, p)


async def map_pool_remove(ctx, queue: str, pool: str, maps: str):
	""" Remove maps from a pool """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue is None or pool is None or maps is None:
		raise bot.Exc.SyntaxError("Please provide queue, pool and maps to remove. Example: *!pooldel pickup ctf rok,bwcity2*")
	q = _find_queue(ctx, queue)

	pools = _copy_pools(q)
	if (p := _find_pool(pools, pool)) is None:
		raise bot.Exc.NotFoundError(f"Map pool '{pool}' not found on the channel.")
	to_remove = _split_maps(maps)
	if missing := [m for m in to_remove if m not in p['maps']]:
		raise bot.Exc.NotFoundError("Maps not found in pool **{pool}**: {maps}.".format(
			pool=p['name'], maps=", ".join((f"`{m}`" for m in missing))
		))
	p['maps'] = [m for m in p['maps'] if m not in to_remove]

	await _save_pools(q, {"map_pools": pools})
	await _show_pool(ctx, q, p)
	if not len(p['maps']) and q.cfg.map_current_pool and q.cfg.map_current_pool.lower() == p['name'].lower():
		await ctx.notice(ctx.qc.gt("Pool **{pool}** is now empty, the maps list is used until maps are added to it.").format(
			pool=p['name']
		))


async def map_pool_destroy(ctx, queue: str, pool: str):
	""" Delete a pool, falling back to the queue maps list if it was the active one """
	ctx.check_perms(ctx.Perms.MODERATOR)
	if queue is None or pool is None:
		raise bot.Exc.SyntaxError("Please provide queue and pool to destroy. Example: *!pooldestroy pickup ctf*")
	q = _find_queue(ctx, queue)

	pools = _copy_pools(q)
	if (p := _find_pool(pools, pool)) is None:
		raise bot.Exc.NotFoundError(f"Map pool '{pool}' not found on the channel.")
	pools.remove(p)

	data = {"map_pools": pools}
	if q.cfg.map_current_pool and q.cfg.map_current_pool.lower() == p['name'].lower():
		data["map_current_pool"] = None
	await _save_pools(q, data)

	await ctx.success(ctx.qc.gt("Pool **{pool}** in {queue} destroyed.").format(
		pool=p['name'], queue=q.name), title="Pool destroyed.")
