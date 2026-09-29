import os
import discord
from discord import app_commands
from discord.ext import commands
import sqlite3

intents = discord.Intents.default()
intents.guilds = True
intents.members = True
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ==================== 1. ระบบฐานข้อมูล SQLite ====================
db = sqlite3.connect("clan_scores.db")
cursor = db.cursor()

# ตารางเก็บรายชื่อแคลน
cursor.execute("""
CREATE TABLE IF NOT EXISTS clans (
    clan_name TEXT PRIMARY KEY,
    creator_id INTEGER
)
""")

# ตารางเก็บรูปภาพสกอร์ของแต่ละแคลน
cursor.execute("""
CREATE TABLE IF NOT EXISTS clan_images (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    clan_name TEXT,
    image_url TEXT,
    uploader_id INTEGER,
    FOREIGN KEY(clan_name) REFERENCES clans(clan_name) ON DELETE CASCADE
)
""")

# ตารางเก็บบันทึกข้อความแสดงผลรวม (สำหรับอัปเดตแบบเรียลไทม์)
cursor.execute("""
CREATE TABLE IF NOT EXISTS display_panel (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    channel_id INTEGER,
    message_id INTEGER
)
""")
db.commit()

@bot.event
async def on_ready():
    print(f"บอทระบบแคลนออนไลน์แล้ว: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"ซิงค์ Slash Commands ทั้งหมด {len(synced)} คำสั่งเรียบร้อยแล้ว")
    except Exception as e:
        print(e)

# ==================== ฟังก์ชันสร้างและอัปเดต Embed สรุปภาพรวมแบบเรียลไทม์ ====================
async def update_display_panel(guild: discord.Guild):
    cursor.execute("""
        SELECT c.clan_name, COUNT(i.id) 
        FROM clans c 
        LEFT JOIN clan_images i ON c.clan_name = i.clan_name 
        GROUP BY c.clan_name
    """)
    clans_data = cursor.fetchall()

    # สร้าง Embed สวยงามหรูหรา
    embed = discord.Embed(
        title="🏆 ระบบบันทึกสกอร์และรูปภาพแคลน",
        description="📊 **สรุปรายชื่อแคลนและจำนวนรูปภาพสะสมทั้งหมดในระบบ**\n*(ข้อมูลจะอัปเดตแบบเรียลไทม์อัตโนมัติ)*",
        color=discord.Color.gold()
    )

    if not clans_data:
        embed.add_field(name="สถานะ", value="❌ ยังไม่มีการสร้างชื่อแคลนในระบบ", inline=False)
    else:
        clan_list = ""
        for idx, (c_name, c_count) in enumerate(clans_data, 1):
            clan_list += f"` {idx}. ` 🛡️ **{c_name}** — มีรูปภาพสะสม `{c_count}` รูป\n"
        embed.add_field(name="📋 รายชื่อแคลนทั้งหมด", value=clan_list, inline=False)

    embed.set_footer(text="💡 ใช้คำสั่ง /เพิ่มรูป หรือ /สร้างสกอแคลน เพื่ออัปเดตข้อมูล")

    # ค้นหาว่ามีการตั้งค่าห้องแสดงผลไว้หรือยัง
    cursor.execute("SELECT channel_id, message_id FROM display_panel WHERE id = 1")
    panel = cursor.fetchone()

    if panel:
        channel_id, message_id = panel
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed)
                return
            except Exception:
                pass # ถ้าหาข้อความไม่พบ ให้สร้างใหม่ด้านล่าง

# ==================== 2. ระบบ UI ปุ่มกดเลื่อนดูรูปภาพ (Pagination) ====================
class ClanImageView(discord.ui.View):
    def __init__(self, images, clan_name):
        super().__init__(timeout=180)
        self.images = images
        self.clan_name = clan_name
        self.current_page = 0
        self.update_buttons()

    def update_buttons(self):
        self.prev_button.disabled = self.current_page == 0
        self.next_button.disabled = self.current_page == len(self.images) - 1

    def create_embed(self):
        img_id, img_url, uploader_id = self.images[self.current_page]
        embed = discord.Embed(
            title=f"🏆 สกอร์แคลน: {self.clan_name}",
            description=f"📄 **รูปที่:** `{self.current_page + 1} / {len(self.images)}`\n🆔 **รหัสรูปภาพ (ID สำหรับใช้ลบ):** `{img_id}`\n👤 **ผู้อัปโหลด:** <@{uploader_id}>",
            color=discord.Color.green()
        )
        embed.set_image(url=img_url)
        return embed

    @discord.ui.button(label="◀️ ก่อนหน้า", style=discord.ButtonStyle.blurple, custom_id="prev_img")
    async def prev_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="ถัดไป ▶️", style=discord.ButtonStyle.blurple, custom_id="next_img")
    async def next_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.current_page < len(self.images) - 1:
            self.current_page += 1
            self.update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

# ==================== 3. คำสั่งหลักของบอท ====================

@bot.tree.command(name="สร้างสกอแคลน", description="[แอดมิน] สร้างชื่อหัวข้อแคลนใหม่เพื่อเก็บรูปสกอร์")
@app_commands.describe(ชื่อแคลน="ระบุชื่อแคลนที่ต้องการสร้าง (เช่น ฮาเรียล)")
async def create_clan(interaction: discord.Interaction, ชื่อแคลน: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (เฉพาะแอดมิน)", ephemeral=True)
        return

    cursor.execute("SELECT clan_name FROM clans WHERE clan_name = ?", (ชื่อแคลน,))
    if cursor.fetchone():
        await interaction.response.send_message(f"❌ มีชื่อแคลน `{ชื่อแคลน}` นี้อยู่ในระบบอยู่แล้ว!", ephemeral=True)
        return

    cursor.execute("INSERT INTO clans (clan_name, creator_id) VALUES (?, ?)", (ชื่อแคลน, interaction.user.id))
    db.commit()

    # อัปเดตแผงแสดงผลรวมแบบเรียลไทม์ทันที
    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ สร้างหัวข้อสกอร์แคลน `{ชื่อแคลน}` สำเร็จแล้ว! (ระบบอัปเดตหน้าจอเรียลไทม์ให้แล้ว)", ephemeral=True)

@bot.tree.command(name="เพิ่มรูป", description="อัปโหลดและบันทึกรูปภาพสกอร์การแข่งเข้าไปในแคลน")
@app_commands.describe(ชื่อแคลน="เลือกหรือพิมพ์ชื่อแคลน", รูปภาพ="แนบไฟล์รูปภาพสกอร์")
async def add_image(interaction: discord.Interaction, ชื่อแคลน: str, รูปภาพ: discord.Attachment):
    cursor.execute("SELECT clan_name FROM clans WHERE clan_name = ?", (ชื่อแคลน,))
    if not cursor.fetchone():
        await interaction.response.send_message(f"❌ ไม่พบชื่อแคลน `{ชื่อแคลน}` ในระบบ! (กรุณาให้แอดมินสร้างชื่อแคลนด้วย /สร้างสกอแคลน ก่อน)", ephemeral=True)
        return

    if not รูปภาพ.content_type or not รูปภาพ.content_type.startswith("image/"):
        await interaction.response.send_message("❌ กรุณาแนบไฟล์ที่เป็นรูปภาพเท่านั้น!", ephemeral=True)
        return

    cursor.execute("INSERT INTO clan_images (clan_name, image_url, uploader_id) VALUES (?, ?, ?)", 
                   (ชื่อแคลน, รูปภาพ.url, interaction.user.id))
    db.commit()

    # อัปเดตแผงแสดงผลรวมแบบเรียลไทม์ทันที
    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ บันทึกรูปภาพสกอร์ของแคลน `{ชื่อแคลน}` เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="เช็ครูป", description="เรียกดูรูปภาพสกอร์ทั้งหมดของแคลนที่ต้องการ")
@app_commands.describe(ชื่อแคลน="ระบุชื่อแคลนที่ต้องการดูรูป")
async def check_images(interaction: discord.Interaction, ชื่อแคลน: str):
    cursor.execute("SELECT id, image_url, uploader_id FROM clan_images WHERE clan_name = ?", (ชื่อแคลน,))
    images = cursor.fetchall()

    if not images:
        await interaction.response.send_message(f"❌ ยังไม่มีรูปภาพสกอร์ของแคลน `{ชื่อแคลน}` ในระบบ", ephemeral=True)
        return

    view = ClanImageView(images, ชื่อแคลน)
    embed = view.create_embed()
    await interaction.response.send_message(embed=embed, view=view)

@bot.tree.command(name="แสดงผลรวม", description="[แอดมิน] สร้างหน้าต่างแสดงรายชื่อแคลนและจำนวนรูปภาพแบบเรียลไทม์ในห้องนี้")
async def display_panel_cmd(interaction: discord.Interaction):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (เฉพาะแอดมิน)", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)

    cursor.execute("""
        SELECT c.clan_name, COUNT(i.id) 
        FROM clans c 
        LEFT JOIN clan_images i ON c.clan_name = i.clan_name 
        GROUP BY c.clan_name
    """)
    clans_data = cursor.fetchall()

    embed = discord.Embed(
        title="🏆 ระบบบันทึกสกอร์และรูปภาพแคลน",
        description="📊 **สรุปรายชื่อแคลนและจำนวนรูปภาพสะสมทั้งหมดในระบบ**\n*(ข้อมูลจะอัปเดตแบบเรียลไทม์อัตโนมัติ)*",
        color=discord.Color.gold()
    )

    if not clans_data:
        embed.add_field(name="สถานะ", value="❌ ยังไม่มีการสร้างชื่อแคลนในระบบ", inline=False)
    else:
        clan_list = ""
        for idx, (c_name, c_count) in enumerate(clans_data, 1):
            clan_list += f"` {idx}. ` 🛡️ **{c_name}** — มีรูปภาพสะสม `{c_count}` รูป\n"
        embed.add_field(name="📋 รายชื่อแคลนทั้งหมด", value=clan_list, inline=False)

    embed.set_footer(text="💡 ใช้คำสั่ง /เพิ่มรูป หรือ /สร้างสกอแคลน เพื่ออัปเดตข้อมูล")

    # ส่งข้อความลงในห้องที่ใช้คำสั่ง
    message = await interaction.channel.send(embed=embed)

    # บันทึกตำแหน่งข้อความนี้ลงในฐานข้อมูล เพื่อให้บอทวิ่งมาแก้ข้อความนี้อัตโนมัติเวลาข้อมูลเปลี่ยน
    cursor.execute("REPLACE INTO display_panel (id, channel_id, message_id) VALUES (1, ?, ?)", 
                   (interaction.channel.id, message.id))
    db.commit()

    await interaction.followup.send("✅ สร้างแผงแสดงผลรวมแบบเรียลไทม์ในห้องนี้เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="ลบรูปภาพ", description="ลบรูปภาพเดี่ยวๆ ออกจากระบบ (ดูรหัสรูปได้จากคำสั่ง /เช็ครูป)")
@app_commands.describe(รหัสรูป="ใส่ ID ของรูปภาพที่ต้องการลบ")
async def delete_image(interaction: discord.Interaction, รหัสรูป: int):
    cursor.execute("SELECT clan_name, uploader_id FROM clan_images WHERE id = ?", (รหัสรูป,))
    result = cursor.fetchone()

    if not result:
        await interaction.response.send_message(f"❌ ไม่พบรูปภาพที่มีรหัส ID `{รหัสรูป}` ในระบบ", ephemeral=True)
        return

    clan_name, uploader_id = result

    if interaction.user.id != uploader_id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ คุณสามารถลบได้เฉพาะรูปที่คุณเป็นคนอัปโหลดเท่านั้น (ยกเว้นแอดมิน)", ephemeral=True)
        return

    cursor.execute("DELETE FROM clan_images WHERE id = ?", (รหัสรูป,))
    db.commit()

    # อัปเดตแผงแสดงผลรวมแบบเรียลไทม์ทันที
    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ ลบรูปภาพรหัส ID `{รหัสรูป}` ของแคลน `{clan_name}` เรียบร้อยแล้ว! (อัปเดตผลรวมให้แล้ว)", ephemeral=True)

@bot.tree.command(name="ลบแคลน", description="[แอดมิน] ลบชื่อแคลนและรูปภาพทั้งหมดในแคลนนั้นทิ้ง")
@app_commands.describe(ชื่อแคลน="ชื่อแคลนที่ต้องการลบ")
async def delete_clan(interaction: discord.Interaction, ชื่อแคลน: str):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ คุณไม่มีสิทธิ์ใช้งานคำสั่งนี้ (เฉพาะแอดมิน)", ephemeral=True)
        return

    cursor.execute("SELECT clan_name FROM clans WHERE clan_name = ?", (ชื่อแคลน,))
    if not cursor.fetchone():
        await interaction.response.send_message(f"❌ ไม่พบชื่อแคลน `{ชื่อแคลน}` ในระบบ", ephemeral=True)
        return

    cursor.execute("DELETE FROM clan_images WHERE clan_name = ?", (ชื่อแคลน,))
    cursor.execute("DELETE FROM clans WHERE clan_name = ?", (ชื่อแคลน,))
    db.commit()

    # อัปเดตแผงแสดงผลรวมแบบเรียลไทม์ทันที
    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ ลบแคลน `{ชื่อแคลน}` เรียบร้อยแล้ว! (อัปเดตผลรวมให้แล้ว)", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))
