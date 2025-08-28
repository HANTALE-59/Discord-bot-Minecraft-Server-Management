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
    def __init__(self, bot):
        self.bot = bot
        self.listeners = {}



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
