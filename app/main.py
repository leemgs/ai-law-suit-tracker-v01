#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import json
import time
import re
import html
import tldextract
import requests
from datetime import datetime, timezone
from dateutil import tz
from bs4 import BeautifulSoup
import html2text

GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY")
GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID")
REPO = os.environ.get("GITHUB_REPOSITORY")
DATE_RESTRICT_DAYS = int(os.environ.get("DATE_RESTRICT_DAYS", "3"))
MAX_RESULTS_PER_KEYWORD = int(os.environ.get("MAX_RESULTS_PER_KEYWORD", "8"))
KEYWORDS_FILE = os.environ.get("KEYWORDS_FILE", "keywords.txt")
SEEN_FILE = os.environ.get("SEEN_FILE", "seen.json")

if not GOOGLE_API_KEY or not GOOGLE_CSE_ID:
    raise SystemExit("ERROR: GOOGLE_API_KEY/GOOGLE_CSE_ID 가 필요합니다. 리포 시크릿에 설정하세요.")

KST = tz.gettz("Asia/Seoul")

def load_seen():
    if not os.path.exists(SEEN_FILE):
        return {"items": {}}
    with open(SEEN_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_seen(data):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def google_search(query, num=10, date_restrict_days=3):
    params = {
        "key": GOOGLE_API_KEY,
        "cx": GOOGLE_CSE_ID,
        "q": query,
        "num": min(10, num),
        "sort": ""
    }
    if date_restrict_days and date_restrict_days > 0:
        params["dateRestrict"] = f"d{date_restrict_days}"

    resp = requests.get("https://www.googleapis.com/customsearch/v1", params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("items", []) or []

def fetch_page_text(url, timeout=20):
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        title = (soup.title.get_text(strip=True) if soup.title else "")[:300]
        desc = ""
        md = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
        if md and md.get("content"):
            desc = md["content"].strip()
        article = soup.find("article")
        if article:
            text = article.get_text(" ", strip=True)
        else:
            ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
            text = " ".join(ps)
        if len(text) < 200:
            text = html2text.html2text(r.text)
        return title, desc, text
    except Exception:
        return "", "", ""

CASE_PATTERNS = [
    r"(Case\s*No\.?\s*[:\-]?\s*[A-Za-z0-9\-\:\.]+)",
    r"(Docket\s*No\.?\s*[:\-]?\s*[A-Za-z0-9\-\:\.]+)",
    r"(No\.?\s*[0-9]{2,4}[\-–][A-Za-z]{1,6}[\-–]?[0-9]{1,6})",
    r"(\d{2,4}\s*[가-힣]{1,3}\s*\d{1,6})",
]

def extract_case_number(text):
    for pat in CASE_PATTERNS:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            raw = m.group(0)
            parts = raw.split(":")
            cand = parts[-1].strip() if len(parts) > 1 else raw
            cand = cand.replace("Case No.", "").replace("Docket No.", "").replace("No.", "").strip(" :.-")
            return cand[:64]
    return ""

def extract_parties(text):
    mv = re.search(r"([A-Z][A-Za-z0-9& ,.\-]{2,})\s+v[.]?s?[.]?\s+([A-Z][A-Za-z0-9& ,.\-]{2,})", text)
    if mv:
        return mv.group(1).strip(), mv.group(2).strip()
    mk = re.search(r"원고[:\s]+([^\n,]+)[,\s]+피고[:\s]+([^\n,]+)", text)
    if mk:
        return mk.group(1).strip(), mk.group(2).strip()
    mk2 = re.search(r"([가-힣A-Za-z0-9&\(\)·\-\s]{2,})\s*가\s*([가-힣A-Za-z0-9&\(\)·\-\s]{2,})\s*상대로\s*소송", text)
    if mk2:
        return mk2.group(1).strip(), mk2.group(2).strip()
    return "", ""

def detect_country_and_court(url, text):
    ext = tldextract.extract(url)
    tld = ext.suffix
    country = "미국"
    if tld.endswith("co.kr") or tld.endswith("kr"):
        country = "대한민국"
    elif tld.endswith("co.jp") or tld.endswith("jp"):
        country = "일본"
    elif tld.endswith("co.uk") or tld.endswith("uk"):
        country = "영국"
    elif tld.endswith("au"):
        country = "호주"
    elif tld.endswith("nz"):
        country = "뉴질랜드"
    elif tld.endswith("de"):
        country = "독일"
    elif tld.endswith("fr"):
        country = "프랑스"
    elif tld.endswith("it"):
        country = "이탈리아"
    elif tld.endswith("ca"):
        country = "캐나다"

    court = ""
    m_us = re.search(r"(U\.S\.\s*District\s*Court|United\s*States\s*District\s*Court|Superior\s*Court|Court\s*of\s*Appeals|\d+th\s*Circuit)", text, re.IGNORECASE)
    if m_us:
        court = m_us.group(0)
    m_kr = re.search(r"(지방법원|고등법원|대법원)", text)
    if m_kr:
        court = m_kr.group(0)
    return country, court

def find_tracker_url(plaintiff, defendant, case_no):
    if not (plaintiff or defendant or case_no):
        return ""
    q_bits = []
    if plaintiff: q_bits.append(plaintiff)
    if defendant: q_bits.append(defendant)
    if case_no:   q_bits.append(case_no)
    base = " ".join(q_bits)
    query = f"{base} site:courtlistener.com OR site:law.justia.com OR site:casetext.com OR site:casemine.com"
    try:
        items = google_search(query, num=3, date_restrict_days=0)
        if items:
            return items[0].get("link", "")
    except Exception:
        pass
    return ""

def summarize(text, limit=3):
    sents = re.split(r'(?<=[.!?。])\s+', text.strip())
    sents = [s for s in sents if len(s) > 10]
    return " ".join(sents[:limit])

def conclude_and_implicate(text):
    infr = bool(re.search(r"(infring|저작권|무단|불법|copyright)", text, re.IGNORECASE))
    fair = bool(re.search(r"(fair use|공정 이용|fair-use)", text, re.IGNORECASE))
    privacy = bool(re.search(r"(privacy|개인정보)", text, re.IGNORECASE))
    conclusion = []
    if infr:
        conclusion.append("저작권 침해 쟁점이 핵심으로 부각되었습니다.")
    if fair:
        conclusion.append("공정 이용(fair use) 판단이 결과를 좌우할 가능성이 큽니다.")
    if privacy:
        conclusion.append("개인정보/프라이버시 이슈가 병행되어 검토됩니다.")
    if not conclusion:
        conclusion.append("사안의 구체적 사실관계와 관할 법원의 기존 판례가 결과에 큰 영향을 미칠 전망입니다.")
    implications = [
        "AI 학습 데이터 수집·활용 시 출처·라이선스 검증 프로세스가 요구됩니다.",
        "기업은 데이터 거버넌스 및 저작권 리스크 관리를 위한 계약·로그·거부(옵트아웃) 체계를 갖출 필요가 있습니다.",
        "관할 국가의 판례 동향에 따라 글로벌 서비스 정책(학습 제외/허용 범위) 조정이 필요합니다."
    ]
    return " ".join(conclusion), " ".join(implications)

def create_issue(title, body):
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if not token:
        token = os.environ.get("GITHUB_ACTIONS") and os.environ.get("ACTIONS_RUNTIME_TOKEN")
    if not token:
        raise SystemExit("ERROR: GITHUB_TOKEN 이 없습니다.")
    url = f"https://api.github.com/repos/{REPO}/issues"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json"
    }
    data = {
        "title": title[:250],
        "body": body,
        "labels": ["ai-lawsuit", "automation"]
    }
    r = requests.post(url, headers=headers, json=data, timeout=30)
    if r.status_code >= 300:
        raise RuntimeError(f"Failed to create issue: {r.status_code} {r.text}")
    return r.json().get("html_url", "")

ISSUE_TEMPLATE = """**원고(Plaintiff)**: {plaintiff}
**피고(Defendant)**: {defendant}
**소송번호(Case No.)**: {case_no}
**소송이유**: {reason}
**국가**: {country}
**법원 정보**: {court}

**관련기사(URL)**: {article_url}
**소송 번호 Tracker(URL)**: {tracker_url}

---

### 요약(Summary)
{summary}

### 결론(Conclusion)
{conclusion}

### 시사점(Implications)
{implications}

---

_자동 수집 시각(KST): {ts}_
"""


def main():
    seen = load_seen()
    if not os.path.exists(KEYWORDS_FILE):
        raise SystemExit(f"ERROR: {KEYWORDS_FILE} 파일이 필요합니다.")
    with open(KEYWORDS_FILE, "r", encoding="utf-8") as f:
        queries = [q.strip() for q in f if q.strip()]
    LAWSUIT_REASON = "AI 모델 학습을 위해 불법으로 데이터셋을 이용"
    for q in queries:
        items = google_search(q, num=MAX_RESULTS_PER_KEYWORD, date_restrict_days=DATE_RESTRICT_DAYS)
        for it in items:
            link = it.get("link")
            title = html.unescape(it.get("title", "")).strip()
            if not link:
                continue
            key = link
            if key in seen["items"]:
                continue
            page_title, meta_desc, text = fetch_page_text(link)
            page_text = f"{page_title}\n{meta_desc}\n{text}"
            case_no = extract_case_number(page_text)
            plaintiff, defendant = extract_parties(page_text)
            country, court = detect_country_and_court(link, page_text)
            tracker_url = find_tracker_url(plaintiff, defendant, case_no)
            summary = summarize(meta_desc or text, limit=3)
            conclusion, implications = conclude_and_implicate(page_text)
            title_base = title or page_title or "AI 소송 관련 기사"
            issue_title = f"[AI 소송] {title_base}".strip()
            body = ISSUE_TEMPLATE.format(
                plaintiff=plaintiff or "미상",
                defendant=defendant or "미상",
                case_no=case_no or "미상",
                reason=LAWSUIT_REASON,
                country=country or "미상",
                court=court or "미상",
                article_url=link,
                tracker_url=tracker_url or "미상",
                summary=summary or "본문이 짧아 자동 요약이 제한적입니다.",
                conclusion=conclusion,
                implications=implications,
                ts=datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S %Z")
            )
            issue_url = create_issue(issue_title, body)
            seen["items"][key] = {
                "created_at": datetime.now(timezone.utc).isoformat(),
                "issue_url": issue_url,
                "case_no": case_no,
                "plaintiff": plaintiff,
                "defendant": defendant
            }
            time.sleep(1)
    save_seen(seen)

if __name__ == "__main__":
    main()
