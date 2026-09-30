"""봇 프로필 사진·배너를 assets/ 이미지로 설정한다. 설치 스크립트가 한 번 호출한다.
실패해도 봇 동작에는 영향이 없다 (디스코드 개발자 포털에서 직접 올려도 된다)."""
import base64
import json
import os
import urllib.request

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_uri(name):
    with open(os.path.join(HERE, "assets", name), "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def main():
    for field, name in (("avatar", "avatar.png"), ("banner", "profile_banner.png")):
        req = urllib.request.Request(
            "https://discord.com/api/v10/users/@me", method="PATCH",
            data=json.dumps({field: data_uri(name)}).encode(),
            headers={"Authorization": f"Bot {os.environ['BOT_TOKEN']}", "Content-Type": "application/json",
                     "User-Agent": "DiscordBot (emoji-bot, 1.0)"})
        try:
            urllib.request.urlopen(req, timeout=30).close()
            print(f"봇 {field} 설정 완료")
        except Exception as e:
            print(f"봇 {field} 설정 건너뜀 ({e}). 개발자 포털에서 assets/{name}을 직접 올려도 됩니다.")


if __name__ == "__main__":
    main()
