"""관리용 CLI: `python -m app.cli <command>`

Web UI 없이 쓰는 관리 도구다. Discord 안에서는 `/emoticon ...` 명령을 쓴다.

  python -m app.cli init-db
  python -m app.cli preview   <url>
  python -m app.cli add       <url> <이름> [--index 1] [--emotions 황당,체념] [--keywords 아무튼]
  python -m app.cli list      [검색어]
  python -m app.cli tag       <이름> [--emotions ...] [--keywords ...] [--rename 새이름]
  python -m app.cli delete    <이름>
  python -m app.cli search    <질의>
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from app.config import settings
from app.db.base import create_all, dispose, session_scope
from app.emoticon import repository as repo
from app.emoticon import service as emoticon_service
from app.emoticon.service import DuplicateEmoticon, RegistrationError
from app.emotion.service import seed_emotions
from app.main import setup_logging
from app.search import service as search_service


def _split(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [p.strip() for p in raw.replace(",", " ").split() if p.strip()]


async def cmd_init_db(_: argparse.Namespace) -> int:
    await create_all()
    async with session_scope() as session:
        added = await seed_emotions(session)
    print(f"DB 준비 완료. 감정 태그 {added}개 추가.")
    return 0


async def cmd_preview(args: argparse.Namespace) -> int:
    result = await emoticon_service.extract_candidates(args.url)
    print(f"parser={result.parser}  후보 {len(result.candidates)}개")
    for i, candidate in enumerate(result.candidates, start=1):
        print(f"{i:3d}. {candidate.url}")
    return 0


async def cmd_add(args: argparse.Namespace) -> int:
    extracted = await emoticon_service.extract_candidates(args.url)
    if args.index > len(extracted.candidates):
        print(f"후보가 {len(extracted.candidates)}개뿐입니다.", file=sys.stderr)
        return 1
    candidate = extracted.candidates[args.index - 1]

    async with session_scope() as session:
        emoticon = await emoticon_service.register(
            session,
            name=args.name,
            image_url=candidate.url,
            source_url=extracted.source_url,
            keywords=_split(args.keywords),
            emotions=_split(args.emotions),
        )
        print(f"등록 완료 #{emoticon.id} {emoticon.name} -> {emoticon.processed_path}")
    return 0


async def cmd_list(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        found = await repo.list_all(session, query=args.query, limit=args.limit)
        total = await repo.count(session)
    for emoticon in found:
        tags = " ".join(f"#{e.tag}" for e in emoticon.emotions)
        keywords = " ".join(k.value for k in emoticon.keywords)
        print(f"#{emoticon.id:<4} {emoticon.name:<28} {tags:<30} {keywords}")
    print(f"-- {len(found)}건 표시 / 전체 {total}건")
    return 0


async def cmd_tag(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        emoticon = await repo.get_by_name(session, args.name)
        if emoticon is None:
            print(f"'{args.name}' 없음", file=sys.stderr)
            return 1
        await emoticon_service.update_metadata(
            session,
            emoticon,
            name=args.rename,
            keywords=_split(args.keywords) if args.keywords is not None else None,
            emotions=_split(args.emotions) if args.emotions is not None else None,
        )
        print(f"수정 완료: {emoticon.name}")
    return 0


async def cmd_delete(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        emoticon = await repo.get_by_name(session, args.name)
        if emoticon is None:
            print(f"'{args.name}' 없음", file=sys.stderr)
            return 1
        await emoticon_service.delete(session, emoticon)
    print(f"삭제 완료: {args.name}")
    return 0


async def cmd_search(args: argparse.Namespace) -> int:
    async with session_scope() as session:
        hits = await search_service.search(session, args.query)
    for hit in hits:
        print(f"{hit.score:6.1f}  {hit.emoticon.name:<28} {hit.reason}")
    if not hits:
        print("결과 없음")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="app.cli", description="이모티콘 관리 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="테이블 생성 + 감정 태그 seed").set_defaults(func=cmd_init_db)

    p = sub.add_parser("preview", help="URL에서 이미지 후보 목록 보기")
    p.add_argument("url")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("add", help="이모티콘 등록")
    p.add_argument("url")
    p.add_argument("name")
    p.add_argument("--index", type=int, default=1, help="preview에서 본 후보 번호")
    p.add_argument("--emotions", default=None)
    p.add_argument("--keywords", default=None)
    p.set_defaults(func=cmd_add)

    p = sub.add_parser("list", help="목록 보기")
    p.add_argument("query", nargs="?", default=None)
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("tag", help="이름/감정/키워드 수정")
    p.add_argument("name")
    p.add_argument("--rename", default=None)
    p.add_argument("--emotions", default=None)
    p.add_argument("--keywords", default=None)
    p.set_defaults(func=cmd_tag)

    p = sub.add_parser("delete", help="삭제")
    p.add_argument("name")
    p.set_defaults(func=cmd_delete)

    p = sub.add_parser("search", help="검색 점수 확인")
    p.add_argument("query")
    p.set_defaults(func=cmd_search)

    return parser


async def _run(args: argparse.Namespace) -> int:
    try:
        return await args.func(args)
    except (RegistrationError, DuplicateEmoticon) as exc:
        print(f"실패: {exc}", file=sys.stderr)
        return 1
    finally:
        await dispose()


def main() -> None:
    setup_logging()
    args = build_parser().parse_args()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    raise SystemExit(asyncio.run(_run(args)))


if __name__ == "__main__":
    main()
