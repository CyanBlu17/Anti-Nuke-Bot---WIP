import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import asyncio
import random
import time
import re
import json

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="/", intents=intents)

audit_channel_id = None 

logging.basicConfig(level=logging.INFO)

spam_tracker = {}
warn_tracker = {}
blacklisted_users = set()
mention_tracker = {}

@bot.tree.command()
async def about(interaction: discord.Interaction):
    await interaction.response.send_message("I am a security bot that helps prevent raids and nukes. I monitor server activity and provide commands to ban users and prevent malicious actions.")

@bot.tree.command()
async def ban(interaction: discord.Interaction, user: discord.User, reason: str = None):
    if interaction.user.guild_permissions.ban_members:
        await interaction.guild.ban(user, reason=reason)
        await interaction.response.send_message(f"Banned {user.name} for reason: {reason}")
        await log_event(f"Banned {user.name} for {reason}")
    else:
        await interaction.response.send_message("You don't have permission to ban users.")

@bot.tree.command(name="lockdown", description="Lock all channels in a category.")
async def lockall(interaction: discord.Interaction, category: discord.CategoryChannel):
    for channel in category.channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"\U0001F512 All channels in {category.name} have been locked.")

@bot.tree.command(name="unlockall", description="Unlock all channels in a category.")
async def unlockall(interaction: discord.Interaction, category: discord.CategoryChannel, delay: int = 0):
    if delay > 0:
        await asyncio.sleep(delay)
    for channel in category.channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = True
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"\U0001F513 All channels in {category.name} have been unlocked.")

@bot.tree.command(name="warn", description="Warn a user for inappropriate behavior.")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if interaction.user.guild_permissions.administrator:
        if member.id not in warn_tracker:
            warn_tracker[member.id] = 0
        warn_tracker[member.id] += 1
        await member.send(f"You have been warned in {interaction.guild.name} for: {reason}")
        await interaction.response.send_message(f"{member.mention} has been warned for: {reason}")
        await log_event(f"{member.mention} has been warned for: {reason}")
        if warn_tracker[member.id] >= 3:
            await interaction.guild.ban(member, reason="3 warnings reached (anti-nuke system)")
            await interaction.response.send_message(f"{member.mention} has been banned for reaching 3 warnings.")
            await log_event(f"{member.mention} was banned for 3 warnings.")
    else:
        await interaction.response.send_message("You don't have permission to warn members.")

@bot.tree.command(name="serverinfo", description="Get detailed information about the server.")
async def serverinfo(interaction: discord.Interaction):
    guild = interaction.guild
    embed = discord.Embed(title=f"Server Info: {guild.name}", color=discord.Color.blue())
    embed.add_field(name="Owner", value=guild.owner, inline=True)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="userinfo", description="Get information about a specific user.")
async def userinfo(interaction: discord.Interaction, member: discord.Member):
    embed = discord.Embed(title=f"User Info: {member}", color=discord.Color.green())
    embed.add_field(name="ID", value=member.id, inline=True)
    embed.add_field(name="Status", value=member.status, inline=True)
    embed.add_field(name="Top Role", value=member.top_role, inline=True)
    embed.add_field(name="Joined", value=member.joined_at.strftime('%Y-%m-%d %H:%M:%S'), inline=True)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="addrole", description="Add a role to a user.")
async def addrole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    if interaction.user.guild_permissions.manage_roles:
        await member.add_roles(role)
        await interaction.response.send_message(f"Added role {role.name} to {member.mention}.")
        await log_event(f"Added role {role.name} to {member.mention}.")
    else:
        await interaction.response.send_message("You don't have permission to manage roles.")

@bot.tree.command(name="removerole", description="Remove a role from a user.")
async def removerole(interaction: discord.Interaction, member: discord.Member, role: discord.Role):
    if interaction.user.guild_permissions.manage_roles:
        await member.remove_roles(role)
        await interaction.response.send_message(f"Removed role {role.name} from {member.mention}.")
        await log_event(f"Removed role {role.name} from {member.mention}.")
    else:
        await interaction.response.send_message("You don't have permission to manage roles.")

@bot.tree.command(name="tempmute", description="Temporarily mute a user.")
async def tempmute(interaction: discord.Interaction, member: discord.Member, duration: int, reason: str = None):
    if interaction.user.guild_permissions.manage_roles:
        overwrite = interaction.channel.overwrites_for(member)
        overwrite.send_messages = False
        await interaction.channel.set_permissions(member, overwrite=overwrite)
        await interaction.response.send_message(f"{member.mention} has been muted for {duration} seconds.")
        if reason:
            await log_event(f"{member.mention} was muted for {duration}s. Reason: {reason}")
        await asyncio.sleep(duration)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(member, overwrite=overwrite)
        await log_event(f"{member.mention}'s mute has expired.")
    else:
        await interaction.response.send_message("You don't have permission to mute members.")

@bot.tree.command(name="setauditlog", description="Set the audit log channel.")
async def set_audit_log(interaction: discord.Interaction, channel: discord.TextChannel):
    global audit_channel_id
    if interaction.user.guild_permissions.administrator:
        audit_channel_id = channel.id
        await interaction.response.send_message(f"Audit log channel set to {channel.mention}.")
    else:
        await interaction.response.send_message("You don't have permission to set the audit log channel.")

async def log_event(message):
    if audit_channel_id:
        channel = bot.get_channel(audit_channel_id)
        if channel:
            await channel.send(message)

# this section is optional because of commands
whitelisted_users = set() 
whitelisted_roles = set()  

#-----------------------------------------------
@bot.tree.command(name="whitelist_user", description="Add or remove a user from the whitelist.")
async def whitelist_user(interaction: discord.Interaction, user: discord.User, action: str):
    if interaction.user.guild_permissions.administrator:
        if action.lower() == "add":
            whitelisted_users.add(user.id)
            await interaction.response.send_message(f"{user.name} has been added to the whitelist.")
        elif action.lower() == "remove":
            whitelisted_users.discard(user.id)
            await interaction.response.send_message(f"{user.name} has been removed from the whitelist.")
        else:
            await interaction.response.send_message("Invalid action. Use 'add' or 'remove'.")
    else:
        await interaction.response.send_message("You don't have permission to manage the whitelist.")

@bot.tree.command(name="whitelist_role", description="Add or remove a role from the whitelist.")
async def whitelist_role(interaction: discord.Interaction, role: discord.Role, action: str):
    if interaction.user.guild_permissions.administrator:
        if action.lower() == "add":
            whitelisted_roles.add(role.id)
            await interaction.response.send_message(f"{role.name} has been added to the whitelist.")
        elif action.lower() == "remove":
            whitelisted_roles.discard(role.id)
            await interaction.response.send_message(f"{role.name} has been removed from the whitelist.")
        else:
            await interaction.response.send_message("Invalid action. Use 'add' or 'remove'.")
    else:
        await interaction.response.send_message("You don't have permission to manage the whitelist.")

@bot.event
async def on_message(message):
    if message.author.bot:
        return

    if message.author.id in whitelisted_users:
        return 

    if any(role.id in whitelisted_roles for role in message.author.roles):
        return  

    author_id = message.author.id
    current_time = time.time()
    if author_id not in spam_tracker:
        spam_tracker[author_id] = []
    spam_tracker[author_id].append(current_time)
    spam_tracker[author_id] = [t for t in spam_tracker[author_id] if current_time - t < 10]
    if len(spam_tracker[author_id]) > 5:
        for channel in message.guild.text_channels:
            overwrite = channel.overwrites_for(message.author)
            overwrite.send_messages = False
            await channel.set_permissions(message.author, overwrite=overwrite)
        await message.channel.send(f"\U0001F507 {message.author.mention} has been muted for spamming in all channels.")
        await log_event(f"{message.author.mention} was muted for spamming in all channels.")

        await asyncio.sleep(180)  
        for channel in message.guild.text_channels:
            overwrite = channel.overwrites_for(message.author)
            overwrite.send_messages = None  
            await channel.set_permissions(message.author, overwrite=overwrite)
        await message.channel.send(f"{message.author.mention} has been unmuted in all channels.")
        await log_event(f"{message.author.mention} was automatically unmuted in all channels.")

    if len(message.mentions) > 3:
        await message.delete()
        await message.channel.send(f"{message.author.mention}, excessive mentions are not allowed.")
        await log_event(f"{message.author.mention}'s message deleted for excessive mentions.")
        return

    if "http://" in message.content or "https://" in message.content:
        if not message.author.guild_permissions.administrator:
            await message.delete()
            await message.channel.send(f"{message.author.mention}, links are not allowed.")

    await bot.process_commands(message)

@bot.tree.command(name="unmute", description="Unmute a user in all channels.")
async def unmute(interaction: discord.Interaction, member: discord.Member):
    if interaction.user.guild_permissions.manage_roles:
        for channel in interaction.guild.text_channels:
            overwrite = channel.overwrites_for(member)
            overwrite.send_messages = None  
            await channel.set_permissions(member, overwrite=overwrite)
        await interaction.response.send_message(f"{member.mention} has been unmuted in all channels.")
        await log_event(f"{member.mention} was manually unmuted in all channels.")
    else:
        await interaction.response.send_message("You don't have permission to unmute members.")

@bot.event
async def on_member_join(member):
    bot_name_patterns = [r"^bot.*", r".*spam.*"]
    if any(re.match(pattern, member.name.lower()) for pattern in bot_name_patterns):
        await member.kick(reason="Detected as a bot or spam user.")
        await log_event(f"User {member} was kicked for matching anti-bot patterns.")

@bot.tree.command(name="anti_raid", description="Enable or disable anti-raid mode.")
async def anti_raid(interaction: discord.Interaction, action: str):
    if interaction.user.guild_permissions.administrator:
        if action.lower() == "enable":
            for channel in interaction.guild.text_channels:
                overwrite = channel.overwrites_for(interaction.guild.default_role)
                overwrite.send_messages = False
                await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.guild.edit(verification_level=discord.VerificationLevel.high)
            await interaction.response.send_message("Anti-raid mode enabled. All channels are locked, and verification level is set to high.")
            await log_event("Anti-raid mode was enabled.")
        elif action.lower() == "disable":
            for channel in interaction.guild.text_channels:
                overwrite = channel.overwrites_for(interaction.guild.default_role)
                overwrite.send_messages = None
                await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
            await interaction.guild.edit(verification_level=discord.VerificationLevel.low)
            await interaction.response.send_message("Anti-raid mode disabled. Channels unlocked and verification level set to low.")
            await log_event("Anti-raid mode was disabled.")
        else:
            await interaction.response.send_message("Invalid action. Use 'enable' or 'disable'.")
    else:
        await interaction.response.send_message("You don't have permission to manage anti-raid mode.")

@bot.event
async def on_member_join(member):
    account_age = (discord.utils.utcnow() - member.created_at).days
    if account_age < 7: 
        await member.kick(reason="Account too new (anti-raid)")
        await log_event(f"User {member.name} was kicked for having an account younger than 7 days.")
    else:
        await log_event(f"User {member.name} joined with an account age of {account_age} days.")

@bot.tree.command(name="set_permissions", description="Set custom permissions for a role.")
async def set_permissions(interaction: discord.Interaction, role: discord.Role, permission: str, allow: bool):
    if interaction.user.guild_permissions.administrator:
        permission_map = {
            "send_messages": "send_messages",
            "manage_messages": "manage_messages",
            "add_reactions": "add_reactions",
            "embed_links": "embed_links"
        }
        if permission in permission_map:
            overwrite = discord.PermissionOverwrite(**{permission_map[permission]: allow})
            for channel in interaction.guild.text_channels:
                await channel.set_permissions(role, overwrite=overwrite)
            action = "allowed" if allow else "denied"
            await interaction.response.send_message(f"{action.capitalize()} {permission} for role {role.name}.")
            await log_event(f"{permission} was {action} for role {role.name}.")
        else:
            await interaction.response.send_message("Invalid permission. Available options: send_messages, manage_messages, add_reactions, embed_links.")
    else:
        await interaction.response.send_message("You don't have permission to manage role permissions.")

@bot.event
async def on_message(message):
    if message.author.id in spam_tracker:
        spam_tracker[message.author.id] += 1
        if spam_tracker[message.author.id] > 10:  # Example threshold
            await message.author.ban(reason="Exceeded spam threshold.")
            await log_event(f"{message.author.mention} was banned for exceeding spam threshold.")
    else:
        spam_tracker[message.author.id] = 1

@bot.tree.command(name="backup_server", description="Backup the server structure.")
async def backup_server(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        guild = interaction.guild
        backup_data = {
            "channels": [],
            "roles": []
        }

        # Backup roles
        for role in guild.roles:
            backup_data["roles"].append({
                "name": role.name,
                "permissions": role.permissions.value,
                "color": role.color.value,
                "position": role.position,
                "hoist": role.hoist,
                "mentionable": role.mentionable
            })

        for channel in guild.channels:
            if isinstance(channel, discord.TextChannel) or isinstance(channel, discord.VoiceChannel):
                backup_data["channels"].append({
                    "name": channel.name,
                    "type": "text" if isinstance(channel, discord.TextChannel) else "voice",
                    "category": channel.category.name if channel.category else None,
                    "permissions_overwrites": [
                        {
                            "target": overwrite.target.id,
                            "allow": overwrite.overwrite.pair()[0],
                            "deny": overwrite.overwrite.pair()[1]
                        }
                        for overwrite in channel.overwrites.items()
                    ],
                    "position": channel.position
                })

        with open(f"backup_{guild.id}.json", "w") as file:
            json.dump(backup_data, file, indent=4)

        await interaction.response.send_message("Server structure has been backed up successfully.")
    else:
        await interaction.response.send_message("You don't have permission to back up the server.")

@bot.tree.command(name="restore_server", description="Restore the server structure from a backup.")
async def restore_server(interaction: discord.Interaction):
    if interaction.user.guild_permissions.administrator:
        guild = interaction.guild

        try:
            with open(f"backup_{guild.id}.json", "r") as file:
                backup_data = json.load(file)

            for role_data in sorted(backup_data["roles"], key=lambda x: x["position"], reverse=True):
                existing_role = discord.utils.get(guild.roles, name=role_data["name"])
                if not existing_role:
                    await guild.create_role(
                        name=role_data["name"],
                        permissions=discord.Permissions(role_data["permissions"]),
                        color=discord.Color(role_data["color"]),
                        hoist=role_data["hoist"],
                        mentionable=role_data["mentionable"]
                    )

            # Restore channels
            for channel_data in sorted(backup_data["channels"], key=lambda x: x["position"]):
                category = None
                if channel_data["category"]:
                    category = discord.utils.get(guild.categories, name=channel_data["category"])
                    if not category:
                        category = await guild.create_category(channel_data["category"])

                existing_channel = discord.utils.get(guild.channels, name=channel_data["name"])
                if not existing_channel:
                    if channel_data["type"] == "text":
                        await guild.create_text_channel(
                            name=channel_data["name"],
                            category=category
                        )
                    elif channel_data["type"] == "voice":
                        await guild.create_voice_channel(
                            name=channel_data["name"],
                            category=category
                        )

            await interaction.response.send_message("Server structure has been restored successfully.")
        except FileNotFoundError:
            await interaction.response.send_message("Backup file not found. Please create a backup first.")
        except Exception as e:
            await interaction.response.send_message(f"An error occurred: {e}")
    else:
        await interaction.response.send_message("You don't have permission to restore the server.")

@bot.event
async def on_ready():
    print(f'Bot logged in as {bot.user}')
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} command(s)")
    except Exception as e:
        print(f"Error syncing commands: {e}")

if BOT_TOKEN:
    bot.run(BOT_TOKEN)
else:
    print("Bot token not found. Please check your .env file.")
