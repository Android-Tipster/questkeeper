# QuestKeeper Setup

## 1. Create the Discord application

1. Go to https://discord.com/developers/applications and click **New Application**. Name it QuestKeeper.
2. In the sidebar click **Bot**, then **Reset Token** and copy the token. This is your `DISCORD_TOKEN`.
3. Under **Privileged Gateway Intents**, leave all three disabled (QuestKeeper only uses slash commands).
4. In the sidebar click **OAuth2 > URL Generator**. Check scopes `bot` and `applications.commands`. In bot permissions, check `Send Messages` and `Embed Links`. Copy the generated URL and open it to invite the bot to your server.

## 2. Get a Claude API key

1. Go to https://console.anthropic.com and sign in.
2. Create a key under **Settings > API Keys**. This is your `ANTHROPIC_API_KEY`.
3. Add at least $5 of credit so slash commands work. The default model is `claude-haiku-4-5-20251001`, which costs roughly half a cent per NPC generation.

## 3. Run locally

```bash
git clone https://github.com/Android-Tipster/questkeeper
cd questkeeper
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# edit .env: paste DISCORD_TOKEN and ANTHROPIC_API_KEY
python bot.py
```

On first start the bot registers its slash commands with Discord. They may take up to a minute to appear in your server.

## 4. Deploy to Railway (recommended for always-on)

1. Push your fork to GitHub.
2. Go to https://railway.app, click **New Project > Deploy from GitHub repo**, pick your fork.
3. In **Variables**, add `DISCORD_TOKEN` and `ANTHROPIC_API_KEY`.
4. Railway auto-detects `railway.json` and runs `python bot.py`.
5. QuestKeeper now stays online 24/7 for your group.

## 5. First campaign

In any channel where the bot can post:

```
/campaign create name:"Dragons of Ashfall" setting:"dark fantasy, steampunk cities"
/npc new tag:"tavern"
/scene place:"candlelit backroom" mood:"tense"
/event text:"The party learned the Marquis betrayed the Crown."
/recap
```

## Troubleshooting

- **Slash commands not showing**: wait a minute, then try typing `/` in a fresh channel. Discord sometimes caches old command lists.
- **Bot appears offline**: check Railway logs. The most common cause is a missing or rotated `DISCORD_TOKEN`.
- **Empty generations**: make sure your Anthropic account has credit.
- **Database is too big**: SQLite handles thousands of NPCs fine. If you ever want to prune, delete `questkeeper.db` and restart (you will lose all data).
