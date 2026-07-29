# g2b_email_scheduler

나라장터(G2B) 입찰공고정보서비스에서 원하는 키워드에 맞는 입찰공고를 조회하고 HTML 이메일로 발송하는 프로그램입니다.

## 1. 주요 기능

- 나라장터 입찰공고정보서비스 API 호출
- 키워드별 공고명 검색
- 용역/물품/공사/외자 업무구분 선택 조회
- 신규/기존 공고 구분
- 입찰마감일이 지난 공고 제외
- HTML 이메일 본문 생성
- `g2b_bid_latest.html` 첨부파일 발송
- GitHub Actions 자동 실행 지원

## 2. 인증키

공공데이터포털에서 `조달청_나라장터 입찰공고정보서비스` 활용신청 후 받은 일반 인증키를 사용합니다.

로컬에서는 `.env` 파일에 입력합니다.

```env
G2B_SERVICE_KEY=발급받은_인증키
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USER=보내는_메일주소
SMTP_PASSWORD=구글_앱비밀번호
MAIL_FROM=보내는_메일주소
MAIL_TO=받는_메일주소
MAIL_CC=
```

GitHub Actions에서는 Repository Secrets에 같은 이름으로 등록합니다.

## 3. 키워드 수정

`config.example.yaml`을 복사해 `config.yaml`을 만들고, 아래 부분을 원하는 키워드로 바꿉니다.

```yaml
keywords:
  - "LMS"
  - "교육관리시스템"
```

## 4. 업무구분 수정

기본은 용역/물품만 조회합니다. 공사나 외자도 조회하려면 `enabled: true`로 바꿉니다.

```yaml
work_types:
  - name: "용역"
    operation: "getBidPblancListInfoServc"
    enabled: true
  - name: "물품"
    operation: "getBidPblancListInfoThng"
    enabled: true
  - name: "공사"
    operation: "getBidPblancListInfoCnstwk"
    enabled: false
```

## 5. 로컬 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy config.example.yaml config.yaml
copy .env.example .env
python main.py
```

## 6. GitHub Actions

`.github/workflows/g2b_email_notice.yml`이 포함되어 있습니다.
기본 스케줄은 매주 월요일 오전 11:07 KST입니다.

수동 실행하려면 GitHub 저장소의 Actions 탭에서 `G2B Bid Notice Email` 워크플로를 선택하고 `Run workflow`를 누르면 됩니다.
