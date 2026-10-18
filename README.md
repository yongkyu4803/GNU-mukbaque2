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

## 개발 및 검증

```bash
python3 run.py --setup-only
.venv/bin/python -m pip install -r requirements-dev.txt -c constraints-server.txt
.venv/bin/python tools/fetch_structure.py 2ZTA
.venv/bin/python -m pytest tests -q
```

실제 PDB를 다운로드하지 않으면 해당 13개 회귀 테스트는 건너뜁니다. Tk가 없는 환경에서는 디스플레이가 필요한 기존 GUI 호환성 테스트도 건너뛸 수 있습니다. Windows에서는 `.venv\Scripts\python.exe`를 사용합니다.

웹 화면 수정에는 Node.js 22.12 이상이 필요합니다.

```bash
cd client
npm ci
npm run build
npx playwright install chromium
npm run test:e2e
```

서버는 개발 빌드 `client/dist/`가 있으면 우선 사용하고, 없으면 저장소에 포함된 `web/`을 사용합니다. 배포용 `web/` 업데이트에는 루트에서 `python3 tools/publish_web.py`를 실행합니다. API 프로세스를 재시작하면 새 클라이언트가 반영됩니다.

API와 워커를 수동으로 실행할 수도 있습니다. 두 프로세스는 같은 `LZ_DATA_DIR`를 사용해야 합니다.

```bash
.venv/bin/python -m lz serve --port 8001
.venv/bin/python -m server.worker
```

[API 안내](SERVER.md) · [클라이언트 안내](client/README.md) · [아키텍처](01-fastapi-architecture.md) · [연구 자동화](02-research-automation.md)
