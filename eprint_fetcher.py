#!/usr/bin/env python3
"""
IACR ePrint Archive Paper Fetcher

OAI-PMH 프로토콜로 ePrint Archive에서 논문 메타데이터를 가져옵니다.
"""

import re
import requests
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import List, Optional, Generator
from datetime import datetime, timedelta, timezone
import time

# 한국 시간대 (UTC+9)
KST = timezone(timedelta(hours=9))

# OAI-PMH 네임스페이스
OAI_NAMESPACES = {
    'oai': 'http://www.openarchives.org/OAI/2.0/',
    'dc': 'http://purl.org/dc/elements/1.1/',
    'oai_dc': 'http://www.openarchives.org/OAI/2.0/oai_dc/'
}


@dataclass
class Paper:
    """ePrint 논문 메타데이터"""
    id: str
    title: str
    authors: List[str] = field(default_factory=list)
    abstract: str = ""
    categories: List[str] = field(default_factory=list)  # OAI-PMH dc:subject
    keywords: List[str] = field(default_factory=list)    # 웹페이지 keyword badges
    url: str = ""
    pdf_url: str = ""
    published_date: Optional[datetime] = None


class EPrintFetcher:
    """IACR ePrint Archive OAI-PMH Fetcher"""

    BASE_URL = "https://eprint.iacr.org"
    OAI_URL = f"{BASE_URL}/oai"

    def __init__(self, delay: float = 0.5):
        self.delay = delay
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'IACR-Paper-Fetcher/1.0'
        })

    def fetch_today(self) -> List[Paper]:
        """오늘 업데이트된 논문 가져오기 (KST 기준)"""
        today = datetime.now(KST).replace(hour=0, minute=0, second=0, microsecond=0)
        return self.fetch_since(today)

    def fetch_recent_days(self, days: int = 1) -> List[Paper]:
        """최근 N일 이내 논문 가져오기"""
        since = datetime.now(KST) - timedelta(days=days)
        return self.fetch_since(since)

    def fetch_since(self, since: datetime) -> List[Paper]:
        """특정 시점 이후 논문 가져오기 (시간순 정렬)"""
        from_date = since.astimezone(timezone.utc).strftime('%Y-%m-%d')
        papers = []

        for paper in self._harvest(from_date):
            if paper.published_date and paper.published_date >= since:
                papers.append(paper)

        # 시간순 정렬 (오래된 것부터)
        papers.sort(key=lambda p: p.published_date or datetime.min.replace(tzinfo=KST))
        return papers

    def _harvest(self, from_date: str) -> Generator[Paper, None, None]:
        """OAI-PMH로 레코드 수집"""
        params = {
            'verb': 'ListRecords',
            'metadataPrefix': 'oai_dc',
            'from': from_date
        }
        resumption_token = None

        while True:
            if resumption_token:
                request_params = {'verb': 'ListRecords', 'resumptionToken': resumption_token}
            else:
                request_params = params

            try:
                response = self.session.get(self.OAI_URL, params=request_params, timeout=60)
                response.raise_for_status()
                root = ET.fromstring(response.text)
            except Exception as e:
                print(f"Error: {e}")
                break

            # 에러 체크
            error = root.find('.//oai:error', OAI_NAMESPACES)
            if error is not None:
                if error.get('code') == 'noRecordsMatch':
                    break
                print(f"OAI error: {error.text}")
                break

            # 레코드 파싱
            for record in root.findall('.//oai:record', OAI_NAMESPACES):
                paper = self._parse_record(record)
                if paper:
                    yield paper

            # 다음 페이지
            token_elem = root.find('.//oai:resumptionToken', OAI_NAMESPACES)
            if token_elem is not None and token_elem.text:
                resumption_token = token_elem.text.strip()
                time.sleep(self.delay)
            else:
                break

    def _parse_record(self, record: ET.Element) -> Optional[Paper]:
        """OAI-PMH 레코드 파싱"""
        header = record.find('oai:header', OAI_NAMESPACES)
        if header is not None and header.get('status') == 'deleted':
            return None

        # ID 추출
        identifier_elem = header.find('oai:identifier', OAI_NAMESPACES) if header else None
        identifier = identifier_elem.text if identifier_elem is not None else ""
        eprint_id = identifier.split(':')[-1] if identifier else ""

        # 메타데이터
        metadata = record.find('.//oai_dc:dc', OAI_NAMESPACES)
        if metadata is None:
            return None

        title = self._get_text(metadata, 'dc:title')
        abstract = self._get_text(metadata, 'dc:description')
        date_str = self._get_text(metadata, 'dc:date')
        authors = self._get_all_text(metadata, 'dc:creator')
        categories = self._get_all_text(metadata, 'dc:subject')

        # 날짜 파싱 (KST)
        published_date = None
        if date_str:
            try:
                if 'T' in date_str:
                    published_date = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                else:
                    published_date = datetime.strptime(date_str, '%Y-%m-%d').replace(tzinfo=timezone.utc)
                published_date = published_date.astimezone(KST)
            except Exception:
                pass

        return Paper(
            id=eprint_id,
            title=title,
            authors=authors,
            abstract=abstract,
            categories=categories,
            keywords=self.fetch_keywords(eprint_id),
            url=f"{self.BASE_URL}/{eprint_id}",
            pdf_url=f"{self.BASE_URL}/{eprint_id}.pdf",
            published_date=published_date
        )

    def _get_text(self, elem: ET.Element, tag: str) -> str:
        child = elem.find(tag, OAI_NAMESPACES)
        return child.text.strip() if child is not None and child.text else ""

    def _get_all_text(self, elem: ET.Element, tag: str) -> List[str]:
        return [e.text.strip() for e in elem.findall(tag, OAI_NAMESPACES) if e.text]

    def fetch_keywords(self, eprint_id: str) -> List[str]:
        """개별 논문 페이지에서 키워드 파싱"""
        url = f"{self.BASE_URL}/{eprint_id}"
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            # <dd class="keywords">...<a ... class="... keyword">keyword text</a>...</dd>
            pattern = r'<dd class="keywords">(.*?)</dd>'
            match = re.search(pattern, response.text, re.DOTALL)
            if match:
                keywords_html = match.group(1)
                # 각 keyword badge에서 텍스트 추출
                keyword_pattern = r'class="[^"]*keyword[^"]*">([^<]+)</a>'
                keywords = re.findall(keyword_pattern, keywords_html)
                return [kw.strip() for kw in keywords if kw.strip()]
        except Exception as e:
            print(f"Error fetching keywords for {eprint_id}: {e}")
        return []


if __name__ == "__main__":
    fetcher = EPrintFetcher()
    papers = fetcher.fetch_recent_days(days=3)

    print(f"Found {len(papers)} papers\n")
    for p in papers:
        print(f"[{p.id}] {p.title}")
        print(f"  Authors: {', '.join(p.authors[:3])}")
        print(f"  Categories: {', '.join(p.categories)}")
        print(f"  Keywords: {', '.join(p.keywords)}")
        print(f"  Date: {p.published_date.strftime('%Y-%m-%d %H:%M KST') if p.published_date else 'N/A'}")
        print()
