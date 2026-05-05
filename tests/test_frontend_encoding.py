from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_ROOTS = (REPO_ROOT / "templates", REPO_ROOT / "static")
FRONTEND_SUFFIXES = {".html", ".js", ".css", ".svg"}
IGNORED_FILES = {"tailwind.min.js"}

# Common mojibake markers produced when UTF-8 Chinese is decoded as GBK/CP936,
# plus replacement/private-use characters that should never reach the UI.
MOJIBAKE_CODEPOINTS = {
    0x20AC,  # €
    0xFFFD,  # replacement character
    0x951B,  # 锛
    0x9286,  # 銆
    0x6D60,  # 浠
    0x8BF2,  # 诲
    0x59DF,  # 姟
    0x95C3,  # 闃
    0x71B7,  # 熷
    0x57AA,  # 垪
    0x7487,  # 璇
    0x5A63,  # 婃
    0x67C7,  # 柇
    0x9359,  # 鍙
    0x93CC,  # 鏌
    0x6427,  # 搧
    0x92D2,  # 鋒
    0x93C2,  # 鏂
    0x93B4,  # 鎴
    0x9352,  # 鍒
    0x935D,  # 鍝
    0x93BE,  # 鎾
    0x9418,  # 鐘
    0x9410,  # 鐐
    0x9428,  # 鐨
    0x95BF,  # 閿
}


def _frontend_files() -> list[Path]:
    files: list[Path] = []
    for root in FRONTEND_ROOTS:
        for path in root.rglob("*"):
            if path.is_file() and path.suffix.lower() in FRONTEND_SUFFIXES and path.name not in IGNORED_FILES:
                files.append(path)
    return sorted(files)


def test_frontend_files_are_utf8_and_free_of_mojibake():
    offenders: list[str] = []
    suspicious = {chr(codepoint) for codepoint in MOJIBAKE_CODEPOINTS}

    for path in _frontend_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            offenders.append(f"{path.relative_to(REPO_ROOT)} is not UTF-8: {exc}")
            continue

        for line_no, line in enumerate(text.splitlines(), 1):
            found = sorted({char for char in line if char in suspicious or "\ue000" <= char <= "\uf8ff"})
            if found:
                markers = " ".join(f"U+{ord(char):04X}" for char in found)
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{line_no} contains mojibake markers {markers}")

    assert offenders == []
