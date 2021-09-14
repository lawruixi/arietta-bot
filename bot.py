import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import youtube_dl
import asyncio

#TODO: Now playing progress bar?
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
    async def from_url(cls, url, *, loop=None, stream=False):
        loop = loop or asyncio.get_event_loop()
        data = await loop.run_in_executor(None, lambda: ytdl.extract_info(url, download=not stream))
        if 'entries' in data:
            # take first item from a playlist
            data = data['entries'][0]
        print(data)
        global current_song
        current_song = data['title']
        filename = data['title'] if stream else ytdl.prepare_filename(data)
        return filename

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')       

EMBED_COLOUR = 0xF875A2
current_song = "";
current_time = 0

@bot.event
async def on_message(message):
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
        await voice_client.disconnect()
    else:
        await ctx.send("I'm not in a voice channel... D:")

@bot.command(name='play', help='Let me play some songs for you! :OOO')
async def play(ctx,*url):
    url = " ".join(url) #Allows for searching of more than one word at a time.
    voice_client = ctx.message.guild.voice_client
    if(voice_client is None): #Join if not connected to voice channel.
        try:
            await ctx.invoke(bot.get_command('join'))
        except Exception as e: 
            print(e)
            await ctx.send("I'm sorry! Something bad happened! ;-;")
            return;

    try:
        server = ctx.message.guild
        voice_channel = server.voice_client

        def removeFile(filename):
            os.remove(filename)

        global current_song
        filename = await YTDLSource.from_url(url, loop=bot.loop)
        voice_channel.play(discord.FFmpegPCMAudio(executable="/usr/bin/ffmpeg", source=filename), after=lambda e: removeFile(filename))
        await ctx.send('**Now playing:** {}'.format(current_song)) 

        #TODO: Add time to current_time for np progressbar?
    except Exception as e:
        print(e)
        await ctx.send("I'm sorry! Something bad happened! ;-;")

@bot.command(pass_context=True)
async def p(ctx):
    await play.invoke(ctx);

@bot.command(name='now_playing', help='What\'s playing now? :O')
async def now_playing(ctx):
        #TODO: Progressbar?
        await ctx.send('**Now playing:** {}'.format(current_song)) 
        # embed=discord.Embed(title="Added Homework!", description="Successfully added homework **{name}** due on **{duedate}**, with index **{list_number}**!".format(name=name, duedate=duedate, list_number=list_number), color=EMBED_COLOUR)
        # embed = discord.Embed(title="**Now Playing:**", description="{0}\n{1}/{2}")
        await ctx.send(embed=embed);

@bot.command(pass_context=True)
async def np(ctx):
    await now_playing.invoke(ctx);

@bot.command(name='pause', help='Pauses the song!')
async def pause(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_playing():
        await voice_client.pause()
    else:
        await ctx.send("I'm not playing anything right now...")

    
@bot.command(name='resume', help='Resumes the song!')
async def resume(ctx):
    voice_client = ctx.message.guild.voice_client
    if voice_client.is_paused():
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
                await voice.disconnect()
            if not voice.is_connected():
                break

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
