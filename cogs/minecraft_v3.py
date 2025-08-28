import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
import asyncio
import json
import websockets
from discord.ext import commands, tasks
from typing import Optional, Literal
from datetime import datetime


def notif_enabled(bot: commands.Bot, key: str) -> bool:
    """Retourne si une notif est activée ou pas"""
    return bot.config.get("notifications", {}).get(key, True)


class MinecraftManager(commands.Cog, name="minecraft_v2"):
    """A fully featured Minecraft server management cog using MSMP."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.listeners = {}
        self.active_servers = set()  # Track servers we're already connected to
        self.load_config()
    
    def load_config(self):
        with open("config.json", "r", encoding="utf-8") as f:
            self.bot.config = json.load(f)


    # Centralized JSON-RPC request handler
    async def send_rpc_request(self, ip: str, port: int, method: str, params=None):
        if params is None:
            params = []
        ws_url = f"ws://{ip}:{port}"
        try:
            async with websockets.connect(ws_url) as websocket:
                request = {"id": 1, "jsonrpc": "2.0", "method": method, "params": params}
                await websocket.send(json.dumps(request))
                response_raw = await websocket.recv()
                return json.loads(response_raw)
                print('resquest response: ',response_raw)
        except Exception as e:
            return {"error": str(e)}


    @tasks.loop(seconds=30)
    async def monitor_servers(self):
        await self.bot.wait_until_ready()
        all_servers = await self.bot.database.get_all_mc_servers_full()  # returns [(name, ip, port, channel_id), ...]

        for (name, ip, port, channel_id) in all_servers:
            if name in self.active_servers:
                continue  # Already monitoring
            print(f'adresse of {name}: {ip}, {port}. Channel id: {channel_id}')
            try:
                resp = await self.send_rpc_request(ip, port, "minecraft:server/status")
                if resp.get("result", {}).get("started", False):
                    self.active_servers.add(name)  # Mark as active
                    self.listeners[name] = asyncio.create_task(
                        self.listen_to_mc_server(ip, port, channel_id, name)
                    )
                    print(f"Started listening for server {name}")
            except Exception:
                pass

    async def cog_load(self):
        # Start task when cog is loaded
        self.monitor_servers.start()

    async def cog_unload(self):
        # Stop the task when cog unloads
        self.monitor_servers.cancel()



    # Real-time notification listener
    async def listen_to_mc_server(self, mc_ip, mc_port, channel_id, server_name):
        ws_url = f"ws://{mc_ip}:{mc_port}"
        channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
        try:
            async with websockets.connect(ws_url) as websocket:
                await websocket.send(json.dumps({"id": 1, "jsonrpc": "2.0", "method": "rpc.discover"}))
                await websocket.recv()
                while True:
                    try:
                        message = json.loads(await websocket.recv())
                        method = message.get("method", "")
                        params = message.get("params", [{}])[0]

                        embed = None

                        # Joueur rejoint
                        if method == "notification:players/joined" and notif_enabled(self.bot, "players_joined"):
                            player_name = params.get('name')
                            embed = discord.Embed(
                                title="✅ Player Joined",
                                description=f"`{player_name}` joined **{server_name}**",
                                color=0x57F287,  # vert
                                timestamp=datetime.utcnow()
                            )
                            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{player_name}")

                        # Joueur quitte
                        elif method == "notification:players/left" and notif_enabled(self.bot, "players_left"):
                            player_name = params.get('name')
                            embed = discord.Embed(
                                title="❌ Player Left",
                                description=f"`{player_name}` left **{server_name}**",
                                color=0xED4245,  # rouge
                                timestamp=datetime.utcnow()
                            )
                            embed.set_thumbnail(url=f"https://mc-heads.net/avatar/{player_name}")

                        # Ban ajouté
                        elif method == "notification:bans/added" and notif_enabled(self.bot, "bans_added"):
                            embed = discord.Embed(
                                title="⛔ Player Banned",
                                description=f"`{params['player']['name']}` was banned.",
                                color=0x992D22,
                                timestamp=datetime.utcnow()
                            )

                        # Ban retiré
                        elif method == "notification:bans/removed" and notif_enabled(self.bot, "bans_removed"):
                            embed = discord.Embed(
                                title="✔️ Player Unbanned",
                                description=f"`{params['name']}` was unbanned.",
                                color=0x2ECC71,
                                timestamp=datetime.utcnow()
                            )

                        # Allowlist
                        elif method == "notification:allowlist/added" and notif_enabled(self.bot, "allowlist_added"):
                            embed = discord.Embed(
                                title="📃 Allowlist Update",
                                description=f"`{params.get('name')}` added to allowlist.",
                                color=0x5865F2,
                                timestamp=datetime.utcnow()
                            )
                        elif method == "notification:allowlist/removed" and notif_enabled(self.bot, "allowlist_removed"):
                            embed = discord.Embed(
                                title="📃 Allowlist Update",
                                description=f"`{params.get('name')}` removed from allowlist.",
                                color=0x5865F2,
                                timestamp=datetime.utcnow()
                            )

                        # OP
                        elif method == "notification:operators/added" and notif_enabled(self.bot, "operators_added"):
                            embed = discord.Embed(
                                title="⭐ Operator Granted",
                                description=f"`{params['player']['name']}` is now OP.",
                                color=0xF1C40F,
                                timestamp=datetime.utcnow()
                            )
                        elif method == "notification:operators/removed" and notif_enabled(self.bot, "operators_removed"):
                            embed = discord.Embed(
                                title="⚠️ Operator Removed",
                                description=f"`{params['player']['name']}` removed from OPs.",
                                color=0xF1C40F,
                                timestamp=datetime.utcnow()
                            )

                        # Serveur status
                        elif method == "notification:server/started" and notif_enabled(self.bot, "server_started"):
                            embed = discord.Embed(
                                title="🟢 Server Started",
                                description=f"Server **{server_name}** is now online!",
                                color=0x57F287,
                                timestamp=datetime.utcnow()
                            )
                        elif method == "notification:server/stopping" and notif_enabled(self.bot, "server_stopping"):
                            embed = discord.Embed(
                                title="🛑 Server Stopping",
                                description=f"Server **{server_name}** is shutting down...",
                                color=0xED4245,
                                timestamp=datetime.utcnow()
                            )
                        elif method == "notification:server/saving" and notif_enabled(self.bot, "server_saving"):
                            embed = discord.Embed(
                                title="💾 Saving World",
                                description=f"Server **{server_name}** is saving...",
                                color=0x3498DB,
                                timestamp=datetime.utcnow()
                            )
                        elif method == "notification:server/saved" and notif_enabled(self.bot, "server_saved"):
                            embed = discord.Embed(
                                title="💾 World Saved",
                                description=f"Server **{server_name}** finished saving.",
                                color=0x2ECC71,
                                timestamp=datetime.utcnow()
                            )
                        elif method == "notification:server/status" and notif_enabled(self.bot, "server_status"):
                            embed = discord.Embed(
                                title="❤️‍🔥 Server Heartbeat",
                                description=f"Server **{server_name}** is alive!",
                                color=0xE67E22,
                                timestamp=datetime.utcnow()
                            )

                        # Gamerules
                        elif method == "notification:gamerules/updated" and notif_enabled(self.bot, "server_gamerules_updatedstatus"):
                            rule = params.get("gamerule", {})
                            embed = discord.Embed(
                                title="🎮 Gamerule Updated",
                                description=f"`{rule.get('name')}` → `{rule.get('value')}`",
                                color=0x9B59B6,
                                timestamp=datetime.utcnow()
                            )
                        if embed:
                            embed.set_footer(text=f"Minecraft server: {server_name}")
                            await channel.send(embed=embed)

                    except websockets.ConnectionClosed:
                        await channel.send(f"⚠️ Connection to `{server_name}` lost.")
                        self.active_servers.remove(server_name)
                        break
        except Exception as e:
            await channel.send(f"❌ Could not connect to `{server_name}`: `{e}`")

    # Autocomplete for server names
    async def mc_serv_name_autocomplete(self, _, current: str):
        all_servers = await self.bot.database.get_all_mc_servers()
        servers = [row[0] for row in all_servers if current.lower() in row[0].lower()]
        return [app_commands.Choice(name=s, value=s) for s in servers[:25]]


    async def mc_ban_list_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        channel_id = interaction.channel_id
        info = await self.bot.database.get_mc_server_info(channel_id=channel_id)
        if not info:
            return []
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:bans")

        ban_names = [
            b['player']['name']
            for b in resp.get('result', [])
            if current.lower() in b['player']['name'].lower()
        ]
        return [app_commands.Choice(name=name, value=name) for name in ban_names[:25]]

    async def mc_online_players_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str
    ) -> list[app_commands.Choice[str]]:
        """
        Autocomplete for online players on the server linked to the current channel.
        """
        channel_id = interaction.channel_id
        info = await self.bot.database.get_mc_server_info(channel_id=channel_id)
        if not info:
            return []

        _, _, ip, port = info

        try:
            # Récupérer le status du serveur pour obtenir les joueurs en ligne
            resp = await self.send_rpc_request(ip, port, "minecraft:server/status")
            players = resp.get("result", {}).get("players", [])
        except Exception:
            return []

        # Filtrer selon la saisie de l'utilisateur
        player_names = [p["name"] for p in players if current.lower() in p["name"].lower()]

        # Limiter à 25 choix pour Discord
        return [app_commands.Choice(name=name, value=name) for name in player_names[:25]]


    # Command group for Minecraft server
    @commands.hybrid_group(name="mc", description="Minecraft server management")
    async def mc(self, ctx: Context):
        """Root group for Minecraft commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use a subcommand. Try `/mc help`.")

    @commands.hybrid_group(name="mc_config", description="Minecraft server configuration management")
    async def mc_config(self, ctx: Context):
        """Root group for Minecraft commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use a subcommand. Try `/mc help`.")


    # Mc help
    @mc.command(name="help", description="Show all /mc commands and their descriptions")
    async def help(self, ctx):
        # Get the 'mc' command group from the bot
        mc_group = self.mc
        
        embed = discord.Embed(title="/mc commands", color=0xE02B2B)
        embed.description = "List of all available /mc subcommands:\n"

        for cmd in mc_group.commands:
            # Add name and description for each subcommand
            embed.add_field(name=f"/mc {cmd.name}", value=cmd.description or "No description", inline=False)

        await ctx.send(embed=embed)



    @mc_config.command(name="reload", description="Reload the Minecraft config.json file")
    async def reload_config(self, ctx: commands.Context):
        try:
            with open("config.json", "r", encoding="utf-8") as f:
                self.bot.config = json.load(f)

            embed = discord.Embed(
                title="✅ Config Reloaded",
                description="Le fichier `config.json` a été rechargé avec succès.",
                color=0x57F287
            )
            await ctx.send(embed=embed)

        except Exception as e:
            embed = discord.Embed(
                title="❌ Reload Failed",
                description=f"Erreur lors du rechargement : `{e}`",
                color=0xED4245
            )
            await ctx.send(embed=embed)

    # Add a Minecraft server
    @mc_config.command(name="add", description="Add a Minecraft server connection")
    async def add_server(self, ctx: Context, name: str, ip: str = "localhost", port: int = 25585):
        success = await self.bot.database.add_minecraft_server(ctx.guild.id, ctx.channel.id, name, ip, port)
        msg = "✅ Server added." if success else "❌ Name already taken."
        await ctx.send(msg)

    # Remove a Minecraft server
    @mc_config.command(name="remove", description="Remove a Minecraft server connection")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def remove_server(self, ctx: Context, name: str):
        success = await self.bot.database.remove_minecraft_server(ctx.guild.id, name)
        msg = f"🗑️ Server `{name}` removed." if success else f"❌ Server `{name}` not found."
        await ctx.send(msg)

    # Edit a Minecraft server
    @mc_config.command(name="edit", description="Edit an existing Minecraft server connection")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def edit_server(self, ctx: Context, name: str, new_ip: str = None, new_port: int = None):
        success = await self.bot.database.edit_minecraft_server(ctx.guild.id, name, new_ip, new_port)
        if success:
            await ctx.send(f"✏️ Server `{name}` updated.")
        else:
            await ctx.send(f"❌ Server `{name}` not found.")

    @mc_config.command(name="list", description="List all configured Minecraft servers")
    async def list_servers(self, ctx: Context):
        servers = await self.bot.database.get_all_mc_servers_full()
        if not servers:
            return await ctx.send("⚠️ No servers configured.")

        embed = discord.Embed(title="Configured Minecraft Servers", color=0x00ff00)
        for name, ip, port, channel_id in servers:
            embed.add_field(
                name=name,
                value=f"IP: `{ip}`\nPort: `{port}`\nChannel: <#{channel_id}>",
                inline=False
            )
        await ctx.send(embed=embed)


    # Start listening for events on the server // Deprecated
    @mc.command(name="start", description="Start listening to server events")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def start(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        if not info:
            return await ctx.send("❌ Server not found.")
        _, channel_id, ip, port = info
        self.listeners[name] = asyncio.create_task(self.listen_to_mc_server(ip, port, channel_id, name))
        await ctx.send(f"🎧 Listening for events from `{name}` ({ip}:{port})")

    # Stop server // Need to use /mc start now lol
    @mc.command(name="stop", description="Stop the Minecraft server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def stop_server(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        if not info:
            return await ctx.send("❌ Not found.")
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:server/stop")
        await ctx.send(f"🛑 Stop server: `{resp}`")


    ########################################
    # Get server status
    @mc.command(name="status", description="Get the current status of the server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def status(self, ctx, name: str):
        # Récupérer les infos du serveur
        info = await self.bot.database.get_mc_server_info(name)
        if not info:
            return await ctx.send("❌ Server not found.")

        _, _, ip, port = info
        # Envoyer la requête RPC pour obtenir le status
        resp = await self.send_rpc_request(ip, port, "minecraft:server/status")

        if "result" in resp:
            status_data = resp["result"]
            embed = discord.Embed(
                title=f"🖥️ Server Status - {name}",
                color=0x57F287,
                timestamp=datetime.utcnow()
            )

            # Server started?
            embed.add_field(name="Status", value="🟢 Online" if status_data.get("started") else "🔴 Offline", inline=False)

            # Joueurs connectés
            players = status_data.get("players", [])
            if players:
                player_list = "\n".join(f"- {p['name']}" for p in players)
                embed.add_field(name=f"Players ({len(players)})", value=player_list, inline=False)
            else:
                embed.add_field(name="Players", value="Aucun joueur en ligne", inline=False)

            # Version
            version = status_data.get("version", {})
            embed.add_field(name="Version", value=f"{version.get('name', 'Unknown')} (Protocol {version.get('protocol', 'Unknown')})", inline=False)

            await ctx.send(embed=embed)
        else:
            await ctx.send(f"⚠️ Error fetching server status: `{resp}`")



    # Change MOTD
    @mc.command(name="motd", description="Change the server's MOTD")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def motd(self, ctx, name: str, *, motd: str):
        info = await self.bot.database.get_mc_server_info(name)
        if not info:
            return await ctx.send("❌ Not found.")
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/motd/set", [motd])
        if "result" in resp:
            await ctx.send(f"✅ MOTD changed: `{motd}`")
        else:
            await ctx.send(f"⚠️ Error: `{resp}`")

    # Change difficulty
    @mc.command(name="difficulty", description="Set the server difficulty")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def difficulty(self, ctx, name: str, difficulty: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/difficulty/set", [difficulty])
        await ctx.send(f"🎚️ Difficulty changed to `{difficulty}` -> `{resp}`")

    # Change game mode
    @mc.command(name="gamemode", description="Set the server game mode")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def gamemode(self, ctx, name: str, mode: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/game_mode/set", [mode])
        await ctx.send(f"🎮 Gamemode: `{mode}` -> `{resp}`")

    # Kick player
    @mc.command(name="kick", description="Kick a player from the server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def kick(self, ctx, name: str, player: str, *, reason: str = "Kicked!"):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        # PAYLOAD corrected: dict not list
        payload = {
            "players": [{"name": player}],
            "message": {"literal": reason}
        }
        resp = await self.send_rpc_request(ip, port, "minecraft:players/kick", [payload])
        await ctx.send(f"👢 Kicked `{player}`: {resp}")

    # List allowlist
    @mc.command(name="allowlist", description="Show server allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def allowlist(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist")
        names = [p['name'] for p in resp.get('result', [])]
        await ctx.send(f"📃 Allowlist: {', '.join(names) if names else 'Nobody'}")

    # Add player to allowlist
    @mc.command(name="allowlist_add", description="Add player to allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def allowlist_add(self, ctx, name: str, player: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist/add", [[{"name": player}]])
        await ctx.send(f"✅ `{player}` added to allowlist: {resp}")

    # Remove player from allowlist
    @mc.command(name="allowlist_remove", description="Remove player from allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def allowlist_remove(self, ctx, name: str, player: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist/remove", [[{"name": player}]])
        await ctx.send(f"❌ `{player}` removed from allowlist: {resp}")

    # Clear allowlist
    @mc.command(name="allowlist_clear", description="Clear the allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def allowlist_clear(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist/clear")
        await ctx.send(f"🧹 Allowlist cleared: {resp}")

    # Banlist commands
    @mc.command(name="banlist", description="Show server banlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def banlist(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:bans")
        ban_names = [b['player']['name'] for b in resp.get('result', [])]
        await ctx.send(f"⛔ Banlist: {', '.join(ban_names) if ban_names else 'Nobody banned.'}")

    @mc.command(name="ban", description="Ban a player")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def ban(self, ctx: discord.Interaction, player: str, *, reason: Optional[str] = "Banned via Discord", name: Optional[str] = None):
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)
        if not info:
            return await ctx.send("Server config not found for this channel.", ephemeral=True)

        _, _, ip, port = info
        ban_data = [{"player": {"name": player}, "reason": reason}]
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/add", [ban_data])
        await ctx.send(f"⛔ {player} banned: {resp}")



    @mc.command(name="unban", description="Unban a player")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_ban_list_autocomplete)
    async def unban(self, ctx, player: str,name: Optional[str] = None):
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/remove", [[{"name": player}]])
        await ctx.send(f"✔️ `{player}` unbanned: {resp}")

    # Clear banlist
    @mc.command(name="banlist_clear", description="Clear the banlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def banlist_clear(self, ctx, name: Optional[str] = None):
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/clear")
        await ctx.send(f"🧹 Banlist cleared: {resp}")
    
    # Operators
    @mc.command(name="ops", description="Show server operators")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def ops(self, ctx, name: Optional[str]=None):
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:operators")
        op_names = [o['player']['name'] for o in resp.get('result',[])]
        await ctx.send(f"👑 Operators: {', '.join(op_names) if op_names else 'None'}")

    @mc.command(name="op", description="Promote player to operator")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def op(self, ctx, player: str, permission_level: int = 4, name: Optional[str]=None):
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)
        _, _, ip, port = info
        op_data = [{"player": {"name": player}, "permissionLevel": permission_level, "bypassesPlayerLimit": True}]
        resp = await self.send_rpc_request(ip, port, "minecraft:operators/add", [op_data])
        await ctx.send(f"⭐ `{player}` OPed: {resp}")

    @mc.command(name="deop", description="Remove operator status")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def deop(self, ctx, player: str, name: Optional[str]=None):
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:operators/remove", [[{"name": player}]])
        await ctx.send(f"⬇️ `{player}` de-opped: {resp}")

    # Gamerules

    @mc.command(name="gamerules", description="Show all gamerules")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.describe(name="Server name (optional, defaults to this channel)")
    async def gamerules(self, ctx: discord.Interaction, name: Optional[str] = None):
        # Récupérer la config du serveur
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)

        if not info:
            return await ctx.send("❌ Aucun serveur trouvé pour ce canal.", ephemeral=True)

        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:gamerules")
        gamerules = resp.get("result", [])

        if not gamerules:
            return await ctx.send("⚠️ Aucune gamerule trouvée.", ephemeral=True)

        # Embed
        embed = discord.Embed(title=f"🎮 Gamerules for `{name or 'this server'}`", color=0x9B59B6)
        embed.description = "\n".join(f"`{r['key']}` = `{r['value']}`" for r in gamerules)
        embed.set_footer(text=f"{len(gamerules)} gamerules total")

        await ctx.send(embed=embed)


    @mc.command(name="set_gamerule", description="Set a gamerule")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def set_gamerule(self, ctx, name: str, key: str, value: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        rule = {"key": key, "value": value}
        resp = await self.send_rpc_request(ip, port, "minecraft:gamerules/update", [rule])
        await ctx.send(f"🛠️ Gamerule `{key}` set to `{value}`: {resp}")

    # Example server setting: autosave toggle
    @mc.command(name="autosave", description="Enable or disable autosave")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def autosave(self, ctx, name: str, enable: bool):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/autosave/set", [enable])
        await ctx.send(f"💾 Autosave {'enabled' if enable else 'disabled'}: {resp}")

    # Example server setting: max players
    @mc.command(name="maxplayers", description="Change maximum number of players")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def maxplayers(self, ctx, name: str, max_players: int):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/max_players/set", [max_players])
        await ctx.send(f"👥 Max players set to {max_players}: {resp}")

    # Example server setting: view distance
    @mc.command(name="viewdistance", description="Change view distance in chunks")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def viewdistance(self, ctx, name: str, distance: int):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/view_distance/set", [distance])
        await ctx.send(f"🌐 View distance set to `{distance}`: {resp}")

    # Add any additional Minecraft server setting commands here

async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftManager(bot))
