#!/usr/bin/python3
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import youtube_dl
import asyncio
import time
import datetime
from queue import Queue

#TODO: QUEUE
#TODO: seek to timestamp? https://stackoverflow.com/questions/62354887/is-it-possible-to-seek-through-streamed-youtube-audio-with-discord-py-play-from

load_dotenv()

DISCORD_TOKEN = os.getenv("discord_token")

intents = discord.Intents().all()
client = discord.Client(intents=intents)
bot = commands.Bot(command_prefix='^',intents=intents)

youtube_dl.utils.bug_reports_message = lambda: ''

ytdl_format_options = {
    'format': 'bestaudio/best',
    'restrictfilenames': True,
    'noplaylist': True,
    'nocheckcertificate': True,
    'ignoreerrors': False,
    'logtostderr': False,
    'quiet': True,
    'no_warnings': True,
    'default_search': 'auto',
    'source_address': '0.0.0.0' # bind to ipv4 since ipv6 addresses cause issues sometimes
}

ffmpeg_options = {
    'options': '-vn'
}

ytdl = youtube_dl.YoutubeDL(ytdl_format_options)

class YTDLSource(discord.PCMVolumeTransformer):
    def __init__(self, source, *, data, volume=0.5):
        super().__init__(source, volume)
        self.data = data
        self.title = data.get('title')
        self.url = ""

    @classmethod
    async def get_data(cls, url, *, loop=None):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=False))
        return data;

    @classmethod
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]
        global current_song
        current_song = Song(data['title'], url, data['duration'])
        filename = data['url'] if stream else ytdl.prepare_filename(data)
        return filename

class Song():
    def __init__(self, title, url, duration):
        self.title = title;
        self.url = url;
        self.duration = duration;

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')       

EMBED_COLOUR = 0xF875A2
current_song = None;
current_progress = 0
start_time = 0
play_queues = dict(); #A dictionary of server_id : Queue. Each queue does not include the currently playing song.

@bot.event
async def on_message(message):
    await bot.process_commands(message);

    if bot.user.mentioned_in(message):
        if("goodnight" in message.content.lower()):
            await message.channel.send("goodnight!")

@bot.command(name='introduce', help="Hoi! :D")
async def introduce(ctx):
    embed=discord.Embed(title="Hello, I'm Arietta!", description="I'm here to play music for you! Have fun and enjoy! :D\nMy command prefix is the caret (^) symbol btw :P", color=EMBED_COLOUR)
    await ctx.send(embed=embed)

@bot.command(pass_context=True)
async def intro(ctx):
    await introduce.invoke(ctx);

@bot.command(name='ping', help="pong!")
async def ping(ctx):
    await ctx.send("pong!");

@bot.command(name='pong', help="ping!")
async def ping(ctx):
    await ctx.send("ping!");

@bot.command(name='join', help='Call me if you\'re lonely! :)))))')
async def join(ctx):
    if not ctx.message.author.voice:
        await ctx.send("You aren't connected to a voice channel... D:".format(ctx.message.author.name))
        return
    else:
        channel = ctx.message.author.voice.channel
    await channel.connect()

@bot.command(name='leave', help='Tell me if you want me to go...')
async def leave(ctx):
    voice_client = ctx.message.guild.voice_client
    if (not voice_client is None) and (voice_client.is_connected()):
        global current_song; current_song = None;
        await voice_client.disconnect()
    else:
        await ctx.send("I'm not in a voice channel... D:")

async def play_song(ctx, channel):
    async with ctx.typing():
        server_id = channel.guild.id;
        song = play_queues[server_id].get();
        if(song == None): return;

        player = await YTDLSource.from_url(song.url, loop=client.loop, stream=True)
        def after_song(e):
            if(play_queues[server_id].qsize() == 0):
                current_song = None;
            return play_song(ctx, channel)

        channel.play(
                # discord.FFmpegPCMAudio(executable="/usr/bin/ffmpeg", source=player),
                discord.FFmpegPCMAudio(player),
                after = lambda e: after_song
                )

        current_progress = 0
        start_time = time.time();

        current_song = song;
        await ctx.send('**Now playing:** {}'.format(current_song.title)) 


def add_to_queue(server_id, song):
    if(play_queues.get(server_id, None) is None):
        play_queues[server_id] = Queue();
    play_queues[server_id].put(song)


@bot.command(name='play', help='Let me play some songs for you! :OOO')
async def play(ctx,*url):
    url = " ".join(url) #Allows for searching of more than one word at a time.
    voice_client = ctx.message.guild.voice_client
    if(voice_client is None): #Join if not connected to voice channel.
        try:
            await ctx.invoke(bot.get_command('join'))
            voice_client = ctx.message.guild.voice_client
        except Exception as e: 
            print(e)
            await ctx.send("I'm sorry! Something bad happened! ;-;")
            return;

    server_id = ctx.guild.id;
    data = await YTDLSource.get_data(url, loop=bot.loop); #Get data about the song being added
    if not current_song is None: #If there is currently a song being played:
        # print(data.get('_type', "video")); //TODO: Check if playlist

        title = data['title']
        duration = data['duration']

        add_to_queue(server_id, Song(title, url, duration))

        title = "Added song to queue! :D"
        duration_hms = str(datetime.timedelta(seconds=duration));

        embed=discord.Embed(title=title, color=EMBED_COLOUR)
        embed.add_field(name="Position", value="{0}".format(play_queues[server_id].qsize()), inline = True);
        embed.add_field(name="Name", value="{0}".format(title), inline = True);
        embed.add_field(name="Duration", value="{0}".format(duration_hms), inline = True);
        await ctx.send(embed=embed)
        return;

    try:
        #TODO: playlist?
        server = ctx.message.guild
        voice_channel = server.voice_client

        data = await YTDLSource.get_data(url, loop=bot.loop); #Get data about the song being added
        print("EEE")
        print(data)
        title = data['title']
        duration = data['duration']
        add_to_queue(server_id, Song(title, url, duration))

        await play_song(ctx, voice_channel)

    except Exception as e:
        print(e)
        await ctx.send("I'm sorry! Something bad happened! ;-;")

@bot.command(pass_context=True)
async def p(ctx):
    await play.invoke(ctx);

@bot.command(pass_context=True)
async def np(ctx):
    await ctx.invoke(bot.get_command('now_playing'))

@bot.command(name='now_playing', help='What\'s playing now? :O')
async def now_playing(ctx):
    if(current_song is None):
        await ctx.send("I'm not playing anything right now...")
        return;
    progress = 0;
    duration = current_song.duration
    
    #Get progress; if paused, it should just be the current progress. Otherwise, add the unpaused time as well.
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_paused():
        progress = int(current_progress);
    else:
        progress = int(time.time() - start_time + current_progress);
    play_frac = progress/duration;
    progressbar_string = ""
    #Formatting and stuff
    if(play_frac <= 0.5):
        progressbar_string += "=" * (int(play_frac * 40))
        progressbar_string += "O"
        progressbar_string += "-" * (40 - int(play_frac * 40))
    else:
        progressbar_string += "=" * (1 + int(play_frac * 40));
        progressbar_string += "O"
        progressbar_string += "-" * (40 - (1 + int(play_frac * 40)))

    duration_hms = str(datetime.timedelta(seconds=duration));
    progress_hms = str(datetime.timedelta(seconds=progress));

    title = "**Now Playing:**"
    description = "{0}\n```\n{1}\n{2}/{3}```".format(current_song.title, progressbar_string, progress_hms, duration_hms)

    # await ctx.send('**Now playing:** {}'.format(current_song)) 
    embed=discord.Embed(title=title, description=description, color=EMBED_COLOUR)
    # embed = discord.Embed(title="**Now Playing:**", description="{0}\n{1}/{2}")
    await ctx.send(embed=embed);

@bot.command(name='pause', help='Pauses the song!')
async def pause(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_playing():
        global current_progress
        current_progress = time.time() - start_time;
        await voice_client.pause()
    else:
        await ctx.send("I'm not playing anything right now...")

    
@bot.command(name='resume', help='Resumes the song!')
async def resume(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_paused():
        global start_time
        start_time = time.time();
        await voice_client.resume()
    else:
        await ctx.send("I'm not playing anything. Try using `!play`! :D")

@bot.command(name='stop', help='Stops the song!')
async def stop(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_playing():
        await voice_client.stop()
    else:
        await ctx.send("I'm not playing anything right now...")


#https://stackoverflow.com/questions/63658589/how-to-make-a-discord-bot-leave-the-voice-channel-after-being-inactive-for-x-min
#Make discord bot leave after 60s
@bot.event
async def on_voice_state_update(member, before, after):
    if not member.id == bot.user.id:
        return

    if before.channel is None:
        voice = after.channel.guild.voice_client
        time = 0
        while True:
            await asyncio.sleep(1) #TODO: Test out again
            time = time + 1
            if voice.is_playing() and not voice.is_paused():
                time = 0
            if time == 60:
                global current_song; current_song = None;
                await voice.disconnect()
            if not voice.is_connected():
                break

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
