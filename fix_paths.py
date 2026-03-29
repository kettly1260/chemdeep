"""修复数据库中重复的路径"""
import sqlite3

conn = sqlite3.connect('chemdeep.db')

# 修复重复路径
cursor = conn.execute("""
    SELECT id, raw_html_path FROM papers 
    WHERE raw_html_path LIKE '%data\\library\\data\\library%'
    OR raw_html_path LIKE '%data/library/data/library%'
""")

rows = cursor.fetchall()
print(f"需要修复的重复路径数量: {len(rows)}")

for row in rows:
    paper_id = row[0]
    old_path = row[1]
    new_path = old_path.replace("data\\library\\data\\library\\", "data\\library\\")
    new_path = new_path.replace("data/library/data/library/", "data/library/")
    
    conn.execute("UPDATE papers SET raw_html_path = ? WHERE id = ?", (new_path, paper_id))

conn.commit()
print(f"已修复 {len(rows)} 条记录")

# 验证
cursor = conn.execute("SELECT raw_html_path FROM papers WHERE raw_html_path IS NOT NULL LIMIT 3")
print("\n修复后的路径示例:")
for row in cursor.fetchall():
    print(f"  {row[0]}")
