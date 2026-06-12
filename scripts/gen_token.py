#!/usr/bin/env python3
"""Token 生成器。管理员运行此脚本为用户生成 bearer token。

Usage:
    python3 scripts/gen_token.py alice
    # 输出 Token: nkb_alice_xxx...
    #      Hash:  sha256...
    # 把 Hash 写入 auth/users.toml，把 Token 发给用户
"""

import sys
import secrets
import hashlib

if len(sys.argv) < 2:
    print("Usage: python3 scripts/gen_token.py <username>")
    sys.exit(1)

user = sys.argv[1]
tok = f"nkb_{user}_" + secrets.token_urlsafe(16)
h = hashlib.sha256(tok.encode()).hexdigest()

print(f"Token: {tok}")
print(f"Hash:  {h}")
print()
print(f"写入 auth/users.toml:")
print(f'{user} = "{h}"')
