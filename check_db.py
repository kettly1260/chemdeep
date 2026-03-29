import sqlite3

conn = sqlite3.connect('chemdeep.db')

# 查看这个任务的论文
cursor = conn.execute("SELECT id, doi, status, raw_html_path, fetch_error FROM papers WHERE job_id='5c85d8545112' LIMIT 10")
print("任务 5c85d8545112 的论文:")
for row in cursor.fetchall():
    print(f"  id={row[0]}, status={row[2]}, path={row[3]}, error={row[4]}")

# 查看哪些论文有 raw_html_path
cursor = conn.execute("SELECT COUNT(*) FROM papers WHERE raw_html_path IS NOT NULL AND raw_html_path != ''")
print(f"\n有 HTML 路径的论文总数: {cursor.fetchone()[0]}")

# 查看有路径的论文示例
cursor = conn.execute("SELECT id, doi, raw_html_path FROM papers WHERE raw_html_path IS NOT NULL AND raw_html_path != '' LIMIT 3")
print("\n有路径的论文示例:")
for row in cursor.fetchall():
    print(f"  id={row[0]}, doi={row[1]}, path={row[2]}")
