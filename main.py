import asyncio
from typing import Optional, Union, Tuple

from pyrogram import Client, filters, idle
from pyrogram.types import Message
from pyrogram.enums import ChatType, ChatMemberStatus, ParseMode
from pyrogram.errors import UserNotParticipant, FloodWait, RPCError, PeerIdInvalid, ChannelInvalid

# ====================== CONFIG ======================
from config import API_ID, API_HASH, BOT_TOKEN

APP_NAME = "keyword_forward_bot"

class State:
    source_chat_id: Optional[int] = None
    target_chat_id: Optional[int] = None
    start_id: Optional[int] = None
    end_id: Optional[int] = None
    next_id: Optional[int] = None
    keyword: str = "Completed"          # Default keyword
    lock = asyncio.Lock()               # Prevent concurrent forwards
    custom_replies: dict = {}           # NEW: trigger → response

app = Client(APP_NAME, api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# ====================== HELP TEXT ======================
HELP = f"""
🤖 **Keyword Forward Bot**

**Commands**
/setsource `<chat_id|@username>` – Set source channel
/settarget `<chat_id|@username>` – Set target group/channel
/setrange `<first_id> <last_id>` – Set message ID range (inclusive)
/setkeyword `<text>` – Set trigger keyword (default: `Completed`)
/setreply `<trigger> <response>` – Add a custom auto-reply
/replies – Show all custom replies
/delreply `<trigger>` – Delete a custom reply
/status – Show current settings & progress
/reset – Clear all settings

**How it works**
• When the bot sees the keyword in the **target chat**, it forwards the **next message** from the configured range in the **source** to the **target**, one by one.  
• Custom replies: if the bot sees a message containing a trigger word, it auto-replies with the saved response.

**Notes**
• Add the bot to both chats.  
• Bot must be able to **read** the source channel and **send** in the target chat.
"""

# ====================== HELP / START ======================
@app.on_message(filters.command(["start", "help"]))
async def start_cmd(_c: Client, m: Message):
    await m.reply_text(HELP, parse_mode=ParseMode.MARKDOWN)

# ====================== UTILS ======================
async def resolve_chat_id(client: Client, ident: Union[str, int]) -> int:
    chat = await client.get_chat(ident)
    return chat.id

async def can_read_source(client: Client, chat_id: int) -> Tuple[bool, str]:
    try:
        chat = await client.get_chat(chat_id)
        if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP):
            return False, "Source must be a channel or group"
        try:
            await client.get_chat_member(chat.id, "me")
        except UserNotParticipant:
            return False, "Bot is not a member of the source"
        return True, "OK"
    except (PeerIdInvalid, ChannelInvalid):
        return False, "Invalid source chat"
    except Exception as e:
        return False, f"{e}"

async def can_send_target(client: Client, chat_id: int) -> Tuple[bool, str]:
    try:
        chat = await client.get_chat(chat_id)
        if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP, ChatType.GROUP):
            return False, "Target must be a channel or group"
        try:
            member = await client.get_chat_member(chat.id, "me")
        except UserNotParticipant:
            return False, "Bot is not a member of the target"
        if member.status == ChatMemberStatus.ADMINISTRATOR:
            return True, "OK"
        if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
            return True, "OK"
        return False, "Bot must be admin in target channel to post"
    except (PeerIdInvalid, ChannelInvalid):
        return False, "Invalid target chat"
    except Exception as e:
        return False, f"{e}"

def ready_to_forward() -> Tuple[bool, str]:
    if State.source_chat_id is None:
        return False, "Source not set. Use /setsource"
    if State.target_chat_id is None:
        return False, "Target not set. Use /settarget"
    if State.start_id is None or State.end_id is None:
        return False, "Range not set. Use /setrange <first_id> <last_id>"
    if State.next_id is None:
        return False, "Internal: next_id not initialized"
    return True, "OK"

def range_str() -> str:
    if State.start_id is None or State.end_id is None:
        return "Not set"
    lo = min(State.start_id, State.end_id)
    hi = max(State.start_id, State.end_id)
    return f"{lo}–{hi} (next: {State.next_id})"

# ====================== COMMANDS ======================
@app.on_message(filters.command("setsource"))
async def cmd_set_source(c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /setsource <chat_id|@username>")
    ident = m.command[1]
    try:
        chat_id = await resolve_chat_id(c, ident)
        ok, msg = await can_read_source(c, chat_id)
        if not ok:
            return await m.reply_text(f"❌ Source check failed: {msg}")
        State.source_chat_id = chat_id
        await m.reply_text(f"✅ Source set to `{chat_id}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await m.reply_text(f"❌ Failed to set source: {e}")

@app.on_message(filters.command("settarget"))
async def cmd_set_target(c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /settarget <chat_id|@username>")
    ident = m.command[1]
    try:
        chat_id = await resolve_chat_id(c, ident)
        ok, msg = await can_send_target(c, chat_id)
        if not ok:
            return await m.reply_text(f"❌ Target check failed: {msg}")
        State.target_chat_id = chat_id
        await m.reply_text(f"✅ Target set to `{chat_id}`", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await m.reply_text(f"❌ Failed to set target: {e}")

@app.on_message(filters.command("setrange"))
async def cmd_set_range(_c: Client, m: Message):
    if len(m.command) < 3:
        return await m.reply_text("Usage: /setrange <first_id> <last_id>")
    try:
        a = int(m.command[1])
        b = int(m.command[2])
        lo = min(a, b)
        hi = max(a, b)
        State.start_id = lo
        State.end_id = hi
        State.next_id = lo
        await m.reply_text(f"✅ Range set to `{lo}..{hi}` (next: {State.next_id})", parse_mode=ParseMode.MARKDOWN)
    except ValueError:
        await m.reply_text("❌ first_id and last_id must be integers")

@app.on_message(filters.command("setkeyword"))
async def cmd_set_keyword(_c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /setkeyword <text>\nExample: /setkeyword Completed")
    State.keyword = " ".join(m.command[1:]).strip()
    await m.reply_text(f"✅ Keyword set to: `{State.keyword}`", parse_mode=ParseMode.MARKDOWN)

# --- NEW: setreply, replies, delreply ---
@app.on_message(filters.command("setreply"))
async def cmd_set_reply(_c: Client, m: Message):
    if len(m.command) < 3:
        return await m.reply_text("Usage: /setreply <trigger> <response>")
    trigger = m.command[1].lower()
    response = " ".join(m.command[2:])
    State.custom_replies[trigger] = response
    await m.reply_text(f"✅ Reply set: when someone says `{trigger}`, bot replies `{response}`",
                       parse_mode=ParseMode.MARKDOWN)

@app.on_message(filters.command("replies"))
async def cmd_list_replies(_c: Client, m: Message):
    if not State.custom_replies:
        return await m.reply_text("ℹ️ No custom replies set.")
    text = "🔹 **Custom Replies:**\n"
    for k, v in State.custom_replies.items():
        text += f"▫️ `{k}` → `{v}`\n"
    await m.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@app.on_message(filters.command("delreply"))
async def cmd_del_reply(_c: Client, m: Message):
    if len(m.command) < 2:
        return await m.reply_text("Usage: /delreply <trigger>")
    trigger = m.command[1].lower()
    if trigger in State.custom_replies:
        del State.custom_replies[trigger]
        await m.reply_text(f"✅ Deleted reply for `{trigger}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await m.reply_text(f"❌ No reply found for `{trigger}`")

@app.on_message(filters.command("status"))
async def cmd_status(c: Client, m: Message):
    async def name_or_id(chat_id: Optional[int]) -> str:
        if chat_id is None:
            return "Not set"
        try:
            ch = await c.get_chat(chat_id)
            label = ch.title or (f"@{ch.username}" if ch.username else str(chat_id))
            return f"{label} (`{chat_id}`)"
        except Exception:
            return f"`{chat_id}`"
    src = await name_or_id(State.source_chat_id)
    tgt = await name_or_id(State.target_chat_id)
    text = f"""🔧 **Bot Status**
• Source: {src}
• Target: {tgt}
• Range: {range_str()}
• Keyword: `{State.keyword}`
• Custom replies: {len(State.custom_replies)}
"""
    await m.reply_text(text, parse_mode=ParseMode.MARKDOWN)

@app.on_message(filters.command("reset"))
async def cmd_reset(_c: Client, m: Message):
    State.source_chat_id = None
    State.target_chat_id = None
    State.start_id = None
    State.end_id = None
    State.next_id = None
    State.keyword = "Completed"
    State.custom_replies = {}
    await m.reply_text("✅ Settings reset. Keyword reverted to `Completed`. All custom replies cleared.")

# ====================== FORWARD LOGIC ======================
async def forward_next_if_ready(c: Client, trigger_msg: Message):
    if State.target_chat_id is None or trigger_msg.chat.id != State.target_chat_id:
        return
    ok, why = ready_to_forward()
    if not ok:
        await trigger_msg.reply_text(f"⚠️ Not ready to forward: {why}")
        return
    async with State.lock:
        if State.next_id is None or State.start_id is None or State.end_id is None:
            return
        if State.next_id > State.end_id:
            await trigger_msg.reply_text("✅ All messages in the range have already been forwarded.")
            return
        try:
            msg = await c.get_messages(State.source_chat_id, State.next_id)
            if not msg or msg.empty:
                await trigger_msg.reply_text(f"⚠️ Skipping missing message ID {State.next_id}")
                State.next_id += 1
                return
            await c.copy_message(
                chat_id=State.target_chat_id,
                from_chat_id=State.source_chat_id,
                message_id=State.next_id
            )
            await trigger_msg.reply_text(f"➡️ Forwarded message `{State.next_id}`", parse_mode=ParseMode.MARKDOWN)
            State.next_id += 1
        except FloodWait as e:
            await trigger_msg.reply_text(f"⏳ FloodWait: sleeping {e.value}s")
            await asyncio.sleep(e.value)
        except RPCError as e:
            await trigger_msg.reply_text(f"❌ Forward error on ID {State.next_id}: {e}")
            State.next_id += 1
        except Exception as e:
            await trigger_msg.reply_text(f"❌ Unexpected error on ID {State.next_id}: {e}")
            State.next_id += 1

# ====================== TEXT HANDLER ======================
@app.on_message(filters.text)
async def on_text(c: Client, m: Message):
    if not m.text:
        return
    text_lower = m.text.lower()

    # 1) Custom replies
    for trigger, response in State.custom_replies.items():
        if trigger in text_lower:
            await m.reply_text(response)

    # 2) Forward keyword
    if State.keyword and State.keyword.lower() in text_lower:
        await forward_next_if_ready(c, m)

# ====================== MAIN ======================
if __name__ == "__main__":
    print("🚀 Keyword Forward Bot starting…")
    try:
        app.start()
        print("✅ Bot connected.")
        idle()
    except KeyboardInterrupt:
        print("\n🛑 Stopped by user")
    finally:
        try:
            app.stop()
            print("👋 Bot stopped.")
        except Exception:
            pass
