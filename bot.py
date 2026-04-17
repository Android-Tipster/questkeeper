"""
QuestKeeper - AI campaign memory for TTRPG groups on Discord.

Core differentiator: persistent per-campaign memory. The bot remembers NPCs the
party has met, plot threads mentioned, and session events. When the GM asks for
a new NPC or description, context from past sessions informs the output.

Commands:
  /campaign create name:"Dragons of Ashfall" setting:"dark fantasy"
  /campaign switch name:"Dragons of Ashfall"
  /npc new [tag:"tavern"]          - generate a contextual NPC, remember them
  /npc recall name:"Oldham"        - pull an NPC the party has met
  /npc list                         - list known NPCs for this campaign
  /thread log text:"..."           - log a plot thread the party is chasing
  /thread list                     - list open plot threads
  /scene describe mood:"tense"     - write a vivid scene that fits the campaign
  /recap                            - generate a session recap from tagged events
  /event log text:"..."            - log an event that happened this session
  /session end                      - seal the current session, bump session number
"""

from __future__ import annotations

import os
import sqlite3
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import discord
from discord import app_commands
from anthropic import Anthropic

DB_PATH = Path(__file__).parent / "questkeeper.db"
MODEL = os.getenv("QUESTKEEPER_MODEL", "claude-haiku-4-5-20251001")
DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("questkeeper")

intents = discord.Intents.default()
bot = discord.Client(intents=intents)
tree = app_commands.CommandTree(bot)
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY) if ANTHROPIC_API_KEY else None


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as c:
        c.executescript(
            """
            CREATE TABLE IF NOT EXISTS campaigns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id TEXT NOT NULL,
                name TEXT NOT NULL,
                setting TEXT,
                current_session INTEGER DEFAULT 1,
                created_at TEXT DEFAULT (datetime('now')),
                UNIQUE (guild_id, name)
            );
            CREATE TABLE IF NOT EXISTS active_campaign (
                guild_id TEXT PRIMARY KEY,
                campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE
            );
            CREATE TABLE IF NOT EXISTS npcs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                race TEXT,
                role TEXT,
                description TEXT,
                tag TEXT,
                first_met_session INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS threads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                status TEXT DEFAULT 'open',
                session INTEGER,
                created_at TEXT DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                campaign_id INTEGER NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                session INTEGER,
                text TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now'))
            );
            """
        )


def active_campaign_id(guild_id: str) -> Optional[int]:
    with db() as c:
        row = c.execute(
            "SELECT campaign_id FROM active_campaign WHERE guild_id = ?",
            (guild_id,),
        ).fetchone()
        return row["campaign_id"] if row else None


def require_campaign(guild_id: str) -> Optional[sqlite3.Row]:
    cid = active_campaign_id(guild_id)
    if cid is None:
        return None
    with db() as c:
        return c.execute("SELECT * FROM campaigns WHERE id = ?", (cid,)).fetchone()


def campaign_context(campaign_id: int, max_items: int = 8) -> str:
    """Build a compact context string from recent NPCs, threads, events."""
    with db() as c:
        camp = c.execute("SELECT * FROM campaigns WHERE id = ?", (campaign_id,)).fetchone()
        npcs = c.execute(
            "SELECT name, role, description FROM npcs WHERE campaign_id = ? ORDER BY id DESC LIMIT ?",
            (campaign_id, max_items),
        ).fetchall()
        threads = c.execute(
            "SELECT text FROM threads WHERE campaign_id = ? AND status = 'open' ORDER BY id DESC LIMIT ?",
            (campaign_id, max_items),
        ).fetchall()
        events = c.execute(
            "SELECT session, text FROM events WHERE campaign_id = ? ORDER BY id DESC LIMIT ?",
            (campaign_id, max_items),
        ).fetchall()

    parts = [f"Campaign: {camp['name']} (setting: {camp['setting'] or 'unspecified'}, current session: {camp['current_session']})"]
    if npcs:
        parts.append("Known NPCs:")
        for n in npcs:
            parts.append(f"- {n['name']} ({n['role'] or 'unclear role'}): {n['description'] or ''}")
    if threads:
        parts.append("Open plot threads:")
        for t in threads:
            parts.append(f"- {t['text']}")
    if events:
        parts.append("Recent events:")
        for e in events:
            parts.append(f"- [session {e['session']}] {e['text']}")
    return "\n".join(parts)


async def ask_claude(system: str, user: str, max_tokens: int = 700) -> str:
    if anthropic is None:
        return "[ANTHROPIC_API_KEY not set, bot running in demo mode]"
    resp = anthropic.messages.create(
        model=MODEL,
        max_tokens=max_tokens,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


# --- Campaign commands -------------------------------------------------------

campaign_group = app_commands.Group(name="campaign", description="Manage campaigns")


@campaign_group.command(name="create", description="Create a new campaign")
@app_commands.describe(name="Campaign name", setting="Setting description (e.g. dark fantasy, space opera)")
async def campaign_create(interaction: discord.Interaction, name: str, setting: str = "high fantasy"):
    gid = str(interaction.guild_id)
    with db() as c:
        try:
            cur = c.execute(
                "INSERT INTO campaigns (guild_id, name, setting) VALUES (?, ?, ?)",
                (gid, name, setting),
            )
            cid = cur.lastrowid
            c.execute(
                "INSERT INTO active_campaign (guild_id, campaign_id) VALUES (?, ?) "
                "ON CONFLICT(guild_id) DO UPDATE SET campaign_id = excluded.campaign_id",
                (gid, cid),
            )
        except sqlite3.IntegrityError:
            await interaction.response.send_message(f"A campaign named '{name}' already exists.", ephemeral=True)
            return
    await interaction.response.send_message(
        f"Campaign **{name}** created ({setting}). It is now the active campaign."
    )


@campaign_group.command(name="switch", description="Switch the active campaign")
async def campaign_switch(interaction: discord.Interaction, name: str):
    gid = str(interaction.guild_id)
    with db() as c:
        row = c.execute(
            "SELECT id FROM campaigns WHERE guild_id = ? AND name = ?", (gid, name)
        ).fetchone()
        if not row:
            await interaction.response.send_message(f"No campaign named '{name}'.", ephemeral=True)
            return
        c.execute(
            "INSERT INTO active_campaign (guild_id, campaign_id) VALUES (?, ?) "
            "ON CONFLICT(guild_id) DO UPDATE SET campaign_id = excluded.campaign_id",
            (gid, row["id"]),
        )
    await interaction.response.send_message(f"Switched to campaign **{name}**.")


@campaign_group.command(name="list", description="List campaigns on this server")
async def campaign_list(interaction: discord.Interaction):
    gid = str(interaction.guild_id)
    active = active_campaign_id(gid)
    with db() as c:
        rows = c.execute(
            "SELECT id, name, setting, current_session FROM campaigns WHERE guild_id = ? ORDER BY created_at DESC",
            (gid,),
        ).fetchall()
    if not rows:
        await interaction.response.send_message("No campaigns yet. Create one with /campaign create.", ephemeral=True)
        return
    lines = []
    for r in rows:
        marker = " (active)" if r["id"] == active else ""
        lines.append(f"- **{r['name']}**{marker}, session {r['current_session']}, {r['setting']}")
    await interaction.response.send_message("\n".join(lines))


tree.add_command(campaign_group)


# --- NPC commands ------------------------------------------------------------

npc_group = app_commands.Group(name="npc", description="Generate and track NPCs")


@npc_group.command(name="new", description="Generate a new NPC that fits the campaign")
@app_commands.describe(tag="Optional location or scene tag, e.g. 'tavern', 'dockside'")
async def npc_new(interaction: discord.Interaction, tag: str = ""):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign. /campaign create first.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    context = campaign_context(camp["id"])
    system = (
        "You are a tabletop RPG worldbuilding assistant. Generate a single NPC that fits the "
        "campaign's tone and avoids duplicating existing NPCs. Output strictly as:\n"
        "NAME: <name>\nRACE: <race>\nROLE: <one line role or occupation>\n"
        "DESCRIPTION: <2-3 sentences covering appearance, voice, a motivation, and a quirk>"
    )
    user = f"{context}\n\nGenerate an NPC" + (f" fitting the tag: {tag}." if tag else ".")
    text = await ask_claude(system, user)

    name = race = role = description = ""
    for line in text.splitlines():
        if line.startswith("NAME:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("RACE:"):
            race = line.split(":", 1)[1].strip()
        elif line.startswith("ROLE:"):
            role = line.split(":", 1)[1].strip()
        elif line.startswith("DESCRIPTION:"):
            description = line.split(":", 1)[1].strip()

    if not name:
        await interaction.followup.send("Generation failed, try again.")
        return

    with db() as c:
        c.execute(
            "INSERT INTO npcs (campaign_id, name, race, role, description, tag, first_met_session) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (camp["id"], name, race, role, description, tag, camp["current_session"]),
        )

    embed = discord.Embed(title=name, description=description, color=0x8B5CF6)
    if race:
        embed.add_field(name="Race", value=race, inline=True)
    if role:
        embed.add_field(name="Role", value=role, inline=True)
    embed.set_footer(text=f"{camp['name']} - session {camp['current_session']}")
    await interaction.followup.send(embed=embed)


@npc_group.command(name="recall", description="Recall an NPC the party has met")
async def npc_recall(interaction: discord.Interaction, name: str):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        row = c.execute(
            "SELECT * FROM npcs WHERE campaign_id = ? AND LOWER(name) LIKE ? ORDER BY id DESC LIMIT 1",
            (camp["id"], f"%{name.lower()}%"),
        ).fetchone()
    if not row:
        await interaction.response.send_message(f"No NPC matching '{name}' in this campaign.", ephemeral=True)
        return
    embed = discord.Embed(title=row["name"], description=row["description"], color=0x8B5CF6)
    if row["race"]:
        embed.add_field(name="Race", value=row["race"], inline=True)
    if row["role"]:
        embed.add_field(name="Role", value=row["role"], inline=True)
    if row["first_met_session"]:
        embed.set_footer(text=f"First met in session {row['first_met_session']}")
    await interaction.response.send_message(embed=embed)


@npc_group.command(name="list", description="List known NPCs for the active campaign")
async def npc_list(interaction: discord.Interaction):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        rows = c.execute(
            "SELECT name, role FROM npcs WHERE campaign_id = ? ORDER BY id DESC LIMIT 25",
            (camp["id"],),
        ).fetchall()
    if not rows:
        await interaction.response.send_message("No NPCs yet. Generate one with /npc new.", ephemeral=True)
        return
    lines = [f"- **{r['name']}**: {r['role'] or '?'}" for r in rows]
    await interaction.response.send_message("\n".join(lines))


tree.add_command(npc_group)


# --- Threads -----------------------------------------------------------------

thread_group = app_commands.Group(name="thread", description="Track plot threads")


@thread_group.command(name="log", description="Log an open plot thread the party is chasing")
async def thread_log(interaction: discord.Interaction, text: str):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        c.execute(
            "INSERT INTO threads (campaign_id, text, session) VALUES (?, ?, ?)",
            (camp["id"], text, camp["current_session"]),
        )
    await interaction.response.send_message(f"Thread logged: _{text}_")


@thread_group.command(name="list", description="List open plot threads")
async def thread_list(interaction: discord.Interaction):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        rows = c.execute(
            "SELECT id, text FROM threads WHERE campaign_id = ? AND status = 'open' ORDER BY id DESC",
            (camp["id"],),
        ).fetchall()
    if not rows:
        await interaction.response.send_message("No open threads. Log one with /thread log.", ephemeral=True)
        return
    lines = [f"{r['id']}. {r['text']}" for r in rows]
    await interaction.response.send_message("**Open plot threads**\n" + "\n".join(lines))


@thread_group.command(name="close", description="Mark a plot thread as resolved")
async def thread_close(interaction: discord.Interaction, thread_id: int):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        cur = c.execute(
            "UPDATE threads SET status = 'resolved' WHERE id = ? AND campaign_id = ?",
            (thread_id, camp["id"]),
        )
        if cur.rowcount == 0:
            await interaction.response.send_message("No such thread.", ephemeral=True)
            return
    await interaction.response.send_message(f"Thread {thread_id} marked resolved.")


tree.add_command(thread_group)


# --- Scene description -------------------------------------------------------

@tree.command(name="scene", description="Describe a vivid scene that fits the campaign")
@app_commands.describe(
    place="Place or location for the scene",
    mood="Mood or tone, e.g. tense, jovial, ominous",
)
async def scene_describe(interaction: discord.Interaction, place: str, mood: str = "atmospheric"):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    context = campaign_context(camp["id"])
    system = (
        "You are a tabletop RPG Game Master's assistant. Write an evocative scene description "
        "in 4-6 sentences. Use sensory detail (sight, sound, smell). Seed one small hook the "
        "party could investigate. Match the campaign's tone. No em dashes."
    )
    user = f"{context}\n\nDescribe the scene. Place: {place}. Mood: {mood}."
    text = await ask_claude(system, user, max_tokens=500)
    await interaction.followup.send(text)


# --- Events + recap ----------------------------------------------------------

@tree.command(name="event", description="Log something that happened this session")
async def event_log(interaction: discord.Interaction, text: str):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        c.execute(
            "INSERT INTO events (campaign_id, session, text) VALUES (?, ?, ?)",
            (camp["id"], camp["current_session"], text),
        )
    await interaction.response.send_message(f"Event logged for session {camp['current_session']}.")


@tree.command(name="recap", description="Write a session recap from logged events")
async def recap(interaction: discord.Interaction):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True)
    with db() as c:
        events = c.execute(
            "SELECT text FROM events WHERE campaign_id = ? AND session = ? ORDER BY id",
            (camp["id"], camp["current_session"]),
        ).fetchall()
    if not events:
        await interaction.followup.send("No events logged for this session. Use /event first.")
        return
    bullets = "\n".join(f"- {e['text']}" for e in events)
    system = (
        "You are a tabletop RPG chronicler. Write a vivid session recap in 3-5 short paragraphs "
        "from the bullet points provided. Use present tense, second person ('the party'). "
        "End with a one-line cliffhanger. No em dashes."
    )
    user = f"Campaign: {camp['name']}\nSession {camp['current_session']} events:\n{bullets}"
    text = await ask_claude(system, user, max_tokens=900)
    await interaction.followup.send(text)


@tree.command(name="session_end", description="Seal the current session and advance to the next")
async def session_end(interaction: discord.Interaction):
    gid = str(interaction.guild_id)
    camp = require_campaign(gid)
    if not camp:
        await interaction.response.send_message("No active campaign.", ephemeral=True)
        return
    with db() as c:
        c.execute(
            "UPDATE campaigns SET current_session = current_session + 1 WHERE id = ?",
            (camp["id"],),
        )
    await interaction.response.send_message(
        f"Session {camp['current_session']} sealed. Next session: {camp['current_session'] + 1}."
    )


# --- Help --------------------------------------------------------------------

@tree.command(name="questkeeper_help", description="Show QuestKeeper usage")
async def questkeeper_help(interaction: discord.Interaction):
    text = (
        "**QuestKeeper** - AI campaign memory for your TTRPG group.\n"
        "Start with `/campaign create name:\"My Campaign\" setting:\"dark fantasy\"`\n"
        "Then: `/npc new`, `/scene place:\"tavern\" mood:\"tense\"`, `/thread log text:\"...\"`, "
        "`/event text:\"...\"`, `/recap`, `/session_end`.\n"
        "Data is kept per Discord server, per campaign, and per session."
    )
    await interaction.response.send_message(text, ephemeral=True)


# --- Startup -----------------------------------------------------------------

@bot.event
async def on_ready():
    init_db()
    await tree.sync()
    log.info("QuestKeeper online as %s", bot.user)


def main() -> None:
    if not DISCORD_TOKEN:
        raise SystemExit("DISCORD_TOKEN env var is required.")
    init_db()
    bot.run(DISCORD_TOKEN)


if __name__ == "__main__":
    main()
