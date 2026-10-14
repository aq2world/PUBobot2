# -*- coding: utf-8 -*-

from time import time
from core.console import log
from core.cfg_factory import FactoryTable, CfgFactory, Variables, VariableTable, ListTable
from core.utils import get_nick, get, find, seconds_to_str, SafeTemplateDict
from core.client import dc
from nextcord import DiscordException

import bot

class PickupQueue:
	cfg_factory = CfgFactory(
		table=FactoryTable(name="pq_configs", p_key="pq_id", f_key="channel_id"),
		name="pq_config",
		sections=["General", "Teams", "Appearance", "Maps"],
		icon='pq.png',
		variables=[
			Variables.StrVar(
				"name",
				display="Queue name",
				section="General",
				notnull=True,
				verify=lambda name: len(name) and not any((c in name for c in ": \t\n")),
				verify_message="Invalid queue name. A queue name should be one word without +-: characters."
			),
			Variables.TextVar(
				"description",
				display="Description",
				section="Appearance",
				description="Set an answer on '!help queue' command."
			),
			Variables.IntVar(
				"size",
				display="Queue size",
				section="General",
				verify=lambda i: 2 <= i <= 100,
				verify_message="Queue size must be between 2 and 100.",
				notnull=True
			),
			Variables.BoolVar(
				"is_default",
				display="is default",
				section="General",
				default=1,
				description="Set if users can add to this queue without specifying its name.",
				notnull=True
			),
			Variables.BoolVar(
				"ranked",
				display="is ranked",
				section="General",
				default=0,
				description="Enable rating features on this queue.",
				notnull=True
			),
			Variables.BoolVar(
				"autostart",
				display="Start when full",
				section="General",
				default=1,
				notnull=True
			),
			Variables.DurationVar(
				"start_delay",
				display="Start delay",
				section="General",
				verify=lambda i: 0 < i <= 300,
				verify_message="Start delay must be between 1 second and 5 minutes.",
				description="\n".join([
					"Wait this long after the queue fills before starting the match.",
					"A player leaving during the delay cancels the start, so a last moment remove is never put in a match."
				])
			),
			Variables.DurationVar(
				"check_in_timeout",
				display="Require check-in",
				section="General",
				verify=lambda i: 0 < i < 3601,
				default=60*5,
				verify_message="Check in timeout must be less than a hour.",
				description="Set the check-in stage duration."
			),
			Variables.BoolVar(
				"check_in_discard",
				display="Allow discard check-in",
				section="General",
				default=1,
				description="".join((
					"Allow to discard participation during the check-in stage ",
					"and abort the match if not everyone is ready in time.")),
				notnull=True
			),
			Variables.BoolVar(
				"check_in_discard_immediately",
				display="Check-in discard immediately",
				section="General",
				default=1,
				description="Revert check-in state immediately when someone discards check-in",
				notnull=True
			),
			Variables.IntVar(
				"team_size",
				display="Force team size",
				section="Teams",
				description="Force a maximum amount of players per team.",
				verify=lambda i: 0 < i < 101
			),
			Variables.OptionVar(
				"pick_teams",
				display="Pick teams",
				section="Teams",
				options=["draft", "matchmaking", "random teams", "no teams"],
				default="draft",
				description="\n".join([
					"Set how teams should be picked:",
					"  draft - host a draft stage where captains will have to pick players",
					"  matchmaking - form teams automatically based on players ratings",
					"  random teams - form teams randomly",
					"  no teams - do not form teams, only print the players list"
				]),
				notnull=True
			),
			Variables.OptionVar(
				"pick_captains",
				display="Pick captains",
				section="Teams",
				options=["by role and rating", "fair pairs", "random with role preference", "random", "no captains"],
				default="by role and rating",
				description="\n".join([
					"Set how captains should be picked (for 'draft' or 'no teams' above):",
					"  by role and rating - sort by captain role and rating and pick the best",
					"  fair pairs - pick random pair of players with closest ratings to each other",
					"  random with role preference - pick captains randomly with preference of the captain role",
					"  random - pick captains randomly",
					"  no captains - do not pick captains automatically"
				]),
				notnull=True
			),
			Variables.StrVar(
				"pick_order",
				display="Teams picking order",
				section="Teams",
				verify=lambda s: set(s) == set("ab"),
				default="abababba",
				verify_message="Pick order can only contain a and b characters.",
				description="a - 1st team picks, b - 2nd team picks, example: ababba"
			),
			Variables.StrVar(
				"team_names",
				display="Team names",
				section="Teams",
				verify=lambda s: len(s.split()) == 2,
				verify_message="Team names must be exactly two words separated by space.",
				description="Team names separated by space, example: Alpha Beta"
			),
			Variables.StrVar(
				"team_emojis",
				display="Team emojis",
				section="Teams",
				verify=lambda s: len(s.split()) == 2,
				verify_message="Team emojis must be exactly two emojis separated by space.",
				description="Team emojis separated by space."
			),
			Variables.BoolVar(
				"show_teams_when_voting",
				display="Show teams while voting maps",
				section="Teams",
				default=1,
				notnull=True,
				description="Show teams when voting maps on check-in."
			),
			Variables.TextVar(
				"start_msg",
				display="Start message",
				section="Appearance",
				verify=lambda s: len(s) < 1001,
				description="Set additional information to be printed on a match start.",
				verify_message="Start message is too long."
			),
			Variables.TextVar(
				"start_direct_msg",
				display="Start direct message",
				section="Appearance",
				verify=lambda s: len(s) < 1001,
				description="\n".join([
					"Set the content of a direct message sent to players when the queue starts.",
					"You can use this aliases in text: {queue}, {channel}, {server}.",
					"If not set, default translated message is used."
				]),
				verify_message="Start direct message is too long."
			),
			Variables.TextVar(
				"server",
				display="Server",
				section="Appearance",
				description="Print this server on a match start.",
				verify=lambda s: len(s) < 501,
				verify_message="Server string is too long."
			),
			VariableTable(
				"servers",
				display="Servers",
				section="Appearance",
				description="List of servers that will be randomly displayed on a match start. Format [{\"name\": \"server:port\"}]",
				variables=[
					Variables.StrVar("name", notnull=True)
				]
			),
			Variables.BoolVar(
				"vote_server",
				display="Enable server voting",
				section="Appearance",
				default=0,
				notnull=True,
				description="Enable server voting from the servers variable. If vote_server is disabled, servers will be randomized."
			),
			Variables.RoleVar(
				"promotion_role",
				display="Promotion role",
				section="General",
				description="Set a role to highlight on !promote and !sub commands."
			),
			Variables.TextVar(
				"promotion_msg",
				display="Promotion message",
				section="Appearance",
				description="Replace default promotion message. You can use {name}, {role} and {left} placeholders in the text."
			),
			Variables.BoolVar(
				"show_streamers",
				display="Show streamers",
				section="Appearance",
				default=1,
				notnull=True,
				description="Show streaming players on a match start."
			),
			Variables.RoleVar(
				"captains_role",
				display="Captains role",
				section="Teams",
				description="Users with this role may have preference in captains choosing process."
			),
			Variables.RoleVar(
				"blacklist_role",
				display="Blacklist role",
				section="General",
				description="Users with this role wont be able to add to this queue."
			),
			Variables.RoleVar(
				"whitelist_role",
				display="Whitelist role",
				section="General",
				description="Only users with this role will be able to add to this queue."
			),
			Variables.DurationVar(
				"match_lifetime",
				display="Match lifetime",
				verify=lambda i: 299 < i < 86401,
				verify_message="Must be not lesser than 5 minutes and not bigger than 24 hours.",
				section="General",
				description="Set a custom match life time before it times out then ranked is enabled. Default: 3 hours."
			),
			Variables.StrVar(
				"map_current_pool",
				display="Current Map Pool",
				section="Maps",
				description="Map pool used for the next matches. If not set, not found or empty, the maps list is used."
			),
			Variables.IntVar(
				"map_count",
				display="Map count",
				section="Maps",
				default=1,
				verify=lambda n: 0 <= n <= 15,
				verify_message="Maps number must be between 0 and 15.",
				description="Number of maps to show on match start."
			),
			Variables.IntVar(
				"map_cooldown",
				display="Map cooldown",
				section="Maps",
				default=1,
				notnull=True,
				verify=lambda n: 0 <= n <= 100,
				verify_message="Map cooldown number must be between 0 and 100.",
				description="\n".join([
					"Prefer to not choose last played map(s) for the next specified matches amount.",
					"This affects map voting pools as well. Set 0 to disable."
				])
			),
			Variables.StrVar(
				"map_cooldown_group",
				display="Map cooldown group",
				section="Maps",
				verify=lambda s: not any((c in s for c in " \t\n")),
				verify_message="Map cooldown group must be one word.",
				description="\n".join([
					"Queues on this channel with the same group name share their played maps history,",
					"so a map played in one queue is on cooldown in the others too. Each queue applies its own map_cooldown."
				])
			),
			VariableTable(
				"map_pools",
				display="Map pools (RAW)",
				section="Maps",
				description="Alternative map pools. Format [{\"name\": \"ctf\", \"maps\": [\"urban\", \"urban2\"]}]",
				default=[],
				variables=[
					Variables.StrVar("name", notnull=True),
					ListTable("maps")
				]
			),
			Variables.IntVar(
				"vote_maps",
				display="Vote poll map count",
				section="Maps",
				default=None,
				verify=lambda n: 2 <= n <= 9,
				verify_message="Vote maps number must be between 2 and 9.",
				description="Set to enable map voting, this requires check-in timeout to be set."
			),
			Variables.StrVar(
				"redo_queue",
				display="Redo queue",
				section="General",
				default="split",
				description="\n".join([
					"Queue that receives the players of a redone match when they no longer fit into this queue,",
					"for example because others joined it in the meantime."
				])
			),
			VariableTable(
				"aliases", display="Aliases", section="General",
				description="Other names for this queue, you can also group queues by giving them a same alias.",
				variables=[
					Variables.StrVar("alias", notnull=True)
				]
			),
			VariableTable(
				"maps", display="Maps", section="Maps",
				description="Default list of maps to choose from. Format [{\"name\": \"urban\"}, {\"name\": \"urban2\"}]",
				variables=[
					Variables.StrVar("name", notnull=True)
				]
			)
		]
	)

	# Words that select the maps list in !pool. 'default' is also accepted there unless a pool has that name,
	# since older versions encouraged a pool called 'default'.
	RESERVED_POOL_NAMES = ('none', 'null')
	MAPS_LIST_KEYWORDS = ('none', 'null', 'default')

	@staticmethod
	def validate_name(name):
		if not len(name) or any((c in name for c in ": \t\n")):
			raise ValueError(f"Invalid queue name '{name}'. A queue name should be one word without +-: characters.")
		return name

	@classmethod
	def validate_pool_name(cls, name):
		""" New pool names are single words and must not collide with the keywords that select the maps list """
		if not len(name) or any((c in name for c in ",: \t\n")) or name.lower() in cls.RESERVED_POOL_NAMES:
			raise ValueError(f"Invalid pool name '{name}'. A pool name must be one word and can not be 'none'.")
		return name

	@classmethod
	async def create(cls, ctx, name, size=2):
		cfg = await cls.cfg_factory.spawn(ctx.channel.guild, f_key=ctx.channel.id)
		try:
			await cfg.update({"name": name, "size": str(size)})
		except Exception:
			# do not leave a half-configured queue in the database
			await cfg.delete()
			raise
		return cls(ctx.qc, cfg)

	def serialize(self):
		return dict(
			queue_type=self.__class__.__name__,
			queue_id=self.id,
			channel_id=self.qc.id,
			players=[i.id for i in self.queue if i]
		)

	@classmethod
	async def from_json(cls, data):
		if (qc := bot.queue_channels.get(data['channel_id'])) is None:
			raise bot.Exc.ValueError("QueueChannel not found.")
		if (q := get(qc.queues, id=data['queue_id'])) is None:
			raise bot.Exc.ValueError("Queue not found.")
		if (guild := dc.get_guild(qc.guild_id)) is None:
			raise bot.Exc.ValueError("Guild not found.")

		players = [guild.get_member(user_id) for user_id in data['players']]
		if None in players:
			# a member who left while the bot was down should not cost the others their place
			log.error(f"Dropping {players.count(None)} missing member(s) from queue '{q.name}' ({q.id}) state.")
			players = [p for p in players if p is not None]

		q.queue = players
		if q.length and q not in bot.active_queues:
			bot.active_queues.append(q)

	def __init__(self, qc, cfg):
		self.qc = qc
		self.cfg = cfg
		self.id = self.cfg.p_key
		self.queue = []
		self.start_at = None  # timestamp of a pending delayed autostart

	@property
	def name(self):
		return self.cfg.name

	@property
	def status(self):  # (length/max)
		return f"{len(self.queue)}/{self.cfg.size}"

	@property
	def who(self):
		return "/".join([f"`{get_nick(m)}`" for m in self.queue])

	@property
	def length(self):
		return len(self.queue)

	MAP_HISTORY_LIMIT = 100  # finished matches kept per history

	@property
	def map_history_key(self):
		""" Queues sharing a map_cooldown_group share one history, other queues have their own """
		if self.cfg.map_cooldown_group:
			return "group:" + self.cfg.map_cooldown_group.lower()
		return "queue:" + str(self.id)

	@property
	def map_history(self):
		""" Finished matches' maps, most recent last. Shared with the queues in the same cooldown group """
		return self.qc.map_history.get(self.map_history_key, [])

	def recent_maps(self):
		""" Maps played in the last map_cooldown matches of this queue's history, these are avoided when picking maps """
		if not self.cfg.map_cooldown:
			return []
		return [m for played in self.map_history[-self.cfg.map_cooldown:] for m in played]

	def cooldown_maps(self):
		""" Maps currently on cooldown as (map, matches left) pairs, the most recently played first """
		if not self.cfg.map_cooldown:
			return []
		result = {}
		window = self.map_history[-self.cfg.map_cooldown:]
		for age, played in enumerate(reversed(window)):  # age 0 is the latest match
			for m in played:
				result.setdefault(m, self.cfg.map_cooldown - age)
		return list(result.items())

	def record_maps(self, maps):
		""" Remember the maps of a finished match """
		if not len(maps):
			return
		history = self.qc.map_history.setdefault(self.map_history_key, [])
		history.append(list(maps))
		del history[:-self.MAP_HISTORY_LIMIT]

	def find_pool(self, name):
		""" Find a map pool by name, case-insensitively """
		name = (name or '').strip().lower()
		return find(lambda p: p['name'].lower() == name, self.cfg.map_pools) if name else None

	def active_pool(self):
		""" The selected map pool if it exists and has maps, otherwise None (the maps list is used) """
		pool = self.find_pool(self.cfg.map_current_pool)
		return pool if pool and len(pool['maps']) else None

	def active_maps(self):
		""" Map names of the active map pool, or of the maps list if no usable pool is selected """
		if (pool := self.active_pool()) is not None:
			return list(pool['maps'])
		return [i['name'] for i in self.cfg.maps]

	def _match_cfg(self):
		return dict(
			team_names=self.cfg.team_names.split() if self.cfg.team_names else None,
			team_emojis=self.cfg.team_emojis.split() if self.cfg.team_emojis else None,
			ranked=self.cfg.ranked, pick_captains=self.cfg.pick_captains,
			captains_role_id=self.cfg.captains_role.id if self.cfg.captains_role else None,
			pick_teams=self.cfg.pick_teams, pick_order=self.cfg.pick_order,
			maps=self.active_maps(), vote_maps=self.cfg.vote_maps,
			map_count=self.cfg.map_count, check_in_timeout=self.cfg.check_in_timeout,
			check_in_discard=self.cfg.check_in_discard, check_in_discard_immediately=self.cfg.check_in_discard_immediately,
			match_lifetime=self.cfg.match_lifetime,
			start_msg=self.cfg.start_msg, server=self.cfg.server, servers=self.cfg.servers,
			vote_server=self.cfg.vote_server, show_teams_when_voting=self.cfg.show_teams_when_voting
		)

	async def promote(self, ctx):
		promotion_role = self.cfg.promotion_role or self.qc.cfg.promotion_role
		promotion_msg = self.cfg.promotion_msg or self.qc.gt("{role} Please add to **{name}** pickup, `{left}` players left!")
		promotion_msg = promotion_msg.format_map(SafeTemplateDict(
			role=promotion_role.mention if promotion_role else "",
			name=self.name,
			left=self.cfg.size-self.length
		))

		if (
			promotion_role and not promotion_role.mentionable and
			ctx.channel.guild.me and not ctx.channel.guild.me.guild_permissions.mention_everyone
		):
			raise bot.Exc.PermissionError("Insufficient permissions to ping the promotion role.")
		else:
			# answers on /slash commands do not ping, so have to answer sth on /slash command first before sending ctx.notice
			await ctx.ignore(ctx.qc.gt("Sending **{queue}** promotion...").format(queue=self.name))
			await ctx.notice(promotion_msg)

	async def reset(self):
		members, self.queue = self.queue, []
		if self in bot.active_queues:
			bot.active_queues.remove(self)

		for member in members:
			if not any((q.is_added(member) for q in self.qc.queues)):
				bot.expire.cancel(self.qc, member)
			try:
				await member.send(content=self.qc.gt("The **{queue}** queue has been cleared, please add again if you want to play.").format(
					queue=self.name
				))
			except DiscordException:
				pass

	async def check_allowed_to_add(self, member):
		if (
			self.cfg.blacklist_role and self.cfg.blacklist_role in member.roles
			or self.cfg.whitelist_role and self.cfg.whitelist_role not in member.roles
		):
			raise bot.Exc.PermissionError(
				self.qc.gt("You are not allowed to add to {queues} queues.".format(queues=self.name))
			)

	async def add_member(self, ctx, member):
		if (
			self.cfg.blacklist_role and self.cfg.blacklist_role in member.roles
			or self.cfg.whitelist_role and self.cfg.whitelist_role not in member.roles
		):
			return bot.Qr.NotAllowed

		if len(self.queue) >= self.cfg.size:
			return bot.Qr.QueueFull

		if member not in self.queue:
			self.queue.append(member)

			if self not in bot.active_queues:
				bot.active_queues.append(self)

			if len(self.queue) == self.cfg.size and self.cfg.autostart:
				if await self.autostart(ctx):
					return bot.Qr.QueueStarted

			return bot.Qr.Success
		else:
			return bot.Qr.Duplicate

	def is_added(self, member):
		return member in self.queue

	def pop_members(self, *members):
		ids = [m.id for m in members]
		members = [member for member in self.queue if member.id in ids]
		for m in members:
			self.queue.remove(m)
		if len(self.queue) < self.cfg.size:
			self.start_at = None  # a pending start is off once the queue is not full any more
		return members

	async def autostart(self, ctx):
		""" The queue has filled up: start now, or schedule the start if a start delay is configured. Returns True if started """
		if not self.cfg.start_delay:
			await self.start(ctx)
			return True
		if self.start_at is None:
			self.start_at = int(time()) + self.cfg.start_delay
			await ctx.notice(self.qc.gt("**{queue}** is full, starting in {delay} unless someone leaves...").format(
				queue=self.name, delay=seconds_to_str(self.cfg.start_delay)
			))
		return False

	async def think(self, frame_time):
		""" Called every bot tick: fire a pending delayed start, or pick up a full queue that never got started """
		if not self.cfg.autostart or len(self.queue) < self.cfg.size:
			self.start_at = None
			return
		if self.start_at is None:
			self.start_at = frame_time + (self.cfg.start_delay or 0)
		if frame_time >= self.start_at:
			self.start_at = None
			await self.start(bot.SystemContext(self.qc))

	async def start(self, ctx):
		if len(self.queue) < 2:
			raise bot.Exc.PubobotException(self.qc.gt("Not enough players to start the queue."))

		self.start_at = None
		players = self.queue[:self.cfg.size]  # anyone beyond the size stays queued for the next match
		if self.cfg.team_size:
			team_size = min(int(self.cfg.size / 2), int(self.cfg.team_size))
		else:
			team_size = int(self.cfg.size / 2)

		# Create the match first so a failure here leaves the players in the queue
		await bot.Match.new(ctx, self, players, team_size=team_size, **self._match_cfg())

		dm_text = self.cfg.start_direct_msg or self.qc.gt("**{queue}** pickup has started @ {channel}!")
		await self.qc.queue_started(
			ctx,
			members=players,
			message=dm_text.format_map(SafeTemplateDict(
				queue=self.name,
				channel=ctx.channel.mention,
				server=self.cfg.server
			))
		)

	async def split(self, ctx, group_size: int = None, sort_by_rating: bool = False):
		group_size = group_size or len(self.queue)//2

		if len(self.queue) < group_size or group_size < 2:
			raise bot.Exc.PubobotException(self.qc.gt("Not enough players to start the queue."))

		if sort_by_rating:
			ratings = {p['user_id']: p['rating'] for p in await ctx.qc.rating.get_players((p.id for p in self.queue))}
			self.queue = sorted(self.queue, key=lambda p: ratings[p.id], reverse=True)

		groups = [self.queue[i-group_size:i] for i in range(group_size, len(self.queue)+1, group_size)]
		for group in groups:
			dm_text = self.cfg.start_direct_msg or self.qc.gt("**{queue}** pickup has started @ {channel}!")
			await self.qc.queue_started(
				ctx,
				members=group,
				message=dm_text.format_map(SafeTemplateDict(
					queue=self.name,
					channel=ctx.channel.mention,
					server=self.cfg.server
				))
			)

			await bot.Match.new(ctx, self, group, team_size=group_size//2, **self._match_cfg())

	async def fake_ranked_match(self, ctx, winners, losers, draw=False):
		if not self.cfg.ranked:
			raise bot.Exc.ValueError("Specified queue is not ranked.")

		await bot.Match.fake_ranked_match(
			ctx, self, self.qc, winners, losers, draw=draw,
			team_names=self.cfg.team_names.split(" ") if self.cfg.team_names else None,
		)

	def fits(self, players):
		""" Whether the given players can be added on top of the current queue """
		return self.length + len([p for p in players if p not in self.queue]) <= self.cfg.size

	async def readd(self, ctx, players):
		""" Put players back at the front of the queue, starting the match if that fills it """
		await self.revert(ctx, [], [p for p in players if p not in self.queue])

	async def revert(self, ctx, not_ready, ready):
		old_players = list(self.queue)
		self.queue = list(ready)
		if self.cfg.autostart:
			while len(self.queue) < self.cfg.size and len(old_players):
				self.queue.append(old_players.pop(0))
			if len(self.queue) >= self.cfg.size:
				self.queue += old_players  # start() only takes the first size players, the rest keep waiting
				await self.autostart(ctx)
			else:
				for p in ready:
					await self.qc.update_expire(p)
		else:
			self.queue = list(ready) + old_players
			for p in ready:
				await self.qc.update_expire(p)

		await ctx.notice(self.qc.topic)
		if self not in bot.active_queues and self.length:
			bot.active_queues.append(self)