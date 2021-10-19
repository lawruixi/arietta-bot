#!/usr/bin/python3
import discord
from discord.ext import commands
import os
from dotenv import load_dotenv
import youtube_dl
import asyncio
import time
import datetime
import functools
import itertools
import math
from queue import Queue
from async_timeout import timeout
import hashlib

#TODO: QUEUE
#TODO: seek to timestamp? https://stackoverflow.com/questions/62354887/is-it-possible-to-seek-through-streamed-youtube-audio-with-discord-py-play-from

load_dotenv()

DISCORD_TOKEN = os.getenv("discord_token")

intents = discord.Intents().all()
client = discord.Client(intents=intents)
bot = commands.Bot(command_prefix='^',intents=intents)

EMBED_COLOUR = 0xF875A2
ERROR_DIRECTORY = "errors/"
ERROR_FILE = "error.txt"

youtube_dl.utils.bug_reports_message = lambda: ''

def get_error_file(error):
    if not os.path.exists(ERROR_DIRECTORY):
        os.mkdir(ERROR_DIRECTORY);
    error_file = open(ERROR_DIRECTORY + ERROR_FILE, "w");
    error_file.write(str(error));
    error_file.close();
    return discord.File(ERROR_DIRECTORY + ERROR_FILE);

class VoiceError(Exception):
    pass

class YTDLError(Exception):
    pass

class YTDLSource(discord.PCMVolumeTransformer):
    YTDL_OPTIONS = {
        'format': 'bestaudio/best',
        'extractaudio': True,
        'audioformat': 'mp3',
        'outtmpl': '%(extractor)s-%(id)s-%(title)s.%(ext)s',
        'restrictfilenames': True,
        'noplaylist': True,
        'nocheckcertificate': True,
        'ignoreerrors': False,
        'logtostderr': False,
        'quiet': True,
        'no_warnings': True,
        'default_search': 'auto',
        'source_address': '0.0.0.0',
    }

    FFMPEG_OPTIONS = {
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn',
    }

    ytdl = youtube_dl.YoutubeDL(YTDL_OPTIONS)

    def __init__(self, ctx: commands.Context, source: discord.FFmpegPCMAudio, *, data: dict, volume: float = 0.5):
        super().__init__(source, volume)

        self.requester = ctx.author
        self.channel = ctx.channel
        self.data = data

        self.uploader = data.get('uploader')
        self.uploader_url = data.get('uploader_url')
        date = data.get('upload_date')
        self.upload_date = date[6:8] + '.' + date[4:6] + '.' + date[0:4]
        self.title = data.get('title')
        self.thumbnail = data.get('thumbnail')
        self.description = data.get('description')
        self.duration = int(data.get('duration'))
        self.duration_hms = self.parse_duration(int(data.get('duration')))
        self.tags = data.get('tags')
        self.url = data.get('webpage_url')
        self.views = data.get('view_count')
        self.likes = data.get('like_count')
        self.dislikes = data.get('dislike_count')
        self.stream_url = data.get('url')

    def __str__(self):
        return '**{0.title}** by **{0.uploader}**'.format(self)

    @classmethod
    async def get_info(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)
        return data;

    @classmethod
    async def create_source(cls, ctx: commands.Context, search: str, *, loop: asyncio.BaseEventLoop = None):
        loop = loop or asyncio.get_event_loop()

        partial = functools.partial(cls.ytdl.extract_info, search, download=False, process=False)
        data = await loop.run_in_executor(None, partial)

        if data is None:
            raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        if 'entries' not in data:
            process_info = data
        else:
            process_info = None
            for entry in data['entries']:
                if entry:
                    process_info = entry
                    break

            if process_info is None:
                raise YTDLError('Couldn\'t find anything that matches `{}`'.format(search))

        webpage_url = process_info['webpage_url']
        partial = functools.partial(cls.ytdl.extract_info, webpage_url, download=False)
        processed_info = await loop.run_in_executor(None, partial)

        if processed_info is None:
            raise YTDLError('Couldn\'t fetch `{}`'.format(webpage_url))

        if 'entries' not in processed_info:
            info = processed_info
        else:
            info = None
            while info is None:
                try:
                    info = processed_info['entries'].pop(0)
                except IndexError:
                    raise YTDLError('Couldn\'t retrieve any matches for `{}`'.format(webpage_url))

        return cls(ctx, discord.FFmpegPCMAudio(info['url'], **cls.FFMPEG_OPTIONS), data=info)

    @staticmethod
    def parse_duration(duration: int):
        minutes, seconds = divmod(duration, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)

        duration_list = []
        if days > 0:
            duration_list.append('{}:'.format(days))
        if hours > 0:
            duration_list.append('{:02d}:'.format(hours))
        duration_list.append('{:02d}:'.format(minutes))
        duration_list.append('{:02d}:'.format(seconds))

        if len(duration_list) == 1:
            duration_list.insert(0, "00:")

        return ''.join(duration_list).strip(":")

class Song:
    __slots__ = ('source', 'requester')

    def __init__(self, source: YTDLSource):
        self.source = source
        self.requester = source.requester

    def create_embed(self):
        embed = (discord.Embed(title='Now playing',
                               description='```css\n{0.source.title}\n```'.format(self),
                               color=EMBED_COLOUR)
                 .add_field(name='Duration', value=self.source.duration_hms)
                 .add_field(name='Requested by', value=self.requester.mention)
                 .add_field(name='Uploader', value='[{0.source.uploader}]({0.source.uploader_url})'.format(self))
                 .set_thumbnail(url=self.source.thumbnail))

        return embed


class SongQueue(asyncio.Queue):
    def __getitem__(self, item):
        if isinstance(item, slice):
            return list(itertools.islice(self._queue, item.start, item.stop, item.step))
        else:
            return self._queue[item]

    def __iter__(self):
        return self._queue.__iter__()

    def __len__(self):
        return self.qsize()

    def clear(self):
        self._queue.clear()

    def shuffle(self):
        random.shuffle(self._queue)

    def remove(self, index: int):
        del self._queue[index]

    def remove_n(self, indices: list):
        indices.sort(reverse = True);
        for i in indices:
            self.remove(i);

class VoiceState:
    def __init__(self, bot: commands.Bot, ctx: commands.Context):
        self.bot = bot
        self._ctx = ctx

        self.current = None
        self.voice = None
        self.next = asyncio.Event()
        self.songs = SongQueue()

        self._loop = False
        self._volume = 0.5
        
        self.current_progress = 0
        self.start_time = 0

        self.audio_player = bot.loop.create_task(self.audio_player_task())

    def __del__(self):
        self.audio_player.cancel()

    @property
    def loop(self):
        return self._loop

    @loop.setter
    def loop(self, value: bool):
        self._loop = value

    @property
    def volume(self):
        return self._volume

    @volume.setter
    def volume(self, value: float):
        self._volume = value

    @property
    def is_playing(self): #In voice channel and there is currently a song playing.
        return self.voice and self.current

    async def audio_player_task(self):
        while True:
            self.next.clear()

            if not self.loop:
                # Try to get the next song within 3 minutes.
                # If no song will be added to the queue in time,
                # the player will disconnect due to performance
                # reasons.
                try:
                    async with timeout(60):  # 1 minute
                        self.current = await self.songs.get()
                except asyncio.TimeoutError:
                    self.bot.loop.create_task(self.stop())
                    return


            self.start_time = time.time();
            self.current.source.volume = self._volume
            self.voice.play(self.current.source, after=self.play_next_song)
            await self.current.source.channel.send(embed=self.current.create_embed())

            await self.next.wait()

    def play_next_song(self, error=None):
        self.current = None;
        if error:
            raise VoiceError(str(error))

        self.next.set()

    def skip(self):
        if self.is_playing:
            self.voice.stop()

    async def stop(self):
        self.songs.clear()

        if self.voice:
            await self.voice.disconnect()
            self.voice = None

class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.voice_states = {}

    def get_voice_state(self, ctx: commands.Context):
        state = self.voice_states.get(ctx.guild.id)
        if not state:
            state = VoiceState(self.bot, ctx)
            self.voice_states[ctx.guild.id] = state

        return state

    def cog_unload(self):
        for state in self.voice_states.values():
            self.bot.loop.create_task(state.stop())

    def cog_check(self, ctx: commands.Context):
        if not ctx.guild:
            raise commands.NoPrivateMessage('This command can\'t be used in DM channels.')

        return True

    async def cog_before_invoke(self, ctx: commands.Context):
        ctx.voice_state = self.get_voice_state(ctx)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError):
        print(str(error))
        error_file = get_error_file(error)
        await ctx.send("I'm sorry! An error occurred! ;-;", file=error_file)

    @commands.command(name='join', invoke_without_subcommand=True, help='Call me if you\'re lonely! :)))))')
    async def _join(self, ctx: commands.Context):
        """Joins a voice channel."""

        destination = ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='summon')
    async def _summon(self, ctx: commands.Context, *, channel: discord.VoiceChannel = None):
        """Summons the bot to a voice channel.
        If no channel was specified, it joins your channel.
        """

        if not channel and not ctx.author.voice:
            raise VoiceError("You aren't in a voice channel...")

        destination = channel or ctx.author.voice.channel
        if ctx.voice_state.voice:
            await ctx.voice_state.voice.move_to(destination)
            return

        ctx.voice_state.voice = await destination.connect()

    @commands.command(name='leave', aliases=['disconnect'], help='Tell me if you want me to go...')
    async def _leave(self, ctx: commands.Context):
        """Clears the queue and leaves the voice channel."""

        if not ctx.voice_state.voice:
            return await ctx.send("I'm not in a voice channel...")

        await ctx.voice_state.stop()
        del self.voice_states[ctx.guild.id]

    @commands.command(name='volume')
    async def _volume(self, ctx: commands.Context, *, volume: int):
        """Sets the volume of the player."""

        if not ctx.voice_state.is_playing:
            return await ctx.send("I'm not playing anything right now...")

        if 0 > volume > 100:
            return await ctx.send('Please enter between 0 and 100!')

        ctx.voice_state.volume = volume / 100
        await ctx.send('Playing at {} volume! :>'.format(volume))

    @commands.command(name='now', aliases=['current', 'playing', 'np'], help='What\'s playing now? :O')
    async def _now(self, ctx: commands.Context):
        """Displays the currently playing song."""
        if(ctx.voice_state.current is None):
            return await ctx.send("I'm not playing anything right now...")
        progress = 0
        duration = ctx.voice_state.current.source.duration 
        
        #Get progress; if paused, it should just be the current progress. Otherwise, add the unpaused time as well.
        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            progress = int(ctx.voice_state.current_progress);
        else:
            progress = int(time.time() - ctx.voice_state.start_time + ctx.voice_state.current_progress);

        play_frac = max(min(progress/duration, 1), 0); #Ensure between 1 and 0.
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

        progress_hms = YTDLSource.parse_duration(progress)
        duration_hms = YTDLSource.parse_duration(duration)

        embed = (discord.Embed(title='Now Playing:',
                               description='```css\n{0.title}\n{1}\n{2}/{3}```'.format(ctx.voice_state.current.source, progressbar_string, progress_hms, duration_hms),
                               color=EMBED_COLOUR)
                 .add_field(name='Requested by', value=ctx.voice_state.current.requester.mention)
                 .add_field(name='Uploader', value='[{0.uploader}]({0.uploader_url})'.format(ctx.voice_state.current.source))
                 .set_thumbnail(url=ctx.voice_state.current.source.thumbnail))

        await ctx.send(embed=embed);

        # await ctx.send(embed=ctx.voice_state.current.create_embed())

    @commands.command(name='pause', help='Pauses the song!')
    async def _pause(self, ctx: commands.Context):
        """Pauses the currently playing song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_playing():
            #Set current progress
            ctx.voice_state.current_progress = time.time() - ctx.voice_state.start_time;
            ctx.voice_state.voice.pause()
            await ctx.message.add_reaction('✅')

    @commands.command(name='resume', help="Resumes the song!")
    async def _resume(self, ctx: commands.Context):
        """Resumes a currently paused song."""

        if not ctx.voice_state.is_playing and ctx.voice_state.voice.is_paused():
            #Set start_time
            ctx.voice_state.start_time = time.time()
            ctx.voice_state.voice.resume()
            await ctx.message.add_reaction('✅')

    @commands.command(name='stop', help="Stops all songs!")
    async def _stop(self, ctx: commands.Context):
        """Stops playing song and clears the queue."""

        ctx.voice_state.songs.clear()

        if ctx.voice_state.is_playing:
            ctx.voice_state.voice.stop()
            await ctx.message.add_reaction('✅')

    @commands.command(name='skip', help="Skips the song!")
    async def _skip(self, ctx: commands.Context, *, skip = 1):
        """Vote to skip a song. Can skip multiple songs.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send("I'm not playing any music right now...")
        if(skip > 1):
            # remove (skip - 1) number of songs from front of queue, then skip current song. this prevents playing any of the skipping songs for like 1ms before skipping.
            indices = [i for i in range(skip - 1)]
            ctx.voice_state.songs.remove_n(indices)
        ctx.voice_state.skip()
        await ctx.message.add_reaction('✅')

    @commands.command(name='queue', aliases=['q'], help="Displays the queue! :O")
    async def _queue(self, ctx: commands.Context, *, page: int = 1):
        """Shows the player's queue.
        You can optionally specify the page to show. Each page contains 10 elements.
        """

        if len(ctx.voice_state.songs) == 0 and ctx.voice_state.current is None:
            return await ctx.send("The queue's empty D:")
        # If there are no songs in the queue, but there is a song currently playing:
        elif len(ctx.voice_state.songs) == 0:
            return await ctx.invoke(self.bot.get_command("now")); 

        current_song = ctx.voice_state.current
        current_name = truncate_string(current_song.source.title);
        # Display with the URL:
        current_title = "[**{0}**]({1.source.url})".format(current_name, current_song)
        current_duration = current_song.source.duration_hms;

        items_per_page = 10
        pages = math.ceil(len(ctx.voice_state.songs) / items_per_page)

        start = (page - 1) * items_per_page
        end = start + items_per_page

        indices = '';
        titles = '';
        durations = '';

        for i, song in enumerate(ctx.voice_state.songs[start:end], start=start):
            # queue += '`{0}.` [**{1.source.title}**]({1.source.url})\n'.format(i + 1, song)
            indices += "`{0}`\n".format(i + 1);
            #TODO: Fix formatting hotfix for long titles?
            truncated_title = truncate_string("{0.source.title}".format(song))

            titles += "[**{0}**]({1.source.url})\n".format(truncated_title, song)
            durations += "`{0}`\n".format(song.source.duration_hms);

        embed = discord.Embed(title="Queue:", description = "{0} tracks in queue!\n\n**Now Playing:**".format(len(ctx.voice_state.songs)), color=EMBED_COLOUR);
        embed.add_field(name="*", value="`0`", inline = True)
        embed.add_field(name="Name", value=current_title, inline = True)
        embed.add_field(name="Duration", value="`{0}`".format(current_duration), inline = True)

        embed.add_field(name="Index", value = indices, inline=True)
        embed.add_field(name="Name", value = titles, inline=True)
        embed.add_field(name="Duration", value = durations, inline=True)
        embed.set_footer(text="Viewing page {}/{}".format(page, pages))
        await ctx.send(embed=embed)

    @commands.command(name='shuffle')
    async def _shuffle(self, ctx: commands.Context):
        """Shuffles the queue."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("The queue's empty D:")

        ctx.voice_state.songs.shuffle()
        await ctx.message.add_reaction('✅')

    @commands.command(name='remove')
    async def _remove(self, ctx: commands.Context, index: int):
        """Removes a song from the queue at a given index."""

        if len(ctx.voice_state.songs) == 0:
            return await ctx.send("The queue's empty D:")

        ctx.voice_state.songs.remove(index - 1)
        await ctx.message.add_reaction('✅')

    @commands.command(name='loop')
    async def _loop(self, ctx: commands.Context):
        """Loops the currently playing song.
        Invoke this command again to unloop the song.
        """

        if not ctx.voice_state.is_playing:
            return await ctx.send("I'm not playing anything...")

        # Inverse boolean value to loop and unloop.
        ctx.voice_state.loop = not ctx.voice_state.loop
        await ctx.message.add_reaction('✅')

    @commands.command(name='play', aliases=['p'], help='Let me play some songs for you! :OOO')
    # async def _play(self, ctx: commands.Context, *, search: str):
    async def _play(self, ctx: commands.Context, *args):
        """Plays a song.
        If there are songs in the queue, this will be queued until the
        other songs finished playing.
        This command automatically searches from various sites if no URL is provided.
        A list of these sites can be found here: https://rg3.github.io/youtube-dl/supportedsites.html
        """
        search = " ".join(args)
        if search.strip() == "":
            await ctx.send("Tell me what to play :O\n\ntry this :D\n`^play https://www.youtube.com/watch?v=dQw4w9WgXcQ`\n`^play Epic Music`")
            return

        if not ctx.voice_state.voice:
            await ctx.invoke(self._join)

        async with ctx.typing():
            try:
                data = await YTDLSource.get_info(ctx, search, loop = self.bot.loop)
                is_playlist = False
                if('entries' in data):
                    is_playlist = True
                    #Playlist
                    enqueued = 0;
                    total_time = 0;
                    for entry in data['entries']:
                        if entry:
                            url = "www.youtube.com/watch?v=" + entry['url']
                            total_time += entry['duration'];
                            #TODO: New thread instead of blocking main thread?
                            source = await YTDLSource.create_source(ctx, url, loop = self.bot.loop);
                            song = Song(source)
                            await ctx.voice_state.songs.put(song)
                            enqueued += 1;

                    #TODO: Thumbnail of first song?
                    embed = discord.Embed(title = "Added playlist to queue! :D", description="```{0}```".format(data['title']), color = EMBED_COLOUR)
                    embed.add_field(name="Songs", value="`{0}`".format(enqueued), inline=True);
                    embed.add_field(name="Duration", value="`{0}`".format(YTDLSource.parse_duration(int(total_time))))
                    embed.add_field(name="Requester", value="{0}".format(ctx.author.mention))
                    await ctx.send(embed=embed) 
                    return;

                #play first song from playlist, or search otherwise.
                source = await YTDLSource.create_source(ctx, search, loop=self.bot.loop)
            except YTDLError as error:
                print(str(error))
                error_file = get_error_file(error)
                await ctx.send("I'm sorry! An error occurred! ;-;", file=error_file)
            else:
                song = Song(source)

                await ctx.voice_state.songs.put(song)

                if len(ctx.voice_state.songs) > 1 or not ctx.voice_state.current is None: #Not the only song playing
                    title = "Added to queue! :D"

                    duration_hms = source.duration_hms;
                    position = len(ctx.voice_state.songs)

                    embed=discord.Embed(title=title, color=EMBED_COLOUR)
                    embed.add_field(name="Position", value="`{0}`".format(position), inline = True);
                    embed.add_field(name="Name", value="{0}".format(source.title), inline = True);
                    embed.add_field(name="Duration", value="`{0}`".format(duration_hms), inline = True);
                    await ctx.send(embed=embed)


    # https://stackoverflow.com/questions/63658589/how-to-make-a-discord-bot-leave-the-voice-channel-after-being-inactive-for-x-min
    # @commands.Cog.listener()
    # async def on_voice_state_update(self, member, before, after):
        # if not member.id == self.bot.user.id:
            # return

        # elif before.channel is None:
            # voice = after.channel.guild.voice_client
            # time = 0
            # while True:
                # await asyncio.sleep(1)
                # time = time + 1
                # if voice.is_playing() and not voice.is_paused():
                    # time = 0
                # if time == 30:
                    # await voice.disconnect()
                # if not voice.is_connected():
                    # break

    @_join.before_invoke
    @_play.before_invoke
    async def ensure_voice_state(self, ctx: commands.Context):
        if not ctx.author.voice or not ctx.author.voice.channel:
            raise commands.CommandError("You aren't connected to a voice channel...")

        if ctx.voice_client:
            if ctx.voice_client.channel != ctx.author.voice.channel:
                raise commands.CommandError("I'm already in a voice channel!")

bot.add_cog(Music(bot))

@bot.event
async def on_ready():
    print(f'{bot.user.name} has connected to Discord!')       

@bot.event
async def on_message(message):
    debug_mode = check_debug_mode();
    if debug_mode and message.author.id != 498808695170269184:
        return

    await bot.process_commands(message);

    if bot.user.mentioned_in(message):
        if("goodnight" in message.content.lower()):
            await message.channel.send("goodnight!")
        if("<3" in message.content.lower()):
            await message.channel.send("<3")

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

@bot.command(name='changelog')
async def changelog(ctx):
    changelog="""
    hoi!! im version 0.1.0 now :D

    **Bug Fixes**
    `stop` now actually works. woaaa!
    I can now `play` playlists~~~!
    
    **Commands:**
    `join`
    `leave`
    `play`
    `stop`
    `skip`
    `queue`
    `ping`
    `pong`
    `changelog`
    """
    embed = discord.Embed(title="Changelog", description = changelog, color = EMBED_COLOUR)
    await ctx.send(embed=embed)

#TODO: Not show up in help
@bot.command(name='debug')
async def debug(ctx, password, *args):
    if ctx.message.author.id != 498808695170269184:
        return

    PASSWORD_HASH = os.getenv("dev_password")
    password_hash = hashlib.sha256(password.encode())
    if(password_hash.hexdigest() != PASSWORD_HASH):
        return;

    expr = ' '.join(args);
    string = eval(expr)
    await ctx.send(string)

def check_debug_mode():
    debug_mode = os.getenv("debug_mode");
    return debug_mode;

def truncate_string(string):
    # Truncates string, adding ellipsis behind if it exceeds 50 characters.
    if len(string) > 50:
        string = string[:50] + "..."
    return string;

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)

