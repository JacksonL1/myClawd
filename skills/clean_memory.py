"""
clean_memory.py
一次性清理 skill_memory 表中已有记录：
  - python3 → python 标准化
  - 合并重复命令
在项目根目录执行：python clean_memory.py
"""
import re
import sqlite3
from pathlib import Path

DB_PATH = "./data/superchat.db"

if not Path(DB_PATH).exists():
    print(f"数据库不存在: {DB_PATH}")
    exit()

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    "SELECT id, skill_name, command, success_count, last_used_at FROM skill_memory"
).fetchall()
print(f"清理前记录数: {len(rows)}")

for r in rows:
    cmd = r["command"]
    normalized = re.sub(r"\bpython3\b", "python", cmd).strip()
    normalized = re.sub(r" {2,}", " ", normalized)
    if normalized != cmd:
        conn.execute("UPDATE skill_memory SET command=? WHERE id=?", (normalized, r["id"]))
        print(f"  标准化: {cmd[:70]}")
        print(f"       → {normalized[:70]}")

conn.commit()

# 合并标准化后重复的记录
rows2 = conn.execute("""
    SELECT skill_name, command,
           SUM(success_count) AS total,
           MAX(last_used_at)  AS latest
    FROM skill_memory
    GROUP BY skill_name, command
""").fetchall()

conn.execute("DELETE FROM skill_memory")
for r in rows2:
    conn.execute(
        "INSERT INTO skill_memory(skill_name, command, success_count, last_used_at) VALUES(?,?,?,?)",
        (r["skill_name"], r["command"], r["total"], r["latest"])
    )
conn.commit()
conn.close()

print(f"\n清理后记录数: {len(rows2)}")
for r in rows2:
    print(f"  [{r['total']}次] {r['command'][:80]}")