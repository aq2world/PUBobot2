# -*- coding: utf-8 -*-
import random
import bot
from nextcord.errors import DiscordException
from nextcord import File

from core.utils import join_and
from core.console import log
from .map_stitch import map_stitch


class CheckIn:

	READY_EMOJI = "☑"
	NOT_READY_EMOJI = "⛔"
	INT_EMOJIS = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣", "6⃣", "7⃣", "8⃣", "9⃣"]
	ABC_EMOJIS = ["🇦", "🇧", "🇨", "🇩", "🇪", "🇫", "🇬", "🇭", "🇮", "🇯"]


	def __init__(self, match, timeout):
		self.m = match
		self.timeout = timeout
		self.allow_discard = self.m.cfg['check_in_discard']
		self.ready_players = set()
		self.message = None
		self.srv_vote_message = None
		self.image = None
		self.thumbnail = None

		for p in (p for p in self.m.players if p.id in bot.auto_ready.keys()):
			self.ready_players.add(p)

		self.available_servers = self.m.available_servers()
		self.server_votes = [set() for i in self.available_servers]

		if len(self.m.cfg['maps']) > 1 and self.m.cfg['vote_maps']:
			self.maps = self.m.random_maps(self.m.cfg['maps'], self.m.cfg['vote_maps'], self.m.queue.last_maps)
			maps_img = map_stitch(self.maps)
			# Generate map thumbnails
			self.image = maps_img
			#self.thumbnail = maps_img
			self.map_votes = [set() for i in self.maps]			
		else:
			self.maps = []
			self.map_votes = []

		if self.timeout:
			self.m.states.append(self.m.CHECK_IN)		

	async def think(self, frame_time):
		if frame_time > self.m.start_time + self.timeout:
			ctx = bot.SystemContext(self.m.qc)
			if self.allow_discard:
				await self.abort_timeout(ctx)
			else:
				await self.finish(ctx)

	async def start(self, ctx):	
		# Map voting message
		text = f"!spawn message {self.m.id}"
		if self.image or self.thumbnail:
			files = []
			if self.image:
				files.append(File(self.image, filename='maps-img.jpeg'))
			#if self.thumbnail:
			#	files.append(File(self.thumbnail, filename='maps-thumbs.jpeg'))
			self.message = await ctx.channel.send(text, files=files)
		else:
			self.message = await ctx.channel.send(text)

		emojis = [self.READY_EMOJI, '🔸', self.NOT_READY_EMOJI] if self.allow_discard else [self.READY_EMOJI]
		emojis += [self.INT_EMOJIS[n] for n in range(len(self.maps))]
		try:
			for emoji in emojis:
				await self.message.add_reaction(emoji)
		except DiscordException:
			pass
		bot.waiting_reactions[self.message.id] = self.process_reaction

		# Map voting emojis
		if (self.m.cfg['vote_server']):			
			# Server voting and emojis
			text = f"Vote server ↓"
			self.srv_vote_message = await ctx.channel.send(text)
			#emojis = [self.READY_EMOJI]
			emojis = [self.ABC_EMOJIS[n] for n in range(len(self.available_servers))]
			try:
				for emoji in emojis:
					await self.srv_vote_message.add_reaction(emoji)
			except DiscordException:
				pass
			bot.waiting_reactions[self.srv_vote_message.id] = self.process_srv_reaction
		await self.refresh(ctx)

	async def refresh(self, ctx):
		not_ready = list(filter(lambda m: m not in self.ready_players, self.m.players))
		server_voted = not self.m.cfg['vote_server'] or sum(1 for vote in self.server_votes if vote) > 1

		if len(not_ready) or not server_voted:
			try:
				await self.message.edit(content=None, embed=self.m.embeds.check_in(not_ready, self.m.cfg['vote_server'], 'maps-img.jpeg'))
			except DiscordException:
				pass
		else:
			await self.finish(ctx)


	async def finish(self, ctx):
		bot.waiting_reactions.pop(self.message.id)

		if (self.srv_vote_message):
			bot.waiting_reactions.pop(self.srv_vote_message.id)
		self.ready_players = set()
		
		if len(self.maps):
			order = list(range(len(self.maps)))
			random.shuffle(order)
			order.sort(key=lambda n: len(self.map_votes[n]), reverse=True)
			self.m.maps = [self.maps[n] for n in order[:self.m.cfg['map_count']]]

		if self.m.cfg['vote_server']: 
			# Check if votes higher then zero, otherwise randomize
			if len(self.server_votes) > 1:
				order = list(range(len(self.available_servers)))
				random.shuffle(order)
				order.sort(key=lambda n: len(self.server_votes[n]), reverse=True)
				# Find available server
				ordered_servers = [self.available_servers[n] for n in order]
				i = 0
				self.m.cfg['server'] = ordered_servers[i]
				while self.m.cfg['server'] in bot.active_servers and i < len(ordered_servers):
					i = i + 1
					self.m.cfg['server'] = ordered_servers[i]				
			else:
				self.m.cfg['server'] = self.m.random_server()

		bot.active_servers.append(self.m.cfg['server'])
		await self.message.delete()

		if (self.srv_vote_message):
			await self.srv_vote_message.delete()

		for p in (p for p in self.m.players if p.id in bot.auto_ready.keys()):
			bot.auto_ready.pop(p.id)

		await self.m.next_state(ctx)

	async def process_srv_reaction(self, reaction, user_id, remove=False):
		user_ids = [p.id for p in self.m.players]
		if user_id not in user_ids:
			return
			
		if str(reaction) in self.ABC_EMOJIS:
			idx = self.ABC_EMOJIS.index(str(reaction))
			if remove:
				self.server_votes[idx].discard(user_id)
			else:
				self.server_votes[idx].add(user_id)
			await self.refresh(bot.SystemContext(self.m.queue.qc))

	async def process_reaction(self, reaction, user_id, remove=False):
		user_ids = [p.id for p in self.m.players]
		users = {p.id:p for p in self.m.players}

		if self.m.state != self.m.CHECK_IN or user_id not in user_ids:
			return

		if str(reaction) in self.INT_EMOJIS:
			idx = self.INT_EMOJIS.index(str(reaction))
			if idx <= len(self.maps):
				if remove:
					self.map_votes[idx].discard(user_id)
					self.ready_players.discard(users[user_id])
				else:
					self.map_votes[idx].add(user_id)
					self.ready_players.add(users[user_id])
				await self.refresh(bot.SystemContext(self.m.queue.qc))

		elif str(reaction) == self.READY_EMOJI:
			if remove:
				self.ready_players.discard(users[user_id])
			else:
				self.ready_players.add(users[user_id])
			await self.refresh(bot.SystemContext(self.m.queue.qc))

		elif str(reaction) == self.NOT_READY_EMOJI and self.allow_discard:
			await self.abort_member(bot.SystemContext(self.m.queue.qc), users[user_id])

	async def set_ready(self, ctx, member, ready):
		if self.m.state != self.m.CHECK_IN:
			raise bot.Exc.MatchStateError(self.m.gt("The match is not on the check-in stage."))
		if ready:
			self.ready_players.add(member)
			await self.refresh(ctx)
		elif not ready:
			if not self.allow_discard:
				raise bot.Exc.PermissionError(self.m.gt("Discarding check-in is not allowed."))
			await self.abort_member(ctx, member)

	async def abort_member(self, ctx, member):
		bot.waiting_reactions.pop(self.message.id)
		await self.message.delete()
		await ctx.notice("\n".join((
			self.m.gt("{member} has aborted the check-in.").format(member=f"<@{member.id}>"),
			self.m.gt("Reverting {queue} to the gathering stage...").format(queue=f"**{self.m.queue.name}**")
		)))

		await self.m.clear_server()
		bot.active_matches.remove(self.m)
		await self.m.queue.revert(ctx, [member], [m for m in self.m.players if m != member])

	async def abort_timeout(self, ctx):
		not_ready = [m for m in self.m.players if m not in self.ready_players]
		if self.message:
			bot.waiting_reactions.pop(self.message.id, None)
			try:
				await self.message.delete()
			except DiscordException:
				pass

		await self.m.clear_server()
		bot.active_matches.remove(self.m)

		await ctx.notice("\n".join((
			self.m.gt("{members} was not ready in time.").format(members=join_and([m.mention for m in not_ready])),
			self.m.gt("Reverting {queue} to the gathering stage...").format(queue=f"**{self.m.queue.name}**")
		)))

		await self.m.queue.revert(ctx, not_ready, list(self.ready_players))
