"""检查 DOI 去重问题"""
import sqlite3

conn = sqlite3.connect('chemdeep.db')
conn.row_factory = sqlite3.Row

# 获取全局已抓取的 DOI
cursor = conn.execute("SELECT DISTINCT LOWER(doi) as doi FROM papers WHERE status='fetched' AND doi IS NOT NULL")
fetched_dois = {row["doi"] for row in cursor.fetchall()}
print(f"全局已抓取 DOI 数量: {len(fetched_dois)}")

# 获取新任务的 DOI
cursor = conn.execute("SELECT LOWER(doi) as doi FROM papers WHERE job_id='326d1a20ce34' AND doi IS NOT NULL")
new_dois = [row["doi"] for row in cursor.fetchall()]
print(f"新任务 DOI 数量: {len(new_dois)}")

# 检查匹配
matched = 0
not_matched = 0
for doi in new_dois[:10]:
    if doi in fetched_dois:
        matched += 1
        print(f"  匹配: {doi}")
    else:
        not_matched += 1
        print(f"  未匹配: {doi}")

print(f"\n前10个 DOI: 匹配 {matched}, 未匹配 {not_matched}")

# 检查新任务论文的状态
cursor = conn.execute("SELECT status, COUNT(*) as cnt FROM papers WHERE job_id='326d1a20ce34' GROUP BY status")
print("\n新任务论文状态分布:")
for row in cursor.fetchall():
    print(f"  {row['status']}: {row['cnt']}")
