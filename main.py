import os
import sys
import json
import discord
import yt_dlp
from discord.ext import commands
from discord import app_commands
import asyncio
from concurrent.futures import ThreadPoolExecutor

if os.path.exists("config.json"):
    config = json.loads(open("config.json", "r").read())
else:
    config = {
        "token": "YOUR_TOKEN_HERE",
        "ownerid": 0,
        "prefix": "!",
        "leave_time": 120,
        "status_text": "/ or !help",
    }
    open("config.json", "w").write(json.dumps(config))
    print("Please edit config.json and restart the bot!")
    sys.exit(1)

# 設定機器人的意圖
intents = discord.Intents.default()
intents.message_content = True
intents.guilds = True
intents.voice_states = True

bot = commands.Bot(command_prefix=config["prefix"], intents=intents)

# 每個伺服器的播放狀態和播放清單（使用 guild.id 作為 key）
guild_data = {}

executor = ThreadPoolExecutor(max_workers=4)  # 執行緒池

@bot.event
async def on_ready():
    print(f'Logged in as {bot.user.name}')
    if config["status_text"]:
        print("Changing rich presence...")
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=config["status_text"])
    print("Syncing slash commands...")
    await bot.tree.sync()
    print("All ready!")

# 嵌入式訊息顯示當前播放的內容
async def embeded(ctx, msg, thumbna):
    embed = discord.Embed(
        colour=discord.Colour.brand_green(),
        title='目前播放:',
        description=f'{msg}'
    )
    embed.set_author(name='FrogPlayer')
    embed.set_image(url=thumbna)
    await ctx.send(embed=embed)

async def embeded_slash(interaction, msg, thumbna, title='目前播放:'):
    embed = discord.Embed(
        colour=discord.Colour.brand_green(),
        title=title,
        description=f'{msg}'
    )
    embed.set_author(name='FrogPlayer')
    embed.set_image(url=thumbna)
    await interaction.followup.send(embed=embed)

# 搜尋影片
async def search_video(ctx, urlq):
    yt_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'default_search': 'auto',
        'noplaylist': True,
        'verbose': True
    }
    yt_search = yt_dlp.YoutubeDL(yt_opts)
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(executor, lambda: yt_search.extract_info(url=urlq, download=False))
    if 'entries' in data:
        data = data['entries'][0]
    return [data['title'], data['url']], data['webpage_url'], data['thumbnail']

# 搜尋播放清單
async def playlist(ctx, urlq):
    pl_opts = {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
        'default_search': 'auto',
        'noplaylist': False,
        'ignoreerrors': True,
        'flat_playlist': True,
        'verbose': True
    }
    playlist_search = yt_dlp.YoutubeDL(pl_opts)
    loop = asyncio.get_event_loop()
    data = await loop.run_in_executor(executor, lambda: playlist_search.extract_info(url=urlq, download=False))
    return [[entry['title'], entry['url']] for entry in data['entries']], [entry['webpage_url'] for entry in data['entries']], [entry['thumbnail'] for entry in data['entries']]

# 加入語音頻道
async def join(ctx):
    guild_id = ctx.guild.id
    if guild_id not in guild_data:
        guild_data[guild_id] = {"queue": [], "actual_url": [], "thumb_url": [], "play_status": False, "in_chat": None, "doom": False}
    
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if not voice_client:
        if ctx.author.voice:
            voice_channel = ctx.author.voice.channel
            voice_client = await voice_channel.connect()
            guild_data[guild_id]["in_chat"] = voice_channel
        else:
            await ctx.send(embed=discord.Embed(title='錯誤', description='您不在語音頻道中', colour=discord.Colour.brand_red()))
            return None
    elif ctx.author.voice.channel != guild_data[guild_id]["in_chat"]:
        await ctx.send(embed=discord.Embed(title='錯誤', description='我們不在同一個語音頻道中', colour=discord.Colour.brand_red()))
        return None
    return voice_client

async def join_slash(interaction):
    guild_id = interaction.guild.id
    if guild_id not in guild_data:
        guild_data[guild_id] = {"queue": [], "actual_url": [], "thumb_url": [], "play_status": False, "in_chat": None, "doom": False}

    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)
    if not voice_client:
        if interaction.user.voice:
            voice_channel = interaction.user.voice.channel
            voice_client = await voice_channel.connect()
            guild_data[guild_id]["in_chat"] = voice_channel
        else:
            await interaction.response.send_message("您不在語音頻道中。", ephemeral=True)
            return None
    elif interaction.user.voice.channel != guild_data[guild_id]["in_chat"]:
        await interaction.response.send_message("我們不在同一個語音頻道中。", ephemeral=True)
        return None
    return voice_client

@bot.listen()
async def on_voice_state_update(member, before, after):
    if not member.id == bot.user.id:
        return
    elif before.channel is None:
        voice = after.channel.guild.voice_client
        time = 0
        while True:
            await asyncio.sleep(1)
            time += 1
            if voice.is_playing() and not voice.is_paused():
                time = 0
            if time == config["leave_time"]:
                await voice.disconnect()
            if not voice.is_connected():
                break

# 播放指令
@bot.command(name='play', help=f'搜尋影片或播放清單 例如：{config["prefix"]}play Never gonna give you up')
@commands.cooldown(1, 2, commands.BucketType.user)
async def play(ctx, *, search_query):
    guild_id = ctx.guild.id
    voice_client = await join(ctx)
    if not voice_client:
        return

    guild_data[guild_id]["doom"] = False
    queue, actual_url, thumb_url = guild_data[guild_id]["queue"], guild_data[guild_id]["actual_url"], guild_data[guild_id]["thumb_url"]
    
    if '&list=' in search_query or '&start_radio=' in search_query:
        await ctx.send(embed=discord.Embed(title='錯誤', description='不支援此網址格式', colour=discord.Colour.dark_orange()))
        return

    elif '/playlist?' in search_query and not '/watch?' in search_query:
        await ctx.send(embed=discord.Embed(title='注意:', description='正在獲取播放清單資料，可能需要一段時間...', colour=discord.Colour.yellow()))
        data1, url, tn = await playlist(ctx, search_query)
        queue.extend(data1)
        actual_url.extend(url)
        thumb_url.extend(tn)

    else:
        data1, url, tn = await search_video(ctx, search_query)
        queue.append(data1)
        actual_url.append(url)
        thumb_url.append(tn)
    
    if not guild_data[guild_id]["play_status"]:
        await play_now(ctx, queue.pop(0))

@bot.tree.command(name="play", description="播放音樂 (搜尋影片或提供連結)")
@app_commands.describe(search_query="歌曲名稱或 YouTube 連結")
async def play_slash(interaction: discord.Interaction, search_query: str):
    await interaction.response.defer()
    guild_id = interaction.guild.id
    voice_client = await join_slash(interaction)
    if not voice_client:
        return

    guild_data[guild_id]["doom"] = False
    queue, actual_url, thumb_url = guild_data[guild_id]["queue"], guild_data[guild_id]["actual_url"], guild_data[guild_id]["thumb_url"]
    
    if '&list=' in search_query or '&start_radio=' in search_query:
        await interaction.followup.send("不支援此網址格式。")
        return

    data1, url, tn = await search_video(interaction, search_query)
    queue.append(data1)
    actual_url.append(url)
    thumb_url.append(tn)

    if not guild_data[guild_id]["play_status"]:
        await play_now_slash(interaction, queue.pop(0))
    else:
        await embeded_slash(interaction, "成功增加影片到隊列。", tn, title="隊列")

# 播放當前隊列中的歌曲
async def play_now(ctx, url):
    guild_id = ctx.guild.id
    voice_client = await join(ctx)
    if not voice_client:
        return

    guild_data[guild_id]["play_status"] = True
    queue, actual_url, thumb_url = guild_data[guild_id]["queue"], guild_data[guild_id]["actual_url"], guild_data[guild_id]["thumb_url"]
    ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

    async def after(error):
        if error:
            print(error)
        if guild_data[guild_id]["play_status"] and queue:
            next_song = queue.pop(0)
            embed_msg = f'{next_song[0]}  {actual_url.pop(0)}'
            thumb = thumb_url.pop(0)
            await embeded(ctx, embed_msg, thumb)
            voice_client.play(discord.FFmpegPCMAudio(next_song[1], **ffmpeg_options), after=lambda e: asyncio.run_coroutine_threadsafe(after(e), bot.loop))

    embed_msg = f'{url[0]}  {actual_url.pop(0)}'
    thumb = thumb_url.pop(0)
    await embeded(ctx, embed_msg, thumb)
    voice_client.play(discord.FFmpegPCMAudio(url[1], **ffmpeg_options), after=lambda e: asyncio.run_coroutine_threadsafe(after(e), bot.loop))

async def play_now_slash(interaction, url):
    guild_id = interaction.guild.id
    voice_client = await join_slash(interaction)
    if not voice_client:
        return

    guild_data[guild_id]["play_status"] = True
    queue, actual_url, thumb_url = guild_data[guild_id]["queue"], guild_data[guild_id]["actual_url"], guild_data[guild_id]["thumb_url"]
    ffmpeg_options = {'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5', 'options': '-vn'}

    async def after(error):
        if error:
            print(error)
        if guild_data[guild_id]["play_status"] and queue:
            next_song = queue.pop(0)
            embed_msg = f'{next_song[0]}  {actual_url.pop(0)}'
            thumb = thumb_url.pop(0)
            await embeded_slash(interaction, embed_msg, thumb)
            voice_client.play(discord.FFmpegPCMAudio(next_song[1], **ffmpeg_options), after=lambda e: asyncio.run_coroutine_threadsafe(after(e), bot.loop))

    embed_msg = f'{url[0]}  {actual_url.pop(0)}'
    thumb = thumb_url.pop(0)
    await embeded_slash(interaction, embed_msg, thumb)
    voice_client.play(discord.FFmpegPCMAudio(url[1], **ffmpeg_options), after=lambda e: asyncio.run_coroutine_threadsafe(after(e), bot.loop))


# 跳過當前歌曲
@bot.command(name='skip', help='跳過當前播放或暫停的歌曲')
@commands.cooldown(1, 2, commands.BucketType.user)
async def skip(ctx):
    voice_client = await join(ctx)
    if voice_client and voice_client.is_playing():
        voice_client.stop()

@bot.tree.command(name="skip", description="跳過目前正在播放的歌曲")
async def skip_slash(interaction: discord.Interaction):
    voice_client = await join_slash(interaction)
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await interaction.response.send_message("已跳過歌曲。")

# 停止播放並清空播放清單
@bot.command(name='stop', help='停止播放並清空播放清單')
@commands.cooldown(1, 2, commands.BucketType.user)
async def stop(ctx):
    guild_id = ctx.guild.id
    guild_data[guild_id]["doom"] = True
    guild_data[guild_id]["queue"].clear()
    guild_data[guild_id]["actual_url"].clear()
    guild_data[guild_id]["thumb_url"].clear()
    guild_data[guild_id]["play_status"] = False
    voice_client = await join(ctx)
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()

@bot.tree.command(name="stop", description="停止播放並清空播放清單")
async def stop_slash(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    guild_data[guild_id]["doom"] = True
    guild_data[guild_id]["queue"].clear()
    guild_data[guild_id]["actual_url"].clear()
    guild_data[guild_id]["thumb_url"].clear()
    guild_data[guild_id]["play_status"] = False
    voice_client = await join_slash(interaction)
    if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
        voice_client.stop()
    await interaction.response.send_message("已停止播放並清空播放清單。")

@bot.command(name='leave', help='離開語音頻道')
async def leave(ctx):
    guild_id = ctx.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild=ctx.guild)
    if voice_client and voice_client.is_connected():
        channelname = voice_client.channel.name
        guild_data[guild_id]["doom"] = True
        guild_data[guild_id]["queue"].clear()
        guild_data[guild_id]["actual_url"].clear()
        guild_data[guild_id]["thumb_url"].clear()
        guild_data[guild_id]["play_status"] = False
        await voice_client.disconnect()
        await ctx.send(embed=discord.Embed(title='成功', description=f'已經離開`{channelname}`。', colour=discord.Colour.brand_green()))
    else:
        await ctx.send(embed=discord.Embed(title='錯誤', description='機器人未在語音頻道中', colour=discord.Colour.brand_red()))

@bot.tree.command(name="leave", description="讓機器人離開語音頻道")
async def leave_slash(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    voice_client = discord.utils.get(bot.voice_clients, guild=interaction.guild)

    if voice_client and voice_client.is_connected():
        channel_name = voice_client.channel.name
        guild_data[guild_id]["doom"] = True
        guild_data[guild_id]["queue"].clear()
        guild_data[guild_id]["actual_url"].clear()
        guild_data[guild_id]["thumb_url"].clear()
        guild_data[guild_id]["play_status"] = False
        await voice_client.disconnect()

        embed = discord.Embed(
            title='成功',
            description=f'已經離開 `{channel_name}`。',
            colour=discord.Colour.brand_green()
        )
        await interaction.response.send_message(embed=embed)
    else:
        embed = discord.Embed(
            title='錯誤',
            description='機器人未在語音頻道中。',
            colour=discord.Colour.brand_red()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

class MyHelp(commands.HelpCommand):
    async def send_bot_help(self, mapping):
        embed = discord.Embed(title="幫助", colour=discord.Colour.gold())
        for command in self.context.bot.commands:
            embed.add_field(name=f"{config["prefix"]}{config["prefix"]}{command.name}", value=command.help, inline=False)
        await self.get_destination().send(embed=embed)
        
    async def send_command_help(self, command):
        embed = discord.Embed(title=f"指令說明: {command.qualified_name}", description=command.help, colour=discord.Colour.gold())
        await self.get_destination().send(embed=embed)

bot.help_command = MyHelp()

@bot.tree.command(name="help", description="查看所有指令或特定指令的使用說明")
@app_commands.describe(command_name="（可選）要查看說明的指令名稱")
async def help_slash(interaction: discord.Interaction, command_name: str = None):
    if command_name:
        # 查詢特定指令
        command = bot.tree.get_command(command_name)
        if command:
            embed = discord.Embed(
                title=f"指令說明: /{command.name}",
                description=command.description or "無描述",
                colour=discord.Colour.gold()
            )
            await interaction.response.send_message(embed=embed)
        else:
            # 如果找不到該指令，回傳錯誤訊息
            await interaction.response.send_message(
                embed=discord.Embed(
                    title="錯誤",
                    description=f"找不到指令 `{command_name}`。",
                    colour=discord.Colour.brand_red()
                ),
                ephemeral=True  # 僅發送給請求者
            )
    else:
        # 顯示所有指令
        embed = discord.Embed(
            title="幫助",
            colour=discord.Colour.gold(),
            description="以下是所有可用的指令："
        )
        for command in bot.tree.get_commands():
            embed.add_field(name=f"/{command.name}", value=command.description or "無描述", inline=False)

        await interaction.response.send_message(embed=embed)


bot.run(config["token"])
