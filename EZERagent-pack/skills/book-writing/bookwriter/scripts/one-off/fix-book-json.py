"""One-liner: rename 14장 in book.json to '책을 닫으며 — 더 멀리 차는 공'."""
import json

P = "C:\\dev\\bookwriter\\manuscripts\\soccer-mission-book\\book.json"
with open(P, "r", encoding="utf-8") as f:
    book = json.load(f)
for ch in book["chapters"]:
    if ch["file"] == "14-forward.md":
        ch["title"] = "책을 닫으며 — 더 멀리 차는 공"
with open(P, "w", encoding="utf-8") as f:
    json.dump(book, f, ensure_ascii=False, indent=2)
    f.write("\n")
print("book.json: 14-forward.md title updated")
