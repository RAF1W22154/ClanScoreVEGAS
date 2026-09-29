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
db.commit()

@bot.event
async def on_ready():
    print(f"บอทระบบแคลนออนไลน์แล้ว: {bot.user.name}")
    try:
        synced = await bot.tree.sync()
        print(f"ซิงค์ Slash Commands ทั้งหมด {len(synced)} คำสั่งเรียบร้อยแล้ว")
    except Exception as e:
        print(e)

# ==================== 2. ระบบ UI ปุ่มกดเลื่อนดูรูปภาพ (Pagination) ====================
class ClanImageView(discord.ui.View):
    def __init__(self, images, clan_name):
        super().__init__(timeout=180) # ปุ่มหมดอายุใน 3 นาที
        self.images = images # รายการลิงก์รูปภาพทั้งหมด
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
    await interaction.response.send_message(f"✅ สร้างหัวข้อสกอร์แคลน `{ชื่อแคลน}` สำเร็จแล้ว!", ephemeral=True)

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

@bot.tree.command(name="รายชื่อแคลน", description="ตรวจสอบดูว่าในระบบมีบันทึกชื่อแคลนอะไรไว้บ้าง")
async def list_clans(interaction: discord.Interaction):
    cursor.execute("SELECT clan_name FROM clans")
    clans = cursor.fetchall()

    if not clans:
        await interaction.response.send_message("❌ ยังไม่มีการสร้างชื่อแคลนใดๆ ในระบบ", ephemeral=True)
        return

    clan_list = "\n".join([f"• `{c[0]}`" for c in clans])
    embed = discord.Embed(title="📋 รายชื่อแคลนทั้งหมดในระบบ", description=clan_list, color=discord.Color.blue())
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="ลบรูปภาพ", description="ลบรูปภาพเดี่ยวๆ ออกจากระบบ (ดูรหัสรูปได้จากคำสั่ง /เช็ครูป)")
@app_commands.describe(รหัสรูป="ใส่ ID ของรูปภาพที่ต้องการลบ")
async def delete_image(interaction: discord.Interaction, รหัสรูป: int):
    cursor.execute("SELECT clan_name, uploader_id FROM clan_images WHERE id = ?", (รหัสรูป,))
    result = cursor.fetchone()

    if not result:
        await interaction.response.send_message(f"❌ ไม่พบรูปภาพที่มีรหัส ID `{รหัสรูป}` ในระบบ", ephemeral=True)
        return

    clan_name, uploader_id = result

    # อนุญาตให้คนที่ส่งรูปนั้น หรือ แอดมิน ลบรูปได้
    if interaction.user.id != uploader_id and not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("❌ คุณสามารถลบได้เฉพาะรูปที่คุณเป็นคนอัปโหลดเท่านั้น (ยกเว้นแอดมิน)", ephemeral=True)
        return

    cursor.execute("DELETE FROM clan_images WHERE id = ?", (รหัสรูป,))
    db.commit()

    await interaction.response.send_message(f"✅ ลบรูปภาพรหัส ID `{รหัสรูป}` ของแคลน `{clan_name}` ออกจากระบบเรียบร้อยแล้ว!", ephemeral=True)

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

    # ลบข้อมูลแคลนและรูปภาพทั้งหมดที่ผูกอยู่
    cursor.execute("DELETE FROM clan_images WHERE clan_name = ?", (ชื่อแคลน,))
    cursor.execute("DELETE FROM clans WHERE clan_name = ?", (ชื่อแคลน,))
    db.commit()

    await interaction.response.send_message(f"✅ ลบแคลน `{ชื่อแคลน}` และรูปภาพทั้งหมดข้างในเรียบร้อยแล้ว!", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))