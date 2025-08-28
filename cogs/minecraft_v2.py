import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
import asyncio
import json
import websockets

class MinecraftManager(commands.Cog, name="minecraft_v2"):
    """A fully featured Minecraft server management cog using MSMP."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self.listeners = {}

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
        except Exception as e:
            return {"error": str(e)}

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
                        # All main server notifications
                        if method == "notification:players/joined":
                            await channel.send(f"✅ `{params.get('name')}` joined `{server_name}`!")
                        elif method == "notification:players/left":
                            await channel.send(f"❌ `{params.get('name')}` left `{server_name}`.")
                        elif method == "notification:bans/added":
                            await channel.send(f"⛔ `{params['player']['name']}` was banned!")
                        elif method == "notification:bans/removed":
                            await channel.send(f"✔️ `{params['name']}` was unbanned!")
                        elif method == "notification:allowlist/added":
                            await channel.send(f"📃 `{params.get('name')}` added to allowlist.")
                        elif method == "notification:allowlist/removed":
                            await channel.send(f"📃 `{params.get('name')}` removed from allowlist.")
                        elif method == "notification:operators/added":
                            await channel.send(f"⭐ `{params['player']['name']}` is now OP!")
                        elif method == "notification:operators/removed":
                            await channel.send(f"⚠️ `{params['player']['name']}` removed from OPs.")
                        elif method == "notification:server/started":
                            await channel.send("🟢 Server started.")
                        elif method == "notification:server/stopping":
                            await channel.send("🛑 Server stopping.")
                        elif method == "notification:server/saving":
                            await channel.send("💾 Server save started.")
                        elif method == "notification:server/saved":
                            await channel.send("💾 Server saved.")
                        elif method == "notification:gamerules/updated":
                            rule = params.get("gamerule", {})
                            await channel.send(f"🎮 Gamerule `{rule.get('key')}` updated to `{rule.get('value')}`.")
                    except websockets.ConnectionClosed:
                        await channel.send(f"⚠️ Connection to `{server_name}` lost.")
                        break
        except Exception as e:
            await channel.send(f"❌ Could not connect to `{server_name}`: `{e}`")

    # Autocomplete for server names
    async def mc_serv_name_autocomplete(self, _, current: str):
        all_servers = await self.bot.database.get_all_mc_servers()
        servers = [row[0] for row in all_servers if current.lower() in row[0].lower()]
        return [app_commands.Choice(name=s, value=s) for s in servers[:25]]

    # Command group for Minecraft server
    @commands.hybrid_group(name="mc", description="Minecraft server management")
    async def mc(self, ctx: Context):
        """Root group for Minecraft commands."""
        if ctx.invoked_subcommand is None:
            await ctx.send("Use a subcommand. Try `/mc help`.")

    # Add a Minecraft server
    @mc.command(name="add", description="Add a Minecraft server connection")
    async def add_server(self, ctx: Context, name: str, ip: str = "localhost", port: int = 25585):
        success = await self.bot.database.add_minecraft_server(ctx.guild.id, ctx.channel.id, name, ip, port)
        msg = "✅ Server added." if success else "❌ Name already taken."
        await ctx.send(msg)

    # Start listening for events on the server
    @mc.command(name="start", description="Start listening to server events")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def start(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        if not info:
            return await ctx.send("❌ Server not found.")
        _, channel_id, ip, port = info
        self.listeners[name] = asyncio.create_task(self.listen_to_mc_server(ip, port, channel_id, name))
        await ctx.send(f"🎧 Listening for events from `{name}` ({ip}:{port})")

    # Stop server
    @mc.command(name="stop", description="Stop the Minecraft server")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def stop_server(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        if not info:
            return await ctx.send("❌ Not found.")
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:server/stop")
        await ctx.send(f"🛑 Stop server: `{resp}`")

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
    async def ban(self, ctx, name: str, player: str, *, reason: str = "Banned via Discord"):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        ban_data = [{"player": {"name": player}, "reason": reason}]
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/add", [ban_data])
        await ctx.send(f"⛔ `{player}` banned: {resp}")

    @mc.command(name="unban", description="Unban a player")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def unban(self, ctx, name: str, player: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/remove", [[{"name": player}]])
        await ctx.send(f"✔️ `{player}` unbanned: {resp}")

    # Clear banlist
    @mc.command(name="banlist_clear", description="Clear the banlist")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def banlist_clear(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:bans/clear")
        await ctx.send(f"🧹 Banlist cleared: {resp}")

    # Operators
    @mc.command(name="ops", description="Show server operators")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def ops(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:operators")
        op_names = [o['player']['name'] for o in resp.get('result',[])]
        await ctx.send(f"👑 Operators: {', '.join(op_names) if op_names else 'None'}")

    @mc.command(name="op", description="Promote player to operator")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def op(self, ctx, name: str, player: str, permission_level: int = 4):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        op_data = [{"player": {"name": player}, "permissionLevel": permission_level, "bypassesPlayerLimit": True}]
        resp = await self.send_rpc_request(ip, port, "minecraft:operators/add", [op_data])
        await ctx.send(f"⭐ `{player}` OPed: {resp}")

    @mc.command(name="deop", description="Remove operator status")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def deop(self, ctx, name: str, player: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:operators/remove", [[{"name": player}]])
        await ctx.send(f"⬇️ `{player}` de-opped: {resp}")

    # Gamerules
    @mc.command(name="gamerules", description="Show all gamerules")
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    async def gamerules(self, ctx, name: str):
        info = await self.bot.database.get_mc_server_info(name)
        _, _, ip, port = info
        resp = await self.send_rpc_request(ip, port, "minecraft:gamerules")
        rules = "\n".join([f"{r['key']} = {r['value']}" for r in resp.get('result', [])])
        await ctx.send(f"🎮 Gamerules:\n``````")

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
