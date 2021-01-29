# -*- coding: utf-8 -*-
from time import time
from itertools import combinations
import random

import bot
from core.utils import find, get, iter_to_dict
from core.client import dc

from .check_in import CheckIn
from .draft import Draft
from .embeds import Embeds


class Match:

	INIT = 0
	CHECK_IN = 1
	DRAFT = 2
	WAITING_REPORT = 3

	TEAM_EMOJIS = [
		":fox:", ":wolf:", ":dog:", ":bear:", ":panda_face:", ":tiger:", ":lion:", ":pig:", ":octopus:", ":boar:",
		":scorpion:", ":crab:", ":eagle:", ":shark:", ":bat:", ":rhino:", ":dragon_face:", ":deer:"
	]

	default_cfg = dict(
		teams=None, team_names=['Alpha', 'Beta'], team_emojis=None, ranked=False,
		max_players=None, pick_captains="no captains", captains_role_id=None, pick_teams="draft",
		pick_order=None, maps=[], map_count=0, check_in_timeout=0,
		match_lifetime=0, start_msg=None, server=None
	)

	class Team(list):
		""" Team is basically a set of member objects, but we need it ordered so list is used """

		def __init__(self, name=None, emoji=None, players=None, idx=-1):
			super().__init__(players or [])
			self.name = name
			self.emoji = emoji
			self.want_draw = False
			self.idx = idx

		def set(self, players):
			self.clear()
			self.extend(players)

		def add(self, p):
			if p not in self:
				self.append(p)

		def rem(self, p):
			if p in self:
				self.remove(p)

	@classmethod
	async def new(cls, queue, qc, players, **kwargs):
		# Create the Match object
		ratings = {p['user_id']: p['rating'] for p in await qc.rating.get_ratings((p.id for p in players))}
		match = cls(0, queue, qc, players, ratings, **kwargs)
		# Prepare the Match object
		match.init_maps(match.cfg['maps'], match.cfg['map_count'])
		match.init_captains(match.cfg['pick_captains'], match.cfg['captains_role_id'])
		match.init_teams(match.cfg['pick_teams'])
		if match.cfg['ranked']:
			match.states.append(match.WAITING_REPORT)
		bot.active_matches.append(match)

	def serialize(self):
		return dict(
			match_id=self.id,
			queue_id=self.queue.id,
			channel_id=self.qc.channel.id,
			cfg=self.cfg,
			players=[p.id for p in self.players],
			teams=[[p.id for p in team] for team in self.teams],
			maps=self.maps,
			state=self.state,
			states=self.states,
			ready_players=[p.id for p in self.check_in.ready_players]
		)

	@classmethod
	async def from_json(cls, queue, qc, data):
		# Prepare discord objects
		data['players'] = [qc.channel.guild.get_member(user_id) for user_id in data['players']]
		if None in data['players']:
			await qc.error(f"Unable to load match {data['match_id']}, error fetching guild members.")
			return

		# Fill data with discord objects
		for i in range(len(data['teams'])):
			data['teams'][i] = [get(data['players'], id=user_id) for user_id in data['teams'][i]]
		data['ready_players'] = [get(data['players'], id=user_id) for user_id in data['ready_players']]

		# Create the Match object
		ratings = {p['user_id']: p['rating'] for p in await qc.rating.get_ratings((p.id for p in data['players']))}
		match = cls(data['match_id'], queue, qc, data['players'], ratings, **data['cfg'])

		# Set state data
		for i in range(len(match.teams)):
			match.teams[i].set(data['teams'][i])
		match.check_in.ready_players = data['ready_players']
		match.maps = data['maps']
		match.state = data['state']
		match.states = data['states']
		if match.state == match.CHECK_IN:
			await match.check_in.start()  # Spawn a new check_in message

		bot.active_matches.append(match)

	def __init__(self, match_id, queue, qc, players, ratings, **cfg):

		# Set parent objects and shorthands
		self.queue = queue
		self.qc = qc
		self.send = qc.channel.send
		self.error = qc.error
		self.gt = qc.gt

		# Set configuration variables
		self.cfg = self.default_cfg.copy()
		self.cfg.update(cfg)

		# Set working objects
		self.id = match_id
		self.players = list(players)
		self.ratings = ratings
		print(self.ratings)

		team_names = self.cfg['team_names']
		team_emojis = self.cfg['team_emojis'] or random.sample(self.TEAM_EMOJIS, 2)
		self.teams = [
			self.Team(name=team_names[0], emoji=team_emojis[0], idx=0),
			self.Team(name=team_names[1], emoji=team_emojis[1], idx=1),
			self.Team(name="unpicked", emoji="📋", idx=-1)
		]

		self.captains = []
		self.states = []
		self.maps = []
		self.lifetime = self.cfg['match_lifetime']
		self.start_time = int(time())
		self.state = self.INIT

		# Init self sections
		self.check_in = CheckIn(self, self.cfg['check_in_timeout'])
		self.draft = Draft(self, self.cfg['pick_order'], self.cfg['captains_role_id'])
		self.embeds = Embeds(self)

	def init_maps(self, maps, map_count):
		self.maps = random.sample(maps, map_count)

	def init_captains(self, pick_captains, captains_role_id):
		if pick_captains == "by role and rating":
			self.captains = sorted(
				self.players,
				key=lambda p: [captains_role_id in [role.id for role in p.roles], self.ratings[p.id]],
				reverse=True
			)
		elif pick_captains == "fair pairs":
			candidates = sorted(self.players, key=lambda p: [self.ratings[p.id]], reverse=True)
			i = random.randrange(len(candidates) - 1)
			self.captains = [candidates[i], candidates[i + 1]]
		elif pick_captains == "random":
			self.captains = random.sample(self.players, 2)

	def init_teams(self, pick_teams):
		if pick_teams == "draft":
			self.teams[0].set(self.captains[:1])
			self.teams[1].set(self.captains[1:])
			self.teams[2].set([p for p in self.players if p not in self.captains])
		elif pick_teams == "matchmaking":
			team_len = int(len(self.players)/2)
			best_rating = sum(self.ratings.values())/2
			best_team = min(
				combinations(self.players, team_len),
				key=lambda team: abs(sum([self.ratings[m.id] for m in team])-best_rating)
			)
			self.teams[0].set(best_team)
			self.teams[1].set((p for p in self.players if p not in best_team))
		elif pick_teams == "random teams":
			self.teams[0].set(random.sample(self.players, int(len(self.players)/2)))
			self.teams[1].set((p for p in self.players if p not in self.teams[0]))

	async def think(self, frame_time):
		if self.state == self.INIT:
			await self.next_state()

		elif self.state == self.CHECK_IN:
			await self.check_in.think(frame_time)

		elif frame_time > self.lifetime + self.start_time:
			pass

	async def next_state(self):
		if len(self.states):
			self.state = self.states.pop(0)
			if self.state == self.CHECK_IN:
				await self.check_in.start()
			elif self.state == self.DRAFT:
				await self.draft.start()
			elif self.state == self.WAITING_REPORT:
				await self.start_waiting_report()
		else:
			if self.state != self.WAITING_REPORT:
				await self.final_message()
			await self.finish_match()

	def rank_str(self, member):
		return self.qc.rating_rank(self.ratings[member.id])['rank']

	async def start_waiting_report(self):
		await self.final_message()

	async def report(self, member=None, team_name=None, draw=False, force=False):
		# TODO: Only captain must be able to do this
		if self.state != self.WAITING_REPORT:
			await self.error(self.gt("The match must be on the waiting report stage."))
			return

		if member:
			team = find(lambda t: member in t, self.teams[:2])
		elif team_name:
			team = find(lambda t: t.name.lower() == team_name, self.teams[:2])
		else:
			team = self.teams[0]

		if team is None:
			await self.error(self.gt("Team not found."))
			return

		e_team = self.teams[abs(team.idx-1)]

		if not force and (draw and not e_team.want_draw):
			team.want_draw = True
			await self.qc.channel.send(
				self.gt("{team} team captain is calling a draw, waiting for {enemy} to type `{prefix}rd`.")
			)
			return

		before = [
			await self.qc.rating.get_ratings((p.id for p in e_team)),
			await self.qc.rating.get_ratings((p.id for p in team))
		]
		results = self.qc.rating.rate(
			winners=before[0],
			losers=before[1],
			draw=draw)

		print(results)
		await self.qc.rating.set_ratings(results)

		before = iter_to_dict((*before[0], *before[1]), key='user_id')
		after = iter_to_dict(results, key='user_id')
		await self.print_rating_results(e_team, team, before, after)

		await self.finish_match()

	async def print_rating_results(self, winners, losers, before, after):
		msg = "```markdown\n"
		msg += f"{self.queue.name.capitalize()}({self.id}) results\n"
		msg += "-------------\n"

		if len(winners) == 1 and len(losers) == 1:
			p = winners[0]
			msg += f"1. {p.nick or p.name} {before[p.id]['rating']} ⟼ {after[p.id]['rating']}\n"
			p = losers[0]
			msg += f"2. {p.nick or p.name} {before[p.id]['rating']} ⟼ {after[p.id]['rating']}"
		else:
			n = 0
			for team in (winners, losers):
				avg_bf = int(sum((before[p.id]['rating'] for p in team))/len(team))
				avg_af = int(sum((after[p.id]['rating'] for p in team))/len(team))
				msg += f"{n}. {team.name} {avg_bf} ⟼ {avg_af}\n"
				msg += "\n".join(
					(f"> {p.name or p.nick} {before[p.id]['rating']} ⟼ {after[p.id]['rating']}" for p in team)
				)
				n += 1
		msg += "```"
		await self.qc.channel.send(msg)

	async def final_message(self):
		#  Embed message with teams
		await self.qc.channel.send(embed=self.embeds.final_message())

	async def finish_match(self):
		bot.active_matches.remove(self)