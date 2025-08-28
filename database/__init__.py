import aiosqlite

class DatabaseManager:
    def __init__(self, *, connection: aiosqlite.Connection) -> None:
        self.connection = connection

    async def add_minecraft_server(
        self, 
        server_id: int, 
        channel_id: int, 
        mc_server_name: str, 
        mc_IP: str, 
        mc_port: int
    ) -> bool:
        # Vérifier si un serveur existe déjà avec ce nom dans le même serveur Discord
        async with self.connection.execute(
            "SELECT 1 FROM minecraft_servers WHERE mc_server_name = ? AND server_id = ?",
            (mc_server_name, server_id)
        ) as cursor:
            row = await cursor.fetchone()

        if row is not None:
            return False  # Déjà existant

        # Sinon → insérer
        await self.connection.execute(
            """
            INSERT INTO minecraft_servers (server_id, channel_id, mc_server_name, mc_IP, mc_port) 
            VALUES (?, ?, ?, ?, ?)
            """,
            (server_id, channel_id, mc_server_name, mc_IP, mc_port)
        )
        await self.connection.commit()
        return True

    async def get_all_mc_servers(self):
        """Retourne la liste des noms de serveurs enregistrés"""
        async with self.connection.execute(
            "SELECT DISTINCT mc_server_name FROM minecraft_servers"
        ) as cursor:
            return await cursor.fetchall()

    async def get_all_mc_servers_full(self):
        async with self.connection.execute(
            "SELECT mc_server_name, mc_IP, mc_port, channel_id FROM minecraft_servers"
        ) as cursor:
            return await cursor.fetchall()

    async def get_mc_server_info(self, mc_server_name: str = None, channel_id: int = None):
        if mc_server_name is not None:
            query = "SELECT server_id, channel_id, mc_IP, mc_port FROM minecraft_servers WHERE mc_server_name = ?"
            params = (mc_server_name,)
        elif channel_id is not None:
            query = "SELECT server_id, channel_id, mc_IP, mc_port FROM minecraft_servers WHERE channel_id = ?"
            params = (channel_id,)
        else:
            return None

        async with self.connection.execute(query, params) as cursor:
            return await cursor.fetchone()


    async def remove_minecraft_server(self, server_id: int, mc_server_name: str) -> bool:
        """Supprime un serveur Minecraft d’un serveur Discord"""
        async with self.connection.execute(
            "DELETE FROM minecraft_servers WHERE server_id = ? AND mc_server_name = ?",
            (server_id, mc_server_name)
        ) as cursor:
            await self.connection.commit()
            return cursor.rowcount > 0

    async def edit_minecraft_server(
        self, 
        server_id: int, 
        mc_server_name: str, 
        new_ip: str = None, 
        new_port: int = None
    ) -> bool:
        """Modifie l'IP et/ou le port d’un serveur"""
        if not new_ip and not new_port:
            return False  # Rien à changer

        # Construire la requête dynamiquement
        updates = []
        params = []
        if new_ip:
            updates.append("mc_IP = ?")
            params.append(new_ip)
        if new_port:
            updates.append("mc_port = ?")
            params.append(new_port)
        params.extend([server_id, mc_server_name])

        query = f"""
            UPDATE minecraft_servers
            SET {", ".join(updates)}
            WHERE server_id = ? AND mc_server_name = ?
        """
        async with self.connection.execute(query, params) as cursor:
            await self.connection.commit()
            return cursor.rowcount > 0

#####################################

    async def add_warn(
        self, user_id: int, server_id: int, moderator_id: int, reason: str
    ) -> int:
        """
        This function will add a warn to the database.

        :param user_id: The ID of the user that should be warned.
        :param reason: The reason why the user should be warned.
        """
        rows = await self.connection.execute(
            "SELECT id FROM warns WHERE user_id=? AND server_id=? ORDER BY id DESC LIMIT 1",
            (
                user_id,
                server_id,
            ),
        )
        async with rows as cursor:
            result = await cursor.fetchone()
            warn_id = result[0] + 1 if result is not None else 1
            await self.connection.execute(
                "INSERT INTO warns(id, user_id, server_id, moderator_id, reason) VALUES (?, ?, ?, ?, ?)",
                (
                    warn_id,
                    user_id,
                    server_id,
                    moderator_id,
                    reason,
                ),
            )
            await self.connection.commit()
            return warn_id

    async def remove_warn(self, warn_id: int, user_id: int, server_id: int) -> int:
        """
        This function will remove a warn from the database.

        :param warn_id: The ID of the warn.
        :param user_id: The ID of the user that was warned.
        :param server_id: The ID of the server where the user has been warned
        """
        await self.connection.execute(
            "DELETE FROM warns WHERE id=? AND user_id=? AND server_id=?",
            (
                warn_id,
                user_id,
                server_id,
            ),
        )
        await self.connection.commit()
        rows = await self.connection.execute(
            "SELECT COUNT(*) FROM warns WHERE user_id=? AND server_id=?",
            (
                user_id,
                server_id,
            ),
        )
        async with rows as cursor:
            result = await cursor.fetchone()
            return result[0] if result is not None else 0

    async def get_warnings(self, user_id: int, server_id: int) -> list:
        """
        This function will get all the warnings of a user.

        :param user_id: The ID of the user that should be checked.
        :param server_id: The ID of the server that should be checked.
        :return: A list of all the warnings of the user.
        """
        rows = await self.connection.execute(
            "SELECT user_id, server_id, moderator_id, reason, strftime('%s', created_at), id FROM warns WHERE user_id=? AND server_id=?",
            (
                user_id,
                server_id,
            ),
        )
        async with rows as cursor:
            result = await cursor.fetchall()
            result_list = []
            for row in result:
                result_list.append(row)
            return result_list
