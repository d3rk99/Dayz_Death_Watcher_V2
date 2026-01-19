# DeathWatcher v2

DeathWatcher v2 is a Python Discord bot + local desktop GUI that manages death-based bans with timed revives and voice-channel-dependent enforcement across up to five DayZ servers. The application lives outside of the DayZ server folders and is configured per server using a shared `config.json`.

## Highlights

- **Unified user database** shared across all servers.
- **Per-server log tracking** with independent ban/whitelist enforcement.
- **Policy-driven unban logic** for single active server, all servers, or per-user home server.
- **Local GUI** with dark/light toggle, live logs, settings editor, and safe admin actions.
- **Future-ready architecture** to support server travel/linking.

## Repository Structure

```
src/
  core/        # config, persistence, audit logging, policies
  adapters/    # DayZ ban/whitelist file adapter
  watchers/    # per-server LJSON tailer
  bot/         # Discord bot entrypoint and logic
  gui/         # Desktop GUI
```

## Requirements

- Python 3.11+
- discord.py 2.x

## Windows Setup (recommended)

1. Copy the example config and update paths + IDs:

```bat
copy config.example.json config.json
```

2. Create the virtual environment and install dependencies:

```bat
setup_env.bat
```

## Running (Windows)

### Discord bot

```bat
run_bot.bat
```

### Desktop GUI

```bat
run_gui.bat
```

### Run both

```bat
run_all.bat
```

## Manual Setup (any OS)

Install dependencies:

```bash
pip install -U discord.py
```

## Configuration

Update `config.json` with:

- Discord token, guild ID, role IDs, channel IDs.
- For each server: paths to Detailed Logs, `ban.txt`, and `whitelist.txt`.
- Policy mode and ban duration.

## Running (manual)

### Discord bot

```bash
python -m src.bot
```

### Desktop GUI

```bash
python -m src.gui
```

## Core Behavior

### Death ban system

- Tails the newest `dl_*.ljson` file per server.
- Detects `PLAYER_DEATH` events.
- Marks the user dead in the shared JSON DB.
- Adds the user to that server’s `ban.txt`.
- Starts a timer; when it expires, the user is revived and removed from the ban list.

### Voice-channel enforcement

- Users must join the Click-to-Join VC to get moved into a private VC named **exactly their Discord ID**.
- Users are unbanned only when inside that private VC.
- Leaving their private VC immediately re-bans them.

### Server tie policy

Configured in `policy`:

- `single_active_server`: unban only on the active server.
- `all_servers`: unban on all servers.
- `per_user_server`: unban on the user’s home server ID.

Users can set their active server via `/setserver <serverId>`.

## Admin Commands

- `/validatesteamid <steam64>` — validate and whitelist, then ban until voice join.
- `/setserver <serverId>` — set active server for policy.
- `/revive <steam64>` — admin revive.
- `/ban <steam64>` — admin ban.
- `/unban <steam64>` — admin unban.
- `/wipe` — wipe user DB (danger zone).

## GUI Overview

Tabs include:

1. Dashboard / Live Logs
2. Currently Dead
3. Death Counter
4. Lists (ban/whitelist views)
5. Admins
6. Leaderboard
7. Settings (config editor + reload)
8. Danger Zone

GUI is read-only by default. Toggle **Enable Writes** to allow DB edits or dangerous actions.

## Data Files

- `data/users.json` — unified user database.
- `data/cursors.json` — per-server log cursor offsets.
- `data/audit.log` — append-only activity log for GUI.

## Notes

- Log tailer handles partial lines and JSON decode errors safely.
- Ban/whitelist writes are atomic and de-duplicated.
- No RCON required.

## Next Steps

- Add GUI list viewers for ban/whitelist files.
- Add live log streaming per server in GUI.
- Implement Steam Web API validator interface.
- Expand leaderboard generation and posting.
