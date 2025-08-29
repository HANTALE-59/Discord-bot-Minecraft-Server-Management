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


    @tasks.loop(seconds=40)
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
                    chnl = self.bot.get_channel(channel_id)
                    chnl.send(f"Started listening for server {name}")
            except Exception:
                pass

    async def cog_load(self):
        # Start task when cog is loaded
        self.monitor_servers.start()

    async def cog_unload(self):
        # Stop the task when cog unloads
        self.monitor_servers.cancel()


    async def resolve_server(self, ctx, name: Optional[str] = None):
        """Retourne (ip, port, name) pour le serveur lié au canal ou au nom donné."""
        if name is None:
            info = await self.bot.database.get_mc_server_info(channel_id=ctx.channel.id)
        else:
            info = await self.bot.database.get_mc_server_info(mc_server_name=name)

        if not info:
            await ctx.send("❌ Server configuration not found for this channel.", ephemeral=True)
            return None

        _, _, ip, port = info
        return ip, port, name or info[0]

    def parse_rpc_response(self, resp, success_msg: str = None, error_msg: str = None):
        """Formate une réponse RPC pour un affichage Discord propre."""
        if not isinstance(resp, dict):
            return f"⚠️ Invalid response: {resp}"

        if "error" in resp:
            return f"❌ {error_msg or 'Error'}: {resp['error']}"
        elif "result" in resp:
            if success_msg:
                return f"✅ {success_msg}: {resp['result']}"
            return str(resp["result"])
        else:
            return f"❓ Unexpected response: {resp}"


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
                            status = params.get("status", {})
                            players = status.get("players", [])
                            player_names = ", ".join(p["name"] for p in players) if players else "No players"
                            embed = discord.Embed(
                                title="❤️‍🔥 Server Heartbeat",
                                description=(
                                    f"Server **{server_name}** is alive!\n"
                                    f"Players online: **{len(players)}** ({player_names})"
                                ),
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
            # Request the list of online players via minecraft:players RPC method
            resp = await self.send_rpc_request(ip, port, "minecraft:players")
            players = resp.get("result", [])
        except Exception:
            return []

        # Filter players by current input string (case insensitive)
        player_names = [p["name"] for p in players if current.lower() in p["name"].lower()]

        # Limit to max 25 choices for Discord autocomplete
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
    async def add_server(self, ctx: Context, name: Optional[str] = None, ip: str = "localhost", port: int = 25585):
        success = await self.bot.database.add_minecraft_server(ctx.guild.id, ctx.channel.id, name, ip, port)
        msg = "✅ Server added." if success else "❌ Name already taken."
        await ctx.send(msg)

    # Remove a Minecraft server
    @mc_config.command(name="remove", description="Remove a Minecraft server connection")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def remove_server(self, ctx: Context, name: Optional[str] = None):
        success = await self.bot.database.remove_minecraft_server(ctx.guild.id, name)
        msg = f"🗑️ Server `{name}` removed." if success else f"❌ Server `{name}` not found."
        await ctx.send(msg)

    # Edit a Minecraft server
    @mc_config.command(name="edit", description="Edit an existing Minecraft server connection")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def edit_server(self, ctx: Context, name: Optional[str] = None, new_ip: str = None, new_port: int = None):
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
    @mc.command(name="connect", description="Start listening to server events")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def connect(self, ctx, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        self.listeners[name] = asyncio.create_task(self.listen_to_mc_server(ip, port, channel_id, name))
        self.active_servers.add(name)  # Mark as active
        await ctx.send(f"🎧 Listening for events from `{name}` ({ip}:{port})")

    @mc.command(name="disconnect", description="Stop listening to Minecraft server events")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def disconnect(self, ctx: commands.Context, name: Optional[str] = None):
        if name not in self.listeners:
            await ctx.send(f"⚠️ Bot is not currently listening to server `{name}`.")
            return

        # Cancel the listening task
        task = self.listeners.pop(name)
        task.cancel()

        # Remove from active servers set
        self.active_servers.discard(name)

        await ctx.send(f"🛑 Disconnected from server `{name}`. No longer listening to events.")


    # Stop server // Need to use /mc start now lol
    @mc.command(name="stop", description="Stop the Minecraft server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def stop_server(self, ctx, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:server/stop")
        await ctx.send(f"🛑 Stop server: `{resp}`")

    @mc_config.command(name="broadcast", description="Send a system message to all players")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def broadcast(self, ctx, *, message: str, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server

        payload = {
            "message": {"literal": message},
            "overlay": False,
            "receivingPlayers": []  # vide = tout le monde
        }
        resp = await self.send_rpc_request(ip, port, "minecraft:server/system_message", [payload])
        await ctx.send(self.parse_rpc_response(resp, success_msg=f"Broadcast sent: {message}"))

    ########################################
    # Get server status
    @mc.command(name="status", description="Get the current status of the server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def status(self, ctx, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
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
    async def motd(self, ctx, name: Optional[str] = None, *, motd: str):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/motd/set", [motd])
        await ctx.send(self.parse_rpc_response(resp, success_msg=f"MOTD changed to `{motd}`"))

        '''
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/motd/set", [motd])
        if "result" in resp:
            await ctx.send(f"✅ MOTD changed: `{motd}`")
        else:
            await ctx.send(f"⚠️ Error: `{resp}`")
        '''
    # Change difficulty
    @mc.command(name="difficulty", description="Set the server difficulty")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def difficulty(self, ctx, difficulty: Literal['peacful','easy','medium','hard'], name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/difficulty/set", [difficulty])
        await ctx.send(f"🎚️ Difficulty changed to `{difficulty}` -> `{resp}`")

    # Change game mode
    @mc.command(name="gamemode", description="Set the server game mode")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def gamemode(self, ctx, mode: Literal['survival','creative','spectator','adventure'], name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/game_mode/set", [mode])
        await ctx.send(f"🎮 Gamemode: `{mode}` -> `{resp}`")

    # Kick player
    @mc.command(name="kick", description="Kick a player from the server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def kick(self, ctx, player: str, *, reason: str = "Kicked! 🦵 👢", name: Optional[str]):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
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
    async def allowlist(self, ctx, name: Optional[str]=None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist")
        names = [p['name'] for p in resp.get('result', [])]
        await ctx.send(f"📃 Allowlist: {', '.join(names) if names else 'Nobody'}")

    # Add player to allowlist
    @mc.command(name="allowlist_add", description="Add player to allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def allowlist_add(self, ctx, player: str, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist/add", [[{"name": player}]])
        await ctx.send(f"✅ `{player}` added to allowlist: {resp}")

    # Remove player from allowlist
    @mc.command(name="allowlist_remove", description="Remove player from allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def allowlist_remove(self, ctx, player: str, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist/remove", [[{"name": player}]])
        await ctx.send(f"❌ `{player}` removed from allowlist: {resp}")

    # Clear allowlist
    @mc.command(name="allowlist_clear", description="Clear the allowlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def allowlist_clear(self, ctx, name: Optional[str]=None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:allowlist/clear")
        await ctx.send(f"🧹 Allowlist cleared: {resp}")

    # Banlist commands
    @mc.command(name="banlist", description="Show server banlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def banlist(self, ctx, name: Optional[str]=None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:bans")
        ban_names = [b['player']['name'] for b in resp.get('result', [])]
        await ctx.send(f"⛔ Banlist: {', '.join(ban_names) if ban_names else 'Nobody banned.'}")

    @mc.command(name="ban", description="Ban a player")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def ban(self, ctx: discord.Interaction, player: str, *, reason: Optional[str] = "Banned via Discord", name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        ban_data = [{"player": {"name": player}, "reason": reason}]
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/add", [ban_data])
        await ctx.send(f"⛔ {player} banned: {resp}")



    @mc.command(name="unban", description="Unban a player")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_ban_list_autocomplete)
    async def unban(self, ctx, player: str,name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/remove", [[{"name": player}]])
        await ctx.send(f"✔️ `{player}` unbanned: {resp}")

    # Clear banlist
    @mc.command(name="banlist_clear", description="Clear the banlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def banlist_clear(self, ctx, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/clear")
        await ctx.send(f"🧹 Banlist cleared: {resp}")
    
    # Operators
    @mc.command(name="ops", description="Show server operators")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def ops(self, ctx, name: Optional[str]=None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:operators")
        op_names = [o['player']['name'] for o in resp.get('result',[])]
        await ctx.send(f"👑 Operators: {', '.join(op_names) if op_names else 'None'}")

    @mc.command(name="op", description="Promote player to operator")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def op(self, ctx, player: str, permission_level: Literal[1,2,3,4]=4, name: Optional[str]=None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        op_data = [{"player": {"name": player}, "permissionLevel": permission_level, "bypassesPlayerLimit": True}]
        resp = await self.send_rpc_request(ip, port, "minecraft:operators/add", [op_data])
        await ctx.send(f"⭐ `{player}` OPed: {resp}")

    @mc.command(name="deop", description="Remove operator status")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.autocomplete(player=mc_online_players_autocomplete)
    async def deop(self, ctx, player: str, name: Optional[str]=None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:operators/remove", [[{"name": player}]])
        await ctx.send(f"⬇️ `{player}` de-opped: {resp}")

    # Gamerules

    @mc.command(name="gamerules", description="Show all gamerules")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.describe(name="Server name (optional, defaults to this channel)")
    async def gamerules(self, ctx: discord.Interaction, name: Optional[str] = None):
        # Récupérer la config du serveur
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
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
    async def set_gamerule(self, ctx, key: str, value: str, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        rule = {"key": key, "value": value}
        resp = await self.send_rpc_request(ip, port, "minecraft:gamerules/update", [rule])
        await ctx.send(f"🛠️ Gamerule `{key}` set to `{value}`: {resp}")

    # Example server setting: autosave toggle
    @mc.command(name="autosave", description="Enable or disable autosave")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def autosave(self, ctx, enable: bool, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/autosave/set", [enable])
        await ctx.send(f"💾 Autosave {'enabled' if enable else 'disabled'}: {resp}")

    # Example server setting: max players
    @mc.command(name="maxplayers", description="Change maximum number of players")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def maxplayers(self, ctx, max_players: int, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port,"minecraft:serversettings/max_players/set",[max_players])
        await ctx.send(self.parse_rpc_response(resp, success_msg=f"👥 Max players set to {max_players}"))

    # Example server setting: view distance
    @mc.command(name="viewdistance", description="Change view distance in chunks")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def viewdistance(self, ctx, distance: int, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server
        resp = await self.send_rpc_request(ip, port, "minecraft:serversettings/view_distance/set", [distance])
        await ctx.send(f"🌐 View distance set to `{distance}`: {resp}")


    @mc_config.command(name="status_full", description="Show complete server status and info")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def status_full(self, ctx: commands.Context, name: Optional[str] = None):
        server = await self.resolve_server(ctx, name)
        if not server:
            return
        ip, port, name = server

        tasks = [
            self.send_rpc_request(ip, port, "minecraft:server/status"),
            self.send_rpc_request(ip, port, "minecraft:players"),
            self.send_rpc_request(ip, port, "minecraft:bans"),
            self.send_rpc_request(ip, port, "minecraft:ip_bans"),
            self.send_rpc_request(ip, port, "minecraft:operators"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/motd"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/difficulty"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/game_mode"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/max_players"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/autosave"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/use_allowlist"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/enforce_allowlist"),
            self.send_rpc_request(ip, port, "minecraft:allowlist"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/allow_flight"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/force_game_mode"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/view_distance"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/simulation_distance"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/spawn_protection_radius"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/player_idle_timeout"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/pause_when_empty_seconds"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/entity_broadcast_range"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/operator_user_permission_level"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/hide_online_players"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/accept_transfers"),
            self.send_rpc_request(ip, port, "minecraft:serversettings/status_replies"),
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        (status_resp, players_resp, bans_resp, ip_bans_resp, ops_resp,
         motd_resp, difficulty_resp, gamemode_resp, maxplayers_resp, autosave_resp,
         use_allowlist_resp, enforce_allowlist_resp, allowlist_resp, allow_flight_resp,
         force_gamemode_resp, view_distance_resp, sim_distance_resp, spawn_protection_resp,
         idle_timeout_resp, pause_empty_resp, entity_broadcast_resp, op_perm_resp,
         hide_players_resp, accept_transfers_resp, status_replies_resp) = results

        embed = discord.Embed(
            title=f"🖥️ Server Status: {name or 'this server'}",
            color=discord.Color.blurple(),
            timestamp=datetime.utcnow()
        )

        # Server online / version
        if isinstance(status_resp, dict) and "result" in status_resp:
            online = status_resp["result"].get("started", False)
            version = status_resp["result"].get("version", {})
            embed.add_field(
                name="Status",
                value=("🟢 Online" if online else "🔴 Offline") +
                      f"\nVersion: {version.get('name','?')} (protocol {version.get('protocol','?')})",
                inline=False
            )
        else:
            embed.add_field(name="Status", value="❓ Unknown", inline=False)

        # --- Joueurs ---
        if isinstance(players_resp, dict) and "result" in players_resp:
            players = players_resp["result"]
            if players:
                embed.add_field(name=f"👥 Players Online ({len(players)})",
                                value="\n".join(p["name"] for p in players[:15]) +
                                      (f"\n...+{len(players)-15} more" if len(players) > 15 else ""),
                                inline=False)
            else:
                embed.add_field(name="👥 Players Online", value="No players online", inline=False)
        embed.add_field(name="🔨 Operators",
                        value=", ".join(o["player"]["name"] for o in ops_resp.get("result", [])) or "None",
                        inline=False)

        # --- Listes spéciales ---
        embed.add_field(name="🚫 Banlist",
                        value=f"{len(bans_resp.get('result', []))} players | {len(ip_bans_resp.get('result', []))} IPs",
                        inline=True)
        if use_allowlist_resp and "result" in use_allowlist_resp:
            allowlist_enabled = use_allowlist_resp["result"]
            enforced = enforce_allowlist_resp.get("result", False)
            embed.add_field(name="📜 Whitelist",
                            value=("✅ Enabled" if allowlist_enabled else "❌ Disabled") +
                                  (", Enforced" if enforced else ""),
                            inline=True)
        if allowlist_resp and "result" in allowlist_resp:
            wl = [p.get("name", "?") for p in allowlist_resp["result"]]
            embed.add_field(name="Whitelisted Players",
                            value=", ".join(wl[:15]) + (f"...+{len(wl)-15}" if len(wl) > 15 else "") or "None",
                            inline=False)

        # --- Paramètres serveur ---
        embed.add_field(name="⚙️ Difficulty", value=difficulty_resp.get("result", "Unknown"), inline=True)
        embed.add_field(name="🎮 Game Mode", value=gamemode_resp.get("result", "Unknown"), inline=True)
        embed.add_field(name="👤 Max Players", value=str(maxplayers_resp.get("result", "?")), inline=True)
        embed.add_field(name="💾 Autosave", value="✅" if autosave_resp.get("result", False) else "❌", inline=True)
        embed.add_field(name="✈️ Flight Allowed", value="✅" if allow_flight_resp.get("result", False) else "❌", inline=True)
        embed.add_field(name="🎯 Force GameMode", value="✅" if force_gamemode_resp.get("result", False) else "❌", inline=True)

        # --- Distances & protections ---
        embed.add_field(name="🔭 View Distance", value=str(view_distance_resp.get("result", "?")), inline=True)
        embed.add_field(name="🧮 Simulation Distance", value=str(sim_distance_resp.get("result", "?")), inline=True)
        embed.add_field(name="🛡️ Spawn Protection", value=str(spawn_protection_resp.get("result", "?")) + " blocks", inline=True)
        embed.add_field(name="📡 Entity Broadcast", value=str(entity_broadcast_resp.get("result", "?")) + "%", inline=True)

        # --- Timeouts ---
        embed.add_field(name="⌛ Idle Timeout", value=f"{idle_timeout_resp.get('result','?')}s", inline=True)
        embed.add_field(name="⏸️ Pause When Empty", value=f"{pause_empty_resp.get('result','?')}s", inline=True)

        # --- Réseau ---
        embed.add_field(name="🌐 Hide Players", value="✅" if hide_players_resp.get("result", False) else "❌", inline=True)
        embed.add_field(name="🔄 Accept Transfers", value="✅" if accept_transfers_resp.get("result", False) else "❌", inline=True)
        embed.add_field(name="📶 Status Replies", value="✅" if status_replies_resp.get("result", False) else "❌", inline=True)

        # --- Permissions ---
        embed.add_field(name="🔑 Operator Permission Level", value=str(op_perm_resp.get("result", "?")), inline=True)

        # MOTD
        if motd_resp and "result" in motd_resp:
            motd = motd_resp["result"]
            embed.add_field(name="📝 MOTD", value=str(motd), inline=False)

        await ctx.send(embed=embed)

async def setup(bot: commands.Bot):
    await bot.add_cog(MinecraftManager(bot))
