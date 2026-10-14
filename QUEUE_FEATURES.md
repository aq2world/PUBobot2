# Queue features guide

This guide covers the map pool, map cooldown, start delay and redo features with example usage.
Slash commands are shown; every command also has a text form listed in [MESSAGE_COMMANDS.md](MESSAGE_COMMANDS.md).
Queue settings are changed with `/set_queue` or `!set_queue_cfg`, and shown with `/cfg_queue`.

## Map pools

Every queue has a **maps list**, which is the default pool. Alternative **map pools** can be defined on top of it
and one of them selected as the current pool. Matches and map votes use the selected pool, or the maps list when no
pool is selected, the selected pool does not exist, or it is empty.

```
/map_pool_add queue:pickup pool:ctf maps:rok, bwcity2, urban   # creates the pool "ctf" or adds to it
/map_pool_del queue:pickup pool:ctf maps:urban                 # removes maps, reports any that were not there
/map_pools queue:pickup                                        # lists pools and the active one
/map_pools queue:pickup pool:ctf                               # lists the maps of one pool
/map_pool queue:pickup pool:ctf                                # play from the "ctf" pool from now on
/map_pool queue:pickup pool:none                               # back to the maps list ("default" works too)
/map_pool_destroy queue:pickup pool:ctf                        # deletes the pool, resets the selection if it was active
/maps queue:pickup                                             # shows the maps actually in use, naming the pool
```

Pool names are one word and matched case-insensitively. Map names are stored exactly as typed, since they map to
thumbnail file names. Moderators can manage pools; the raw lists are also editable through the `map_pools` and
`map_current_pool` queue settings.

## Map cooldown

`map_cooldown` is the number of finished matches during which a played map is avoided. Set it to `0` to disable.
The bot keeps a history of the maps of the last 100 matches per queue.

```
/map_cooldown queue:pickup
```
```
Map cooldown for pickup: 2 matches (shared with group main)
`cliff` - 2 matches left
`rok` - 1 matches left
```

### Sharing the cooldown between queues

Set `map_cooldown_group` to the same word on several queues of a channel and they share one history. A map played
in one queue is then on cooldown in the others. Each queue still applies its own `map_cooldown` length to the shared
history, so a 2v2 queue with cooldown 1 and a 4v4 queue with cooldown 3 can coexist in one group.

```
/set_queue queue:2v2 variable:map_cooldown_group value:main
/set_queue queue:4v4 variable:map_cooldown_group value:main
```

The history survives bot restarts.

## Start delay

By default a queue starts the moment the last player adds. If someone removes themselves at the same moment, their
remove can arrive after the match was created and they end up in the game anyway. `start_delay` adds a grace period:

```
/set_queue queue:pickup variable:start_delay value:5s
```

When the queue fills, the bot announces `pickup is full, starting in 0:00:05 unless someone leaves...` and starts
the match when the time is up. Anyone leaving during the delay cancels the start, and the next player to fill the
queue begins a new delay. Adds while the queue is full and waiting are refused. The delay also applies when a
check-in abort refills the queue from waiting players. Allowed values are 1 second to 5 minutes.

A full autostart queue that was never started, for example after a bot restart or after a moderator lowered its
size below the number of queued players, is now started by the bot on its next tick. Only `size` players are taken;
the rest keep waiting.

## Redo

`/redo` lets a captain cancel the running match and put everyone back into the queue, for example to re-roll the
captains, teams or maps. Moderators may always use it. Captains are the picked captains, or whoever leads a team
once teams exist. In matches without captains any player may use it.

```
/redo                                   # everyone back into the match queue
/redo queue:big                         # everyone into the "big" queue instead
/redo exclude:@alice @bob               # everyone except alice and bob
!redo @alice big @bob                   # text form, queue name and players in any order
```

Where the players go when no queue is named:

1. The queue the match came from, if the returning players still fit beside anyone who joined meanwhile.
2. Otherwise the queue named by the `redo_queue` setting of that queue, default `split`. This is meant to be a
   large manual queue that moderators divide with `/split`.
3. If that queue is missing or full the command refuses and the match stays active.

Returning players are placed in front of players who joined during the match, which matches the order in which
everyone originally added. If re-adding fills an autostart queue, a new match starts right away, honouring the
start delay when one is configured. Excluded players must be in the match, and they are named in the announcement.

## Running the tests

The test suite runs without Discord or MySQL; it fakes both.

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt pytest pytest-asyncio
.venv/bin/python -m pytest
```
