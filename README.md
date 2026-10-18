# GNU-mukbaque2 · Protein Lab

류신 지퍼의 결합 파트너를 탐색·설계하는 독립 실행형 연구 앱입니다. FastAPI 서버, 별도 CPU 워커, Protein Lab 웹 클라이언트를 제공합니다.

## 바로 실행

Python **3.12 이상**과 Git이 필요합니다. 빌드된 웹 화면이 포함되어 있어 실행에 Node.js나 원본 저장소 클론이 필요하지 않습니다.

```bash
git clone https://github.com/yongkyu4803/GNU-mukbaque2.git
cd GNU-mukbaque2
python3 run.py
```

Windows에서는 `py -3.12 run.py`처럼 설치된 Python으로 실행합니다. 첫 실행에 프로젝트 내부 `.venv`를 생성하고 의존성을 설치한 다음 API와 계산 워커를 함께 시작합니다. 최초 설치에는 인터넷이 필요합니다. 이후에는 설치 결과를 재사용합니다.

- 웹 앱: http://127.0.0.1:8001/
- API 문서: http://127.0.0.1:8001/docs
- 준비 상태: http://127.0.0.1:8001/api/v1/health/ready
- 종료: `Ctrl+C` — API와 워커를 함께 종료합니다.

포트와 데이터 폴더는 변경할 수 있습니다.

```bash
python3 run.py --port 8080 --data-dir ./var
```

기본 바인딩은 로컬 컴퓨터입니다. 현재 버전은 로컬 단일 사용자용이며 인증은 제공하지 않습니다. 실행 이력·업로드·결과는 `var/`에 보관되고 Git에 포함되지 않습니다.

## 기능

- 서열/PDB 입력, 헵타드 레지스터 분석과 구조 경고.
- 라이브러리 스크리닝, 파트너 및 직교 세트 설계.
- 실제 점수 비교 그래프, 최종 shift 재평가 행렬과 경쟁자 확인.
- 작업 진행률·취소·재시도·실행 이력과 CSV/FASTA/JSON 다운로드.
- 서열 라이브러리 등록, 실험 Tm 데이터로 점수 모델 보정.
- 구조 재분석과 도킹 입력 준비. 외부 구조 예측·도킹 실행은 포함하지 않습니다.

기본 점수는 미보정 상대 순위이며 결합 에너지나 친화도 측정값이 아닙니다. 보정 지표는 학습 데이터의 값으로 독립 검증과 구분합니다.

## 구조

```text
run.py              가상환경 설치 및 API·워커 통합 실행
server/             FastAPI, 지속 작업 큐, 데이터 저장, 계산 워커
lz/                 출처·라이선스를 보존한 계산 코어와 CLI
data/               기본 서열 라이브러리
client/             TypeScript/Vite 웹 클라이언트 소스
web/                바로 실행할 수 있는 빌드된 클라이언트
tests/              계산·API·작업 복구 테스트
tools/              구조 다운로드와 격리된 브라우저 테스트 서버
var/                실행 데이터 (자동 생성, Git 제외)
```

`LZ-program/` 원본 체크아웃과 원본 Git 이력은 이 저장소에 포함되지 않습니다. 새 앱의 실행에 필요한 계산 코어는 독립적으로 포함합니다. 원본 코드는 [mukbaque2/LZ-program](https://github.com/mukbaque2/LZ-program)의 커밋 `9b72e00cfd793a27de0bf37cccabea40064f9743`에서 가져왔으며, MIT 저작권과 라이선스를 보존했습니다. 상세 내역은 [NOTICE.md](NOTICE.md)에 있습니다.

## 클론해서 작업하기

아래 명령은 별도 설명이 없으면 macOS/Linux 터미널 기준입니다. `프로젝트 루트`는 `run.py`, `README.md`, `server/`, `client/`가 들어 있는 `GNU-mukbaque2` 폴더를 뜻합니다. Windows 명령은 해당 단계에 함께 적었습니다.

### 1. 필요한 도구 확인

| 도구 | 필요한 경우 | 기준 |
|---|---|---|
| Git | 클론, 변경 이력 관리, pull/push | 터미널에서 `git --version` 실행 가능 |
| Python | 서버·계산 워커 실행과 테스트 | 3.12 이상 |
| Node.js / npm | 웹 화면 소스 수정·빌드·브라우저 테스트 | Node.js 22.12 이상 권장 |
| 웹 브라우저 | 앱 사용 | 로컬 주소 접속 가능 |

이미 빌드된 화면으로 앱을 사용하기만 한다면 Node.js는 설치하지 않아도 됩니다. GitHub 계정과 저장소 쓰기 권한은 변경 사항을 푸시할 때 필요합니다.

```bash
git --version
python3 --version
# 웹 클라이언트도 수정할 경우
node --version
npm --version
```

Windows에서는 `py --version`으로 Python을 확인합니다. 여러 버전이 설치되어 있다면 `py -3.12`처럼 3.12 이상인 버전을 명시합니다.

### 2. 저장소 클론과 폴더 열기

작업물을 보관할 상위 폴더에서 실행합니다.

```bash
git clone https://github.com/yongkyu4803/GNU-mukbaque2.git
cd GNU-mukbaque2
git remote -v
git status
```

`origin`이 이 저장소 주소를 가리키는지 확인합니다. 이후 명령은 이 폴더에서 시작합니다. VS Code나 다른 편집기에서도 `GNU-mukbaque2` 폴더 전체를 열면 됩니다. VS Code 명령이 설치되어 있다면 `code .`로 열 수 있습니다.

원본 `mukbaque2/LZ-program`을 추가로 클론하거나 서브모듈을 초기화할 필요는 없습니다. 실행에 필요한 계산 코어와 기본 라이브러리가 이 저장소에 포함되어 있습니다.

이미 클론한 폴더가 있다면 다시 클론하지 말고 해당 폴더에서 현재 변경 사항을 먼저 확인합니다.

```bash
git status
git pull --ff-only
```

아직 커밋하지 않은 수정이 있다면 내용을 검토해 커밋하거나 별도로 보관한 뒤 업데이트합니다. `--ff-only`가 실패하면 로컬·원격 이력이 갈라진 것이므로 강제 덮어쓰기 대신 브랜치 상태부터 확인합니다.

### 3. 첫 실행과 Python 환경 준비

프로젝트 루트에서 실행합니다.

```bash
python3 run.py
```

Windows:

```powershell
py -3.12 run.py
```

이 명령은 다음 작업을 수행합니다.

1. 프로젝트 전용 `.venv/` 가상환경 생성.
2. `requirements.txt`와 `constraints-server.txt`에 맞춰 서버 의존성 설치.
3. FastAPI API와 별도 CPU 워커를 함께 시작.
4. 저장소에 포함된 웹 클라이언트 제공.

브라우저에서 http://127.0.0.1:8001/ 를 엽니다. 화면 상단에 **연구 워커 연결됨**이 표시되는지 확인합니다. API 명세와 직접 요청은 http://127.0.0.1:8001/docs 에서 확인할 수 있습니다.

터미널을 유지해야 서버가 계속 실행됩니다. 종료는 해당 터미널에서 `Ctrl+C`를 누릅니다. 다음 실행에도 같은 `python3 run.py` 명령을 사용합니다. 의존성 파일이나 실행 Python 정보가 바뀌지 않았다면 기존 설치를 재사용합니다.

서버를 시작하지 않고 의존성만 준비하려면 다음을 실행합니다.

```bash
python3 run.py --setup-only
```

`run.py`는 자체적으로 `.venv`의 Python을 사용하므로 가상환경을 수동 활성화할 필요가 없습니다. 아래 개발 명령도 `.venv/bin/python` 경로를 명시해 다른 Python 환경과 섞이지 않게 합니다. 편집기의 Python 인터프리터도 이 프로젝트의 `.venv`로 선택합니다.

### 4. 수정 작업용 브랜치 만들기

작업 전에 최신 `main`에서 새 브랜치를 만듭니다.

```bash
git switch main
git pull --ff-only
git switch -c feat/my-research-change
```

`feat/my-research-change`는 작업 내용에 맞게 변경합니다. 예를 들어 화면 수정은 `feat/candidate-table`, 오류 수정은 `fix/export-pairs`처럼 이름을 정할 수 있습니다.

### 5. 어떤 파일을 수정하면 되는가

| 수정하려는 내용 | 주요 위치 |
|---|---|
| 화면 구성, 폼, 표, 버튼 동작 | `client/src/main.ts` |
| 색상, 여백, 반응형 배치 | `client/src/style.css`, `client/src/tokens.css` |
| 프론트엔드 API 호출과 타입 | `client/src/api.ts` |
| API 주소·라우트·업로드·파일 응답 | `server/main.py` |
| 요청 필드와 입력 검증 | `server/schemas.py` |
| 분석·설계·보정·내보내기 연결 | `server/services.py` |
| 작업 실행·취소·시간 제한 | `server/worker.py` |
| SQLite 저장·작업 상태·복구 | `server/store.py` |
| 점수 함수, 레지스터, 구조 분석·최적화 | `lz/` |
| 기본 제공 서열 라이브러리 | `data/zippers.json` |
| 통합 시작·설치 절차 | `run.py` |
| Python/API/워커 테스트 | `tests/` |
| 브라우저에서 전체 연구 흐름 검증 | `client/tests/workspace.spec.ts` |

화면 소스는 `client/src/`에서 수정합니다. `web/assets/`의 압축된 JavaScript·CSS는 빌드 결과이므로 직접 편집하지 않습니다.

### 6. 웹 화면을 수정하면서 확인하기

처음 한 번 프론트엔드 의존성을 설치합니다.

```bash
# 프로젝트 루트에서
cd client
npm ci
cd ..
```

개발할 때는 터미널 두 개를 사용합니다.

**터미널 A — API와 계산 워커:**

```bash
# 프로젝트 루트
python3 run.py
```

**터미널 B — 웹 개발 서버:**

```bash
# 프로젝트 루트에서
cd client
npm run dev
```

개발 화면은 http://127.0.0.1:5173/ 입니다. `client/src/`의 변경은 Vite 개발 서버가 반영하며, `/api` 요청은 기본 http://127.0.0.1:8001 로 전달됩니다. 실제 데이터와 계산은 터미널 A의 FastAPI·워커가 처리합니다.

FastAPI를 다른 포트에서 실행했다면 프록시 대상도 맞춰야 합니다.

```bash
# 터미널 A, 프로젝트 루트
python3 run.py --port 8080
```

```bash
# 터미널 B, client/ 폴더
LZ_API_PROXY=http://127.0.0.1:8080 npm run dev
```

Windows PowerShell에서 터미널 B의 환경변수 지정은 다음과 같습니다.

```powershell
$env:LZ_API_PROXY = "http://127.0.0.1:8080"
npm run dev
```

`5173`은 소스를 즉시 확인하는 개발 화면이고, `8001`은 빌드된 화면을 제공하는 FastAPI 주소입니다. 개발 중 어느 주소를 보고 있는지 구분합니다.

### 7. Python/API/계산 코드를 수정하면서 확인하기

`python3 run.py`로 실행한 서버에는 소스 자동 재시작이 설정되어 있지 않습니다. `server/` 또는 `lz/`를 수정했다면 통합 실행 터미널에서 `Ctrl+C`를 누르고 다시 시작합니다.

```bash
python3 run.py
```

API 자동 재시작이 필요하면 통합 실행을 먼저 종료하고, 아래 두 명령을 **서로 다른 터미널에서** 실행합니다.

```bash
# 터미널 A, 프로젝트 루트
.venv/bin/python -m uvicorn server.main:app --host 127.0.0.1 --port 8001 --reload
```

```bash
# 터미널 B, 프로젝트 루트
.venv/bin/python -m server.worker
```

Windows에서는 `.venv/bin/python` 대신 `.venv\Scripts\python.exe`를 사용합니다. 같은 API 포트나 데이터 폴더에 대해 `run.py`와 수동 실행을 중복으로 띄우지 않습니다. 계산 코드를 변경한 경우에는 워커도 재시작합니다.

작업에는 제출 당시의 코드 해시와 설정이 기록됩니다. 코드를 변경한 뒤 이전 작업을 그대로 재시도하면 소스 변경 오류가 발생할 수 있습니다. 새 코드로 계산하려면 서버·워커를 재시작하고 화면에서 **새 설계 실행**을 제출합니다.

별도 데이터 폴더를 쓰는 수동 실행에서는 API와 워커 양쪽에 동일한 `LZ_DATA_DIR`를 지정해야 합니다. 통합 실행에서는 `--data-dir` 하나로 두 프로세스에 같은 경로를 전달합니다.

## 변경 사항 검증하기

### Python·API·워커 테스트

프로젝트 루트에서 개발 의존성을 설치합니다.

```bash
python3 run.py --setup-only
.venv/bin/python -m pip install -r requirements-dev.txt -c constraints-server.txt
```

실제 구조 회귀까지 실행하려면 참조 PDB를 내려받습니다.

```bash
.venv/bin/python tools/fetch_structure.py 2ZTA
.venv/bin/python -m pytest tests -q
```

Windows PowerShell:

```powershell
py -3.12 run.py --setup-only
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -c constraints-server.txt
.venv\Scripts\python.exe tools/fetch_structure.py 2ZTA
.venv\Scripts\python.exe -m pytest tests -q
```

PDB를 받지 않아도 테스트 실행은 가능하지만 실제 구조를 사용하는 13개 테스트는 건너뜁니다. Tk나 디스플레이가 없는 환경에서는 기존 GUI 호환성 테스트가 건너뛰어질 수 있습니다. `tests/test_launcher.py`는 원본 체크아웃과 개발 빌드가 없는 별도 임시 폴더에서 웹·API·워커를 함께 실행해 검증합니다.

API 쪽 변경만 빠르게 확인하려면 다음을 사용할 수 있습니다.

```bash
.venv/bin/python -m pytest tests/test_server.py tests/test_launcher.py -q
```

### 웹 빌드와 브라우저 테스트

Python 개발 의존성 준비 후 `client/`에서 실행합니다.

```bash
cd client
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
cd ..
```

`npm run build`는 TypeScript 검사와 프로덕션 빌드를 수행합니다. 브라우저 테스트는 별도의 임시 데이터 폴더에서 API·워커를 시작하므로 실제 연구 데이터의 `var/`에 테스트 기록을 쓰지 않습니다. 테스트용 포트 `8002`는 비어 있어야 합니다. 캡처와 실패 추적 파일은 `client/test-results/`에 생성됩니다.

## 수정한 웹 화면을 저장소 배포본에 반영하기

이 저장소는 Node.js 없이도 실행할 수 있도록 **웹 소스와 배포용 빌드를 함께 관리**합니다. 화면 소스를 변경했다면 빌드하고 `web/`까지 갱신해야 다른 사람이 새 클론에서 수정된 화면을 볼 수 있습니다.

```bash
# 프로젝트 루트에서
cd client
npm ci
npm run build
cd ..
python3 tools/publish_web.py
git status --short
```

파일의 역할과 우선순위는 다음과 같습니다.

| 위치 | 역할 | Git 포함 |
|---|---|---|
| `client/src/`, `client/public/` | 수정하는 화면·스타일·폰트 원본 | 포함 |
| `client/dist/` | 로컬 빌드 결과 | 제외 |
| `web/` | 다른 사용자가 바로 실행할 배포용 빌드 | 포함 |

서버 시작 시 `client/dist/index.html`이 있으면 로컬 빌드를 우선 사용하고, 없으면 `web/`을 사용합니다. `tools/publish_web.py`는 현재 `client/dist/`의 내용으로 `web/`을 교체하므로, 반드시 빌드를 먼저 수행합니다.

화면 수정 후에는 `client/` 소스 변경과 `web/` 변경을 함께 커밋합니다. 다른 컴퓨터에서 최신 소스를 pull한 뒤에도 예전 화면이 보인다면, 남아 있는 `client/dist/`가 `web/`보다 우선되고 있을 수 있습니다. 최신 소스로 `npm ci && npm run build`를 다시 실행하고 FastAPI를 재시작합니다.

## 커밋하고 GitHub에 올리기

검증과 배포용 웹 빌드 갱신을 마친 뒤 변경 내용을 확인합니다.

```bash
git status --short
git diff
```

문서만 변경했다면 다음처럼 해당 파일만 추가합니다.

```bash
git add README.md
```

코드와 화면을 변경했다면 수정한 경로를 선택해서 추가합니다. 예를 들어:

```bash
git add server/ client/ web/ tests/
```

커밋 직전에는 실제 포함될 내용을 다시 확인합니다.

```bash
git diff --cached --stat
git diff --cached --check
git commit -m "feat: improve candidate comparison workflow"
git push -u origin feat/my-research-change
```

브랜치 이름은 앞서 만든 자신의 작업 브랜치로 바꿉니다. 이후 GitHub에서 해당 브랜치의 Pull Request를 열어 `main`에 반영합니다. 저장소 쓰기 권한이 없다면 자신의 fork에 푸시하고 이 저장소로 Pull Request를 보냅니다. 인증 오류가 나면 자신의 GitHub 인증과 저장소 권한을 확인합니다.

작업이 반영된 뒤 다음 작업을 시작할 때는 다음 순서를 사용합니다.

```bash
git switch main
git pull --ff-only
git switch -c feat/next-change
```

## 연구 데이터와 로컬 파일 관리

다음 항목은 `.gitignore`로 제외됩니다.

- `var/`: SQLite DB, 업로드한 구조·서열·측정 데이터, 실행 결과.
- `.venv/`, `client/node_modules/`: 다시 설치할 수 있는 의존성.
- `client/dist/`, 브라우저 테스트 출력: 로컬 생성물.
- `.env`와 환경별 설정 파일.
- `structures/*.pdb`, `structures/*.cif`: 내려받은 구조 파일.
- `LZ-program/`: 로컬에 남아 있을 수 있는 원본 체크아웃.

따라서 `git push`나 다른 컴퓨터에서의 `git clone`으로 연구 실행 이력과 측정 데이터까지 이동하지는 않습니다. 데이터를 옮기려면 API와 워커를 종료한 뒤 `var/` 폴더 전체를 별도로 백업·복사하고, 새 환경의 `--data-dir`로 지정합니다. SQLite의 WAL 파일이 남아 있을 수 있으므로 실행 중 DB 파일 하나만 복사하는 방식은 사용하지 않습니다.

프로젝트를 다시 클론했을 때 `.venv`, `node_modules`, `var`가 없는 것은 정상입니다. 실행 환경은 설치 명령으로 재생성하고, 필요한 연구 데이터는 별도 백업에서 복원합니다.

## 자주 발생하는 문제

| 증상 | 확인·해결 |
|---|---|
| Python 버전 오류 | `python3 --version` 또는 `py --version` 확인 후 3.12 이상 사용 |
| `8001` 포트 사용 중 | 기존 실행을 종료하거나 `python3 run.py --port 8080` 사용 |
| 화면에 워커 연결 대기 표시 | 통합 실행 로그 확인. 수동 실행이면 워커를 시작하고 양쪽 데이터 경로 일치 확인 |
| 설계가 계속 대기 중 | 워커 실행 여부와 `/api/v1/health/ready` 확인 |
| 개발 화면에서 API 연결 실패 | `run.py` 실행 여부, API 포트와 `LZ_API_PROXY` 일치 확인 |
| `npm ci` 실패 | Node.js 버전과 `client/` 위치 확인. 의존성 수정 작업이 아니라면 lock 파일을 임의 삭제하지 않음 |
| 코드를 수정했는데 화면이 같음 | `5173` 개발 화면인지 확인. `8001`에서는 빌드·재시작 필요 |
| 다른 사람이 예전 화면을 봄 | `npm run build` 후 `tools/publish_web.py` 실행 여부와 `web/` 커밋 여부 확인 |
| 재시도에 source changed 오류 | 수정된 코드로 서버·워커 재시작 후 새 작업 제출 |
| 구조 테스트가 skipped | `tools/fetch_structure.py 2ZTA`로 실제 구조 다운로드 |

실행 옵션 전체는 `python3 run.py --help`, 개별 계산 CLI는 `.venv/bin/python -m lz --help`로 확인할 수 있습니다.

[API 안내](SERVER.md) · [클라이언트 안내](client/README.md) · [아키텍처](01-fastapi-architecture.md) · [연구 자동화](02-research-automation.md)
