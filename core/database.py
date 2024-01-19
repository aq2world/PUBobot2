# -*- coding: utf-8 -*-
from asyncio import get_event_loop
from importlib import import_module
from core.config import cfg
import os

DB_URI = cfg.DB_URI if cfg.DB_URI else os.environ.get("DB_URI")


def init_db(db_uri):
	db_type, db_address = db_uri.split("://", 1)
	adapter = import_module('core.DBAdapters.' + db_type)
	return adapter.Adapter(db_address, get_event_loop())


db = init_db(DB_URI)
