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

# ==================== เมนูดรอปดาวน์เลือกแคลนสำหรับหน้าแสดงผลรวม ====================
class ClanSelectDropdown(discord.ui.Select):
    def __init__(self, clans_data):
        options = []
        if not clans_data:
            options.append(discord.SelectOption(label="ยังไม่มีรูปในระบบ", value="no_clan", description="กรุณาสร้างรูปก่อน"))
        else:
            for c_name, c_count in clans_data:
                label_name = c_name[:100]
                options.append(discord.SelectOption(
                    label=label_name, 
                    description=f"มีรูปภาพสะสม {c_count} รูป", 
                    emoji="🛡️",
                    value=c_name
                ))
        super().__init__(placeholder="เลือกดูรูปภาพ", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        if self.values[0] == "no_clan":
            await interaction.response.send_message("❌ ยังไม่มีรูปในระบบ", ephemeral=True)
            return

        selected_clan = self.values[0]
        cursor.execute("SELECT id, image_url, uploader_id FROM clan_images WHERE clan_name = ?", (selected_clan,))
        images = cursor.fetchall()

        if not images:
            await interaction.response.send_message(f"❌ ยังไม่มีรูปภาพสกอร์ของแคลน `{selected_clan}` ในระบบ", ephemeral=True)
            return

        view = ClanImageView(images, selected_clan)
        embed = view.create_embed()
        
        # ส่งรูปภาพพร้อมปุ่ม และแจ้งให้ผู้ใช้ทราบว่าสามารถเลือกแคลนจากเมนูด้านบนซ้ำได้อีกครั้ง
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

class ClanSelectView(discord.ui.View):
    def __init__(self, clans_data):
        super().__init__(timeout=None)
        self.add_item(ClanSelectDropdown(clans_data))

# ==================== ฟังก์ชันสร้างและอัปเดต Embed สรุปภาพรวมแบบเรียลไทม์ ====================
async def update_display_panel(guild: discord.Guild):
    cursor.execute("""
        SELECT c.clan_name, COUNT(i.id) 
        FROM clans c 
        LEFT JOIN clan_images i ON c.clan_name = i.clan_name 
        GROUP BY c.clan_name
    """)
    clans_data = cursor.fetchall()

    embed = discord.Embed(
        title="🏆 รวมสกอร์ Vegas",
        description="VegasRank1",
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

    view = ClanSelectView(clans_data)

    cursor.execute("SELECT channel_id, message_id FROM display_panel WHERE id = 1")
    panel = cursor.fetchone()

    if panel:
        channel_id, message_id = panel
        channel = guild.get_channel(channel_id)
        if channel:
            try:
                message = await channel.fetch_message(message_id)
                await message.edit(embed=embed, view=view)
                return
            except Exception:
                pass

# ==================== 2. ระบบ UI ปุ่มกดเลื่อนดูรูปภาพ พร้อมปุ่มดาวน์โหลดไฟล์ตรง ====================
class ClanImageView(discord.ui.View):
    def __init__(self, images, clan_name):
        super().__init__(timeout=180)
        self.images = images
        self.clan_name = clan_name
        self.current_page = 0
        self.update_components()

    def update_components(self):
        # เคลียร์ปุ่มเก่าทั้งหมดออกก่อนสร้างใหม่
        self.clear_items()
        
        # สร้างปุ่มย้อนกลับ
        prev_btn = discord.ui.Button(label="◀️ ก่อนหน้า", style=discord.ButtonStyle.blurple, disabled=(self.current_page == 0))
        prev_btn.callback = self.prev_callback
        self.add_item(prev_btn)

        # สร้างปุ่มถัดไป
        next_btn = discord.ui.Button(label="ถัดไป ▶️", style=discord.ButtonStyle.blurple, disabled=(self.current_page == len(self.images) - 1))
        next_btn.callback = self.next_callback
        self.add_item(next_btn)

        # สร้างปุ่มดาวน์โหลดรูปภาพแบบลิงก์ตรง (กดแล้วดาวน์โหลดลงเครื่องทันที)
        img_id, img_url, uploader_id = self.images[self.current_page]
        download_btn = discord.ui.Button(label="📥 โหลดรูปภาพ", style=discord.ButtonStyle.link, url=img_url)
        self.add_item(download_btn)

    def create_embed(self):
        img_id, img_url, uploader_id = self.images[self.current_page]
        embed = discord.Embed(
            title=f"🏆 สกอร์แคลน: {self.clan_name}",
            description=f"📄 **รูปที่:** `{self.current_page + 1} / {len(self.images)}`\n🆔 **รหัสรูปภาพ (ID สำหรับใช้ลบ):** `{img_id}`\n👤 **ผู้อัปโหลด:** <@{uploader_id}>",
            color=discord.Color.green()
        )
        embed.set_image(url=img_url)
        return embed

    async def prev_callback(self, interaction: discord.Interaction):
        if self.current_page > 0:
            self.current_page -= 1
            self.update_components()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    async def next_callback(self, interaction: discord.Interaction):
        if self.current_page < len(self.images) - 1:
            self.current_page += 1
            self.update_components()
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

    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ สร้างหัวข้อสกอร์แคลน `{ชื่อแคลน}` สำเร็จแล้ว! (อัปเดตหน้าจอเรียลไทม์ให้แล้ว)", ephemeral=True)

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

    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ บันทึกรูปภาพสกอร์ของแคลน `{ชื่อแคลน}` เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="แสดงผลรวม", description="[แอดมิน] สร้างหน้าต่างแสดงรายชื่อแคลนและเมนูดรอปดาวน์เลือกดูรูปภาพแบบเรียลไทม์ในห้องนี้")
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
        title="🏆 รวมสกอร์ Vegas",
        description="VegasRank1",
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

    view = ClanSelectView(clans_data)

    message = await interaction.channel.send(embed=embed, view=view)

    cursor.execute("REPLACE INTO display_panel (id, channel_id, message_id) VALUES (1, ?, ?)", 
                   (interaction.channel.id, message.id))
    db.commit()

    await interaction.followup.send("✅ สร้างแผงแสดงผลรวมพร้อมเมนูดรอปดาวน์เรียบร้อยแล้ว!", ephemeral=True)

@bot.tree.command(name="ลบรูปภาพ", description="ลบรูปภาพเดี่ยวๆ ออกจากระบบ (ดูรหัสรูปได้จากหน้าดูรูปภาพ)")
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

    await update_display_panel(interaction.guild)

    await interaction.response.send_message(f"✅ ลบแคลน `{ชื่อแคลน}` เรียบร้อยแล้ว! (อัปเดตผลรวมให้แล้ว)", ephemeral=True)

bot.run(os.getenv("DISCORD_TOKEN"))
