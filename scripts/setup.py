#!/usr/bin/env python3
"""nollmkb interactive setup — configure and initialize the knowledge base.

Usage:
    uv run python3 scripts/setup.py
"""

import subprocess
import shutil
from pathlib import Path


# ============ detection ============

def _detect_cuda() -> bool:
    return shutil.which("nvidia-smi") is not None


def _detect_tailscale() -> tuple[bool, str]:
    ip = ""
    try:
        result = subprocess.run(
            ["tailscale", "ip", "-4"],
            capture_output=True, text=True, timeout=5,
        )
        ip = result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return bool(ip), ip


def _detect_disk(path: str) -> tuple[int, str]:
    """Return (free_gb, status_label)."""
    try:
        usage = shutil.disk_usage(path)
        free = usage.free // (2**30)
        if free < 5:
            return free, "red — 低于 5 GB"
        elif free < 20:
            return free, "yellow — 建议清理"
        return free, "ok"
    except Exception:
        return 0, "unknown"


# ============ UI helpers ============

def _prompt(text: str, default: str = "") -> str:
    suffix = f" [{default}]: " if default else ": "
    raw = input(text + suffix).strip()
    return raw if raw else default


def _prompt_yesno(text: str, default: bool = True) -> bool:
    yn = "Y/n" if default else "y/N"
    raw = input(f"{text} [{yn}]: ").strip().lower()
    if not raw:
        return default
    return raw.startswith("y")


# ============ state management ============

def _load_env(env_file: Path) -> dict[str, str]:
    """Parse existing .env into {KEY: value}. Returns {} if missing."""
    cfg: dict[str, str] = {}
    if not env_file.exists():
        return cfg
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            k, v = line.split("=", 1)
            cfg[k.strip()] = v.strip()
    return cfg


def _load_users(users_file: Path) -> list[str]:
    """Return list of usernames from users.toml. Returns [] if missing."""
    if not users_file.exists():
        return []
    try:
        import tomllib
        raw = tomllib.loads(users_file.read_text(encoding="utf-8"))
        return list(raw.get("users", {}).keys())
    except Exception:
        return []


# ============ user management ============

def _run_gen_token(username: str) -> tuple[str, str] | None:
    """Call scripts/gen_token.py, return (token, hash) or None on failure."""
    script = Path(__file__).resolve().parent / "gen_token.py"
    try:
        result = subprocess.run(
            ["uv", "run", "python3", str(script), username],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            print(f"    ! gen_token.py 失败: {result.stderr.strip()}")
            return None
        token_str = hash_str = ""
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.startswith("Token:"):
                token_str = line.removeprefix("Token:").strip()
            elif line.startswith("Hash:"):
                hash_str = line.removeprefix("Hash:").strip()
        return (token_str, hash_str) if token_str and hash_str else None
    except FileNotFoundError:
        print("    ! 未找到 gen_token.py")
        return None
    except subprocess.TimeoutExpired:
        print("    ! gen_token.py 超时")
        return None


def _write_users_toml(users_file: Path, entries: dict[str, str]) -> None:
    """Write/update auth/users.toml. Merges with existing entries."""
    existing: dict[str, str] = {}
    if users_file.exists():
        try:
            import tomllib
            raw = tomllib.loads(users_file.read_text(encoding="utf-8"))
            existing = raw.get("users", {})
        except Exception:
            pass
    existing.update(entries)

    lines = [
        "# auth/users.toml — 用户 bearer token (sha256 hash)",
        "# 管理员用 gen_token.py 生成 token 发给用户。",
        "[users]",
    ]
    for user, h in existing.items():
        lines.append(f'{user} = "{h}"')
    users_file.parent.mkdir(parents=True, exist_ok=True)
    users_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ============ main ============

def main() -> None:
    nollmkb_dir = Path(__file__).resolve().parent.parent
    env_file = nollmkb_dir / ".env"
    users_file = nollmkb_dir / "auth" / "users.toml"

    has_cuda = _detect_cuda()
    has_tailscale, ts_ip = _detect_tailscale()
    free_gb, disk_status = _detect_disk(str(nollmkb_dir.parent))

    existing = _load_env(env_file)
    current_users = _load_users(users_file)
    cfg: dict[str, str] = dict(existing)

    print()
    print("=" * 60)
    print("  nollmkb setup — 初始化配置")
    print("=" * 60)
    print()
    print("按 Enter 接受方括号中的默认值。")

    # ---- 1/6 环境检测 ----
    print()
    print("-" * 40)
    print("[1/6]  环境检测")
    print()
    cuda_label = "cuda" if has_cuda else "cpu (未检测到 GPU)"
    print(f"  GPU:      {cuda_label}")
    ts_label = ts_ip if has_tailscale else "未检测到"
    print(f"  Tailscale: {ts_label}")
    print(f"  磁盘剩余: {free_gb} GB ({disk_status})")

    # ---- 2/6 监听地址 ----
    print()
    print("-" * 40)
    print("[2/6]  监听地址")
    print(f"  默认: 127.0.0.1 (仅本机访问)")
    current_host = existing.get("NOLLMKB_HOST", "")
    if current_host:
        print(f"  当前值: {current_host}")
        if not _prompt_yesno("  修改?", False):
            cfg["NOLLMKB_HOST"] = current_host
            print()
            # skip to next step
            pass
        else:
            current_host = ""

    if not cfg.get("NOLLMKB_HOST"):
        if has_tailscale:
            print(f"  检测到 Tailscale IP: {ts_ip}")
            use_remote = _prompt_yesno("  允许远程访问 (Tailscale)?", True)
            if use_remote:
                cfg["NOLLMKB_HOST"] = _prompt("    Tailscale IP", ts_ip)
        else:
            use_remote = _prompt_yesno("  允许远程访问? (需要 Tailscale)", False)
            if use_remote:
                cfg["NOLLMKB_HOST"] = _prompt("    IP 或 0.0.0.0", "0.0.0.0")
    if not cfg.get("NOLLMKB_HOST"):
        cfg["NOLLMKB_HOST"] = "127.0.0.1"
    print(f"  → {cfg['NOLLMKB_HOST']}")

    # ---- 3/6 计算设备 ----
    print()
    print("-" * 40)
    print("[3/6]  计算设备")
    current_dev = existing.get("NOLLMKB_DEVICE", "")
    if current_dev:
        print(f"  当前值: {current_dev}")
        if not _prompt_yesno("  修改?", False):
            cfg["NOLLMKB_DEVICE"] = current_dev
            print()
            # skip
            pass
        else:
            current_dev = ""

    if not cfg.get("NOLLMKB_DEVICE"):
        cfg["NOLLMKB_DEVICE"] = "cuda" if has_cuda else "cpu"
        if has_cuda:
            print(f"  检测到 GPU，默认: cuda")
        else:
            print(f"  未检测到 GPU，默认: cpu (较慢)")
        choice = _prompt("  设备 (cuda/cpu)", cfg["NOLLMKB_DEVICE"])
        if choice:
            cfg["NOLLMKB_DEVICE"] = choice
    print(f"  → {cfg['NOLLMKB_DEVICE']}")

    # ---- 4/6 用户管理 ----
    print()
    print("-" * 40)
    print("[4/6]  用户管理")
    print()
    print(f"  认证方式: Bearer token (auth/users.toml)")
    print(f"  不配用户 → 免认证开放模式 (开发环境)")
    print(f"  示例: uv run python3 scripts/gen_token.py alice")
    print(f"        → Token: nkb_alice_xxxx...   (发给用户)")
    print(f"        → Hash:  sha256...           (写入 users.toml)")

    if current_users:
        print()
        print(f"  当前用户 ({len(current_users)}): {', '.join(current_users)}")
        if not _prompt_yesno("  修改用户列表?", False):
            print("  → 保持现有")
            print()
            # users already set, skip to next
            pass
        else:
            current_users = []

    if not current_users:
        if not _prompt_yesno("  添加用户?", True):
            print("  → 跳过 — 免认证模式")
        else:
            raw = _prompt("  用户名 (空格分隔, e.g. alice bob)")
            names = [n.strip() for n in raw.split() if n.strip()]
            if names:
                if not _prompt_yesno(f"  为 {', '.join(names)} 生成 token?", True):
                    names = []

                new_entries: dict[str, str] = {}
                added = 0
                for name in names:
                    result = _run_gen_token(name)
                    if result:
                        token_str, hash_str = result
                        new_entries[name] = hash_str
                        added += 1
                        print(f"    [new] {name}")
                        print(f"          Token: {token_str}  (发给用户)")
                        print(f"          Hash:  {hash_str[:16]}...")
                if new_entries:
                    _write_users_toml(users_file, new_entries)
                    print(f"  → 已写入 {len(new_entries)} 个用户到 {users_file}")
                else:
                    print("  → 未输入有效用户名 — 跳过")

    # ---- 5/6 自定义路径 ----
    print()
    print("-" * 40)
    print("[5/6]  自定义路径 (Enter 跳过使用默认值)")
    custom = _prompt_yesno("  自定义存储目录?", False)
    if custom:
        cur_docs = existing.get("NOLLMKB_DOCS_DIR", "")
        if cur_docs:
            print(f"    文档目录: 当前 {cur_docs}")
        if v := _prompt("    文档目录 (默认 ../inputs)", cur_docs or "../inputs"):
            cfg["NOLLMKB_DOCS_DIR"] = v
        cur_chroma = existing.get("NOLLMKB_KB_DIR", "")
        if cur_chroma:
            print(f"    ChromaDB:  当前 {cur_chroma}")
        if v := _prompt("    ChromaDB (默认 ../chromadb_storage)", cur_chroma or "../chromadb_storage"):
            cfg["NOLLMKB_KB_DIR"] = v
        cur_wiki = existing.get("NOLLMKB_WIKI_DIR", "")
        if cur_wiki:
            print(f"    Wiki:      当前 {cur_wiki}")
        if v := _prompt("    Wiki (默认 ../wiki)", cur_wiki or "../wiki"):
            cfg["NOLLMKB_WIKI_DIR"] = v
        cur_log = existing.get("NOLLMKB_LOG_DIR", "")
        if cur_log:
            print(f"    日志:      当前 {cur_log}")
        if v := _prompt("    日志 (默认 ../logs)", cur_log or "../logs"):
            cfg["NOLLMKB_LOG_DIR"] = v
        cur_users_path = existing.get("NOLLMKB_USERS_FILE", "")
        if cur_users_path:
            print(f"    用户文件:  当前 {cur_users_path}")
        if v := _prompt("    用户文件 (默认 auth/users.toml)", cur_users_path or ""):
            cfg["NOLLMKB_USERS_FILE"] = v
    else:
        print("  → 使用默认路径")

    # ---- 6/6 生成并写入 ----
    print()
    print("-" * 40)
    print("[6/6]  生成 .env")

    env_lines = ["# nollmkb configuration — generated by scripts/setup.py", ""]
    all_keys = [
        "NOLLMKB_HOST", "NOLLMKB_DEVICE",
        "NOLLMKB_USERS_FILE", "NOLLMKB_DOCS_DIR", "NOLLMKB_KB_DIR",
        "NOLLMKB_WIKI_DIR", "NOLLMKB_LOG_DIR",
    ]
    for k in all_keys:
        if k in cfg:
            env_lines.append(f"{k}={cfg[k]}")
        else:
            env_lines.append(f"#{k}=")

    env_lines += [
        "",
        "# Full reference — uncomment and edit as needed:",
        "#NOLLMKB_COLLECTION=nollmkb",
        "#NOLLMKB_LOG_LEVEL=INFO",
    ]
    content = "\n".join(env_lines) + "\n"

    print()
    print("=" * 60)
    print("  预览 — 将写入 .env:")
    print("=" * 60)
    for line in content.strip().split("\n"):
        print(f"  | {line}")
    print()

    if env_file.exists():
        print(f"  ⚠  {env_file} 已存在，将被覆盖。")
    else:
        print(f"  ✓ {env_file} 不存在 — 安全写入。")

    print()
    if _prompt_yesno("写入 .env?", True):
        env_file.write_text(content, encoding="utf-8")
        print(f"  ✓ 已写入 {env_file}")
    else:
        print("  → 跳过。你可以手动复制上方预览内容到 .env")

    print()
    print("=" * 60)
    print("  完成。下一步:")
    print("    uv run python3 server.py")
    print("=" * 60)
    print()


if __name__ == "__main__":
    main()
