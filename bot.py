#!/usr/bin/env python3
"""
IACR ePrint Discord Bot

매일 실행하여 새 논문을 Discord 채널에 알림.
메인 메시지 + 스레드에 Abstract 포스팅.

크론잡: 0 9 * * * python3 /path/to/bot.py
"""

import os
import json
import discord
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv

from eprint_fetcher import EPrintFetcher, Paper, KST
from translator import Translator

# .env 파일 로드
load_dotenv(Path(__file__).parent / ".env")

# 설정
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))
DISCORD_CHANNEL_ID_KR = int(os.environ.get("DISCORD_CHANNEL_ID_KR", "0"))
POSTED_FILE = Path(__file__).parent / "posted_papers.json"
CHECK_DAYS = 4


def load_posted_ids() -> set:
    """이미 올린 논문 ID 로드"""
    if POSTED_FILE.exists():
        with open(POSTED_FILE, 'r') as f:
            data = json.load(f)
            return set(data.get('posted_ids', []))
    return set()


def save_posted_ids(ids: set):
    """올린 논문 ID 저장 (시간순 정렬)"""
    # ID 형식: 2025/1234 -> 년도/번호 순으로 정렬
    sorted_ids = sorted(ids, key=lambda x: (x.split('/')[0], int(x.split('/')[1])))
    with open(POSTED_FILE, 'w') as f:
        json.dump({
            'updated_at': datetime.now(KST).isoformat(),
            'posted_ids': sorted_ids
        }, f, indent=2)


def create_embed(paper: Paper, title_kr: str = None, keywords_kr: list = None) -> discord.Embed:
    """Discord Embed 생성 (Abstract 제외)"""
    embed = discord.Embed(
        title=title_kr or paper.title,
        url=paper.url,
        color=0x3498db
    )

    # 저자
    authors = ", ".join(paper.authors) if paper.authors else "N/A"
    embed.add_field(name="Authors", value=authors, inline=False)

    # 카테고리
    category = ", ".join(paper.categories) if paper.categories else "N/A"
    embed.add_field(name="Category", value=category, inline=True)

    # 키워드 (번역된 키워드가 있으면 "원문(번역)" 형식)
    if keywords_kr and paper.keywords and len(keywords_kr) == len(paper.keywords):
        kw_pairs = [f"{en}({kr})" for en, kr in zip(paper.keywords, keywords_kr)]
        keywords = ", ".join(kw_pairs)
    else:
        keywords = ", ".join(paper.keywords) if paper.keywords else "N/A"
    embed.add_field(name="Keywords", value=keywords, inline=False)

    # 날짜
    date_str = paper.published_date.strftime('%Y-%m-%d %H:%M KST') if paper.published_date else "N/A"
    embed.add_field(name="Published", value=date_str, inline=True)

    # PDF 링크
    embed.add_field(name="PDF", value=f"[Download]({paper.pdf_url})", inline=True)

    embed.set_footer(text=f"ePrint {paper.id}")

    if paper.published_date:
        embed.timestamp = paper.published_date

    return embed


async def send_paper(channel: discord.TextChannel, paper: Paper) -> bool:
    """논문 전송: 메인은 제목만, 스레드에 상세정보"""
    try:
        # 1. 메인 메시지 - 제목 + ID
        title_short = paper.title[:70] + "..." if len(paper.title) > 70 else paper.title
        message = await channel.send(f"📄[{paper.id}] **{title_short}**")

        # 2. 스레드 생성 + Embed + Abstract
        thread = await message.create_thread(
            name=paper.title[:100],
            auto_archive_duration=1440  # 24시간
        )

        # Embed 전송
        embed = create_embed(paper)
        await thread.send(embed=embed)

        # Abstract 전송
        if paper.abstract:
            abstract = paper.abstract
            chunks = [abstract[i:i+1900] for i in range(0, len(abstract), 1900)]

            for i, chunk in enumerate(chunks):
                if len(chunks) > 1:
                    await thread.send(f"**Abstract ({i+1}/{len(chunks)})**\n{chunk}")
                else:
                    await thread.send(f"**Abstract**\n{chunk}")

        return True
    except Exception as e:
        print(f"Error sending paper {paper.id}: {e}")
        return False


async def send_paper_kr(channel: discord.TextChannel, paper: Paper, translator: Translator) -> bool:
    """논문 전송 (한국어 번역): 메인은 제목만, 스레드에 상세정보"""
    try:
        # 한 번에 번역 (용어 일관성 유지)
        translated = translator.translate_paper(paper.title, paper.abstract, paper.keywords)
        title_kr = translated["title"]
        abstract_kr = translated["abstract"]
        keywords_kr = translated["keywords"]

        # 1. 메인 메시지 - 번역된 제목 + ID
        title_short = title_kr[:70] + "..." if len(title_kr) > 70 else title_kr
        message = await channel.send(f"📄[{paper.id}]  **{title_short}**")

        # 2. 스레드 생성 + Embed + Abstract
        thread = await message.create_thread(
            name=title_kr[:100],
            auto_archive_duration=1440  # 24시간
        )

        # Embed 전송 (번역된 제목, 키워드)
        embed = create_embed(paper, title_kr=title_kr, keywords_kr=keywords_kr)
        await thread.send(embed=embed)

        # 번역된 Abstract 전송
        if abstract_kr:
            chunks = [abstract_kr[i:i+1900] for i in range(0, len(abstract_kr), 1900)]

            for i, chunk in enumerate(chunks):
                if len(chunks) > 1:
                    await thread.send(f"**Abstract ({i+1}/{len(chunks)})**\n{chunk}")
                else:
                    await thread.send(f"**Abstract**\n{chunk}")

        return True
    except Exception as e:
        print(f"Error sending paper (KR) {paper.id}: {e}")
        return False


async def main_async():
    """비동기 메인 함수"""
    print(f"[{datetime.now(KST).strftime('%Y-%m-%d %H:%M:%S')}] Starting ePrint check...")

    if not DISCORD_BOT_TOKEN or not DISCORD_CHANNEL_ID:
        print("Error: DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID required")
        print("Set environment variables:")
        print("  export DISCORD_BOT_TOKEN='your-bot-token'")
        print("  export DISCORD_CHANNEL_ID='channel-id'")
        return

    # 논문 가져오기
    fetcher = EPrintFetcher()
    papers = fetcher.fetch_recent_days(days=CHECK_DAYS)
    print(f"Found {len(papers)} papers in last {CHECK_DAYS} days")

    # 이미 올린 논문 확인
    posted_ids = load_posted_ids()
    new_papers = [p for p in papers if p.id not in posted_ids]
    print(f"New papers: {len(new_papers)}")

    if not new_papers:
        print("No new papers to post")
        return

    # 오래된 것부터 정렬
    new_papers.sort(key=lambda p: p.published_date or datetime.min.replace(tzinfo=KST))

    # Discord 클라이언트
    intents = discord.Intents.default()
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready():
        print(f"Logged in as {client.user}")

        # 영어 채널
        try:
            channel = await client.fetch_channel(DISCORD_CHANNEL_ID)
        except Exception as e:
            print(f"Error fetching channel {DISCORD_CHANNEL_ID}: {e}")
            await client.close()
            return

        # 한국어 채널
        channel_kr = None
        if DISCORD_CHANNEL_ID_KR:
            try:
                channel_kr = await client.fetch_channel(DISCORD_CHANNEL_ID_KR)
            except Exception as e:
                print(f"Error fetching KR channel {DISCORD_CHANNEL_ID_KR}: {e}")

        # 번역기 초기화
        translator = Translator() if channel_kr else None

        sent_count = 0
        for paper in new_papers:
            if await send_paper(channel, paper):
                posted_ids.add(paper.id)
                sent_count += 1
                print(f"Sent: [{paper.id}] {paper.title[:50]}...")

                # 한국어 채널에도 전송
                if channel_kr and translator:
                    await send_paper_kr(channel_kr, paper, translator)
                    print(f"Sent (KR): [{paper.id}]")

        save_posted_ids(posted_ids)
        print(f"Done. Sent {sent_count} papers.")

        await client.close()

    try:
        await client.start(DISCORD_BOT_TOKEN)
    except Exception:
        pass
    finally:
        if not client.is_closed():
            await client.close()


def main():
    import asyncio
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
