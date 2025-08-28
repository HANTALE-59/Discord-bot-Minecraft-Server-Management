import discord
from discord import app_commands
from discord.ext import commands
from discord.ext.commands import Context
from typing import Literal
import json
import websockets
import asyncio
#from assets.data import Data
import requests
from mojang import API as MOJANG_API
class Minecraft(commands.Cog, name="minecraft"):
    def __init__(self, bot) -> None:
        self.bot = bot
        
    """ //Useless now but we never know...

    async def listen_to_mc_server(self, mc_ip: str, mc_port: int, channel_id: int, server_name: str):
        ws_url = f"ws://{mc_ip}:{mc_port}"
        try:
            channel = self.bot.get_channel(channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(channel_id)

            async with websockets.connect(ws_url) as websocket:
                # Découverte de l'API
                await websocket.send(json.dumps({"id": 1, "jsonrpc": "2.0", "method": "rpc.discover"}))
                discover_response = await websocket.recv()
                print(f"Découverte MSMP pour {server_name}: {discover_response}")

                while True:
                    message_raw = await websocket.recv()
                    message = json.loads(message_raw)
                    # Affiche toutes les notifications brutes
                    print(f"MSMP raw message: {message}")

                    # Notification joueur rejoint
                    if message.get("method") == "notification:players/joined":
                        params = message.get("params", [{}])[0]
                        player_name = params.get("name", "Unknown")
                        if channel:
                            await channel.send(
                                f"✅ Player`{player_name}` just joined `{server_name}`!"
                            )


                    # Notification joueur quitte
                    if message.get("method") == "notification:players/left":
                        params = message.get("params", [{}])[0]
                        player_name = params.get("name", "Unknown")
                        if channel:
                            await channel.send(
                                f"✅ Player`{player_name}` just left `{server_name}`!"
                            )


        except Exception as e:
            print(f"Erreur de connexion au serveur {server_name}: {e}")
            if channel:
                await channel.send(f"❌ Impossible de se connecter au serveur `{server_name}`: `{e}`")






    async def mc_serv_name_autocomplete(self, ctx, current: str):
        # Récupérer tous les noms d'utilisateurs uniques
        all_users = await self.bot.database.get_all_mc_servers()
        # Extraire les usernames et filtrer par ceux qui correspondent au texte tapé (current)
        usernames = [row[0] for row in all_users if current.lower() in row[0].lower()]
        # Limiter le nombre de résultats à 25, car c'est la limite pour Discord
        return [
            app_commands.Choice(name=mc_server_name, value=mc_server_name)
            for mc_server_name in usernames[:25]
        ]

    @commands.hybrid_group(
        name="servers",
        description="Manage the minecraft servers",
    )
    @commands.has_permissions(ban_members=True)
    async def servers(self, context: Context) -> None:
        if context.invoked_subcommand is None:
            embed = discord.Embed(
                description="Please specify a subcommand.\n\n**Subcommands:**\n`add` - Add a server configuration\n`edit` - edit a server configuration\n`remove` - remove a server configuration",
                color=0xE02B2B)
            await context.send(embed=embed)


    @servers.command(
        name="add",
        description="Add a server configuration")
    async def add(self, ctx, name: str, ip: str = "localhost", port: int = 25585) -> None:
        await ctx.defer()
        add = await self.bot.database.add_minecraft_server(
            server_id=ctx.guild.id,
            channel_id=ctx.channel.id,
            mc_server_name=name,
            mc_IP=ip,
            mc_port=port
        )
        if add is False:
            await ctx.send('Server name already taken, choose a new one')
            return
        await ctx.send('Good')


    @servers.command(
        name="start",
        description="Start using your server protocol"
    )
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.describe(name="Choose the server you want to link with")
    async def start(self, ctx, name: str):
        await ctx.defer()

        # Récupérer les infos du serveur
        server_info = await self.bot.database.get_mc_server_info(name)
        if not server_info:
            await ctx.send("❌ Aucun serveur trouvé avec ce nom.")
            return

        server_id, channel_id, mc_ip, mc_port = server_info

        # Lancer la task d'écoute en arrière-plan
        asyncio.create_task(
            self.listen_to_mc_server(mc_ip, mc_port, channel_id, name)
        )

        await ctx.send(f"✅ Écoute activée pour le serveur `{name}` ({mc_ip}:{mc_port})")




    @servers.command(
        name="stop",
        description="Stop a Minecraft server using the MSMP protocol"
    )
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.describe(name="Choose the server you want to stop")
    async def stop(self, ctx, name: str):
        await ctx.defer()

        # Récupérer les infos du serveur
        server_info = await self.bot.database.get_mc_server_info(name)
        if not server_info:
            await ctx.send("❌ Aucun serveur trouvé avec ce nom.")
            return

        server_id, channel_id, mc_ip, mc_port = server_info
        ws_url = f"ws://{mc_ip}:{mc_port}"

        try:
            async with websockets.connect(ws_url) as websocket:
                # Envoyer la commande stop
                request = {
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "minecraft:server/stop",
                    "params": []
                }
                await websocket.send(json.dumps(request))

                # Essayer de recevoir la réponse (il se peut que le serveur ferme avant)
                try:
                    response_raw = await websocket.recv()
                    response = json.loads(response_raw)
                    await ctx.send(f"🛑 Le serveur `{name}` a été stoppé avec succès.")
                except websockets.ConnectionClosedOK:
                    # Le serveur a fermé le WS normalement
                    await ctx.send(f"🛑 Le serveur `{name}` a été stoppé (WebSocket fermé).")

        finally:
            await websocket.close()

    @servers.command(
        name="motd",
        description="Change the Minecraft server's MOTD"
    )
    @app_commands.autocomplete(name=mc_serv_name_autocomplete)
    @app_commands.describe(
        name="Server name",
        motd="New message of the day for the server"
    )
    async def motd(self, ctx, name: str, *, motd: str):
        await ctx.defer()

        # Récupérer les infos du serveur
        server_info = await self.bot.database.get_mc_server_info(name)
        if not server_info:
            await ctx.send(f"❌ Aucun serveur trouvé avec le nom `{name}`.")
            return

        server_id, channel_id, mc_ip, mc_port = server_info
        ws_url = f"ws://{mc_ip}:{mc_port}"

        try:
            async with websockets.connect(ws_url) as websocket:
                # Envoyer la commande pour changer le MOTD
                request = {
                    "id": 1,
                    "jsonrpc": "2.0",
                    "method": "minecraft:serversettings/motd/set",
                    "params": [motd]  # <-- juste la chaîne
                }
                await websocket.send(json.dumps(request))

                # Recevoir la réponse
                response_raw = await websocket.recv()
                response = json.loads(response_raw)

                if "result" in response:
                    await ctx.send(f"✅ MOTD changé pour `{name}` : `{motd}`")
                else:
                    await ctx.send(f"⚠️ Impossible de changer le MOTD :\n```json\n{json.dumps(response, indent=2)}```")

        except Exception as e:
            await ctx.send(f"❌ Erreur lors de la connexion au serveur `{name}` : `{e}`")



    """

######################################




    @commands.hybrid_command(description='get information about minecraft accounts')
    @app_commands.allowed_installs(guilds=True, users=True)
    @app_commands.allowed_contexts(guilds=True, dms=True, private_channels=True)
    async def mcinfo(self, ctx, username: str):
        await ctx.defer()


        mojang = MOJANG_API()

        uuid2 = mojang.get_uuid(username=username)
        if not uuid2:
            await ctx.send(f'{username} is not taken')
            return
        profile2 = mojang.get_profile(uuid=uuid2)
        await ctx.send(f"{username}'s skin : {profile2.skin_url}\ncape : {profile2.cape_url}\nis legacy profile : {profile2.is_legacy_profile}\ntimestamp : {profile2.timestamp}  ")


        """Get information about a Minecraft account."""
        url = f"https://api.mojang.com/users/profiles/minecraft/{username}"
        response = requests.get(url)
        if response.status_code == 200:
            player_data = response.json()
            uuid = player_data['id']
            name = player_data['name']
            skin_url = f"https://crafatar.com/skins/{uuid}"
            cape_url = f"https://crafatar.com/capes/{uuid}"
            
            embed = discord.Embed(title=name, url=f'https://fr.namemc.com/profile/{uuid}',color=0x00ff00)
            #embed.add_field(name="Username", value=name, inline=False)
            embed.add_field(name="UUID", value=uuid, inline=False)
            #embed.add_field(name="Skin", value=skin_url, inline=False)
            #embed.add_field(name="Cape", value=cape_url, inline=False)
            embed.set_thumbnail(url=f'https://mc-heads.net/avatar/{uuid}')
            embed.set_image(url=f'https://mc-heads.net/body/{uuid}/right')
            
            

            await ctx.send(embed=embed)
        else:
            embed = discord.embed(title='Account no found!',description='try again with an existing minecraft account name',color=0xFF0000)
            await ctx.send(embed=embed)



    @commands.hybrid_group(
        name="minecraft",
        description="Manage the minecraft news on your server.",
    )
    @commands.has_permissions(manage_messages=True)
    async def minecraft(self, context: Context) -> None:
        if context.invoked_subcommand is None:
            embed = discord.Embed(
                description="Please specify a subcommand.\n\n**Subcommands:**\n`snapshot` - Adds a snapshot newsletter to the servers",
                color=0xE02B2B)
            await context.send(embed=embed)

    @minecraft.command(
        name="snapshot",
        description="Adds a snapshot newsletter to the servers")
    @commands.has_permissions(manage_messages=True)
    async def snapshot(self, ctx, edition:Literal['Java','Bedrock','Both'],channel:discord.TextChannel) -> None:
        if channel is None:
            await ctx.send("Insufficient Arguments")
        else:
            if str(ctx.guild.id) not in Data.server_data:
                Data.server_data[str(ctx.guild.id)] = Data.create_new_data()

            if edition == 'Java':

                Data.server_data[str(ctx.guild.id)]["snapshot_java"].append(str(channel.id))
                await ctx.send(f"Added {channel.mention} to the java snapshot newsletter")            
            
            elif edition == 'Bedrock':

                Data.server_data[str(ctx.guild.id)]["snapshot_bedrock"].append(str(channel.id))
                await ctx.send(f"Added {channel.mention} to the bedrock snapshot newsletter")
            
            elif edition == 'Both':
                Data.server_data[str(ctx.guild.id)]["snapshot_bedrock"].append(str(channel.id))
                Data.server_data[str(ctx.guild.id)]["snapshot_java"].append(str(channel.id))
                await ctx.send(f"Added {channel.mention} to the java and bedrock snapshot newsletter")
            

            
            # Call auto_update_data to save changes to data.json
            await Data.auto_update_data()


async def setup(bot) -> None:
    await bot.add_cog(Minecraft(bot))
