"""In-memory stand-ins for the database adapter and the Discord objects the bot touches."""
import asyncio
import itertools


class Types:
	bool = "bool"
	int = "int"
	float = "float"
	str = "str"
	text = "text"
	dict = "dict"


class Errors:
	class DatabaseError(Exception):
		pass
	DataError = OperationalError = IntegrityError = ProgrammingError = DatabaseError


class FakeDB:
	""" Minimal replacement for core.DBAdapters.mysql.Adapter keeping rows in memory """
	types = Types
	errors = Errors

	def __init__(self):
		self.loop = asyncio.new_event_loop()
		self.schemas = {}
		self.tables = {}
		self.counters = {}
		self.update_calls = []
		self.fail_updates = False

	async def connect(self):
		pass

	def ensure_table(self, table):
		self.schemas[table['tname']] = table
		self.tables.setdefault(table['tname'], [])

	def reset(self):
		for name in self.tables:
			self.tables[name] = []
		self.counters = {}
		self.update_calls = []
		self.fail_updates = False

	@staticmethod
	def _match(row, where):
		return all(row.get(k) == v for k, v in (where or {}).items())

	async def select(self, columns, table, where=None, order_by=None, order_asc=False, limit=None, one=False):
		rows = [dict(r) for r in self.tables.get(table, []) if self._match(r, where)]
		if order_by:
			rows.sort(key=lambda r: r.get(order_by) or 0, reverse=not order_asc)
		if limit:
			rows = rows[:limit]
		if columns and list(columns) != ['*']:
			rows = [{c: r.get(c) for c in columns} for r in rows]
		if one:
			return rows[0] if rows else None
		return rows

	async def select_one(self, *args, **kwargs):
		return await self.select(*args, **kwargs, one=True)

	async def insert(self, table, d, on_dublicate=None):
		row, last_id = {}, 0
		for col in self.schemas.get(table, {}).get('columns', []):
			name = col['cname']
			if col.get('autoincrement'):
				if d.get(name) is None:
					self.counters[table] = self.counters.get(table, 0) + 1
					row[name] = self.counters[table]
				else:
					row[name] = d[name]
				last_id = row[name]
			else:
				row[name] = d.get(name, col.get('default'))
		row.update(d)
		self.tables.setdefault(table, []).append(row)
		return last_id

	async def insert_many(self, table, it, on_dublicate=None):
		for d in it:
			await self.insert(table, d, on_dublicate)

	async def update(self, table, d, keys=None):
		self.update_calls.append((table, dict(d), dict(keys or {})))
		if self.fail_updates:
			raise RuntimeError("database write failed")
		for row in self.tables.get(table, []):
			if self._match(row, keys):
				row.update(d)

	async def delete(self, table, where=None):
		self.tables[table] = [r for r in self.tables.get(table, []) if not self._match(r, where)]

	async def execute(self, *args):
		raise NotImplementedError("raw SQL is not supported by FakeDB")

	fetchall = fetchone = execute


class FakeLog:
	def __init__(self):
		self.lines = []

	def _record(self, level):
		def f(*args, **kwargs):
			self.lines.append((level, " ".join(str(a) for a in args)))
		return f

	def __getattr__(self, name):
		return self._record(name)


_ids = itertools.count(1000)


class FakePermissions:
	administrator = True
	mention_everyone = True


class FakeRole:
	def __init__(self, role_id, name, mentionable=True):
		self.id = role_id
		self.name = name
		self.mentionable = mentionable
		self.mention = f"<@&{role_id}>"


class FakeMember:
	def __init__(self, user_id, name, guild=None, roles=(), bot=False):
		self.id = user_id
		self.name = name
		self.nick = None
		self.display_name = name
		self.guild = guild
		self.roles = list(roles)
		self.bot = bot
		self.avatar = None
		self.activity = None
		self.guild_permissions = FakePermissions()
		self.sent = []

	@property
	def mention(self):
		return f"<@{self.id}>"

	def __eq__(self, other):
		return self.id == getattr(other, 'id', None)

	def __hash__(self):
		return self.id

	def __repr__(self):
		return f"<FakeMember {self.name}>"

	async def send(self, *args, **kwargs):
		self.sent.append((args, kwargs))

	async def add_roles(self, *args, **kwargs):
		pass

	async def remove_roles(self, *args, **kwargs):
		pass


class FakeMessage:
	def __init__(self, content=None, **kwargs):
		self.id = next(_ids)
		self.content = content
		self.kwargs = kwargs
		self.edits = []
		self.reactions = []
		self.deleted = False

	async def edit(self, **kwargs):
		self.edits.append(kwargs)

	async def delete(self):
		self.deleted = True

	async def add_reaction(self, emoji):
		self.reactions.append(str(emoji))


class FakeChannel:
	def __init__(self, channel_id, name, guild):
		self.id = channel_id
		self.name = name
		self.guild = guild
		self.mention = f"<#{channel_id}>"
		self.sent = []

	async def send(self, content=None, **kwargs):
		message = FakeMessage(content, **kwargs)
		self.sent.append(message)
		return message

	def permissions_for(self, member):
		return FakePermissions()

	def get_thread(self, thread_id):
		return None


class FakeGuild:
	def __init__(self, guild_id, name):
		self.id = guild_id
		self.name = name
		self.members = []
		self.roles = []
		self.me = FakeMember(1, "PUBobot", self, bot=True)

	def get_member(self, user_id):
		return next((m for m in self.members if m.id == user_id), None)

	def get_role(self, role_id):
		return next((r for r in self.roles if r.id == role_id), None)

	def add_member(self, user_id, name, **kwargs):
		member = FakeMember(user_id, name, self, **kwargs)
		self.members.append(member)
		return member
