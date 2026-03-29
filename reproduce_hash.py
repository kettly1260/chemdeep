
import hashlib
import re

goal = "B(9,12)-(芘-5-噻吩-2)2-邻-碳硼烷是否可以作为Fe3+的荧光探针?如果不行还需要做那些修改？除此之外还可以有哪些可以预见的能做成器件或者可以实现应用的可能。进行预测"

def norm_old(g):
    text = "".join(g.lower().split())
    text = text.strip("?!.。？！")
    return text

def norm_new(g):
    text = "".join(g.lower().split())
    text = re.sub(r'[?!.,。？！，]', '', text)
    return text

def get_hash(t):
    return hashlib.md5(t.encode('utf-8')).hexdigest()

n_old = norm_old(goal)
h_old = get_hash(n_old)

n_new = norm_new(goal)
h_new = get_hash(n_new)

print(f"Goal: {goal[:20]}...")
print(f"Old Norm: {n_old[:50]}...")
print(f"Old Hash: {h_old}")
print(f"New Norm: {n_new[:50]}...")
print(f"New Hash: {h_new}")

expected_check = "7d3d5a5974f7bcb38d97b815a" # from log (truncated?)
expected_add = "1a044487" # from log (truncated)

print(f"Match Check? {h_old.startswith('7d3d') or h_new.startswith('7d3d')}")
print(f"Match Add? {h_old.startswith('1a04') or h_new.startswith('1a04')}")
