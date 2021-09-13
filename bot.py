import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import youtube_dl
import asyncio

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
        filename = data['title'] if stream else ytdl.prepare_filename(data)
        return filename

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')       

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

        filename = await YTDLSource.from_url(url, loop=bot.loop)
        voice_channel.play(discord.FFmpegPCMAudio(executable="/usr/bin/ffmpeg", source=filename), after=lambda e: removeFile(filename))
        await ctx.send('**Now playing:** {}'.format(filename)) 
    except Exception as e:
        print(e)
        await ctx.send("I'm not in a voice channel... D:")


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
            time = time + 1
            if voice.is_playing() and not voice.is_paused():
                time = 0
            if time == 60:
                await voice.disconnect()
            if not voice.is_connected():
                break

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)
