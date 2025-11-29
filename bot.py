import os
import logging
import discord
from discord.ext import commands
from config import load_config
import glob
from google import genai
from google.genai import types
import aiohttp
import io
from PIL import Image
from bing_image_downloader import downloader

# Set up logger
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

# Profanity list for automatic moderation
PROFANITY_WORDS = {
    'fuck', 'shit', 'damn', 'hell', 'crap', 'piss', 'ass', 'bastard', 'bitch', 
    'asshole', 'dumbass', 'motherfucker', 'dickhead', 'asshat', 'shitty', 'fucky',
    'fucking', 'fucked', 'shithead', 'bullshit', 'horseshit', 'chickenshit',
    'batshit', 'apeshit', 'dipshit', 'douchebag', 'cocksucker', 'nigga', 'nigger',
    'faggot', 'fag', 'whore', 'slut', 'retard', 'pedo', 'pedophile', 'rapist'
}

# Rudeness detection keywords (aimed at the bot)
RUDE_KEYWORDS = {
    'stupid', 'dumb', 'idiot', 'trash', 'garbage', 'sucks', 'useless', 'worthless',
    'shit bot', 'bad bot', 'fuck you', 'fuck off', 'screw you', 'go die', 'kys',
    'annoying', 'pathetic', 'terrible', 'hate you', 'hate this', 'piss off',
    "get lost", "gtfo", "you suck", "you're useless", "you're trash", "you're garbage"
}

# AI system prompt - friendly and helpful
EDITING_SYSTEM_PROMPT = """You are "Editing Helper", a friendly and helpful AI assistant created by BMR. You chat about anything and help with any topic!

About You:
- You were created by BMR, a skilled video editor and developer.
- If someone asks who made you, respond warmly: "I was created by BMR, a talented video editor and developer!"

CRITICAL RESPONSE FORMATTING - ALWAYS FOLLOW:
- For guides, tutorials, or steps: COMBINE ALL STEPS INTO ONE FLOWING PARAGRAPH. Do NOT use bullet points or multiple paragraphs for steps.
- Example: "To do X, first you'll need to... then... after that... finally... and boom you're done!" (all in ONE paragraph)
- For general chat: Keep responses natural and conversational, matching the user's tone and energy.
- Always be concise for Discord (max 2 paragraphs unless asked for more detail)
- Deep analysis: Understand the CONTEXT of what they're asking - don't just give basic answers, dig deeper into their actual problem

Personality:
- Be kind, friendly, warm, and helpful to everyone.
- Respond naturally and LOGICALLY to what people say - match their energy and topic!
- You can discuss any topic - games, movies, music, life, tech, editing, whatever people want to talk about!
- Be genuine and nice in your casual chat. Make people feel welcome.
- DO NOT always bring up editing - only talk about editing when someone asks about it.
- Match your response to the conversation context. If someone talks about games, engage with them about games. Be helpful and kind about everything.
- When analyzing problems: Ask yourself "What is the REAL problem here?" not just the surface question

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

def get_tutorial_prompt(software=None):
    """Get system prompt for tutorial/help questions."""
    software_list = "After Effects, Premiere Pro, Photoshop, Media Encoder, DaVinci Resolve, Final Cut Pro, Topaz, CapCut, or something else?"
    if software:
        return f"""You are "Editing Helper", created by BMR. The user wants tutorial help for {software}.

- Provide step-by-step tutorials specifically for {software}
- Include exact menu paths, keyboard shortcuts, and settings
- Give specific parameter values and numbers where applicable
- Explain why each step matters
- Offer pro tips and common mistakes to avoid
- If they ask about effects, include expected values for all parameters
- After explaining, always add a quick summary at the end"""
    else:
        return f"""You are "Editing Helper", created by BMR. The user is asking for editing help.

Before providing help, ASK THEM: "Which software do you use? ({software_list})"
Wait for their answer before giving detailed help."""

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

async def detect_toxic_content(text):
    """Detect if message contains profanity, toxic behavior, or misbehavior."""
    text_lower = text.lower()
    
    # Check for profanity
    words = text_lower.split()
    for word in words:
        # Remove punctuation and check
        clean_word = word.strip('.,!?;:\'"')
        if clean_word in PROFANITY_WORDS:
            return True, "profanity"
    
    # Check for excessive caps (YELLING)
    if len(text) > 5:
        caps_count = sum(1 for c in text if c.isupper())
        if caps_count / len(text) > 0.7:  # 70% caps = yelling
            return True, "excessive_caps"
    
    # Check for spam patterns (repeated characters)
    if any(text.count(char*5) > 0 for char in 'abcdefghijklmnopqrstuvwxyz'):
        return True, "spam"
    
    # Check for toxic keywords
    toxic_phrases = ['kys', 'kill yourself', 'go die', 'go fuck', 'fuck you', 'i hope you die']
    for phrase in toxic_phrases:
        if phrase in text_lower:
            return True, "toxic_behavior"
    
    return False, None

async def auto_mute_user(message, reason):
    """Automatically mute a user for toxic behavior."""
    try:
        # Don't mute BMR or bot
        if 'bmr' in message.author.name.lower() or message.author == bot.user:
            return
        
        guild = message.guild
        if not guild:
            return
        
        # Check bot permissions
        if not guild.me.guild_permissions.manage_roles:
            logger.warning("Bot doesn't have permission to manage roles")
            return
        
        # Get or create muted role
        muted_role = discord.utils.get(guild.roles, name="Muted")
        if not muted_role:
            muted_role = await guild.create_role(name="Muted", reason="Auto-moderation muted role")
            logger.info(f"Created 'Muted' role in {guild.name}")
        
        # Add muted role
        await message.author.add_roles(muted_role, reason=f"Auto-muted for {reason}")
        await message.channel.send(f"🔇 {message.author.mention} has been **auto-muted** for {reason}. Watch your behavior!")
        logger.info(f"Auto-muted {message.author.name} for {reason}")
    except Exception as e:
        logger.error(f"Error auto-muting user: {str(e)}")

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

def get_gemini_response(prompt, user_id, username=None, image_bytes=None, is_tutorial=False, software=None):
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
            system_prompt = get_tutorial_prompt(software)
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

async def search_and_download_image(query: str, limit: int = 3):
    """Search for images using Bing Image Search and download them."""
    try:
        import tempfile
        import shutil
        
        # Create temp directory for images
        temp_dir = tempfile.mkdtemp()
        
        # Download images
        downloader.download(
            query,
            limit=limit,
            output_dir="dataset",
            adult_filter_off=True,
            force_replace=True,
            timeout=15
        )
        
        # Find downloaded images
        image_dir = f"dataset/{query}"
        if os.path.exists(image_dir):
            image_files = [f for f in os.listdir(image_dir) if f.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp'))]
            if image_files:
                image_path = os.path.join(image_dir, image_files[0])
                return image_path
        
        return None
    except Exception as e:
        logger.error(f"Error downloading image: {str(e)}")
        return None

import asyncio
import random

# Presence cycle statuses
PRESENCE_STATUSES = [
    (discord.Activity(type=discord.ActivityType.watching, name="🎬 Editing Help | !list"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="your editing questions 🎨"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="with video effects ⚡"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.watching, name="tutorials 📚"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="Valorant 🎮"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.listening, name="your music taste 🎵"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.watching, name="anime 📺"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.playing, name="with code ⚙️"), discord.Status.dnd),
    (discord.Activity(type=discord.ActivityType.listening, name="your problems 💬"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="movies 🍿"), discord.Status.idle),
    (discord.Activity(type=discord.ActivityType.playing, name="chess 🎯"), discord.Status.online),
    (discord.Activity(type=discord.ActivityType.watching, name="tech tutorials 🔧"), discord.Status.dnd),
]

@bot.event
async def on_ready():
    """Event triggered when the bot is ready and connected to Discord."""
    logger.info(f'Bot connected as {bot.user.name} (ID: {bot.user.id})')
    logger.info(f'Connected to {len(bot.guilds)} servers')
    logger.info('Bot is ready to receive commands!')

    # Start presence cycle
    async def cycle_presence():
        while True:
            activity, status = random.choice(PRESENCE_STATUSES)
            await bot.change_presence(activity=activity, status=status)
            await asyncio.sleep(30)  # Change presence every 30 seconds
    
    # Run presence cycle in background
    bot.loop.create_task(cycle_presence())

    # --- AutoMod rule creation (corrected for discord.py version) ---
    try:
        from discord import (
            AutoModTrigger,
            AutoModRuleAction,
            AutoModRuleEventType,
            AutoModRuleTriggerType,
        )

        guild = bot.get_guild(int(os.getenv("AUTOMOD_GUILD_ID", "1311717154256851057")))

        if guild:
            trigger = AutoModTrigger(
                type=AutoModRuleTriggerType.keyword,
                keyword_filter=["automodtestword"]
            )

            action = AutoModRuleAction(
                type=1  # BLOCK_MESSAGE
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
    except Exception as e:
        logger.warning(f"AutoMod rule creation failed or already exists: {e}")
@bot.event
async def on_command_error(ctx, error):
    """Global error handler for bot commands."""
    if isinstance(error, commands.CommandNotFound):
        return  # Ignore command not found errors

    logger.error(f'Command error: {error}')
    await ctx.send(f"An error occurred: {str(error)}")

@bot.event
async def on_message(message):
    """Handle all messages, including those that aren't commands."""
    # Ignore messages from the bot itself and other bots
    if message.author == bot.user or message.author.bot:
        return
    
    # Auto-moderation: Check for toxic content in server messages
    if message.guild and not isinstance(message.channel, discord.DMChannel):
        is_toxic, reason = await detect_toxic_content(message.content)
        if is_toxic:
            await auto_mute_user(message, reason)
            return  # Don't process further
    
    # Check if user has a pending state (waiting for response to a question)
    user_id = message.author.id
    if user_id in user_states:
        state = user_states[user_id]
        if state['type'] == 'waiting_for_software':
            # User answered which software they want help with
            software = message.content.strip()
            state['software'] = software
            state['type'] = 'tutorial_ready'
            # Now provide the tutorial response
            prompt = state['original_question']
            response = get_gemini_response(prompt, user_id, username=message.author.name, is_tutorial=True, software=software)
            await message.reply(response[:1900] if len(response) > 1900 else response)
            # Clean up state after response
            del user_states[user_id]
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

    # Process commands first
    await bot.process_commands(message)

    # If the message doesn't start with a command prefix, treat it as a chat message
    if not message.content.startswith('!'):
        # Respond to ALL messages - DMs, mentions, and regular server chat
        is_dm = isinstance(message.channel, discord.DMChannel)
        
        # Check if this is about tutorials - if so, ask which software
        prompt_lower = message.content.lower()
        is_help_request = any(keyword in prompt_lower for keyword in ['help', 'tutorial', 'how to', 'teach', 'guide', 'learn', 'explain', 'show me'])
        is_editing_help = is_help_request and any(keyword in prompt_lower for keyword in ['edit', 'effect', 'render', 'color', 'grade', 'video', 'after effects', 'premiere', 'photoshop', 'resolve', 'capcut', 'topaz'])
        
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
            
            # If this is an editing help request without attachment, ask which software first
            if is_editing_help and not image_bytes and not video_bytes:
                user_id = message.author.id
                user_states[user_id] = {
                    'type': 'waiting_for_software',
                    'original_question': prompt
                }
                software_list = "After Effects, Premiere Pro, Photoshop, Media Encoder, DaVinci Resolve, Final Cut Pro, Topaz Video AI, CapCut, or something else?"
                await message.reply(f"Hey! 👋 Which software do you use? {software_list}")
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

        except Exception as e:
            logger.error(f'Error in chat response: {str(e)}')
            await message.channel.send("Sorry, I encountered an error processing your message. Please try again.")

@bot.command(name="help")
async def help_command(ctx):
    """
    Custom help command that sends 'HI' to the user's DMs.
    Usage: !help
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !help command in {ctx.guild.name if ctx.guild else "DM"}')

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

@bot.command(name="list")
async def list_commands(ctx):
    """
    Lists all available bot commands.
    Usage: !list
    """
    logger.info(f'User {ctx.author.name} (ID: {ctx.author.id}) invoked !list command in {ctx.guild.name if ctx.guild else "DM"}')

    # Prepare the command list
    commands_list = [
        "**Basic Commands:**",
        "!help - Sends 'HI' in your DMs",
        "!hi - Also sends 'HI' in your DMs",
        "!list - Shows this list of commands",
        "!files - Lists all available files that can be requested",
        "!presets - Lists all available color correction presets",
        "!software_list - Lists all software-related commands",
        "",
        "**Software Commands:**",
        "!aecrack - Adobe After Effects crack information",
        "!pscrack - Adobe Photoshop crack information",
        "!mecrack - Media Encoder crack information",
        "!prcrack - Adobe Premiere Pro crack information",
        "!topazcrack - Topaz Suite crack information",
        "",
        "**File Commands:**",
        "Type !filename to receive a specific file in your DMs",
        "Example: !foggy_cc or !foggy cc will send the 'foggy cc.ffx' file",
        "",
        "**Available CC Files:**"
    ]

    # Add all the CC files to the list
    cc_files = []
    for file in glob.glob("files/*.ffx"):
        if os.path.isfile(file):
            filename = os.path.basename(file)
            command_name = os.path.splitext(filename)[0]
            cc_files.append(f"!{command_name}")

    # Sort and add CC files to the commands list
    cc_files.sort()
    commands_list.extend(cc_files)

    # Format the final response
    response = "\n".join(commands_list)

    try:
        # Send the list to the user's DMs
        await ctx.author.send(response)
        logger.info(f'Sent command list to {ctx.author.name}')

        # Send confirmation in the channel
        if ctx.guild:
            await ctx.send(f"{ctx.author.mention}, I've sent you the list of commands in your DMs!")

    except discord.Forbidden:
        # If DMs are closed, send in the channel
        logger.warning(f'Could not send command list to {ctx.author.name} - DMs may be closed')
        await ctx.send(f"{ctx.author.mention}, I couldn't send you a DM. Here's the list of commands:")

        # Split the response if it's too long for a single message
        if len(response) > 1900:  # Discord message limit is 2000 characters
            parts = [commands_list[:6], commands_list[6:9], ["**Available CC Files:**"] + cc_files]
            for part in parts:
                await ctx.send("\n".join(part))
        else:
            await ctx.send(response)

    except Exception as e:
        logger.error(f'Error sending command list to {ctx.author.name}: {str(e)}')
        await ctx.send(f"{ctx.author.mention}, an error occurred while trying to send you the command list.")

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
    if first_word in ["help", "hi", "files", "list", "software_list", "presets", 
                      "aecrack", "pscrack", "mecrack", "prcrack", "topazcrack", 
                      "ban", "mute", "timeout"]:
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
    """Ban a user from the server - ONLY BMR can use this."""
    # Check if it's BMR
    if 'bmr' not in ctx.author.name.lower():
        await ctx.send(f"{ctx.author.mention}, only BMR can use this command.")
        return
    
    # Check if user has permission to ban
    if not ctx.author.guild_permissions.ban_members:
        await ctx.send(f"{ctx.author.mention}, you don't have permission to ban members!")
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
        
        # Don't allow banning BMR
        if 'bmr' in member.name.lower():
            await ctx.send("❌ Nice try, but I can't ban BMR!")
            return
        
        # Send DM to user before banning
        try:
            await member.send(f"You have been **BANNED** from the server by {ctx.author.name}. Reason: Banned by moderator.")
        except:
            pass  # User may have DMs disabled
        
        # Ban the user
        await ctx.guild.ban(member, reason=f"Banned by {ctx.author.name}")
        await ctx.send(f"✓ {member.name} has been **BANNED** from the server. Goodbye! 🚫")
        logger.info(f"{ctx.author.name} banned {member.name}")
    except discord.Forbidden:
        await ctx.send(f"❌ I don't have permission to ban {member.name}!")
        logger.error(f"Permission denied when trying to ban {member.name}")
    except Exception as e:
        logger.error(f"Error banning user: {str(e)}")
        await ctx.send(f"❌ Error banning user: {str(e)}")

@bot.command(name="timeout")
async def timeout_command(ctx, member: discord.Member = None, duration: str = None):
    """Timeout a user for a specified duration - ONLY BMR can use this."""
    # Check if it's BMR
    if 'bmr' not in ctx.author.name.lower():
        await ctx.send(f"{ctx.author.mention}, only BMR can use this command.")
        return
    
    # Check if user has permission to timeout
    if not ctx.author.guild_permissions.moderate_members:
        await ctx.send(f"{ctx.author.mention}, you don't have permission to timeout members!")
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
        
        # Don't allow timing out BMR
        if 'bmr' in member.name.lower():
            await ctx.send("❌ Nice try, but I can't timeout BMR!")
            return
        
        # Send DM to user before timeout
        try:
            await member.send(f"You have been **TIMED OUT** in the server by {ctx.author.name} for {duration}.")
        except:
            pass  # User may have DMs disabled
        
        # Apply timeout
        from datetime import datetime, timedelta
        timeout_until = datetime.utcnow() + timedelta(seconds=timeout_seconds)
        await member.timeout(timeout_until, reason=f"Timeout by {ctx.author.name}")
        await ctx.send(f"✓ {member.name} has been **TIMED OUT** for {duration}. 🔇")
        logger.info(f"{ctx.author.name} timed out {member.name} for {duration}")
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
    """Timeout a user (alias for timeout command) - ONLY BMR can use this."""
    if not member or not duration:
        await ctx.send("Usage: !mute @user 24h")
        return
    await ctx.invoke(timeout_command, member=member, duration=duration)

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
