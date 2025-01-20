import discord
from discord.ext import commands
import logging
from dotenv import load_dotenv
import os
import asyncio
import random
import time

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="/", intents=intents)

logging.basicConfig(level=logging.INFO)

@bot.tree.command()
async def about(interaction: discord.Interaction):
    await interaction.response.send_message("I am a security bot that helps prevent raids and nukes. I monitor server activity and provide commands to ban users and prevent malicious actions.")

@bot.tree.command()
async def ban(interaction: discord.Interaction, user: discord.User, reason: str = None):
    if interaction.user.guild_permissions.ban_members:
        await interaction.guild.ban(user, reason=reason)
        await interaction.response.send_message(f"Banned {user.name} for reason: {reason}")
        logging.info(f"Banned {user.name} for {reason}")
    else:
        await interaction.response.send_message("You don't have permission to ban users.")

@bot.tree.command(name="lockdown", description="Lock all channels in a category.")
async def lockall(interaction: discord.Interaction, category: discord.CategoryChannel):
    for channel in category.channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = False
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"🔒 All channels in {category.name} have been locked.")

warn_tracker = {}

@bot.tree.command(name="warn", description="Warn a user for inappropriate behavior.")
async def warn(interaction: discord.Interaction, member: discord.Member, reason: str = "No reason provided"):
    if interaction.user.guild_permissions.administrator:
        if member.id not in warn_tracker:
            warn_tracker[member.id] = 0
        warn_tracker[member.id] += 1
        await member.send(f"You have been warned in {interaction.guild.name} for: {reason}")
        await interaction.response.send_message(f"{member.mention} has been warned for: {reason}")
        if warn_tracker[member.id] >= 3:
            await interaction.guild.ban(member, reason="3 warnings reached (anti-nuke system)")
            await interaction.response.send_message(f"{member.mention} has been banned for reaching 3 warnings.")
    else:
        await interaction.response.send_message("You don't have permission to warn members.")

@bot.tree.command(name="tempban", description="Temporarily ban a user for a set duration.")
async def tempban(interaction: discord.Interaction, member: discord.Member, duration: int, reason: str = None):
    if interaction.user.guild_permissions.ban_members:
        await interaction.guild.ban(member, reason=reason)
        await interaction.response.send_message(f"Temporarily banned {member.mention} for {duration} minutes.")
        await asyncio.sleep(duration * 60)
        await interaction.guild.unban(member)
        await interaction.channel.send(f"{member.mention} has been unbanned after {duration} minutes.")
    else:
        await interaction.response.send_message("You don't have permission to ban members.")

blacklisted_users = set()

@bot.tree.command()
async def blacklist(interaction: discord.Interaction, user: discord.User):
    if interaction.user.guild_permissions.administrator:
        if user.id in blacklisted_users:
            blacklisted_users.remove(user.id)
            await interaction.response.send_message(f"{user.name} has been removed from the blacklist.")
        else:
            blacklisted_users.add(user.id)
            await interaction.response.send_message(f"{user.name} has been added to the blacklist.")
    else:
        await interaction.response.send_message("You don't have permission to modify the blacklist.")

@bot.event
async def on_member_join(member: discord.Member):
    if member.id in blacklisted_users:
        await member.ban(reason="Blacklisted user")
        print(f"Blacklisted user {member.name} banned.")
        await member.guild.system_channel.send(f"{member.name} was blacklisted and banned upon joining.")

@bot.tree.command(name="lock", description="Lock a channel by preventing @everyone from sending messages.")
async def lock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"🔒 {channel.mention} has been locked.")

@bot.tree.command(name="unlock", description="Unlock a channel.")
async def unlock(interaction: discord.Interaction, channel: discord.TextChannel = None):
    channel = channel or interaction.channel
    overwrite = channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message(f"🔓 {channel.mention} has been unlocked.")

@bot.tree.command(name="unlockall", description="Unlock all channels server-wide.")
async def unlockall(interaction: discord.Interaction):
    for channel in interaction.guild.text_channels:
        overwrite = channel.overwrites_for(interaction.guild.default_role)
        overwrite.send_messages = None
        await channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔓 All channels in the server have been unlocked.")

@bot.tree.command(name="purge", description="Delete a number of messages from the channel.")
async def purge(interaction: discord.Interaction, amount: int):
    if amount < 1 or amount > 100:
        await interaction.response.send_message("🧹 You can only delete between 1 and 100 messages.", ephemeral=True)
        return
    deleted = await interaction.channel.purge(limit=amount)
    await interaction.response.send_message(f"🧹 Deleted {len(deleted)} messages.", ephemeral=True)

@bot.tree.command(name="mute", description="Mute a user in this channel.")
async def mute(interaction: discord.Interaction, member: discord.Member, duration: int = 0):
    overwrite = interaction.channel.overwrites_for(member)
    overwrite.send_messages = False
    await interaction.channel.set_permissions(member, overwrite=overwrite)
    await interaction.response.send_message(f"🔇 {member.mention} has been muted.")
    if duration > 0:
        await asyncio.sleep(duration)
        overwrite.send_messages = None
        await interaction.channel.set_permissions(member, overwrite=overwrite)
        await interaction.channel.send(f"🔊 {member.mention} has been unmuted after {duration} seconds.")

@bot.tree.command(name="unmute", description="Unmute a user in this channel.")
async def unmute(interaction: discord.Interaction, member: discord.Member):
    overwrite = interaction.channel.overwrites_for(member)
    overwrite.send_messages = None
    await interaction.channel.set_permissions(member, overwrite=overwrite)
    await interaction.response.send_message(f"🔊 {member.mention} has been unmuted.")

spam_tracker = {}

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    author_id = message.author.id
    current_time = time.time()
    if author_id not in spam_tracker:
        spam_tracker[author_id] = []
    spam_tracker[author_id].append(current_time)
    spam_tracker[author_id] = [t for t in spam_tracker[author_id] if current_time - t < 10]
    if len(spam_tracker[author_id]) > 5:
        overwrite = message.channel.overwrites_for(message.author)
        overwrite.send_messages = False
        await message.channel.set_permissions(message.author, overwrite=overwrite)
        await message.channel.send(f"🔇 {message.author.mention} has been muted for spamming.")
        spam_tracker.pop(author_id, None)
    await bot.process_commands(message)

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
