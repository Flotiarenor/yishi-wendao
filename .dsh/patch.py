import sys
try:
    sys.stdout.reconfigure(errors="replace")
except Exception:
    pass

def read(p):
    with open(p, encoding="utf-8") as f:
        return f.read().replace("\r\n", "\n")

def main():
    if len(sys.argv) < 4:
        print("usage: patch.py <target> <old_file> <new_file> [expected_count]")
        return 2
    target, oldf, newf = sys.argv[1:4]
    expected = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    old, new, text = read(oldf), read(newf), read(target)
    cands = [old]
    cands.append(old[:-1] if old.endswith("\n") else old + "\n")
    picked = None
    for c in cands:
        if text.count(c) == expected:
            picked = c
            break
    if picked is None:
        print("FAIL %s: old 出现 %d 次（期望 %d）" % (target, text.count(old), expected))
        print("--- old head ---")
        print(old[:400])
        return 1
    text = text.replace(picked, new)
    with open(target, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("OK %s: 替换 %d 处" % (target, expected))
    return 0

sys.exit(main())