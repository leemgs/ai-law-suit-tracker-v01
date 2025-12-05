# AI Lawsuit Tracker (GitHub Actions)

Google Custom Search JSON API를 사용하여 `keywords.txt`에 정의된 키워드(예: `AI 소송`, `AI lawsuit`)로
정기적으로 뉴스를 검색하고, 관련 AI 소송 정보를 GitHub Issues로 자동 업로드하는 워크플로우입니다.

## 기능 개요

- **검색 주기**: GitHub Actions의 cron 스케줄러로 **2시간 간격** 실행
- **검색 키워드**: `keywords.txt`에 한 줄당 하나씩 정의
- **데이터 수집**:
  - Google Custom Search JSON API로 뉴스/웹 검색
  - 기사 페이지를 간단히 파싱하여 텍스트 추출
- **추출 필드(요구사항 반영)**:
  - 원고(Plaintiff)
  - 피고(Defendant)
  - 소송번호(Case No.)
  - 소송이유
  - 국가
  - 법원 정보
  - 관련기사 웹주소
  - 소송 번호 Tracker 웹주소(법원/판례 DB 추가 검색 결과)
- **추가 분석(요구사항 3)**:
  - 해당 소송의 **요약(Summary)**, **결론(Conclusion)**, **시사점(Implications)** 자동 기입
- **중복 방지**:
  - `seen.json`에 이미 처리한 기사 URL 기록
  - 이후 같은 URL은 다시 Issue로 만들지 않음

## 폴더 구조

```text
.
├─ README.md
├─ keywords.txt
├─ requirements.txt
├─ seen.json
├─ app/
│  └─ main.py
└─ .github/
   └─ workflows/
      └─ ai-lawsuit-tracker.yml
```

## 사전 준비

1. **Google Custom Search JSON API 키 발급**
   - Google Cloud Console에서 API를 활성화하고 API 키 발급
2. **Custom Search Engine(CSE) 생성**
   - https://cse.google.com/cse/ 에서 검색 엔진 생성
   - 전체 웹을 대상으로 할 수도 있고, 특정 뉴스/법률 사이트로 도메인 화이트리스트를 구성할 수도 있음
   - 생성된 **검색 엔진 ID**(cx)를 확보

3. 리포지토리를 GitHub에 생성 후, 이 프로젝트 파일들을 업로드합니다.

4. 리포지토리 Settings → *Secrets and variables* → *Actions* 에서 아래 시크릿을 추가합니다.

   - `GOOGLE_API_KEY` : Google Custom Search JSON API 키
   - `GOOGLE_CSE_ID` : Custom Search Engine ID (cx)

## `keywords.txt` 예시

```text
AI 소송
AI lawsuit
```

- 한 줄에 하나의 검색 키워드를 적습니다.
- 필요 시 다른 언어 키워드도 추가 가능합니다.

## `requirements.txt`

```text
requests
beautifulsoup4
lxml
tldextract
python-dateutil
html2text
```

로컬 테스트 시:

```bash
pip install -r requirements.txt
python app/main.py
```

> 실제 Google API 호출이 일어나므로, 테스트 시 쿼리 수와 호출 간격에 주의하세요.

## GitHub Actions 워크플로우

`.github/workflows/ai-lawsuit-tracker.yml`:

```yaml
name: AI Lawsuit Tracker

on:
  schedule:
    - cron: "0 */2 * * *"   # 2시간 간격(UTC 기준)
  workflow_dispatch:        # 수동 실행도 가능

jobs:
  run:
    runs-on: ubuntu-latest
    permissions:
      issues: write
      contents: write
    env:
      GOOGLE_API_KEY: ${{ secrets.GOOGLE_API_KEY }}
      GOOGLE_CSE_ID: ${{ secrets.GOOGLE_CSE_ID }}
      GITHUB_REPOSITORY: ${{ github.repository }}
      DATE_RESTRICT_DAYS: "3"
      MAX_RESULTS_PER_KEYWORD: "8"
    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install deps
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run tracker
        run: |
          python app/main.py

      - name: Persist seen.json (dedup store)
        run: |
          if ! git diff --quiet; then
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add seen.json
            git commit -m "chore: update seen.json"
            git push
          fi
```

- `DATE_RESTRICT_DAYS`: 최근 며칠 이내의 기사 위주로 검색할지(기본 3일)
- `MAX_RESULTS_PER_KEYWORD`: 키워드당 최대 검색 결과 수(기본 8개)

## `app/main.py` 개요

- `keywords.txt`에서 키워드 목록을 읽습니다.
- 각 키워드에 대해 Google CSE 검색을 수행합니다.
- 각 검색 결과 기사 페이지를 가져와서:
  - 제목, 메타 설명, 본문 텍스트 추출
  - 정규식을 사용하여:
    - **원고 / 피고 (Plaintiff / Defendant)**
    - **소송번호 (Case No.)**
  - 도메인과 텍스트 키워드를 기반으로:
    - **국가**
    - **법원 정보**
  - `courtlistener.com`, `law.justia.com`, `casetext.com`, `casemine.com` 등에서 **소송 번호 Tracker URL**을 2차 검색으로 시도
- 소송이유는 고정값:
  - **"AI 모델 학습을 위해 불법으로 데이터셋을 이용"**
- 기사 내용으로부터:
  - **요약(Summary)**: 본문 첫 몇 문장을 단순 추출
  - **결론(Conclusion)**, **시사점(Implications)**: 키워드 기반 템플릿으로 자동 생성
- 최종적으로 위 정보를 Markdown 형식으로 정리하여 GitHub Issue를 생성합니다.

Issue 본문 예시 형식:

```md
**원고(Plaintiff)**: Foo Corp.
**피고(Defendant)**: Bar AI Inc.
**소송번호(Case No.)**: 2:25-cv-12345
**소송이유**: AI 모델 학습을 위해 불법으로 데이터셋을 이용
**국가**: 미국
**법원 정보**: U.S. District Court for the Northern District of California

**관련기사(URL)**: https://example.com/article
**소송 번호 Tracker(URL)**: https://www.courtlistener.com/docket/...

---

### 요약(Summary)
(기사 내용 자동 요약)

### 결론(Conclusion)
(해당 소송에서 핵심이 되는 법적 쟁점 및 가능 시나리오)

### 시사점(Implications)
(다른 AI 기업/연구기관/데이터 거버넌스에 미치는 영향 정리)

---

_자동 수집 시각(KST): 2025-12-05 12:34:56 KST_
```

## 주의 사항 및 한계

- Google Custom Search JSON API 사용량(쿼터/요금)에 유의하세요.
- 본문 파싱과 정보 추출은 휴리스틱/정규식 기반이라 **100% 정확하지 않을 수 있습니다.**
  - 기사에 소송번호·원고·피고·법원 정보가 명시되지 않은 경우 `미상`으로 채워집니다.
  - 필요하다면 특정 국가별 패턴(예: 한국 "2025가합12345", EU 케이스 번호 등)을 더 추가하여 정교화할 수 있습니다.
- 검색 품질을 높이려면 CSE 설정에서:
  - 신뢰할 수 있는 법률/뉴스 도메인 위주로 검색 대상 도메인을 제한하거나
  - 국가·언어 필터를 활용해 보세요.

## 로컬에서 수동 실행

```bash
export GOOGLE_API_KEY="YOUR_API_KEY"
export GOOGLE_CSE_ID="YOUR_CSE_ID"
export GITHUB_REPOSITORY="yourname/yourrepo"
export GITHUB_TOKEN="ghp_xxx_or_personal_token"

python app/main.py
```

- 로컬에서 실제 GitHub Issue를 만들고 싶지 않다면:
  - `create_issue` 함수 부분을 수정해서, Issue API 호출 대신 콘솔 출력만 하도록 바꿔서 테스트할 수 있습니다.

---

이 리포를 그대로 GitHub에 올린 뒤, Actions 탭에서 워크플로우가 정상 실행되는지만 확인해 주시면
자동 AI 소송 트래커가 동작하게 됩니다.
