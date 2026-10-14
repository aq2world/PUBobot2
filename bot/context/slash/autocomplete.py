from typing import List
from nextcord import Interaction

from core.utils import find, get

import bot


async def queues(interaction: Interaction, queue: str) -> List[str]:
	if (qc := bot.queue_channels.get(interaction.channel_id)) is not None:
		return [q.name for q in qc.queues if q.name.startswith(queue)]
	else:
		return []


def _option(interaction: Interaction, name: str):
	""" Find a top level or sub command option value by name """
	options = interaction.data.get('options', [])
	for opt in options:
		if opt.get('name') == name:
			return opt.get('value')
		for sub in opt.get('options', []):
			if sub.get('name') == name:
				return sub.get('value')
	return None


async def map_pools(interaction: Interaction, pool: str) -> List[str]:
	if (qc := bot.queue_channels.get(interaction.channel_id)) is None:
		return []
	if (queue_name := _option(interaction, 'queue')) is None:
		return []
	if (queue := find(lambda q: q.name.lower() == queue_name.lower(), qc.queues)) is None:
		return []
	return [p['name'] for p in queue.cfg.map_pools if p['name'].lower().startswith((pool or '').lower())][:25]


async def qc_variables(interaction: Interaction, variable: str) -> List[str]:
	return sorted([v for v in bot.QueueChannel.cfg_factory.variables.keys() if v.startswith(variable)])[:10]


async def queue_variables(interaction: Interaction, variable: str) -> List[str]:
	if (qc := bot.queue_channels.get(interaction.channel_id)) is None:
		return []
	interaction_queue = find(lambda i: i['name'] == 'queue', interaction.data['options'][0]['options'])
	if interaction_queue and (queue := get(qc.queues, name=interaction_queue['value'])):
		return sorted([v for v in queue.cfg_factory.variables.keys() if v.startswith(variable)])[:10]
	return []


async def match_ids(interaction: Interaction, match_id: str) -> List[int]:
	if (qc := bot.queue_channels.get(interaction.channel_id)) is None:
		return []
	return [m.id for m in bot.active_matches if m.qc == qc]


async def teams_by_author(interaction: Interaction, name: str) -> List[str]:
	if (match := find(lambda m: interaction.user in m.players, bot.active_matches)) is not None:
		return [team.name for team in match.teams[:2] if team.name.startswith(name)]
	return ['active match not found']


async def teams_by_match_id(interaction: Interaction, name: str) -> List[str]:
	interaction_match = find(lambda i: i['name'] == 'match_id', interaction.data['options'][0]['options'])
	if interaction_match and (match := get(bot.active_matches, id=interaction_match['value'])):
		return [team.name for team in match.teams[:2] if team.name.startswith(name)]
	return ['incorrect match_id supplied']
