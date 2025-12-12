#!/usr/bin/env python3
"""
Cerebras LLM 기반 번역 모듈
"""

import os
from cerebras.cloud.sdk import Cerebras
from dotenv import load_dotenv
from pathlib import Path

# .env 파일 로드
load_dotenv(Path(__file__).parent / ".env")


class Translator:
    """Cerebras API를 사용한 번역기"""

    def __init__(self):
        self.client = Cerebras(
            api_key=os.environ.get("CEREBRAS_API_KEY"),
        )
        self.model = "gpt-oss-120b"

    def translate_paper(self, title: str, abstract: str, keywords: list[str]) -> dict:
        """논문 제목, abstract, 키워드를 한 번에 번역 (용어 일관성 유지)"""
        keywords_str = ", ".join(keywords) if keywords else ""
        keyword_count = len(keywords)

        prompt = f"""Translate the following academic paper information to Korean.
- Use formal/polite speech (존댓말).
- For Title: Translate to Korean naturally. Keep only proper nouns and acronyms in English (e.g., NIST, ARMv9, ML-DSA).
- For Abstract: Translate fully to Korean. Keep only proper nouns and acronyms in English. IMPORTANT: Do NOT use any parentheses for translations like "영어(한글)" or "한글(영어)". Just translate directly.
- For Keywords: Translate them fully to Korean.

Title: {title}

Abstract: {abstract}

Keywords: {keywords_str}

Respond in this exact format:
TITLE: <translated title in Korean, only proper nouns/acronyms in English>
ABSTRACT: <translated abstract in 존댓말, NO parenthetical translations>
KEYWORDS: <translate ONLY the {keyword_count} keywords fully to Korean, comma-separated, in the same order>"""

        try:
            response = self.client.chat.completions.create(
                messages=[
                    {
                        "role": "system",
                        "content": "You are a professional academic translator specializing in cryptography and computer science. Use formal Korean (존댓말). Translate titles and abstracts fully to Korean, keeping only proper nouns/acronyms in English. NEVER use parentheses for translations. Translate keywords fully to Korean. Output only the requested format."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                model=self.model,
            )
            return self._parse_translation(response.choices[0].message.content, title, abstract, keywords)
        except Exception as e:
            print(f"Translation error: {e}")
            return {"title": title, "abstract": abstract, "keywords": keywords}

    def _parse_translation(self, response: str, orig_title: str, orig_abstract: str, orig_keywords: list[str]) -> dict:
        """번역 응답 파싱"""
        result = {"title": orig_title, "abstract": orig_abstract, "keywords": orig_keywords}

        lines = response.strip().split("\n")
        current_field = None
        current_content = []

        for line in lines:
            if line.startswith("TITLE:"):
                if current_field and current_content:
                    result[current_field] = "\n".join(current_content).strip()
                current_field = "title"
                current_content = [line[6:].strip()]
            elif line.startswith("ABSTRACT:"):
                if current_field and current_content:
                    result[current_field] = "\n".join(current_content).strip()
                current_field = "abstract"
                current_content = [line[9:].strip()]
            elif line.startswith("KEYWORDS:"):
                if current_field and current_content:
                    result[current_field] = "\n".join(current_content).strip()
                current_field = "keywords"
                keywords_str = line[9:].strip()
                result["keywords"] = [k.strip() for k in keywords_str.split(",") if k.strip()]
                current_field = None
            elif current_field and current_field != "keywords":
                current_content.append(line)

        # 마지막 필드 저장
        if current_field and current_content:
            result[current_field] = "\n".join(current_content).strip()

        return result


if __name__ == "__main__":
    translator = Translator()

    # 테스트
    result = translator.translate_paper(
        title="Efficient Zero-Knowledge Proofs for Set Membership",
        abstract="We present a novel construction for zero-knowledge proofs that enables efficient verification of set membership without revealing the element.",
        keywords=["zero-knowledge proofs", "set membership", "cryptographic protocols"]
    )
    print(f"Title: {result['title']}")
    print(f"Abstract: {result['abstract']}")
    print(f"Keywords: {result['keywords']}")
