"""기록 밖을 보는 도구 넷 (앞길 살피기 · ahead.py). 2단의 다른 일(빠진 요청 · 요청 외 변경 · 이어 가기)은 쓰지 않아요.

- list_files: 그 대화의 작업 폴더에 있는 파일 목록
- search_files: 그 폴더의 글 파일에서 낱말이 든 줄 찾기 (계획 · 일정 · 남은 일이 긴 문서의 뒤쪽에 있어도 찾게)
- read_file: 그 폴더에 있는 글 파일의 한 부분 (앞부분, 또는 ‘경로:줄 번호’부터)
- look_up: 웹에서 찾아보기 (GADAK_AHEAD_WEB=1로 켰을 때만. 엔진이 검색해서 출처와 함께 돌려줘요)

파일은 읽기만 하고, 읽은 글은 대화 글과 같은 곳(엔진)에만 보내요. 읽지 않는 것:
- 작업 폴더 밖의 파일 (바로 가기로 밖을 가리키는 것 포함)
- 작업 폴더가 홈 · 바탕화면 · 문서 · 다운로드처럼 넓은 곳이면 아무것도 (프로젝트 폴더가 아니에요)
- 깃이 무시하는 파일(.gitignore) — 올리지 않기로 한 파일은 가닥도 읽지 않아요. 작업 폴더 안에 저장소가 들어 있을 때도 같아요
- 이름이 비밀번호 · 키 · 내 PC 전용 파일처럼 보이는 것 (.env · *.pem · *.local.* …)
- 글이 아닌 파일, 너무 큰 파일
"""
import os
import re
import subprocess
import unicodedata
from pathlib import Path

NAMES = ("list_files", "search_files", "read_file", "look_up")
HEADING = re.compile(r"^(#{1,4})\s+(.+?)\s*#*$")       # 마크다운 제목
HEADS_MAX, HEADS_FILES = 40, 60                       # 문서의 목차로 돌려주는 제목 수 · 훑는 문서 수
FILE_TOOLS = ("list_files", "search_files", "read_file")

LIST_MAX = 80                 # 한 번에 보여 주는 파일 수
HITS_MAX, HITS_PER_FILE, HIT_CLIP = 30, 8, 160      # search_files가 돌려주는 줄
SEARCH_FILES = 400            # 낱말을 찾을 때 훑는 파일 수의 한도
READ_BYTES = 300_000          # 이보다 큰 파일은 읽지 않아요
READ_CHARS = 6000             # 읽은 글은 앞에서 이만큼만 돌려줘요
QUESTION_MAX = 200
FOUND_MAX = 6
GIT_SECONDS = 5
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", ".next", ".nuxt", ".idea",
             ".vscode", "target", ".gradle", ".cache", ".pytest_cache", ".mypy_cache", "DerivedData", "Pods"}
# 비밀이 들었을 법한 이름. 깃이 무시하지 않아도 읽지 않아요
SECRET = re.compile(
    r"(^|/)(\.env(\..*)?|\.npmrc|\.netrc|\.pypirc|id_(rsa|dsa|ecdsa|ed25519)[^/]*|[^/]*\.(pem|key|p12|pfx|keystore|jks|kdbx)"
    r"|[^/]*(secret|credential|password|passwd|token)[^/]*|[^/]*\.local(\.[^/]*)?)$", re.I)
TEXT = {".md", ".txt", ".rst", ".py", ".js", ".mjs", ".ts", ".tsx", ".jsx", ".json", ".toml", ".yaml", ".yml", ".html",
        ".css", ".scss", ".swift", ".java", ".kt", ".go", ".rs", ".rb", ".php", ".c", ".h", ".cpp", ".cs", ".sh",
        ".sql", ".cfg", ".ini", ".tex", ".r", ".command", ".mdc", ".vue", ".svelte", ".gradle", ".xml", ".plist"}
PLAIN = {"readme", "makefile", "dockerfile", "license", "changelog", "procfile", "gemfile"}   # 확장자 없는 글 파일
# 홈 바로 아래의 이런 폴더는 프로젝트 폴더가 아니에요. 여기서 연 대화에서는 파일을 읽지 않아요
BROAD = {"Desktop", "Documents", "Downloads", "Library", "Movies", "Music", "Pictures", "Public", "Applications"}


def nfc(text) -> str:
    """파일 이름의 한글을 한 가지 표기로. macOS는 자모를 풀어서(NFD) 돌려주는데, 엔진은 붙여서(NFC) 적어요."""
    return unicodedata.normalize("NFC", str(text or ""))


def root(ctx):
    """그 대화의 작업 폴더. 없으면 None (웹 대화에는 폴더가 없어요)."""
    cwd = ctx.chat["cwd"] if ctx.chat is not None else None
    if not cwd:
        return None
    path = Path(cwd).expanduser()
    if not path.is_dir() or too_broad(path):
        return None
    return path


def too_broad(path) -> bool:
    """홈 · 바탕화면 · 문서처럼 프로젝트 폴더가 아닌 넓은 곳인지."""
    try:
        real, home = Path(path).resolve(), Path.home().resolve()
    except OSError:
        return True
    if real == home or real in home.parents or real.parent == real:
        return True                                   # 홈과 그 위쪽 (/Users · /)
    return real.parent == home and real.name in BROAD


def _git(base, *args):
    """깃 명령 하나. 저장소가 아니거나 깃이 없으면 None."""
    try:
        out = subprocess.run(["git", "-C", str(base), *args], capture_output=True, timeout=GIT_SECONDS)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out


def _tracked(base):
    """깃이 아는 파일(올린 것 + 무시하지 않는 새 파일). 저장소가 아니면 None."""
    out = _git(base, "ls-files", "--cached", "--others", "--exclude-standard", "-z")
    if out is None or out.returncode != 0:
        return None
    return [nfc(name) for name in out.stdout.decode("utf-8", "replace").split("\0") if name]


def _ignored(base, rel) -> bool:
    """깃이 무시하는 파일인지. 그 파일이 든 폴더에서 물어서, 작업 폴더 안에 들어 있는 저장소의 규칙도 지켜요."""
    path = Path(base) / rel
    out = _git(path.parent, "check-ignore", "-q", "--", path.name)
    return out is not None and out.returncode == 0


def _hidden(rel) -> bool:
    parts = Path(rel).parts
    return any(part in SKIP_DIRS for part in parts[:-1]) or bool(SECRET.search(rel))


def _texty(rel) -> bool:
    path = Path(rel)
    return path.suffix.lower() in TEXT or (not path.suffix and path.name.lower() in PLAIN)


def _walk(base, depth=3):
    """깃 저장소가 아닐 때: 폴더를 얕게 훑어요. 안에 저장소가 들어 있으면 그 안은 깃이 아는 파일만 봐요."""
    found = []
    for folder, dirs, names in os.walk(base):
        rel = Path(folder).relative_to(base)
        if rel.parts and (Path(folder) / ".git").exists():
            dirs[:] = []                              # 안에 든 저장소: 무시하기로 한 파일은 여기서도 보지 않아요
            found += [nfc(rel / name) for name in _tracked(folder) or []]
            continue
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS and not d.startswith("."))
        if len(rel.parts) >= depth:
            dirs[:] = []
        found += [nfc(rel / name) if rel.parts else nfc(name) for name in sorted(names)]
        if len(found) > 4000:
            break
    return found


def _readable(base) -> list:
    """읽어도 되는 글 파일들. 얕은 곳부터: README · 설정 같은 큰 그림이 먼저 와요."""
    names = _tracked(base)
    if names is None:
        names = _walk(base)
    names = [n for n in names if not _hidden(n) and _texty(n)]
    names.sort(key=lambda n: (n.count("/"), n.lower()))
    return names


def _text(base, rel):
    """읽어도 되는 파일의 글. 너무 크거나 글이 아니면 None."""
    path = base / rel
    try:
        if path.is_symlink() or path.stat().st_size > READ_BYTES:
            return None
        return path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def list_files(ctx, arg=None) -> dict:
    base = root(ctx)
    if base is None:
        return {"error": "이 대화에는 작업 폴더가 없어요."}
    under = nfc(arg).strip().strip("/")
    if under in (".", "this", "지금"):
        under = ""
    if under and (".." in Path(under).parts or Path(under).is_absolute()):
        return {"error": "작업 폴더 안의 경로만 볼 수 있어요."}
    names = [n for n in _readable(base) if not under or n == under or n.startswith(under + "/")]
    files = []
    for name in names[:LIST_MAX]:
        try:
            size = (base / name).stat().st_size
        except OSError:
            continue
        files.append({"path": name, "size": size})
    out = {"folder": base.name, "files": files}
    if under:
        out["under"] = under
    if len(names) > LIST_MAX:
        tops = {}
        for name in names[LIST_MAX:]:
            top = name.split("/", 1)[0] if "/" in name else "."
            tops[top] = tops.get(top, 0) + 1
        out["more"] = dict(sorted(tops.items(), key=lambda kv: -kv[1])[:12])      # 더 있는 곳. arg에 폴더를 넣으면 그 안을 봐요
    if not files:
        out["note"] = "읽을 수 있는 글 파일이 없어요"
    return out


def search_files(ctx, arg=None) -> dict:
    """작업 폴더의 글 파일에서 낱말이 든 줄. 낱말 여럿은 띄어 써요(하나라도 든 줄). 많이 든 파일부터 보여 줘요."""
    words = [w.lower() for w in str(arg or "").split()[:4] if len(w) >= 2]
    if not words:
        return {"error": "찾을 낱말을 arg에 넣어 주세요 (두 글자 이상)."}
    return find_lines(ctx, words)


def find_lines(ctx, words) -> dict:
    """낱말 중 하나라도 든 줄을, 많이 든 파일부터. search_files와 가닥이 먼저 두는 수(ahead.opening)가 같이 써요."""
    base = root(ctx)
    if base is None:
        return {"error": "이 대화에는 작업 폴더가 없어요."}
    words = [w.lower() for w in words]
    found = []
    for name in _readable(base)[:SEARCH_FILES]:
        text = _text(base, name)
        if text is None:
            continue
        lines = [(n, line) for n, line in enumerate(text.splitlines(), 1) if any(w in line.lower() for w in words)]
        if lines:
            found.append((name, lines))
    found.sort(key=lambda item: -len(item[1]))
    hits = []
    for name, lines in found:
        for n, line in lines[:HITS_PER_FILE]:
            if len(hits) < HITS_MAX:
                hits.append({"path": name, "line": n, "text": " ".join(line.split())[:HIT_CLIP]})
    out = {"query": " ".join(words), "hits": hits, "files": len(found)}
    if sum(len(lines) for _, lines in found) > len(hits):
        out["more"] = sum(len(lines) for _, lines in found) - len(hits)     # 더 있어요. 낱말을 좁히거나 read_file로 ‘경로:줄’부터 읽어요
    if not hits:
        out["note"] = "그 낱말이 든 줄이 없어요"
    return out


def headings(ctx, words) -> dict:
    """문서(마크다운)의 제목 중 낱말이 든 것을 줄 번호와 함께 — 계획 · 일정 · 미정 · 규칙이 어디 적혀 있는지 보는 목차예요.
    가닥이 먼저 두는 수(ahead.opening)가 써요. 얕은 곳의 문서부터 봐요."""
    base = root(ctx)
    if base is None:
        return {"error": "이 대화에는 작업 폴더가 없어요."}
    words = [w.lower() for w in words]
    heads, files = [], 0
    for name in [n for n in _readable(base) if n.lower().endswith((".md", ".mdc", ".rst", ".txt"))][:HEADS_FILES]:
        text = _text(base, name)
        if text is None:
            continue
        mine = []
        for n, line in enumerate(text.splitlines(), 1):
            match = HEADING.match(line)
            if match and any(w in match.group(2).lower() for w in words):
                mine.append({"path": name, "line": n, "text": " ".join(match.group(2).split())[:HIT_CLIP]})
        if mine:
            files += 1
            heads += mine[:HITS_PER_FILE]
    out = {"query": " ".join(words), "hits": heads[:HEADS_MAX], "files": files}
    if not heads:
        out["note"] = "그 낱말이 든 제목이 없어요"
    return out


def read_file(ctx, arg=None) -> dict:
    base = root(ctx)
    if base is None:
        return {"error": "이 대화에는 작업 폴더가 없어요."}
    rel, start = nfc(arg).strip(), 1
    spot = re.fullmatch(r"(.+?):(\d+)", rel)
    if spot:                                       # ‘경로:줄 번호’ — 그 줄의 조금 앞부터 읽어요
        rel, start = spot.group(1).strip(), max(1, int(spot.group(2)) - 2)
    if not rel:
        return {"error": "읽을 파일의 경로를 arg에 넣어 주세요 (list_files에 나온 값)."}
    path = Path(rel)
    if path.is_absolute() or ".." in path.parts:
        return {"error": "작업 폴더 안의 경로만 읽을 수 있어요."}
    try:
        real, home = (base / path).resolve(), base.resolve()
    except OSError:
        return {"error": f"‘{rel}’을 찾지 못했어요."}
    if home != real and home not in real.parents:
        return {"error": "작업 폴더 밖을 가리키는 파일은 읽지 않아요."}
    if not real.is_file():
        return {"error": f"‘{rel}’이라는 파일이 없어요. list_files로 경로를 확인하세요."}
    inside = nfc(real.relative_to(home))
    if _hidden(inside) or _hidden(rel):
        return {"error": "비밀이 들었을 수 있는 파일이라 읽지 않아요."}
    if _ignored(base, rel):
        return {"error": "깃이 무시하는 파일은 읽지 않아요."}
    if not _texty(inside):
        return {"error": "글 파일만 읽어요."}
    if real.stat().st_size > READ_BYTES:
        return {"error": "너무 큰 파일이라 읽지 않아요."}
    try:
        text = real.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return {"error": "글로 읽을 수 없는 파일이에요."}
    lines = text.splitlines(keepends=True)
    part = "".join(lines[start - 1:])
    out = {"path": rel, "lines": len(lines), "text": part[:READ_CHARS]}
    if start > 1:
        out["from_line"] = start
    if len(part) > READ_CHARS:
        out["cut"] = True          # 뒤가 더 있어요
    return out


def look_up(ctx, arg=None) -> dict:
    if ctx.lookup is None:
        return {"error": "웹에서 찾아보기는 꺼져 있어요."}
    question = " ".join(str(arg or "").split())[:QUESTION_MAX]
    if not question:
        return {"error": "찾아볼 물음을 arg에 넣어 주세요."}
    result = ctx.lookup(question) or {}
    found = [{"line": " ".join(str(f.get("line") or "").split()), "source": str(f.get("source") or "").strip()}
             for f in result.get("found") or [] if isinstance(f, dict)]
    found = [f for f in found if f["line"] and f["source"]][:FOUND_MAX]
    out = {"question": question, "found": found, "searched": [str(s) for s in result.get("searched") or []][:6]}
    if result.get("dropped"):
        out["dropped"] = result["dropped"]     # 검색 결과에 없는 주소를 출처로 대서 버린 줄 수
    if not found:
        out["note"] = "찾은 것이 없어요"
    return out


RUN = {"list_files": list_files, "search_files": search_files, "read_file": read_file, "look_up": look_up}


def summary(tool, result) -> str:
    """판단 기록에 남기는 ‘본 것’ 한 줄."""
    if result.get("error"):
        return result["error"]
    if tool == "list_files":
        return f"파일 {len(result['files'])}개" + (" (더 있음)" if result.get("more") else "")
    if tool == "search_files":
        return f"파일 {result['files']}개에서 {len(result['hits'])}줄" + (" (더 있음)" if result.get("more") else "")
    if tool == "read_file":
        return f"{result['path']} · {result['lines']}줄" + (" (한 부분만)" if result.get("cut") or result.get("from_line") else "")
    return f"찾은 것 {len(result['found'])}줄 · 검색 {len(result['searched'])}번"
