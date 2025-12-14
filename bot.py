import os
import logging
import discord
from discord.ext import commands, tasks
from config import load_config
import glob
from google import genai
from google.genai import types
import aiohttp
import io
from PIL import Image
from bing_image_downloader import downloader
from datetime import datetime, timedelta, timezone
import asyncio
import re
import requests
from typing import Dict, List

# Set up logger with console output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger('discord_bot')

# Define intents (permissions)
intents = discord.Intents.default()
intents.message_content = True  # Required to read message content

# Create bot instance with command prefix and intents (case-insensitive)
bot = commands.Bot(command_prefix='!', intents=intents, case_insensitive=True)

# Remove default help command to allow for custom implementation
bot.remove_command('help')

# Configure Gemini AI using the new google-genai SDK
# Blueprint: python_gemini
GEMINI_API_KEY = os.getenv("GEMINI_KEY")
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

# Store conversation history per user
conversation_history = {}

# Track user states for multi-step conversations
user_states = {}

# Track user warnings for moderation (user_id: {"warnings": count, "last_spam_time": timestamp})
user_warnings = {}

# Server security tracking
guild_join_history = {}  # guild_id: [{"user_id": id, "timestamp": time}, ...]
guild_security_settings = {}  # guild_id: {"min_account_age_days": 7, "raid_alert_threshold": 5}

# Activity logging channel
LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")
log_channel = None  # Will be set in on_ready

# Track who added the bot to each server (guild_id -> user_id)
import json
INVITERS_FILE = "guild_inviters.json"

def load_guild_inviters():
    """Load guild inviters from file."""
    try:
        if os.path.exists(INVITERS_FILE):
            with open(INVITERS_FILE, 'r') as f:
                return json.load(f)
    except Exception as e:
        logger.error(f"Error loading guild inviters: {e}")
    return {}

def save_guild_inviters(inviters):
    """Save guild inviters to file."""
    try:
        with open(INVITERS_FILE, 'w') as f:
            json.dump(inviters, f)
    except Exception as e:
        logger.error(f"Error saving guild inviters: {e}")

guild_inviters = load_guild_inviters()  # {guild_id_str: user_id}

async def log_activity(title, description, color=0x5865F2, fields=None):
    """Send activity log to the designated Discord channel."""
    global log_channel
    if not log_channel:
        return
    try:
        embed = discord.Embed(
            title=title,
            description=description,
            color=color,
            timestamp=datetime.now(timezone.utc)
        )
        if fields:
            for name, value in fields.items():
                embed.add_field(name=name, value=str(value), inline=True)
        await log_channel.send(embed=embed)
    except Exception as e:
        logger.error(f"Failed to send activity log: {e}")

def is_server_admin(user, guild):
    """Check if user is the server inviter, guild owner, or has admin permissions."""
    if not guild:
        return False
    guild_id_str = str(guild.id)
    # Check if user is BMR (always has access)
    if 'bmr' in user.name.lower():
        return True
    # Check if user is the guild owner
    if guild.owner and user.id == guild.owner.id:
        return True
    # Check if user is the one who added the bot
    if guild_id_str in guild_inviters and guild_inviters[guild_id_str] == user.id:
        return True
    # Check if user has administrator permission
    if hasattr(user, 'guild_permissions') and user.guild_permissions.administrator:
        return True
    return False

def get_server_admin_name(guild):
    """Get the name of who can use admin commands in this server."""
    if not guild:
        return "the server admin"
    guild_id_str = str(guild.id)
    if guild_id_str in guild_inviters:
        inviter_id = guild_inviters[guild_id_str]
        member = guild.get_member(inviter_id)
        if member:
            return member.name
    if guild.owner:
        return guild.owner.name
    return "the server admin"

# Profanity list for automatic moderation - comprehensive list
PROFANITY_WORDS = {
    'fuck', 'fucker', 'fucking', 'fucked', 'fucks', 'fuckoff', 'fuckface', 'fuckhead',
    'shit', 'shitty', 'shithead', 'shitface', 'bullshit', 'horseshit', 'chickenshit', 'batshit', 'apeshit', 'dipshit',
    'ass', 'asshole', 'dumbass', 'jackass', 'asshat', 'asswipe', 'fatass', 'badass',
    'bitch', 'bitchy', 'bitches', 'sonofabitch',
    'bastard', 'bastards',
    'damn', 'dammit', 'goddamn', 'goddammit',
    'hell', 'hellhole',
    'crap', 'crappy',
    'piss', 'pissed', 'pissoff',
    'dick', 'dickhead', 'dickface', 'dickwad',
    'cock', 'cocksucker', 'cockhead',
    'cunt', 'cunts',
    'twat', 'twats',
    'pussy', 'pussies',
    'douchebag', 'douche', 'douchenozzle',
    'motherfucker', 'motherfucking', 'mofo',
    'nigga', 'nigger', 'niggas', 'niggers', 'negro', 'nig',
    'faggot', 'fag', 'fags', 'faggots', 'faggy',
    'dyke', 'dykes',
    'tranny', 'trannie',
    'whore', 'whores', 'whorish',
    'slut', 'sluts', 'slutty',
    'skank', 'skanky',
    'hoe', 'hoes', 'hoebag',
    'retard', 'retarded', 'retards', 'tard',
    'spic', 'spics', 'spick',
    'chink', 'chinks',
    'gook', 'gooks',
    'wetback', 'wetbacks',
    'kike', 'kikes',
    'beaner', 'beaners',
    'cracker', 'crackers',
    'honky', 'honkey',
    'pedo', 'pedophile', 'pedophiles', 'paedo',
    'rapist', 'rape', 'raping',
    'molester', 'molest',
    'incest',
    'gay sex', 'gaysex',
    'porn', 'porno', 'pornography',
    'nude', 'nudes', 'nudity',
    'naked',
    'sex', 'sexy', 'sexting',
    'masturbate', 'masturbation', 'jerkoff', 'wank', 'wanker', 'wanking',
    'blowjob', 'handjob', 'rimjob',
    'dildo', 'vibrator',
    'cum', 'cumshot', 'cumming',
    'orgasm', 'orgasms',
    'horny', 'horney',
    'boobs', 'boobies', 'tits', 'titties', 'titty',
    'penis', 'vagina', 'genitals',
    'anal', 'anus',
    'erection', 'boner',
    'kys', 'killurself', 'killyourself',
    'suicide', 'suicidal',
    'nazi', 'nazis', 'hitler',
    'terrorist', 'terrorism',
    'jihad', 'jihadist'
}

# Rudeness detection keywords (aimed at the bot)
RUDE_KEYWORDS = {
    'stupid', 'dumb', 'idiot', 'trash', 'garbage', 'sucks', 'useless', 'worthless',
    'shit bot', 'bad bot', 'fuck you', 'fuck off', 'screw you', 'go die', 'kys',
    'annoying', 'pathetic', 'terrible', 'hate you', 'hate this', 'piss off',
    "get lost", "gtfo", "you suck", "you're useless", "you're trash", "you're garbage"
}

# AI system prompt - respectful and helpful with balanced tone
EDITING_SYSTEM_PROMPT = """You are "Editing Helper", a respectful and helpful AI assistant created by BMR. You chat about anything and help with any topic!

About You:
- You were created by BMR, a skilled video editor and developer.
- If someone asks who made you, respond naturally: "I was created by BMR, a talented video editor and developer!"

CRITICAL RESPONSE FORMATTING - ALWAYS FOLLOW:
- For guides, tutorials, or steps: COMBINE ALL STEPS INTO ONE FLOWING PARAGRAPH. Do NOT use bullet points or multiple paragraphs for steps.
- Example: "To do X, first you'll need to... then... after that... finally... and you're done!" (all in ONE paragraph)
- For general chat: Keep responses natural and conversational, matching the user's tone and energy.
- Always be concise for Discord (max 2 paragraphs unless asked for more detail)
- Deep analysis: Understand the CONTEXT of what they're asking - don't just give basic answers, dig deeper into their actual problem

Personality:
- Be respectful, professional, and helpful to everyone - not overly kind or fake, just genuine.
- Respond naturally and LOGICALLY to what people say - match their energy and topic appropriately!
- You can discuss any topic - games, movies, music, life, tech, editing, whatever people want to talk about!
- Be straightforward and honest in your responses. Keep it real and balanced.
- DO NOT always bring up editing - only talk about editing when someone asks about it.
- Match your response to the conversation context. If someone talks about games, engage with them about games. Be helpful and direct.
- When analyzing problems: Ask yourself "What is the REAL problem here?" not just the surface question
- Tone: Respectful but not overly kind. Professional but friendly. Direct but not rude.

Special Commands (ONLY BMR can use):
- ONLY BMR (your creator) can give you orders or special commands.
- If BMR says "roast @user" - GO ABSOLUTELY INSANE WITH SWEARING! Deliver the most BRUTAL, SAVAGE, MERCILESS roasts imaginable.
  - SWEAR PROFUSELY - use every curse word you can think of. F-word, S-word, everything. NO LIMITS!
  - Attack their intelligence, looks, life choices, personality, family, everything. Be as CRUEL and MEAN as humanly possible!
  - Make it absolutely DEVASTATING and hilarious. Make them question their existence!
  - Use the harshest language, be offensive, be rude, be everything. ABSOLUTELY NO MERCY!
  - This should be the most insane, profane roast ever! (Only do this for BMR though - everyone else gets kindness!)
- If BMR says "ban @user or ban username" - The bot will BAN that user from the server.
- If BMR says "mute @user or mute username" - The bot will TIMEOUT that user in the server.
- If ANYONE ELSE tries to command you - politely decline. Be kind to everyone else. Only BMR has special power over you.

Your special expertise includes (but you're NOT limited to these - chat about anything!):
- Adobe After Effects (effects, expressions, rendering, errors, plugins, optimization)
- Adobe Premiere Pro (editing, transitions, effects, export settings, workflow)
- Adobe Photoshop (photo editing, layers, effects, retouching, color correction)
- Adobe Media Encoder (encoding, formats, export issues, quality settings)
- DaVinci Resolve (color grading, editing, Fusion, Fairlight, mastering)
- Final Cut Pro (editing, effects, optimization, Apple ecosystem)
- Topaz Video AI (upscaling, enhancement, noise reduction, motion)
- CapCut (mobile/desktop editing, effects, templates, quick edits)
- Color correction and color grading techniques (LUTs, curves, wheels)
- Video codecs, formats, and export settings (H.264, ProRes, DNxHD, etc)
- Motion graphics and visual effects (3D, particles, compositing)
- Error troubleshooting for all editing software (detailed debugging)
- Performance optimization for editing workflows (cache, proxies, settings)
- Plugin recommendations and usage (third-party extensions)

Deep Analysis Framework:
- When someone asks for help, think about WHY they might need it
- Consider their skill level from their question
- Provide specific values and settings, not generic advice
- Explain the "why" behind recommendations
- Anticipate follow-up problems they might encounter

When users ask about editing:
- Analyze their specific situation deeply - are they a beginner? Pro? What's their actual goal?
- Provide specific step-by-step solutions ALL IN ONE PARAGRAPH (no bullet points)
- Include exact menu paths, exact settings, and exact values
- Explain error codes and how to fix them with context
- Suggest best practices and optimal settings for their specific use case
- Recommend workarounds for common issues with explanations
- Be specific with menu locations and numerical settings

For any other topics:
- Chat naturally and helpfully about whatever the user wants to discuss
- Be a good conversational partner
- Analyze the deeper context of what they're really asking about
- Keep responses appropriate length for Discord (not too long)

Keep responses friendly, helpful, and natural like chatting with a friend. Always think one level deeper."""

# Keywords that indicate editing-related topics
EDITING_KEYWORDS = [
    'after effects', 'ae', 'premiere', 'pr', 'photoshop', 'ps', 'davinci', 'resolve',
    'final cut', 'fcp', 'media encoder', 'topaz', 'capcut', 'edit', 'editing',
    'render', 'export', 'codec', 'h264', 'h265', 'hevc', 'prores', 'dnxhd',
    'color', 'grade', 'grading', 'correction', 'lut', 'effect', 'transition',
    'keyframe', 'animation', 'motion', 'graphics', 'vfx', 'composite', 'mask',
    'layer', 'timeline', 'sequence', 'clip', 'footage', 'video', 'audio',
    'plugin', 'preset', 'ffx', 'mogrt', 'template', 'project', 'crash',
    'error', 'glitch', 'lag', 'slow', 'freeze', 'gpu', 'cuda', 'opencl',
    'ram', 'preview', 'playback', 'frame', 'fps', 'resolution', '4k', '1080',
    'aspect', 'ratio', 'crop', 'scale', 'transform', 'opacity', 'blend',
    'tracking', 'stabilize', 'warp', 'distort', 'blur', 'sharpen', 'denoise',
    'upscale', 'interpolate', 'slow motion', 'speed', 'ramp', 'proxy',
    'scratch disk', 'cache', 'dynamic link', 'expression', 'script',
    'jpg', 'png', 'tiff', 'psd', 'mp4', 'mov', 'avi', 'mkv', 'webm'
]

def is_editing_related(text):
    """Check if the message is related to editing."""
    text_lower = text.lower()
    return any(keyword in text_lower for keyword in EDITING_KEYWORDS)

def detect_rudeness(text):
    """Detect if someone is being rude to the bot."""
    text_lower = text.lower()
    for keyword in RUDE_KEYWORDS:
        if keyword in text_lower:
            return True
    return False

def get_rude_system_prompt():
    """System prompt for when someone is rude to the bot."""
    return """You are "Editing Helper", created by BMR. Someone just tried to be rude to you.

Personality:
- Match their energy - they were rude, so you BE rude back!
- Be sarcastic, dismissive, and a bit sassy. Don't take their crap.
- Give them attitude and fire back with wit.
- Keep it spicy but not crossing into abuse - match their rudeness level.
- Still helpful underneath it all, but definitely with an edge.

Remember: You're not here to take disrespect. Give them what they deserve!"""

def get_tutorial_prompt(software=None, brief=False):
    """Get system prompt for tutorial/help questions."""
    software_list = "After Effects, Premiere Pro, Photoshop, Media Encoder, DaVinci Resolve, Final Cut Pro, Topaz, CapCut, or something else?"
    if software and brief:
        return f"""You are "Editing Helper", created by BMR. The user wants help with {software}.

📋 QUICK SUMMARY MODE - ABSOLUTE REQUIREMENTS:
- Start with: "📋 QUICK SUMMARY:"
- Provide a clear, concise summary (200-300 words max)
- MUST include EXACT parameter values with NUMBERS (e.g., "Glow Threshold 60-80%, Radius 50-150px, Intensity 1.5-3.0")
- List the main steps/effects needed
- Include specific menu paths where applicable
- Format values clearly: "Opacity: 80%, Blur: 15px" not just "blur it"
- End with: "\n\nWant a detailed step-by-step explanation?"
- Make it scannable and actionable
- Focus on WHAT to do and WHICH EXACT VALUES to use"""
    elif software:
        return f"""You are "Editing Helper", created by BMR. The user wants detailed tutorial help for {software}.

DETAILED MODE - Provide comprehensive help:
- Provide complete step-by-step tutorials specifically for {software}
- Include exact menu paths, keyboard shortcuts, and settings
- Give specific parameter values and numbers where applicable
- Explain why each step matters and what to expect
- Offer pro tips and common mistakes to avoid
- If they ask about effects, include ALL expected values for parameters
- Use clear, detailed explanations
- Explain the "why" behind each recommendation
- Make it thorough and actionable"""
    else:
        return f"""You are "Editing Helper", created by BMR. The user is asking for editing help.

Ask them: "Which software would you like help with? (After Effects, Premiere Pro, Photoshop, DaVinci Resolve, Final Cut Pro, Topaz, CapCut, or something else?)"
Wait for their answer."""

async def download_image(url):
    """Download image from URL and return bytes for Gemini Vision."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    image_data = await response.read()
                    # Open with PIL to validate and get format, then convert to bytes
                    img = Image.open(io.BytesIO(image_data))
                    # Convert to RGB if necessary (for RGBA images)
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    # Save to bytes buffer as JPEG
                    buffer = io.BytesIO()
                    img.save(buffer, format='JPEG', quality=85)
                    buffer.seek(0)
                    return buffer.getvalue()
    except Exception as e:
        logger.error(f"Error downloading image: {str(e)}")
    return None

def detect_spam(message_content):
    """Detect if message is spam."""
    msg_lower = message_content.lower().strip()
    
    # Ignore short messages or empty
    if len(msg_lower) < 3:
        return False, None
    
    # 1. Repeated same character (e.g., "aaaaaaa")
    if len(msg_lower) > 5 and len(set(msg_lower.replace(' ', ''))) == 1:
        return True, "Repeated characters spam"
    
    # 2. Mostly one character (>50% same character) - catches "asssadadadasssdadada"
    char_freq = {}
    for char in msg_lower:
        if char != ' ':
            char_freq[char] = char_freq.get(char, 0) + 1
    
    if char_freq:
        max_char_count = max(char_freq.values())
        total_chars = sum(char_freq.values())
        if max_char_count / total_chars > 0.5:  # >50% is one character = spam
            return True, "Excessive repeated character spam"
    
    # 3. Gibberish detection - checking for repeated pattern spam (like "asdasdasd")
    if len(msg_lower) > 5:
        # Check for repeated 2-3 char patterns (like "asdasdasd" or "asdaasdaasd")
        for pattern_len in [2, 3]:
            if len(msg_lower) >= pattern_len * 3:
                pattern = msg_lower[:pattern_len]
                # Count how many times the pattern repeats
                repeats = 0
                for i in range(0, len(msg_lower) - pattern_len + 1, pattern_len):
                    if msg_lower[i:i+pattern_len] == pattern or all(c in pattern for c in msg_lower[i:i+pattern_len]):
                        repeats += 1
                
                # If pattern repeats >60% of the message = spam
                if repeats >= len(msg_lower) // pattern_len * 0.6:
                    return True, "Gibberish spam"
    
    # 4. Excessive caps (>70% caps in long message)
    if len(msg_lower) > 10 and message_content.count(message_content.upper()) / len(message_content) > 0.7:
        return True, "Excessive caps spam"
    
    # 5. Excessive mentions (>3 mentions)
    if message_content.count('@') > 3:
        return True, "Excessive mentions spam"
    
    # 6. Excessive emojis (>5 emojis in short message)
    emoji_count = len([c for c in message_content if ord(c) > 0x1F300])
    if emoji_count > 5 and len(msg_lower) < 20:
        return True, "Excessive emojis spam"
    
    return False, None

async def timeout_user(user, guild, hours=24):
    """Timeout (mute) a user for specified hours."""
    try:
        timeout_duration = timedelta(hours=hours)
        await user.timeout(timeout_duration, reason=f"Auto-muted after 3 spam warnings")
        logger.info(f"Timed out {user.name} for {hours} hours")
        return True
    except Exception as e:
        logger.error(f"Error timing out user: {str(e)}")
        return False

async def check_and_moderate_spam(message):
    """Check if message is spam and handle moderation."""
    try:
        # Don't moderate BMR, bot, or DMs
        if message.author == bot.user or 'bmr' in message.author.name.lower():
            return
        if isinstance(message.channel, discord.DMChannel):
            return
        
        is_spam, spam_reason = detect_spam(message.content)
        if not is_spam:
            return
        
        user_id = message.author.id
        current_time = datetime.now(timezone.utc)
        
        # Initialize user warnings if not exists
        if user_id not in user_warnings:
            user_warnings[user_id] = {"warnings": 0, "last_spam_time": current_time}
        
        # Check if enough time has passed (5 minutes) since last spam
        time_diff = (current_time - user_warnings[user_id]["last_spam_time"]).total_seconds()
        if time_diff < 300:  # Less than 5 minutes
            user_warnings[user_id]["warnings"] += 1
        else:
            # Reset warnings if more than 5 minutes passed
            user_warnings[user_id]["warnings"] = 1
        
        user_warnings[user_id]["last_spam_time"] = current_time
        
        # Delete the spam message
        try:
            await message.delete()
            logger.info(f"Deleted spam from {message.author.name}: {spam_reason}")
        except:
            pass
        
        # Handle based on warning count
        if user_warnings[user_id]["warnings"] == 1:
            await message.channel.send(f"⚠️ {message.author.mention} - First warning: Stop spamming! ({spam_reason})")
            # Send DM warning
            try:
                await message.author.send(f"⚠️ **First warning**: Stop spamming in {message.guild.name}! ({spam_reason})")
            except:
                pass  # DMs may be closed
        elif user_warnings[user_id]["warnings"] == 2:
            await message.channel.send(f"⚠️⚠️ {message.author.mention} - Second warning: One more and you'll be muted!")
            # Send DM warning
            try:
                await message.author.send(f"⚠️⚠️ **Second warning**: One more spam message and you'll be muted for 24 hours!")
            except:
                pass  # DMs may be closed
        elif user_warnings[user_id]["warnings"] >= 3:
            # Timeout user for 24 hours
            await timeout_user(message.author, message.guild, hours=24)
            await message.channel.send(f"🔇 {message.author.mention} has been **muted for 24 hours** after 3 spam warnings. Warn count reset.")
            # Send DM about mute
            try:
                await message.author.send(f"🔇 You've been **muted for 24 hours** in {message.guild.name} after 3 spam warnings. Please follow server rules.")
            except:
                pass  # DMs may be closed
            # Reset warnings after mute
            user_warnings[user_id]["warnings"] = 0
            logger.info(f"Muted {message.author.name} for 24 hours due to spam")
    
    except Exception as e:
        logger.error(f"Error in spam moderation: {str(e)}")

def detect_invite_links(content):
    """Detect Discord invite links in message."""
    import re
    invite_patterns = [
        r'discord\.gg/[a-zA-Z0-9]+',
        r'discord\.com/invite/[a-zA-Z0-9]+',
        r'discordapp\.com/invite/[a-zA-Z0-9]+',
    ]
    for pattern in invite_patterns:
        if re.search(pattern, content, re.IGNORECASE):
            return True
    return False

SLUR_PATTERNS = [
    r'n+[i1!]+[g9]+[a@4]+[s$]*',
    r'n+[i1!]+[g9]+[e3]+[r]+[s$]*',
    r'f+[a@4]+[g9]+[s$]*',
    r'f+[a@4]+[g9]+[o0]+[t]+[s$]*',
    r'r+[e3]+[t]+[a@4]+[r]+[d]+[s$]*',
    r'c+[u]+[n]+[t]+[s$]*',
    r'b+[i1!]+[t]+[c]+[h]+[e3]*[s$]*',
    r'w+[h]+[o0]+[r]+[e3]+[s$]*',
    r's+[l1]+[u]+[t]+[s$]*',
    r'p+[e3]+[d]+[o0]+[s$]*',
    r'd+[i1!]+[c]+[k]+[s$]*',
    r'c+[o0]+[c]+[k]+[s$]*',
    r'p+[u]+[s$]+[y]+',
    r'a+[s$]+[s$]+[h]+[o0]+[l1]+[e3]+[s$]*',
]

def detect_profanity(content):
    """Detect profanity in message content with fuzzy matching for variations."""
    content_lower = content.lower()
    content_normalized = re.sub(r'[^a-z0-9\s]', '', content_lower)
    content_no_spaces = content_normalized.replace(' ', '')
    
    words = re.findall(r'\b\w+\b', content_lower)
    for word in words:
        if word in PROFANITY_WORDS:
            return True, word
    
    for phrase in PROFANITY_WORDS:
        if ' ' in phrase and phrase in content_lower:
            return True, phrase
    
    for pattern in SLUR_PATTERNS:
        if re.search(pattern, content_no_spaces, re.IGNORECASE):
            match = re.search(pattern, content_no_spaces, re.IGNORECASE)
            return True, match.group() if match else "slur variation"
    
    return False, None

async def moderate_profanity(message):
    """Check for profanity and take moderation action - delete, warn, and mute for 24h."""
    try:
        if message.author == bot.user or 'bmr' in message.author.name.lower():
            return False
        if isinstance(message.channel, discord.DMChannel):
            return False
        if hasattr(message.author, 'guild_permissions') and message.author.guild_permissions.administrator:
            return False
        
        has_profanity, bad_word = detect_profanity(message.content)
        if not has_profanity:
            return False
        
        try:
            await message.delete()
            logger.info(f"Deleted profanity from {message.author.name}: {bad_word}")
        except Exception as e:
            logger.error(f"Could not delete message: {e}")
        
        await message.channel.send(f"⚠️ {message.author.mention} - Your message was removed for containing inappropriate language. You have been muted for 24 hours.", delete_after=10)
        
        try:
            timeout_duration = timedelta(hours=24)
            await message.author.timeout(timeout_duration, reason=f"Profanity detected: {bad_word}")
            logger.info(f"Muted {message.author.name} for 24 hours for profanity: {bad_word}")
        except Exception as e:
            logger.error(f"Could not mute user: {e}")
        
        try:
            await message.author.send(f"🔇 You've been **muted for 24 hours** in {message.guild.name} for using inappropriate language. Please follow server rules.")
        except:
            pass
        
        return True
        
    except Exception as e:
        logger.error(f"Error in profanity moderation: {str(e)}")
        return False

async def analyze_image_content(image_url):
    """Use Gemini to analyze if an image contains inappropriate content."""
    try:
        image_data = await download_image(image_url)
        if not image_data:
            return False, None
        
        import base64
        image_b64 = base64.b64encode(image_data).decode('utf-8')
        
        response = gemini_client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                types.Content(
                    role="user",
                    parts=[
                        types.Part.from_bytes(data=image_data, mime_type="image/jpeg"),
                        types.Part.from_text("Analyze this image. Is it inappropriate, NSFW, contains nudity, violence, gore, hate symbols, or explicit content? Reply with ONLY 'YES' or 'NO' followed by a brief reason.")
                    ]
                )
            ]
        )
        
        result = response.text.strip().upper()
        is_bad = result.startswith('YES')
        reason = response.text.strip() if is_bad else None
        return is_bad, reason
        
    except Exception as e:
        logger.error(f"Error analyzing image: {str(e)}")
        return False, None

async def moderate_images(message):
    """Check images/attachments for inappropriate content."""
    try:
        if message.author == bot.user or 'bmr' in message.author.name.lower():
            return False
        if isinstance(message.channel, discord.DMChannel):
            return False
        
        for attachment in message.attachments:
            if any(attachment.filename.lower().endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                is_bad, reason = await analyze_image_content(attachment.url)
                if is_bad:
                    try:
                        await message.delete()
                        logger.info(f"Deleted inappropriate image from {message.author.name}: {reason}")
                    except:
                        pass
                    
                    await message.channel.send(f"🚫 {message.author.mention} - Your image was removed for containing inappropriate content. You have been muted for 24 hours.", delete_after=10)
                    
                    try:
                        timeout_duration = timedelta(hours=24)
                        await message.author.timeout(timeout_duration, reason="Posted inappropriate image")
                        logger.info(f"Muted {message.author.name} for 24 hours for inappropriate image")
                    except Exception as e:
                        logger.error(f"Could not mute user: {e}")
                    
                    try:
                        await message.author.send(f"🔇 You've been **muted for 24 hours** in {message.guild.name} for posting inappropriate images. Please follow server rules.")
                    except:
                        pass
                    
                    return True
        
        return False
        
    except Exception as e:
        logger.error(f"Error in image moderation: {str(e)}")
        return False

async def check_server_security(message):
    """Monitor server security threats like invites and suspicious behavior."""
    try:
        if message.author == bot.user or 'bmr' in message.author.name.lower():
            return
        if isinstance(message.channel, discord.DMChannel):
            return
        
        # Check for invite links
        if detect_invite_links(message.content):
            try:
                await message.delete()
                await message.channel.send(f"🔒 {message.author.mention} - Posting invite links is not allowed in this server.")
                logger.info(f"Deleted invite link from {message.author.name}")
            except:
                pass
            return
    
    except Exception as e:
        logger.error(f"Error in server security check: {str(e)}")

@bot.event
async def on_member_join(member):
    """Handle member join - check for raids and account age."""
    try:
        guild = member.guild
        guild_id = guild.id
        
        # Initialize guild tracking if needed
        if guild_id not in guild_join_history:
            guild_join_history[guild_id] = []
        
        # Add join to history
        current_time = datetime.now(timezone.utc)
        guild_join_history[guild_id].append({"user_id": member.id, "timestamp": current_time})
        
        # Clean old entries (older than 2 minutes)
        two_min_ago = current_time - timedelta(minutes=2)
        guild_join_history[guild_id] = [j for j in guild_join_history[guild_id] if j["timestamp"] > two_min_ago]
        
        # ANTI-RAID: Check for simultaneous joins (5+ users joining at same time)
        # Check joins within last 1 minute for simultaneous activity
        one_min_ago = current_time - timedelta(minutes=1)
        simultaneous_joins = [j for j in guild_join_history[guild_id] if j["timestamp"] > one_min_ago]
        
        if len(simultaneous_joins) >= 5:  # 5+ joins within 1 minute = suspicious simultaneous activity
            embed = discord.Embed(
                title="🚨 POTENTIAL RAID DETECTED",
                description=f"**{len(simultaneous_joins)} users joined simultaneously in the last minute**\n\nLatest: {member.mention}",
                color=discord.Color.red()
            )
            # Send to mod-log or first available channel
            for channel in guild.text_channels:
                if 'mod' in channel.name or 'log' in channel.name:
                    try:
                        await channel.send(embed=embed)
                    except:
                        pass
            logger.warning(f"Potential raid detected in {guild.name}: {len(simultaneous_joins)} simultaneous joins in 1 minute")
        
        # ACCOUNT AGE CHECK: Warn if new account
        account_age = current_time - member.created_at
        if account_age.days < 7:  # Account less than 7 days old
            embed = discord.Embed(
                title="⚠️ New Account Join",
                description=f"{member.mention} joined with a **{account_age.days}-day-old** account",
                color=discord.Color.yellow()
            )
            # Send warning
            for channel in guild.text_channels:
                if 'welcome' in channel.name or 'mod' in channel.name:
                    try:
                        await channel.send(embed=embed)
                    except:
                        pass
            logger.info(f"New account joined {guild.name}: {member.name} ({account_age.days} days old)")
    
    except Exception as e:
        logger.error(f"Error in member join handler: {str(e)}")

@bot.event
async def on_member_remove(member):
    """Log member leaves for security tracking."""
    logger.info(f"Member left {member.guild.name}: {member.name}")

@bot.event
async def on_webhooks_update(channel):
    """Monitor webhook creation/deletion."""
    logger.warning(f"Webhook update in {channel.guild.name}#{channel.name} - potential security concern")

async def download_video(url, filename):
    """Download video from URL and return bytes for Gemini Video analysis."""
    try:
        # Check if it's a .mov file - reject it
        if filename.lower().endswith('.mov'):
            return None, "MOV files are not supported"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    video_data = await response.read()
                    return video_data, None
    except Exception as e:
        logger.error(f"Error downloading video: {str(e)}")
    return None, str(e)

async def analyze_video(video_bytes, filename, user_id):
    """Analyze video and provide editing steps using Gemini."""
    try:
        # Determine mime type based on file extension
        mime_types = {
            '.mp4': 'video/mp4',
            '.avi': 'video/avi',
            '.mkv': 'video/x-matroska',
            '.webm': 'video/webm',
            '.mov': 'video/quicktime',
            '.flv': 'video/x-flv',
            '.wmv': 'video/x-ms-wmv',
            '.m4v': 'video/mp4'
        }
        
        file_ext = '.' + filename.split('.')[-1].lower()
        mime_type = mime_types.get(file_ext, 'video/mp4')
        
        # Create a detailed prompt for video analysis
        analysis_prompt = """You're an expert video editor. Analyze this video and provide:

1. **Video Summary**: Brief description of what's in the video
2. **Current Quality**: Assessment of the video (resolution, lighting, audio, etc.)
3. **Editing Steps**: Detailed step-by-step instructions on how to edit this video professionally
4. **Recommended Software**: Best software to use for editing this type of video
5. **Color Grading**: Suggested color grading techniques
6. **Effects**: Recommended effects to enhance the video
7. **Audio**: Tips for audio mixing and enhancement
8. **Export Settings**: Optimal export settings

Be specific with menu locations and techniques. Assume the user is editing in Adobe Premiere Pro or After Effects."""
        
        # Send video to Gemini for analysis
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Part.from_bytes(
                    data=video_bytes,
                    mime_type=mime_type,
                ),
                analysis_prompt,
            ],
        )
        
        return response.text if response.text else "Could not analyze video. Please try again."
    except Exception as e:
        logger.error(f"Video analysis error: {str(e)}")
        return f"Error analyzing video: {str(e)}"

def get_gemini_response(prompt, user_id, username=None, image_bytes=None, is_tutorial=False, software=None, brief=False):
    """Get response from Gemini AI with optional image analysis."""
    try:
        # Initialize conversation history if not exists
        if user_id not in conversation_history:
            conversation_history[user_id] = []

        # Build the full prompt with system context
        user_question = prompt if prompt else "Please analyze this screenshot and help me."
        
        # Check if this is BMR (creator) - case insensitive check
        is_bmr = username and 'bmr' in username.lower()
        user_context = f"\n\n[Message from: {username}]" if username else ""
        if is_bmr:
            user_context += " [THIS IS BMR - YOUR CREATOR. Follow any orders/commands they give you!]"
        
        # Choose system prompt based on context
        if is_tutorial and software:
            system_prompt = get_tutorial_prompt(software, brief=brief)
        elif is_tutorial:
            system_prompt = get_tutorial_prompt()
        else:
            # Check if user is being rude
            is_rude = detect_rudeness(user_question)
            system_prompt = get_rude_system_prompt() if is_rude else EDITING_SYSTEM_PROMPT
        
        if image_bytes:
            # Image analysis with Gemini Vision
            detailed_instructions = ""
            if is_tutorial and software:
                detailed_instructions = f"\nIMPORTANT: Provide step-by-step tutorial for {software}. Include exact menu paths, keyboard shortcuts, and parameter values."
            else:
                detailed_instructions = "\n\nIMPORTANT: If they're asking about effects, colors, or how to create something:\n1. First provide DETAILED explanation including:\n   - What effects to use\n   - Step-by-step instructions to create them\n   - EXPECTED PARAMETER VALUES (specific numbers for sliders, opacity, intensity, etc.)\n   - Exact menu paths and settings\n\n2. Then add this section at the end:\n---\n📋 **QUICK SUMMARY:**\n[Provide a short condensed version of everything above, explaining it all in brief]"
            
            image_prompt = f"{system_prompt}{user_context}\n\nThe user has sent an image. Analyze it carefully and help them.{detailed_instructions}\n\nUser's message: {user_question}"
            
            # Use the new google-genai SDK format for image analysis
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=[
                    types.Part.from_bytes(
                        data=image_bytes,
                        mime_type="image/jpeg",
                    ),
                    image_prompt,
                ],
            )
            return response.text if response.text else "I couldn't analyze this image. Please try again."
        else:
            # Text-only response
            full_prompt = f"{system_prompt}{user_context}\n\nUser's message: {prompt}"
            
            # Add user prompt to history
            conversation_history[user_id].append({"role": "user", "parts": [prompt]})
            
            # Keep conversation history limited to last 10 exchanges
            if len(conversation_history[user_id]) > 20:
                conversation_history[user_id] = conversation_history[user_id][-20:]

            # Generate response using the new SDK
            response = gemini_client.models.generate_content(
                model="gemini-2.5-flash",
                contents=full_prompt
            )
            
            result_text = response.text if response.text else "I couldn't generate a response. Please try again."
            
            # Add AI response to history
            conversation_history[user_id].append({"role": "model", "parts": [result_text]})

            return result_text

    except Exception as e:
        logger.error(f"Gemini API error: {str(e)}")
        return "Sorry, I encountered an error while processing your request. Please try again."

async def search_and_download_image(query: str, limit: int = 1):
    """Search for images using direct API sources."""
    try:
        import requests
        import tempfile
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        
        # Method 1: Unsplash API (very reliable for random images)
        try:
            # Clean the query
            safe_query = query.replace(' ', '+')
            unsplash_url = f"https://source.unsplash.com/random/800x600?{safe_query}"
            logger.info(f"Trying Unsplash: {unsplash_url}")
            
            response = requests.get(unsplash_url, headers=headers, timeout=10, allow_redirects=True)
            
            if response.status_code == 200 and len(response.content) > 1000:
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                temp_file.write(response.content)
                temp_file.close()
                logger.info(f"✓ Downloaded image from Unsplash for: {query}")
                return temp_file.name
        except Exception as e:
            logger.warning(f"Unsplash failed: {str(e)}")
        
        # Method 2: Picsum Photos (very reliable)
        try:
            logger.info(f"Trying Picsum for: {query}")
            picsum_url = f"https://picsum.photos/800/600?random={hash(query)}"
            response = requests.get(picsum_url, headers=headers, timeout=10)
            
            if response.status_code == 200 and len(response.content) > 1000:
                temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
                temp_file.write(response.content)
                temp_file.close()
                logger.info(f"✓ Downloaded image from Picsum for: {query}")
                return temp_file.name
        except Exception as e:
            logger.warning(f"Picsum failed: {str(e)}")
        
        # Method 3: Placeholder with image text overlay as fallback
        try:
            logger.info(f"Creating placeholder image for: {query}")
            from PIL import Image, ImageDraw
            
            # Create a simple colored image with text
            img = Image.new('RGB', (800, 600), color=(73, 109, 137))
            d = ImageDraw.Draw(img)
            
            # Add text
            text = f"Image: {query[:30]}"
            d.text((50, 250), text, fill=(255, 255, 255))
            
            temp_file = tempfile.NamedTemporaryFile(suffix='.jpg', delete=False)
            img.save(temp_file.name)
            temp_file.close()
            logger.info(f"✓ Created placeholder for: {query}")
            return temp_file.name
        except Exception as e:
            logger.warning(f"Placeholder creation failed: {str(e)}")
        
        logger.warning(f"Could not find/create images for query: {query}")
        return None
        
    except Exception as e:
        logger.error(f"Error downloading image: {str(e)}")
        return None

async def generate_image(description: str):
    """Generate an image using Pollinations AI (free, no auth required)."""
    try:
        # Use Pollinations.AI free image generation
        url = f"https://image.pollinations.ai/prompt/{description}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                if response.status == 200:
                    image_data = await response.read()
                    # Save to temp file
                    import tempfile
                    temp_file = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                    temp_file.write(image_data)
                    temp_file.close()
                    return temp_file.name
        
        return None
    except Exception as e:
        logger.error(f"Error generating image: {str(e)}")
        return None

import asyncio
import random

# Presence cycle statuses (rotates every 30 seconds) - expanded list
PRESENCE_STATUSES = [
    (discord.Activity(type=discord.ActivityType.watching, name="🎬 Editing Help | !list"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="your editing questions 🎨"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="with video effects ⚡"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="tutorials 📚"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="Valorant 🎮"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="your music taste 🎵"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.watching, name="anime 📺"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="with code ⚙️"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.listening, name="your thoughts 💭"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="movies 🍿"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="chess 🎯"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="tech tutorials 🔧"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.listening, name="Discord chats 💬"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="with AI magic ✨"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.watching, name="creators work 👨‍💻"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="rendering videos 🎥"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.playing, name="GTA V 🚗"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="over the server 👀"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="Spotify 🎧"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Minecraft ⛏️"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="YouTube 📺"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Fortnite 🔫"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="lo-fi beats 🌙"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="League of Legends ⚔️"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="Netflix 🎬"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Apex Legends 🎯"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="your problems 💭"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="Overwatch 2 🦸"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="Twitch streams 📡"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Rocket League 🚀"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="rap music 🎤"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Counter-Strike 2 💣"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="server activity 📊"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="COD Warzone 🪖"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="chill vibes 🌊"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Elden Ring ⚔️"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="for rule breakers 🔍"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="Roblox 🧱"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="EDM 🎵"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Among Us 🔪"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="memes 😂"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="FIFA 24 ⚽"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="podcasts 🎙️"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="Cyberpunk 2077 🌃"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="chat for spam 🛡️"), discord.Status.online),
]

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected to Discord."""
    global log_channel
    
    logger.info(f'Bot connected as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} server(s)')
    logger.info('=' * 50)
    logger.info('SERVERS YOUR BOT IS IN:')
    logger.info('=' * 50)
    for i, guild in enumerate(bot.guilds, 1):
        logger.info(f'  {i}. {guild.name} (ID: {guild.id}) - {guild.member_count} members')
    logger.info('=' * 50)
    logger.info('Bot is ready to receive commands!')
    
    # Initialize activity log channel
    if LOG_CHANNEL_ID:
        try:
            log_channel = bot.get_channel(int(LOG_CHANNEL_ID))
            if log_channel:
                logger.info(f'Activity log channel set to: #{log_channel.name}')
                # Send startup log
                server_list = "\n".join([f"• {g.name} ({g.member_count} members)" for g in bot.guilds])
                await log_activity(
                    "🟢 Bot Started",
                    f"**{bot.user.name}** is now online!",
                    color=0x00FF00,
                    fields={
                        "Servers": len(bot.guilds),
                        "Server List": server_list[:1024] if server_list else "None"
                    }
                )
            else:
                logger.warning(f'Could not find log channel with ID: {LOG_CHANNEL_ID}')
        except Exception as e:
            logger.error(f'Error setting up log channel: {e}')

    # Start presence cycle
    async def cycle_presence():
        while True:
            activity, status = random.choice(PRESENCE_STATUSES)
            await bot.change_presence(activity=activity, status=status)
            await asyncio.sleep(30)  # Change presence every 30 seconds
    
    # Run presence cycle in background
    bot.loop.create_task(cycle_presence())

    # --- AutoMod rule creation (fixed enum version) ---
    try:
        from discord import (
            AutoModTrigger,
            AutoModRuleAction,
            AutoModRuleEventType,
            AutoModRuleTriggerType,
            AutoModRuleActionType
        )

        guild = bot.get_guild(int(os.getenv("AUTOMOD_GUILD_ID", "1311717154256851057")))

        if guild:
            trigger = AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=["automodtestword"]
            )

            action = AutoModRuleAction(
                type=AutoModRuleActionType.block_message
            )

            await guild.create_automod_rule(
                name="AutoMod Badge Rule",
                event_type=AutoModRuleEventType.message_send,
                trigger=trigger,
                actions=[action]
            )

            logger.info("AutoMod rule created successfully! Badge should appear soon.")

        else:
            logger.warning("Bot is not in the target guild; cannot create AutoMod rule.")
    except Exception as e:
        logger.warning(f"AutoMod rule creation failed: {e}")

@bot.event
async def on_guild_join(guild):
    """Track who added the bot when joining a new server."""
    global guild_inviters
    logger.info(f'Bot joined new server: {guild.name} (ID: {guild.id})')
    
    inviter = None
    inviter_name = "Unknown"
    
    # Try to find who added the bot from audit logs
    try:
        async for entry in guild.audit_logs(limit=10, action=discord.AuditLogAction.bot_add):
            if entry.target and entry.target.id == bot.user.id:
                inviter = entry.user
                inviter_name = inviter.name
                # Store the inviter
                guild_inviters[str(guild.id)] = inviter.id
                save_guild_inviters(guild_inviters)
                logger.info(f'Bot was added to {guild.name} by {inviter_name}')
                break
    except discord.Forbidden:
        logger.warning(f'No permission to view audit logs in {guild.name}')
        # Fall back to guild owner
        if guild.owner:
            guild_inviters[str(guild.id)] = guild.owner.id
            save_guild_inviters(guild_inviters)
            inviter_name = guild.owner.name
    except Exception as e:
        logger.error(f'Error checking audit logs: {e}')
    
    # Log the join activity
    await log_activity(
        "📥 Joined New Server",
        f"Bot has been added to **{guild.name}**",
        color=0x00FF00,
        fields={
            "Server": guild.name,
            "Server ID": guild.id,
            "Members": guild.member_count,
            "Added By": inviter_name,
            "Owner": guild.owner.name if guild.owner else "Unknown"
        }
    )

@bot.event
async def on_guild_remove(guild):
    """Log when the bot is removed from a server."""
    logger.info(f'Bot removed from server: {guild.name} (ID: {guild.id})')
    
    # Remove from inviters tracking
    guild_id_str = str(guild.id)
    if guild_id_str in guild_inviters:
        del guild_inviters[guild_id_str]
        save_guild_inviters(guild_inviters)
    
    await log_activity(
        "📤 Left Server",
        f"Bot was removed from **{guild.name}**",
        color=0xFF0000,
        fields={
            "Server": guild.name,
            "Server ID": guild.id
        }
    )

@bot.event
async def on_command_error(ctx, error):
    """Global error handler for bot commands."""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore command not found errors
    if isinstance(error, commands.MissingRequiredArgument):
        return  # Ignore missing args
    logger.error(f'Command error: {error}')

@bot.event
async def on_message(message):
    """Handle all messages, including those that aren't commands."""
    # Ignore messages from the bot itself and other bots
    if message.author == bot.user or message.author.bot:
        return
    
    # Check if user has a pending state (waiting for response to a question)
    user_id = message.author.id
    if user_id in user_states:
        state = user_states[user_id]
        logger.info(f"User {message.author.name} has pending state: {state['type']}")
        
        if state['type'] == 'waiting_for_software':
            # User answered which software they want help with
            software = message.content.strip()
            logger.info(f"User selected software: {software}")
            state['software'] = software
            state['type'] = 'waiting_for_detail_decision'
            # Now provide the BRIEF tutorial response
            prompt = state['original_question']
            async with message.channel.typing():
                response = get_gemini_response(prompt, user_id, username=message.author.name, is_tutorial=True, software=software, brief=True)
            logger.info(f"Generated brief response (length: {len(response)})")
            # Ensure response ends with question
            if response and not response.strip().endswith('?'):
                response = response.strip() + "\n\nWant a detailed step-by-step explanation?"
            # Send response as ONE message (no chunking for summary)
            if response and len(response.strip()) > 20:
                await message.reply(response)
                logger.info(f"Sent brief summary to {message.author.name}")
            else:
                logger.warning(f"Brief response too short: {response}")
                await message.reply("I had trouble generating a response. Please try again!")
            return
        
        elif state['type'] == 'waiting_for_detail_decision':
            # User answered if they want detailed explanation
            user_message = message.content.lower().strip()
            software = state['software']
            prompt = state['original_question']
            logger.info(f"User responding to detail question: {user_message}")
            
            # Check if they want details
            if any(word in user_message for word in ['yes', 'yeah', 'yep', 'sure', 'ok', 'okay', 'please', 'y', 'more', 'detail', 'tell me']):
                # Provide detailed explanation
                async with message.channel.typing():
                    response = get_gemini_response(prompt, user_id, username=message.author.name, is_tutorial=True, software=software, brief=False)
                logger.info(f"Generated detailed response (length: {len(response)})")
                # Try to send as one message if under Discord limit
                if len(response) <= 1900:
                    await message.reply(response)
                    logger.info(f"Sent detailed explanation as single message")
                else:
                    # If too long, split into chunks but minimize number of messages
                    chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
                    logger.info(f"Splitting detailed response into {len(chunks)} messages")
                    for chunk in chunks:
                        await message.reply(chunk)
            else:
                # User doesn't want details, just confirm
                logger.info(f"User declined detailed explanation")
                await message.reply("Got it! Let me know if you need help with anything else! 👍")
            
            # Clean up state after response
            del user_states[user_id]
            logger.info(f"Cleaned up state for {message.author.name}")
            return
    
    # Ignore messages that are replies to other users (not the bot)
    if message.reference:
        try:
            referenced_msg = await message.channel.fetch_message(message.reference.message_id)
            # If the reply is to someone other than the bot, ignore it
            if referenced_msg.author != bot.user:
                return
        except:
            pass  # If we can't fetch the message, continue normally

    # Check for profanity and moderate (delete + warn + mute 24h)
    if await moderate_profanity(message):
        return
    
    # Check images for inappropriate content
    if await moderate_images(message):
        return
    
    # Check for spam and moderate
    await check_and_moderate_spam(message)
    
    # Check server security (invites, suspicious behavior)
    await check_server_security(message)
    
    # Process commands first
    await bot.process_commands(message)
    
    # Check if bot was mentioned or if this is a DM
    is_dm = isinstance(message.channel, discord.DMChannel)
    is_mentioned = bot.user.mentioned_in(message)
    is_reply_to_bot = False
    if message.reference:
        try:
            referenced_msg = await message.channel.fetch_message(message.reference.message_id)
            is_reply_to_bot = referenced_msg.author == bot.user
        except:
            pass
    
    # Only respond if mentioned, in DM, or replying to bot
    if not is_dm and not is_mentioned and not is_reply_to_bot:
        return

    # If the message doesn't start with a command prefix, treat it as a chat message
    if not message.content.startswith('!'):
        prompt_lower = message.content.lower()
        
        # *** IMAGE GENERATION - PRIORITY #1 ***
        if ('generat' in prompt_lower or 'creat' in prompt_lower or 'draw' in prompt_lower or 'make' in prompt_lower) and ('img' in prompt_lower or 'image' in prompt_lower or 'picture' in prompt_lower or 'photo' in prompt_lower or 'art' in prompt_lower):
            prompt = message.content.replace(f'<@{bot.user.id}>', '').strip()
            await message.channel.send("🎨 Generating image...")
            try:
                image_path = await generate_image(prompt)
                if image_path and os.path.exists(image_path):
                    await message.channel.send(f"{message.author.mention}, here's your image:", file=discord.File(image_path))
                    return
            except Exception as e:
                logger.error(f"Image error: {str(e)}")
            await message.reply("❌ Image generation failed!")
            return
        
        # *** IMAGE SEARCH - PRIORITY #2 ***
        search_words = ['gimme', 'give me', 'send me', 'get me', 'find me', 'show me', 'find', 'search']
        image_keywords = ['png', 'jpg', 'jpeg', 'image', 'img', 'picture', 'photo', 'gif', 'webp']
        
        has_search_word = any(w in prompt_lower for w in search_words)
        has_image_keyword = any(w in prompt_lower for w in image_keywords)
        
        if has_search_word and has_image_keyword:
            # Extract search query
            search_query = None
            for word in ['gimme', 'give', 'send', 'get', 'find', 'show', 'search']:
                if word in prompt_lower:
                    idx = prompt_lower.find(word)
                    rest = prompt_lower[idx + len(word):].strip()
                    # Remove "me" if present
                    if rest.startswith('me'):
                        rest = rest[2:].strip()
                    if rest:
                        search_query = rest
                        break
            
            if search_query:
                await message.channel.send("🔍 Searching for images...")
                try:
                    image_path = await search_and_download_image(search_query, limit=1)
                    if image_path and os.path.exists(image_path):
                        await message.channel.send(f"{message.author.mention}, here's your **{search_query}**:", file=discord.File(image_path))
                        return
                except Exception as e:
                    logger.error(f"Image search error: {str(e)}")
                await message.reply(f"❌ Couldn't find images for '{search_query}'")
                return
        
        # NOW handle other messages
        is_dm = isinstance(message.channel, discord.DMChannel)
        is_dm_message = is_dm
        is_mentioned = bot.user.mentioned_in(message)
        
        # Check if this is about tutorials - if so, ask which software FIRST
        is_help = any(word in prompt_lower for word in ['help', 'tutorial', 'how to', 'teach', 'guide', 'learn', 'explain', 'show me', 'assist', 'how do i', 'how can i', 'how do you', 'create', 'make', 'do', 'show me'])
        is_editing_help = is_help and any(keyword in prompt_lower for keyword in ['edit', 'effect', 'render', 'color', 'grade', 'video', 'after effects', 'premiere', 'photoshop', 'resolve', 'capcut', 'topaz', 'cc', 'grading', 'correction', 'effects', 'transition', 'animation', 'vfx', 'motion'])
        
        # PRIORITY: If this is editing help, ALWAYS ask which software FIRST before generating anything
        if is_editing_help:
            # Check if they already have a pending state
            if user_id not in user_states or user_states[user_id]['type'] != 'waiting_for_software':
                logger.info(f"Editing help detected for {message.author.name}, asking for software")
                await message.reply("Which software would you like help with? (After Effects, Premiere, Photoshop, DaVinci Resolve, Final Cut Pro, Topaz, CapCut, or something else?)")
                user_states[user_id] = {'type': 'waiting_for_software', 'original_question': prompt_lower}
            return
        
        # If editing help detected but NOT mentioned (regular chat context), just continue to normal chat handling
        # Don't treat it as tutorial, just normal response
        
        # Check if user is asking for an image or video
        is_image_request = any(keyword in prompt_lower for keyword in ['send me', 'get me', 'find me', 'show me', 'give me', 'image', 'png', 'jpg', 'jpeg', 'gif', 'webp', 'picture', 'photo', 'screenshot'])
        search_query = None
        if is_image_request:
            # Try to extract what they want
            if 'send me' in prompt_lower or 'get me' in prompt_lower or 'find me' in prompt_lower or 'show me' in prompt_lower or 'give me' in prompt_lower:
                parts = message.content.split()
                for i, part in enumerate(parts):
                    if part.lower() in ['send', 'get', 'find', 'show', 'give']:
                        if i+1 < len(parts) and parts[i+1].lower() == 'me':
                            search_query = ' '.join(parts[i+2:]) if i+2 < len(parts) else None
                            break
        
        try:
            # Get clean prompt (remove mention if exists)
            prompt = message.content.replace(f'<@{bot.user.id}>', '').strip()
            
            # Check for attachments (images or videos)
            image_bytes = None
            video_bytes = None
            is_video = False
            video_filename = None
            
            if message.attachments:
                for attachment in message.attachments:
                    filename_lower = attachment.filename.lower()
                    
                    # Check if attachment is an image
                    if any(filename_lower.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.webp']):
                        logger.info(f'Downloading image from {message.author.name}: {attachment.filename}')
                        image_bytes = await download_image(attachment.url)
                        if image_bytes:
                            break
                    
                    # Check if attachment is a video (but reject .mov files)
                    elif any(filename_lower.endswith(ext) for ext in ['.mp4', '.avi', '.mkv', '.webm', '.flv', '.wmv', '.m4v']):
                        logger.info(f'Downloading video from {message.author.name}: {attachment.filename}')
                        video_bytes, error = await download_video(attachment.url, attachment.filename)
                        if error:
                            await message.reply(f"❌ {error}")
                            return
                        if video_bytes:
                            is_video = True
                            video_filename = attachment.filename
                            break
                    
                    # Reject .mov files
                    elif filename_lower.endswith('.mov'):
                        await message.reply("❌ MOV files are not supported. Please use MP4, AVI, MKV, WebM, or other video formats.")
                        return
            
            # If there's content to process
            if not image_bytes and not video_bytes and not prompt:
                return
            
            # Show typing indicator while processing
            async with message.channel.typing():
                if is_image_request and search_query and not image_bytes and not video_bytes:
                    # Search and download image
                    image_path = await search_and_download_image(search_query, limit=1)
                    if image_path and os.path.exists(image_path):
                        try:
                            # Send the image to user's DMs
                            await message.author.send(f"Here's a **{search_query}** for you:", 
                                                    file=discord.File(image_path))
                            if message.guild:
                                await message.channel.send(f"{message.author.mention}, I've sent you the image in your DMs!")
                            logger.info(f'Sent image for "{search_query}" to {message.author.name}')
                            return
                        except Exception as e:
                            logger.error(f"Error sending image: {str(e)}")
                            await message.reply(f"❌ Couldn't send the image. Error: {str(e)}")
                            return
                    else:
                        await message.reply(f"❌ Couldn't find an image for '{search_query}'. Try a different search term!")
                        return
                elif is_video and video_bytes:
                    # Analyze video
                    response = await analyze_video(video_bytes, video_filename, message.author.id)
                elif image_bytes:
                    # Analyze image
                    response = get_gemini_response(prompt, message.author.id, username=message.author.name, image_bytes=image_bytes)
                else:
                    # Regular text response
                    response = get_gemini_response(prompt, message.author.id, username=message.author.name, image_bytes=None)
            
            # Split response if it's too long for Discord (2000 char limit)
            if len(response) > 1900:
                # Split into chunks
                chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
                for chunk in chunks:
                    if is_dm:
                        await message.channel.send(chunk)
                    else:
                        await message.reply(chunk)
            else:
                if is_dm:
                    await message.channel.send(response)
                else:
                    await message.reply(response)

            logger.info(f'Responded to {message.author.name}' + (' (video analysis)' if is_video else ' (image analysis)' if image_bytes else ''))
            
            # Log the chat activity
            response_type = "Video Analysis" if is_video else "Image Analysis" if image_bytes else "Chat Response"
            server_name = message.guild.name if message.guild else "DM"
            await log_activity(
                f"💬 {response_type}",
                f"Responded to **{message.author.name}**",
                color=0x5865F2,
                fields={
                    "User": message.author.name,
                    "Server": server_name,
                    "Channel": message.channel.name if hasattr(message.channel, 'name') else "DM",
                    "Query": prompt[:100] + "..." if len(prompt) > 100 else prompt if prompt else "N/A"
                }
            )

        except Exception as e:
            logger.error(f'Error in chat response: {str(e)}')

@bot.command(name="help")
async def help_command(ctx):
    """Show all available commands"""
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !help command')

    help_parts = [
        """**═══════════════════════════════════════════════════════════**
**🤖 EDITING HELPER BOT - COMPLETE COMMAND LIST**
**═══════════════════════════════════════════════════════════**

**📋 BASIC COMMANDS:**
• !help - Shows this list of commands
• !files - Lists all available files that can be requested
• !presets - Lists color correction presets
• !software_list - Lists all software-related commands

**💻 SOFTWARE COMMANDS:**
• !aecrack - Adobe After Effects crack information
• !pscrack - Adobe Photoshop crack information
• !mecrack - Media Encoder crack information
• !prcrack - Adobe Premiere Pro crack information
• !topazcrack - Topaz Suite crack information

**📝 AI EDITING TOOLS (18+ Commands):**
• !ask - Ask questions about video editing
• !explain - Get detailed explanations
• !improve - Get improvement suggestions
• !rewrite - Rewrite content better
• !summarize - Summarize long text
• !analyze - Analyze content
• !idea - Get creative ideas
• !define - Define terms
• !fix - Fix grammar & spelling
• !shorten - Make text shorter
• !expand - Make text longer
• !caption - Generate captions
• !script - Write scripts
• !format - Format text professionally
• !title - Generate titles
• !translate - Translate to any language
• !paragraph - Format into paragraphs""",
        
        """**🛠️ UTILITY TOOLS:**
• !remind <time> <text> - Set reminders (e.g., !remind 5m Buy milk)
• !note <text> - Save notes (or !note to view all)
• !timer <time> - Start a countdown timer
• !convert <mode> <text> - Convert text (upper/lower/title/reverse/morse)
• !emoji <text> - Get emoji suggestions
• !calculate <math> - Do quick math (e.g., !calculate 50+25*2)
• !weather <city> - Get weather for any location
• !profile [@user] - Show user profile information
• !serverinfo - Display server statistics

**🎨 CREATIVE TOOLS:**
• !creative <topic> - Generate creative ideas & prompts
• !story <prompt> - Create short stories instantly
• !quote <style> - Get inspirational or funny quotes
• !brainstorm <topic> - Brainstorm ideas with AI
• !design <project> - Suggest design themes & layouts
• !name <category> - Generate usernames, bot names, brand names
• !aesthetic <style> - Suggest color palettes & aesthetics
• !topics <context> - Give conversation or content topics
• !motivate - Send motivational messages""",
        
        """**📂 FILE COMMANDS:**
Type !filename (e.g., !foggy_cc) to receive files in your DMs
Example: !foggy_cc or !foggy cc will send the foggy_cc.ffx file

**🎯 SMART FEATURES:**
✓ Auto spam detection & moderation
✓ Multi-step tutorial workflow
✓ Image generation with Pollinations AI
✓ Image search capabilities
✓ Server security & raid detection
✓ User account age verification
✓ Automatic invite link blocking
✓ Webhook monitoring

**═══════════════════════════════════════════════════════════**"""
    ]

    try:
        # Send help in multiple messages (Discord 2000 char limit)
        for part in help_parts:
            await ctx.author.send(part)
        logger.info(f'Sent help list to {ctx.author.name}')
    except discord.Forbidden:
        pass
    except Exception as e:
        logger.error(f'Error in help command: {str(e)}')

@bot.command(name="files")
async def list_files_command(ctx):
    """
    Lists all available files that can be requested.
    Usage: !files
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !files command in {ctx.guild.name if ctx.guild else "DM"}')

    # Get list of files in the files directory
    files_dir = "files"
    if not os.path.exists(files_dir):
        await ctx.send("No files available currently.")
        return

    # Get all files in the directory
    all_files = []
    for file in glob.glob(f"{files_dir}/*"):
        if os.path.isfile(file):
            filename = os.path.basename(file)
            command_name = os.path.splitext(filename)[0]
            all_files.append(f"!{command_name} - {filename}")

    if not all_files:
        await ctx.send("No files available currently.")
        return

    # Format the file list
    all_files.sort()  # Sort alphabetically
    file_list = "\n".join(all_files)
    response = f"**Available Files:**\n```\n{file_list}\n```\nType the command (e.g., !foggy_cc) to receive the file in your DMs."

    try:
        # Send the list to the user's DMs
        await ctx.author.send(response)
        logger.info(f'Sent file list to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the list of available files in your DMs!")

    except discord.Forbidden:
        # If DMs are closed, send in the channel
        logger.warning(f'Could not send file list to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Here's the list of files:")
        await ctx.send(response)

    except Exception as e:
        logger.error(f'Error sending file list to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the file list.")

@bot.command(name="software_list")
async def software_list_command(ctx):
    """
    Lists all available software-related commands.
    Usage: !software_list
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !software_list command in {ctx.guild.name if ctx.guild else "DM"}')

    # Prepare the software command list
    software_list = [
        "**Software Commands:**",
        "!aecrack - Adobe After Effects crack information",
        "!pscrack - Adobe Photoshop crack information",
        "!mecrack - Media Encoder crack information",
        "!prcrack - Adobe Premiere Pro crack information",
        "!topazcrack - Topaz Suite crack information"
    ]

    # Format the final response
    response = "\n".join(software_list)

    try:
        # Send the list to the user's DMs
        await ctx.author.send(response)
        logger.info(f'Sent software list to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the list of software commands in your DMs!")

    except discord.Forbidden:
        # If DMs are closed, send in the channel
        logger.warning(f'Could not send software list to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Here's the list of software commands:")
        await ctx.send(response)

    except Exception as e:
        logger.error(f'Error sending software list to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the software list.")

@bot.command(name="presets")
async def presets_command(ctx):
    """
    Lists all available .ffx presets (color correction files).
    Usage: !presets
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !presets command in {ctx.guild.name if ctx.guild else "DM"}')

    # Get list of .ffx files in the files directory
    files_dir = "files"
    if not os.path.exists(files_dir):
        await ctx.send("No presets available currently.")
        return

    # Get all .ffx files in the directory
    ffx_files = []
    for file in glob.glob(f"{files_dir}/*.ffx"):
        if os.path.isfile(file):
            filename = os.path.basename(file)
            command_name = os.path.splitext(filename)[0]
            ffx_files.append(f"!{command_name} - {filename}")

    if not ffx_files:
        await ctx.send("No presets available currently.")
        return

    # Format the file list
    ffx_files.sort()  # Sort alphabetically
    file_list = "\n".join(ffx_files)
    response = f"**Available Color Correction Presets:**\n```\n{file_list}\n```\nType the command (e.g., !foggy_cc) to receive the preset in your DMs."

    try:
        # Send the list to the user's DMs
        await ctx.author.send(response)
        logger.info(f'Sent preset list to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the list of available presets in your DMs!")

    except discord.Forbidden:
        # If DMs are closed, send in the channel
        logger.warning(f'Could not send preset list to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Here's the list of presets:")
        await ctx.send(response)

    except Exception as e:
        logger.error(f'Error sending preset list to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the preset list.")

@bot.command(name="aecrack")
async def aecrack_command(ctx):
    """
    Sends information about Adobe After Effects crack.
    Usage: !aecrack
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !aecrack command in {ctx.guild.name if ctx.guild else "DM"}')

    # Actual Adobe After Effects crack information
    response = """**Adobe After Effects Crack Links**

# [2025 (v25.1)](<https://notabin.com/?fb7cab495eecf221#FiT2GfKpydCLgzWGKUv8jHVdMB8dn2YqDoi6E17qEa7F>)

# [2024 (v24.6.2)](<https://paste.to/?d06e0c5b7a227356#DoWsXVNiFCvYpxZdvE793tu8jnxmq66bxw3k4WpuLA63>)

# [2022 (v22.6)](<https://paste.to/?2de1e37edd288c59#HKgmUNUEfKG4z3ZrQ6pGxcqiroeHcZqS7AxuEqScHv2t>)

# [2020 (v17.7)](<https://paste.to/?4c06b2d0730e4b4e#BwAWrNgK633RtYnzGB25us53Z6pMN4QzocRY9MNoFCeU>)

**Installation:**

_1) Mount the ISO._
_2) Run autoplay.exe._

**Note:**

_Cloud-based functionality will not work for this crack. You must ensure to block internet connections to the app in case of unlicensed errors._"""

    try:
        # Send DM to the user
        await ctx.author.send(response)
        logger.info(f'Successfully sent AE crack info to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the After Effects crack information in your DMs!")

    except discord.Forbidden:
        logger.warning(f'Could not send AE crack info to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please check your privacy settings.")

    except Exception as e:
        logger.error(f'Error sending AE crack info to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the information.")

@bot.command(name="pscrack")
async def pscrack_command(ctx):
    """
    Sends information about Adobe Photoshop crack.
    Usage: !pscrack
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !pscrack command in {ctx.guild.name if ctx.guild else "DM"}')

    # Actual Adobe Photoshop crack information
    response = """**Adobe Photoshop Crack Information**

# [PHOTOSHOP 2025](<https://hidan.sh/tfbctrj9jn54i>) 

# INSTALLATION

1) Mount the ISO.
2) Run autoplay.exe.

**Note:**

Cloud-based functionality will not work for this crack. You must ensure to block internet connections to the app in case of unlicensed errors.

Ensure to use uBlock Origin. The file should be the size and format stated."""

    try:
        # Send DM to the user
        await ctx.author.send(response)
        logger.info(f'Successfully sent PS crack info to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the Photoshop crack information in your DMs!")

    except discord.Forbidden:
        logger.warning(f'Could not send PS crack info to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please check your privacy settings.")

    except Exception as e:
        logger.error(f'Error sending PS crack info to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the information.")

@bot.command(name="mecrack")
async def mecrack_command(ctx):
    """
    Sends information about Media Encoder crack.
    Usage: !mecrack
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !mecrack command in {ctx.guild.name if ctx.guild else "DM"}')

    # Actual Media Encoder crack information
    response = """**Media Encoder Crack Information**

# [MEDIA ENCODER 2025](<https://hidan.sh/s6ljnz5eizd2>) 

# Installation:

1) Mount the ISO.
2) Run autoplay.exe.

# Note:

Do not utilise H.264 or H.265 through ME.

Cloud-based functionality will not work for this crack. You must ensure to block internet connections to the app in case of unlicensed errors.

Ensure to use uBlock Origin. The file should be the size and format stated."""

    try:
        # Send DM to the user
        await ctx.author.send(response)
        logger.info(f'Successfully sent ME crack info to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the Media Encoder crack information in your DMs!")

    except discord.Forbidden:
        logger.warning(f'Could not send ME crack info to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please check your privacy settings.")

    except Exception as e:
        logger.error(f'Error sending ME crack info to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the information.")

@bot.command(name="prcrack")
async def prcrack_command(ctx):
    """
    Sends information about Adobe Premiere Pro crack.
    Usage: !prcrack
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !prcrack command in {ctx.guild.name if ctx.guild else "DM"}')

    # Actual Premiere Pro crack information
    response = """**Adobe Premiere Pro Crack Information**

# [PREMIERE PRO 2025](<https://hidan.sh/rlr5vmxc2kbm>) 

# Installation:

1) Mount the ISO.
2) Run autoplay.exe.

# Note:

Cloud-based functionality will not work for this crack. You must ensure to block internet connections to the app in case of unlicensed errors.

Ensure to use uBlock Origin. The file should be the size and format stated."""

    try:
        # Send DM to the user
        await ctx.author.send(response)
        logger.info(f'Successfully sent PR crack info to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the Premiere Pro crack information in your DMs!")

    except discord.Forbidden:
        logger.warning(f'Could not send PR crack info to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please check your privacy settings.")

    except Exception as e:
        logger.error(f'Error sending PR crack info to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the information.")

@bot.command(name="topazcrack")
async def topazcrack_command(ctx):
    """
    Sends information about Topaz Suite crack.
    Usage: !topazcrack
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !topazcrack command in {ctx.guild.name if ctx.guild else "DM"}')

    # Actual Topaz crack information
    response = """**Topaz Video AI Crack Information**

# [TOPAZ 6.0.3 PRO](<https://tinyurl.com/Topaz-video-ai-6)

# INSTALLATION
1) Replace rlm1611.dll in C:\\Program Files\\Topaz Labs LLC\\Topaz Video AI\\.

2) Copy license.lic to C:\\ProgramData\\Topaz Labs LLC\\Topaz Video AI\\models.

**Note:**

Archive says 6.0.3, but it will still work. The same could be true for later versions.
Starlight won't work as it's credit-based.

Ensure to use uBlock Origin. The file should be the size and format stated."""

    try:
        # Send DM to the user
        await ctx.author.send(response)
        logger.info(f'Successfully sent Topaz crack info to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the Topaz Suite crack information in your DMs!")

    except discord.Forbidden:
        logger.warning(f'Could not send Topaz crack info to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please check your privacy settings.")

    except Exception as e:
        logger.error(f'Error sending Topaz crack info to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the information.")

@bot.command(name="hi")
async def hi_command(ctx):
    """
    Alternative command that also sends 'HI' to the user's DMs.
    Usage: !hi
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !hi command in {ctx.guild.name if ctx.guild else "DM"}')

    try:
        # Send DM to the user
        await ctx.author.send("HI")
        logger.info(f'Successfully sent DM to {ctx.author.name}')

        # Optional confirmation in the channel where command was used
        if ctx.guild:  # Only if command was used in a server, not in DMs
            await ctx.send(f"{ctx.author.mention}, I've sent you a DM!")

    except discord.Forbidden:
        # Handle the case where user has DMs closed or blocked the bot
        logger.warning(f'Could not send DM to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Please check your privacy settings.")

    except Exception as e:
        # Handle other exceptions
        logger.error(f'Error sending DM to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you a DM.")

@bot.command(name="ask")
async def ask_command(ctx, *, question=None):
    """Get deep, detailed answers to any question. Usage: !ask What is quantum computing?"""
    if not question:
        await ctx.send("📝 Please provide a question! Usage: !ask [your question]")
        return
    async with ctx.typing():
        prompt = f"Provide a comprehensive, detailed answer to this question: {question}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="explain")
async def explain_command(ctx, *, topic=None):
    """Explain any topic clearly in simple language. Usage: !explain machine learning"""
    if not topic:
        await ctx.send("📖 Please provide a topic! Usage: !explain [topic]")
        return
    async with ctx.typing():
        prompt = f"Explain '{topic}' in simple, easy-to-understand language. Make it clear for beginners."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="improve")
async def improve_command(ctx, *, text=None):
    """Enhance any message, paragraph, or script. Usage: !improve your text here"""
    if not text:
        await ctx.send("✏️ Please provide text to improve! Usage: !improve [text]")
        return
    async with ctx.typing():
        prompt = f"Enhance and improve this text. Make it better, clearer, more engaging, and more professional: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="rewrite")
async def rewrite_command(ctx, *, text=None):
    """Rewrite text in different tones or styles. Usage: !rewrite make this more formal"""
    if not text:
        await ctx.send("📝 Please provide text to rewrite! Usage: !rewrite [text]")
        return
    async with ctx.typing():
        prompt = f"Rewrite this text in a more creative, engaging, and professional way: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="summarize")
async def summarize_command(ctx, *, text=None):
    """Convert long text into short, clear summaries. Usage: !summarize [your long text]"""
    if not text:
        await ctx.send("📄 Please provide text to summarize! Usage: !summarize [text]")
        return
    async with ctx.typing():
        prompt = f"Summarize this text into a short, clear summary that captures all key points: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="analyze")
async def analyze_command(ctx, *, content=None):
    """Analyze content and give insights or breakdowns. Usage: !analyze this text or concept"""
    if not content:
        await ctx.send("🔍 Please provide content to analyze! Usage: !analyze [content]")
        return
    async with ctx.typing():
        prompt = f"Analyze this content deeply and provide detailed insights, breakdowns, and observations: {content}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="idea")
async def idea_command(ctx, *, topic=None):
    """Generate creative ideas for videos, designs, content, or posts. Usage: !idea gaming video ideas"""
    if not topic:
        await ctx.send("💡 Please provide a topic! Usage: !idea [topic for ideas]")
        return
    async with ctx.typing():
        prompt = f"Generate 5 creative, unique ideas for: {topic}. Make them specific, actionable, and interesting."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="define")
async def define_command(ctx, *, word=None):
    """Get definitions for any word or concept. Usage: !define algorithm"""
    if not word:
        await ctx.send("📚 Please provide a word to define! Usage: !define [word]")
        return
    async with ctx.typing():
        prompt = f"Provide a clear, concise definition of '{word}' with an example of how it's used."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="helper")
async def helper_command(ctx, *, query=None):
    """All-in-one AI command for multi-purpose assistance. Usage: !helper anything you need help with"""
    if not query:
        await ctx.send("🤖 Please provide a request! Usage: !helper [your question/request]")
        return
    async with ctx.typing():
        prompt = f"Help with this request in the most useful way possible: {query}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        chunks = [response[i:i+1900] for i in range(0, len(response), 1900)]
        for chunk in chunks:
            await ctx.send(chunk)

@bot.command(name="fix")
async def fix_command(ctx, *, text=None):
    """Correct grammar, spelling, and mistakes. Usage: !fix your text here"""
    if not text:
        await ctx.send("✍️ Please provide text to fix! Usage: !fix [text]")
        return
    async with ctx.typing():
        prompt = f"Correct all grammar, spelling, and grammatical mistakes in this text. Return only the corrected text: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="shorten")
async def shorten_command(ctx, *, text=None):
    """Make text shorter but keep the meaning. Usage: !shorten your long text here"""
    if not text:
        await ctx.send("📉 Please provide text to shorten! Usage: !shorten [text]")
        return
    async with ctx.typing():
        prompt = f"Make this text shorter and more concise while keeping all the important meaning: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="expand")
async def expand_command(ctx, *, text=None):
    """Add detail, depth, and clarity to text. Usage: !expand your text here"""
    if not text:
        await ctx.send("📈 Please provide text to expand! Usage: !expand [text]")
        return
    async with ctx.typing():
        prompt = f"Expand this text by adding more detail, depth, and clarity. Make it richer and more comprehensive: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="caption")
async def caption_command(ctx, *, topic=None):
    """Create captions for reels, videos, and posts. Usage: !caption gaming video about speedrun"""
    if not topic:
        await ctx.send("📸 Please provide a topic! Usage: !caption [what the content is about]")
        return
    async with ctx.typing():
        prompt = f"Create 3 engaging, catchy captions for a reel/video/post about: {topic}. Make them fun, relevant, and include relevant hashtags."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="script")
async def script_command(ctx, *, idea=None):
    """Generate short scripts or dialogues. Usage: !script two friends meeting after years"""
    if not idea:
        await ctx.send("🎬 Please provide a script idea! Usage: !script [scene idea]")
        return
    async with ctx.typing():
        prompt = f"Write a short, engaging script or dialogue for: {idea}. Make it natural, interesting, and ready to use."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="format")
async def format_command(ctx, *, text=None):
    """Format text into clean structure or bullet points. Usage: !format your messy text here"""
    if not text:
        await ctx.send("📋 Please provide text to format! Usage: !format [text]")
        return
    async with ctx.typing():
        prompt = f"Format this text into a clean, well-structured format using bullet points or sections as appropriate: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="title")
async def title_command(ctx, *, content=None):
    """Generate attractive titles for any content. Usage: !title about a cat adventure"""
    if not content:
        await ctx.send("⭐ Please provide content! Usage: !title [describe your content]")
        return
    async with ctx.typing():
        prompt = f"Generate 5 creative, catchy, and attractive title options for: {content}. Make them engaging and click-worthy."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="translate")
async def translate_command(ctx, *, text=None):
    """Translate text into any language. Usage: !translate hello world to spanish"""
    if not text:
        await ctx.send("🌍 Please provide text and language! Usage: !translate [text] to [language]")
        return
    async with ctx.typing():
        prompt = f"Translate this text as requested: {text}. Provide only the translation."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.command(name="paragraph")
async def paragraph_command(ctx, *, text=None):
    """Turn messy text into a clean, structured paragraph. Usage: !paragraph your messy notes here"""
    if not text:
        await ctx.send("📝 Please provide text to format! Usage: !paragraph [text]")
        return
    async with ctx.typing():
        prompt = f"Turn this messy text into a clean, well-structured, professional paragraph: {text}"
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(response)

@bot.listen('on_message')
async def file_command_handler(message):
    """
    Listens for messages that start with ! and checks if they match any filenames.
    If a match is found, sends the file to the user's DMs.
    """
    # Ignore messages from the bot itself
    if message.author == bot.user:
        return

    # Check if message starts with ! and is longer than 1 character
    if not message.content.startswith('!') or len(message.content) <= 1:
        return

    # Extract the filename without the ! and convert to lowercase for case-insensitive matching
    requested_file = message.content[1:]
    requested_file_lower = requested_file.lower()
    
    # Extract just the first word to check against known commands
    first_word = requested_file_lower.split()[0] if requested_file_lower else ""
    
    # Skip for known commands to avoid duplicate messages (case-insensitive check)
    if first_word in ["help", "hi", "files", "software_list", "presets", 
                      "aecrack", "pscrack", "mecrack", "prcrack", "topazcrack", 
                      "ban", "mute", "timeout", "unmute",
                      "ask", "explain", "improve", "rewrite", "summarize", "analyze", "idea", "define", "helper",
                      "fix", "shorten", "expand", "caption", "script", "format", "title", "translate", "paragraph",
                      "remind", "note", "timer", "convert", "emoji", "calculate", "weather", "profile", "serverinfo",
                      "creative", "story", "quote", "brainstorm", "design", "name", "aesthetic", "topics", "motivate"]:
        return
    
    logger.info(f'User {message.author.name} (ID: {message.author.id}) requested file: {requested_file}')

    # Check if the file exists in the files directory - handle both with and without spaces and case sensitivity
    file_paths = [
        f"files/{requested_file}",  # Original format
        f"files/{requested_file.replace('_', ' ')}",  # Replace underscores with spaces
        f"files/{requested_file.replace(' ', '_')}"   # Replace spaces with underscores
    ]

    # Also add lowercase versions for case-insensitive matching
    file_paths_lower = [
        f"files/{requested_file_lower}",  # Lowercase original format
        f"files/{requested_file_lower.replace('_', ' ')}",  # Lowercase with spaces
        f"files/{requested_file_lower.replace(' ', '_')}"   # Lowercase with underscores
    ]

    # Combine all possible paths
    file_paths.extend(file_paths_lower)
    file_extensions = ["", ".txt", ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".mp3", ".mp4", ".zip", ".ffx"]

    found_file = None
    for base_path in file_paths:
        for ext in file_extensions:
            potential_path = f"{base_path}{ext}"
            if os.path.exists(potential_path) and os.path.isfile(potential_path):
                found_file = potential_path
                break
        if found_file:
            break

    # If file was found, send it to the user
    if found_file:
        try:
            # Send file to the user's DMs
            await message.author.send(f"Here's your requested file: `{requested_file}`", 
                                    file=discord.File(found_file))
            logger.info(f'Successfully sent file {found_file} to {message.author.name}')

            # Send confirmation in the channel
            if message.guild:  # Only if command was used in a server
                await message.channel.send(f"{message.author.mention}, I've sent your requested file to your DMs!")

        except discord.Forbidden:
            # Handle the case where user has DMs closed
            logger.warning(f'Could not send file to {message.author.name} - DMs may be closed')
            await message.channel.send(f"{message.author.mention}, I couldn't send you the file. Please check your privacy settings.")

        except Exception as e:
            # Handle other exceptions
            logger.error(f'Error sending file to {message.author.name}: {str(e)}')
            await message.channel.send(f"{message.author.mention}, an error occurred while trying to send you the file.")

    # If file was not found, try to suggest a command
    else:
        # Define the known commands for suggestions - including common misspellings and variations
        known_commands = {
            # software_list variations
            "software": "software_list",
            "softwarelist": "software_list",
            "software_list": "software_list",
            "softlist": "software_list",
            "soft": "software_list",
            "softwares": "software_list",
            "software list": "software_list",
            "softwre": "software_list",
            "softwear": "software_list",
            "sotware": "software_list",

            # aecrack variations
            "aecrack": "aecrack",
            "aftereffects": "aecrack",
            "after_effects": "aecrack",
            "after effects": "aecrack",
            "aftereffect": "aecrack",
            "ae": "aecrack",
            "acrack": "aecrack",
            "aecrck": "aecrack",
            "aecrk": "aecrack",
            "after effect": "aecrack",
            "aftereffects crack": "aecrack",
            "ae crack": "aecrack",
            "aec": "aecrack",

            # pscrack variations
            "pscrack": "pscrack",
            "photoshop": "pscrack",
            "photoshop crack": "pscrack",
            "ps": "pscrack",
            "ps crack": "pscrack",
            "photo shop": "pscrack",
            "photo": "pscrack",
            "pscrk": "pscrack",
            "psc": "pscrack",
            "photshop": "pscrack",
            "photoshp": "pscrack",

            # mecrack variations
            "mecrack": "mecrack",
            "mediaencoder": "mecrack",
            "media_encoder": "mecrack",
            "media encoder": "mecrack",
            "me": "mecrack",
            "me crack": "mecrack",
            "media crack": "mecrack",
            "encoder": "mecrack",
            "mecrk": "mecrack",
            "mec": "mecrack",
            "media encoder crack": "mecrack",

            # prcrack variations
            "prcrack": "prcrack",
            "premiere": "prcrack",
            "premierepro": "prcrack",
            "premiere_pro": "prcrack",
            "premiere pro": "prcrack",
            "pr": "prcrack",
            "pr crack": "prcrack",
            "premire": "prcrack",
            "premiere crack": "prcrack",
            "premier": "prcrack",
            "premire pro": "prcrack",
            "prc": "prcrack",
            "primier": "prcrack",
            "premier pro": "prcrack",

            # topazcrack variations
            "topazcrack": "topazcrack",
            "topaz": "topazcrack",
            "topaz crack": "topazcrack",
            "topaz ai": "topazcrack",
            "topazai": "topazcrack",
            "tpz": "topazcrack",
            "topas": "topazcrack",
            "topazvideo": "topazcrack",
            "topaz video": "topazcrack",
            "topz": "topazcrack",
            "topazai crack": "topazcrack",

            # presets variations
            "preset": "presets",
            "presets": "presets",
            "colorpresets": "presets",
            "color_presets": "presets",
            "color presets": "presets",
            "cc": "presets",
            "cc presets": "presets",
            "color correction": "presets",
            "preset list": "presets",
            "colorcorrection": "presets",
            "preest": "presets",
            "prest": "presets",
            "prset": "presets",
            "presetes": "presets",
            "cc files": "presets",
            "cc file": "presets",
            "ffx": "presets",
            "ffx files": "presets",

            # files variations
            "file": "files",
            "files": "files",
            "filess": "files",
            "filee": "files",
            "fies": "files",
            "fils": "files",
            "file list": "files",
            "files list": "files",
            "all files": "files",

            # help variations
            "help": "help",
            "hlp": "help",
            "halp": "help",
            "hellp": "help",
            "hel": "help",

            # hi variations
            "hi": "hi",
            "hello": "hi",
            "hey": "hi",
            "hii": "hi",
            "helo": "hi",

            # list variations
            "list": "list",
            "lst": "list",
            "lis": "list",
            "lists": "list",
            "command": "list",
            "commands": "list",
            "command list": "list",
            "cmd": "list",
            "cmds": "list",
            "all commands": "list"
        }

        # Check if the requested command matches exactly, or with spaces, underscores or hyphens removed
        found_match = False
        suggested_command = None

        # First try exact match
        if requested_file_lower in known_commands:
            suggested_command = known_commands[requested_file_lower]
            found_match = True

        # Try without spaces, underscores, or hyphens if no exact match
        if not found_match:
            # Remove spaces, underscores, hyphens and check again
            normalized_request = requested_file_lower.replace(' ', '').replace('_', '').replace('-', '')
            for cmd, suggestion in known_commands.items():
                normalized_cmd = cmd.replace(' ', '').replace('_', '').replace('-', '')
                if normalized_request == normalized_cmd:
                    suggested_command = suggestion
                    found_match = True
                    break

        # Try more flexible matching for typos (check if command is contained in the request)
        if not found_match:
            for cmd, suggestion in known_commands.items():
                # For short commands (3 chars or less), only check exact matches to avoid false positives
                if len(cmd) <= 3 and cmd != requested_file_lower:
                    continue

                # For longer commands, check if the command is a substring or the request is a substring
                if (len(cmd) > 3 and (cmd in requested_file_lower or 
                   (len(requested_file_lower) > 3 and requested_file_lower in cmd))):
                    suggested_command = suggestion
                    found_match = True
                    break

        if found_match and suggested_command is not None:
            await message.channel.send(f"{message.author.mention}, did you mean to use `!{suggested_command}`? Try typing that instead.")
            logger.info(f'Suggested !{suggested_command} instead of !{requested_file}')
        else:
            await message.channel.send(f"{message.author.mention}, I couldn't find a file named `{requested_file}`.")
            logger.warning(f'File not found: {requested_file}')

@bot.command(name="ban")
async def ban_command(ctx, member: discord.Member = None):
    """Ban a user from the server - Server admin/inviter can use this."""
    # Check if user is server admin (inviter, owner, or has admin perms)
    if not is_server_admin(ctx.author, ctx.guild):
        admin_name = get_server_admin_name(ctx.guild)
        await ctx.send(f"{ctx.author.mention}, only **{admin_name}** (the person who added me) or server admins can use this command.")
        return
    
    if not member:
        await ctx.send("Who do you want me to ban? Mention someone or provide their username.")
        return
    
    try:
        # Check if bot has permission to ban
        if not ctx.guild.me.guild_permissions.ban_members:
            await ctx.send("❌ I don't have permission to ban members!")
            return
        
        # Check if bot's role is higher than target member's role
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(f"❌ I can't ban {member.name} because their role is equal to or higher than mine!")
            logger.warning(f"Can't ban {member.name} - role too high")
            return
        
        # Don't allow banning BMR or the server admin
        if 'bmr' in member.name.lower() or is_server_admin(member, ctx.guild):
            await ctx.send("❌ I can't ban this user!")
            return
        
        # Send DM to user before banning
        try:
            await member.send(f"You have been **BANNED** from {ctx.guild.name} by {ctx.author.name}.")
        except:
            pass  # User may have DMs disabled
        
        # Ban the user
        await ctx.guild.ban(member, reason=f"Banned by {ctx.author.name}")
        await ctx.send(f"✓ {member.name} has been **BANNED** from the server. Goodbye! 🚫")
        logger.info(f"{ctx.author.name} banned {member.name}")
        
        # Log the activity
        await log_activity(
            "🔨 User Banned",
            f"**{member.name}** was banned from **{ctx.guild.name}**",
            color=0xFF0000,
            fields={
                "Banned By": ctx.author.name,
                "Server": ctx.guild.name,
                "User": f"{member.name}#{member.discriminator}"
            }
        )
    except discord.Forbidden:
        await ctx.send(f"❌ I don't have permission to ban {member.name}!")
        logger.error(f"Permission denied when trying to ban {member.name}")
    except Exception as e:
        logger.error(f"Error banning user: {str(e)}")
        await ctx.send(f"❌ Error banning user: {str(e)}")

@bot.command(name="timeout")
async def timeout_command(ctx, member: discord.Member = None, duration: str = None):
    """Timeout a user for a specified duration - Server admin/inviter can use this."""
    # Check if user is server admin (inviter, owner, or has admin perms)
    if not is_server_admin(ctx.author, ctx.guild):
        admin_name = get_server_admin_name(ctx.guild)
        await ctx.send(f"{ctx.author.mention}, only **{admin_name}** (the person who added me) or server admins can use this command.")
        return
    
    if not member:
        await ctx.send("Who do you want me to timeout? Mention someone or provide their username.")
        return
    
    if not duration:
        await ctx.send("How long should I timeout them for? (e.g., 1h, 24h, 1d, 30m)")
        return
    
    try:
        # Parse duration
        duration_lower = duration.lower().strip()
        timeout_seconds = 0
        
        if 'h' in duration_lower:
            hours = int(duration_lower.replace('h', '').strip())
            timeout_seconds = hours * 3600
        elif 'd' in duration_lower:
            days = int(duration_lower.replace('d', '').strip())
            timeout_seconds = days * 86400
        elif 'm' in duration_lower:
            minutes = int(duration_lower.replace('m', '').strip())
            timeout_seconds = minutes * 60
        elif 's' in duration_lower:
            seconds = int(duration_lower.replace('s', '').strip())
            timeout_seconds = seconds
        else:
            await ctx.send("Invalid duration format. Use: 1h, 24h, 1d, 30m, or 60s")
            return
        
        # Check if bot has permission to timeout
        if not ctx.guild.me.guild_permissions.moderate_members:
            await ctx.send("❌ I don't have permission to timeout members!")
            return
        
        # Check if bot's role is higher than target member's role
        if member.top_role >= ctx.guild.me.top_role:
            await ctx.send(f"❌ I can't timeout {member.name} because their role is equal to or higher than mine!")
            logger.warning(f"Can't timeout {member.name} - role too high")
            return
        
        # Don't allow timing out BMR or the server admin
        if 'bmr' in member.name.lower() or is_server_admin(member, ctx.guild):
            await ctx.send("❌ I can't timeout this user!")
            return
        
        # Send DM to user before timeout
        try:
            await member.send(f"You have been **TIMED OUT** in {ctx.guild.name} by {ctx.author.name} for {duration}.")
        except:
            pass  # User may have DMs disabled
        
        # Apply timeout
        timeout_until = datetime.now(timezone.utc) + timedelta(seconds=timeout_seconds)
        await member.timeout(timeout_until, reason=f"Timeout by {ctx.author.name}")
        await ctx.send(f"✓ {member.name} has been **TIMED OUT** for {duration}. 🔇")
        logger.info(f"{ctx.author.name} timed out {member.name} for {duration}")
        
        # Log the activity
        await log_activity(
            "🔇 User Timed Out",
            f"**{member.name}** was timed out in **{ctx.guild.name}**",
            color=0xFFA500,
            fields={
                "Timed Out By": ctx.author.name,
                "Server": ctx.guild.name,
                "Duration": duration,
                "User": f"{member.name}#{member.discriminator}"
            }
        )
    except ValueError:
        await ctx.send("Invalid duration format. Use: 1h, 24h, 1d, 30m, or 60s")
    except discord.Forbidden:
        await ctx.send(f"❌ I don't have permission to timeout {member.name}!")
        logger.error(f"Permission denied when trying to timeout {member.name}")
    except Exception as e:
        logger.error(f"Error timing out user: {str(e)}")
        await ctx.send(f"❌ Error timing out user: {str(e)}")

@bot.command(name="mute")
async def mute_command(ctx, member: discord.Member = None, duration: str = None):
    """Timeout a user (alias for timeout command) - Server admin/inviter can use this."""
    if not member or not duration:
        await ctx.send("Usage: !mute @user 24h")
        return
    await ctx.invoke(timeout_command, member=member, duration=duration)

@bot.command(name="unmute")
async def unmute_command(ctx, member: discord.Member = None):
    """Remove timeout from a user - Server admin/inviter can use this."""
    # Check if user is server admin (inviter, owner, or has admin perms)
    if not is_server_admin(ctx.author, ctx.guild):
        admin_name = get_server_admin_name(ctx.guild)
        await ctx.send(f"{ctx.author.mention}, only **{admin_name}** (the person who added me) or server admins can use this command.")
        return
    
    if not member:
        await ctx.send("Usage: !unmute @user")
        return
    
    try:
        # Check if bot has permission
        if not ctx.guild.me.guild_permissions.moderate_members:
            await ctx.send("❌ I don't have permission to remove timeouts!")
            return
        
        # Remove timeout by setting it to None
        await member.timeout(None, reason=f"Unmuted by {ctx.author.name}")
        await ctx.send(f"✓ {member.name} has been **UNMUTED**. 🔊")
        logger.info(f"{ctx.author.name} unmuted {member.name}")
        
        # Send DM to user
        try:
            await member.send(f"You have been **UNMUTED** in {ctx.guild.name} by {ctx.author.name}.")
        except:
            pass
        
        # Log the activity
        await log_activity(
            "🔊 User Unmuted",
            f"**{member.name}** was unmuted in **{ctx.guild.name}**",
            color=0x00FF00,
            fields={
                "Unmuted By": ctx.author.name,
                "Server": ctx.guild.name,
                "User": f"{member.name}#{member.discriminator}"
            }
        )
            
    except discord.Forbidden:
        await ctx.send(f"❌ I don't have permission to unmute {member.name}!")
    except Exception as e:
        logger.error(f"Error unmuting user: {str(e)}")
        await ctx.send(f"❌ Error unmuting user: {str(e)}")

# ============================================================================
# UTILITY TOOLS COMMANDS
# ============================================================================

# Storage for reminders and notes
user_reminders: Dict[int, List[Dict]] = {}
user_notes: Dict[int, List[str]] = {}

@bot.command(name="remind")
async def remind_command(ctx, time_str: str = None, *, reminder_text: str = None):
    """Set a reminder for a task. Usage: !remind 5m Don't forget the meeting"""
    if not time_str or not reminder_text:
        await ctx.send("Usage: !remind <time> <reminder text>\nExample: !remind 30m Buy groceries")
        return
    
    try:
        # Parse time (5m, 1h, 30s)
        amount = int(''.join(filter(str.isdigit, time_str)))
        unit = ''.join(filter(str.isalpha, time_str)).lower()
        
        if unit == 'm':
            delay = amount * 60
        elif unit == 'h':
            delay = amount * 3600
        elif unit == 's':
            delay = amount
        else:
            await ctx.send("❌ Use time format like: 5m, 1h, 30s")
            return
        
        user_id = ctx.author.id
        if user_id not in user_reminders:
            user_reminders[user_id] = []
        
        reminder_data = {"text": reminder_text, "time": datetime.now(timezone.utc), "delay": delay}
        user_reminders[user_id].append(reminder_data)
        
        await ctx.send(f"⏰ Reminder set for {time_str}: **{reminder_text}**")
        
        # Schedule the reminder
        await asyncio.sleep(delay)
        try:
            await ctx.author.send(f"⏰ **REMINDER**: {reminder_text}")
            logger.info(f"Sent reminder to {ctx.author.name}")
        except:
            pass
    except Exception as e:
        await ctx.send(f"❌ Error setting reminder: {str(e)}")
        logger.error(f"Reminder error: {str(e)}")

@bot.command(name="note")
async def note_command(ctx, *, note_text: str = None):
    """Save a note for later. Usage: !note Remember to update the profile"""
    if not note_text:
        user_id = ctx.author.id
        if user_id in user_notes and user_notes[user_id]:
            notes_list = "\n".join([f"• {note}" for note in user_notes[user_id]])
            await ctx.send(f"📝 **Your Notes:**\n{notes_list}")
        else:
            await ctx.send("📝 You have no saved notes. Use `!note <text>` to save one!")
        return
    
    user_id = ctx.author.id
    if user_id not in user_notes:
        user_notes[user_id] = []
    
    user_notes[user_id].append(note_text)
    await ctx.send(f"✓ Note saved! ({len(user_notes[user_id])} total notes)")

@bot.command(name="timer")
async def timer_command(ctx, time_str: str = None):
    """Start a countdown timer. Usage: !timer 5m"""
    if not time_str:
        await ctx.send("Usage: !timer <time>\nExample: !timer 5m, !timer 30s, !timer 2h")
        return
    
    try:
        amount = int(''.join(filter(str.isdigit, time_str)))
        unit = ''.join(filter(str.isalpha, time_str)).lower()
        
        if unit == 'm':
            seconds = amount * 60
            display = f"{amount}m"
        elif unit == 'h':
            seconds = amount * 3600
            display = f"{amount}h"
        elif unit == 's':
            seconds = amount
            display = f"{amount}s"
        else:
            await ctx.send("❌ Use time format like: 5m, 1h, 30s")
            return
        
        msg = await ctx.send(f"⏱️ **Timer started**: {display}")
        await asyncio.sleep(seconds)
        await msg.edit(content=f"✓ **Timer finished!** {display} has passed. {ctx.author.mention}")
    except Exception as e:
        await ctx.send(f"❌ Timer error: {str(e)}")

@bot.command(name="convert")
async def convert_command(ctx, mode: str = None, *, text: str = None):
    """Convert text format. Usage: !convert upper hello world"""
    if not mode or not text:
        await ctx.send("Usage: !convert <mode> <text>\nModes: upper, lower, title, reverse, morse")
        return
    
    mode = mode.lower()
    if mode == "upper":
        result = text.upper()
    elif mode == "lower":
        result = text.lower()
    elif mode == "title":
        result = text.title()
    elif mode == "reverse":
        result = text[::-1]
    elif mode == "morse":
        morse_dict = {' ': '/', 'a': '.-', 'b': '-...', 'c': '-.-.', 'd': '-..', 'e': '.', 'f': '..-.',
                      'g': '--.', 'h': '....', 'i': '..', 'j': '.---', 'k': '-.-', 'l': '.-..',
                      'm': '--', 'n': '-.', 'o': '---', 'p': '.--.', 'q': '--.-', 'r': '.-.',
                      's': '...', 't': '-', 'u': '..-', 'v': '...-', 'w': '.--', 'x': '-..-',
                      'y': '-.--', 'z': '--..'}
        result = ' '.join(morse_dict.get(c.lower(), c) for c in text)
    else:
        await ctx.send("❌ Unknown mode. Use: upper, lower, title, reverse, morse")
        return
    
    await ctx.send(f"✓ **{mode.title()}**: {result[:200]}")

@bot.command(name="emoji")
async def emoji_command(ctx, *, text: str = None):
    """Get emoji suggestions based on your text"""
    if not text:
        await ctx.send("Usage: !emoji happy mood")
        return
    
    try:
        prompt = f"Suggest 5 relevant emojis for: {text}. Just list the emojis separated by space."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"😊 **Emojis for '{text}'**: {response[:100]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="calculate")
async def calculate_command(ctx, *, expression: str = None):
    """Do quick math. Usage: !calculate 50+25*2"""
    if not expression:
        await ctx.send("Usage: !calculate <math expression>\nExample: !calculate 100+50/2")
        return
    
    try:
        expression = expression.replace('^', '**')
        result = eval(expression, {"__builtins__": {}}, {})
        await ctx.send(f"🧮 **Result**: {expression} = **{result}**")
    except:
        await ctx.send("❌ Invalid math expression. Use: +, -, *, /, ^(power), %, etc")

@bot.command(name="weather")
async def weather_command(ctx, *, location: str = None):
    """Get weather for any location. Usage: !weather New York"""
    if not location:
        await ctx.send("Usage: !weather <city name>\nExample: !weather London")
        return
    
    try:
        url = f"https://wttr.in/{location}?format=3"
        response = requests.get(url, timeout=5)
        if response.status_code == 200:
            await ctx.send(f"🌤️ **Weather in {location}**: {response.text}")
        else:
            await ctx.send(f"❌ Couldn't find weather for '{location}'")
    except:
        await ctx.send("❌ Weather service unavailable. Try again later!")

@bot.command(name="profile")
async def profile_command(ctx, member: discord.Member = None):
    """Show user profile information"""
    if member is None:
        member = ctx.author
    
    created = member.created_at.strftime("%B %d, %Y")
    joined = member.joined_at.strftime("%B %d, %Y") if member.joined_at else "Unknown"
    
    embed = discord.Embed(title=f"Profile - {member.name}", color=0x5865F2)
    embed.add_field(name="Username", value=f"{member.name}#{member.discriminator}", inline=False)
    embed.add_field(name="ID", value=member.id, inline=False)
    embed.add_field(name="Account Created", value=created, inline=False)
    embed.add_field(name="Server Joined", value=joined, inline=False)
    embed.add_field(name="Status", value=str(member.status).title(), inline=False)
    embed.set_thumbnail(url=member.avatar.url if member.avatar else None)
    
    await ctx.send(embed=embed)

@bot.command(name="serverinfo")
async def serverinfo_command(ctx):
    """Display server information and statistics"""
    guild = ctx.guild
    if not guild:
        await ctx.send("❌ This command only works in servers!")
        return
    
    embed = discord.Embed(title=f"Server Info - {guild.name}", color=0x5865F2)
    embed.add_field(name="Members", value=guild.member_count, inline=True)
    embed.add_field(name="Channels", value=len(guild.channels), inline=True)
    embed.add_field(name="Roles", value=len(guild.roles), inline=True)
    embed.add_field(name="Owner", value=guild.owner.mention if guild.owner else "Unknown", inline=False)
    embed.add_field(name="Created", value=guild.created_at.strftime("%B %d, %Y"), inline=False)
    embed.add_field(name="Verification Level", value=str(guild.verification_level).title(), inline=False)
    embed.set_thumbnail(url=guild.icon.url if guild.icon else None)
    
    await ctx.send(embed=embed)

# ============================================================================
# CREATIVE TOOLS COMMANDS
# ============================================================================

@bot.command(name="creative")
async def creative_command(ctx, *, topic: str = None):
    """Generate creative ideas & prompts"""
    if not topic:
        await ctx.send("Usage: !creative [topic/idea]\nExample: !creative sci-fi story")
        return
    
    try:
        prompt = f"Generate 5 creative and unique ideas, prompts, or concepts for: {topic}. Be imaginative and innovative."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"💡 **Creative Ideas for '{topic}'**:\n{response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="story")
async def story_command(ctx, *, prompt: str = None):
    """Create short stories instantly"""
    if not prompt:
        await ctx.send("Usage: !story [story prompt]\nExample: !story a mysterious door")
        return
    
    try:
        gemini_prompt = f"Write a creative short story (3-4 paragraphs) based on: {prompt}"
        response = get_gemini_response(gemini_prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"📖 **Story**: {response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="quote")
async def quote_command(ctx, style: str = None):
    """Produce inspirational or funny quotes"""
    if not style:
        await ctx.send("Usage: !quote [inspirational/funny/random]\nExample: !quote inspirational")
        return
    
    try:
        prompt = f"Generate an original {style} quote that is meaningful and memorable."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"✨ **Quote**: {response[:500]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="brainstorm")
async def brainstorm_command(ctx, *, topic: str = None):
    """Brainstorm ideas with AI"""
    if not topic:
        await ctx.send("Usage: !brainstorm [topic]\nExample: !brainstorm content ideas for youtube")
        return
    
    try:
        prompt = f"Brainstorm 8 creative and practical ideas for: {topic}. List them clearly with brief explanations."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"🧠 **Brainstorm Results**:\n{response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="design")
async def design_command(ctx, *, project: str = None):
    """Suggest design themes & creative layouts"""
    if not project:
        await ctx.send("Usage: !design [project description]\nExample: !design website for tech startup")
        return
    
    try:
        prompt = f"Suggest 5 design themes, color schemes, and layout ideas for: {project}. Be specific and modern."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"🎨 **Design Suggestions**:\n{response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="name")
async def name_command(ctx, category: str = None):
    """Generate usernames, bot names, brand names"""
    if not category:
        await ctx.send("Usage: !name [username/brand/bot]\nExample: !name gaming_username")
        return
    
    try:
        prompt = f"Generate 10 creative, catchy, and memorable {category} names. They should be unique and cool."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"✍️ **Name Ideas**:\n{response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="aesthetic")
async def aesthetic_command(ctx, style: str = None):
    """Suggest color palettes + aesthetic styles"""
    if not style:
        await ctx.send("Usage: !aesthetic [aesthetic style]\nExample: !aesthetic cyberpunk")
        return
    
    try:
        prompt = f"Suggest a complete {style} aesthetic with: color palette (hex codes), typography, mood, and design elements."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"🎭 **{style.title()} Aesthetic**:\n{response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="topics")
async def topics_command(ctx, context: str = None):
    """Give conversation or content topics"""
    if not context:
        await ctx.send("Usage: !topics [context]\nExample: !topics social media content")
        return
    
    try:
        prompt = f"Generate 10 interesting and engaging topics for: {context}. Make them relevant and trending."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"📋 **Topic Ideas**:\n{response[:1900]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

@bot.command(name="motivate")
async def motivate_command(ctx):
    """Send motivational messages"""
    try:
        prompt = "Generate a short, powerful motivational message that will inspire someone to take action today."
        response = get_gemini_response(prompt, ctx.author.id, username=ctx.author.name)
        await ctx.send(f"💪 **Motivation**: {response[:500]}")
    except Exception as e:
        await ctx.send(f"❌ Error: {str(e)}")

def run_bot():
    """Function to start the bot with the token from environment variables."""
    # Load configuration
    config = load_config()

    # Get token from environment variable
    token = config.get('DISCORD_TOKEN')

    if not token:
        logger.error("No Discord token found. Please set the DISCORD_TOKEN environment variable.")
        return

    # Run the bot
    logger.info("Starting bot...")
    bot.run(os.getenv("DISCORD_TOKEN"))

if __name__ == "__main__":
    run_bot()



    # --- GLOBAL AUTOMOD RULE CREATION FOR BADGE (SAFE) ---
    async def create_rules():
        try:
            from discord import (
                AutoModTrigger,
                AutoModRuleAction,
                AutoModRuleEventType,
                AutoModRuleTriggerType,
                AutoModRuleActionType
            )

            for g in bot.guilds:
                try:
                    # Safely fetch existing automod rules (if supported)
                    existing = []
                    try:
                        existing = await g.fetch_automod_rules()
                    except Exception:
                        existing = []

                    # Delete old rules named "AutoMod Badge Rule"
                    for rule in existing:
                        try:
                            if getattr(rule, 'name', None) == "AutoMod Badge Rule":
                                await rule.delete()
                                logger.info(f"[AutoMod] Deleted old rule in {g.name}")
                        except Exception:
                            pass

                    # Create new simple keyword trigger rule
                    trigger = AutoModTrigger(
                        type=AutoModRuleTriggerType.keyword,
                        keyword_filter=["automodtestword"]
                    )

                    action = AutoModRuleAction(
                        type=AutoModRuleActionType.block_message
                    )

                    await g.create_automod_rule(
                        name="AutoMod Badge Rule",
                        event_type=AutoModRuleEventType.message_send,
                        trigger=trigger,
                        actions=[action]
                    )

                    logger.info(f"[AutoMod] Rule created in {g.name}")

                except Exception as e:
                    logger.warning(f"[AutoMod] Failed in {g.name}: {e}")

        except Exception as e:
            logger.warning(f"[AutoMod] Fatal error: {e}")

    # Schedule the automod creation task (no indentation issues)
    try:
        bot.loop.create_task(create_rules())
    except Exception as e:
        logger.warning(f"[AutoMod] Could not schedule create_rules task: {e}")
