# QuestKeeper

**AI campaign memory for your TTRPG group, on Discord.**

Every Game Master has the same problem: mid-session someone mentions an NPC from three sessions ago and nobody can remember their voice, their motivation, or even their name. QuestKeeper is a Discord bot that remembers so you don't have to.

Unlike Avrae or Dice Maiden, QuestKeeper does not roll dice or look up spells. It is a worldbuilding companion. It remembers the NPCs your party has met, the plot threads they are chasing, and the key events of each session, and uses Claude to generate new content that respects all of it.

## What it does

- Generates NPCs that fit the campaign's tone and avoid duplicating existing ones
- Writes vivid scene descriptions that match the campaign setting
- Tracks open plot threads and closes them when resolved
- Logs session events and writes cliffhanger recaps on demand
- Keeps everything per Discord server, per campaign, per session

## Commands

```
/campaign create name:"Dragons of Ashfall" setting:"dark fantasy"
/campaign switch name:"Dragons of Ashfall"
/campaign list

/npc new tag:"tavern"
/npc recall name:"Oldham"
/npc list

/thread log text:"Find the stolen relic before the Red Moon"
/thread list
/thread close thread_id:3

/scene place:"abandoned watchtower" mood:"tense"

/event text:"Party bribed the gate captain with 50gp"
/recap
/session_end
```

## How to run

You need a Discord bot token (from the Discord Developer Portal) and a Claude API key (from console.anthropic.com).

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env with your tokens
python bot.py
```

Invite the bot to your server with the `applications.commands` and `bot` scopes, plus `Send Messages` and `Embed Links` permissions.

## Data

All data lives in a local SQLite file (`questkeeper.db`) next to the bot. Nothing leaves your server except the Claude API calls that generate NPCs, scenes, and recaps.

## Why this exists

GM prep is hours per session. Mid-session improvisation eats the rest of your evening. QuestKeeper shaves both down, not by taking creative control from the GM, but by holding the pieces they have already placed on the table so they can focus on what happens next.

## License

MIT
