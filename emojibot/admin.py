"""관리자 웹 계정 설정. 설치 스크립트가 호출하며, 비밀번호를 잊었을 때도 쓴다.

    cd /opt/emoji-bot && sudo -u emojibot bash -c 'set -a; . /etc/emoji-bot/emoji-bot.env; set +a; \
        exec .venv/bin/python -m emojibot.admin --reset'
"""
import getpass
import os
import sys

from werkzeug.security import generate_password_hash

from . import db


def main():
    db.init()
    reset = "--reset" in sys.argv
    with db.conn() as c:
        exists = c.execute("SELECT 1 FROM admin WHERE id=1").fetchone()
        if exists and not reset:
            print("관리자 계정이 이미 있어 그대로 둡니다. (웹의 계정 메뉴에서 변경 가능)")
            return
        user = os.environ.get("ADMIN_USER") or input("관리자 아이디 [admin]: ").strip() or "admin"
        pw = os.environ.get("ADMIN_PW") or getpass.getpass("관리자 비밀번호 (8자 이상): ")
        if len(pw) < 8:
            sys.exit("비밀번호는 8자 이상이어야 합니다.")
        c.execute("INSERT OR REPLACE INTO admin(id, username, pw_hash) VALUES (1, ?, ?)",
                  (user, generate_password_hash(pw)))
    print(f"관리자 계정을 설정했습니다: {user}")


if __name__ == "__main__":
    main()
