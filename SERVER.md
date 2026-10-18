# FastAPI 연구 서버 실행 안내

이 프로젝트는 기존 `lz` 계산 모듈을 사용하는 FastAPI 서버와 별도 CPU 워커, Protein Lab 웹 클라이언트를 제공한다. ``web/` 빌드가 포함되어 있으므로 API 서버를 시작하면 루트 주소에서 웹 화면이 열린다. API 문서는 `/docs`에 유지되며 기존 CLI/Tkinter GUI도 계속 사용할 수 있다. 상세 웹 실행법은 [client/README.md](client/README.md)에 있다.

## 시작하기

프로젝트 루트에서 Python 3.12 이상을 권장한다. 고정 버전 제약 파일은 Python 3.12 이상을 대상으로 하며, 이번 마이그레이션은 macOS의 Python 3.13에서 검증했다. Python 3.10/3.11에서는 `-c constraints-server.txt`를 제외해 호환되는 NumPy를 설치한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt -c constraints-server.txt
python -m lz serve
```

다른 터미널에서 같은 프로젝트 폴더와 가상환경으로 워커를 실행한다.

```bash
source .venv/bin/activate
python -m server.worker
```

Windows에서는 가상환경 활성화에 `.venv\Scripts\activate`를 사용한다. 기존 `build-exe.bat`은 데스크톱 GUI 빌드이며 FastAPI 서버를 빌드하지 않는다.

- API 문서: http://127.0.0.1:8000/docs
- OpenAPI: http://127.0.0.1:8000/openapi.json
- API 생존 확인: `/api/v1/health/live`
- 워커까지 준비됨: `/api/v1/health/ready` (워커가 없으면 503)

API와 워커는 동일한 데이터 폴더를 사용해야 한다. 기본값은 현재 작업 디렉터리의 `var/`이다. 다른 위치를 쓰려면 두 명령에 같은 절대 경로를 지정한다.

```bash
python -m lz serve --data-dir /absolute/path/lz-data --port 8000
python -m server.worker --data-dir /absolute/path/lz-data
```

`LZ_DATA_DIR` 환경변수로도 지정할 수 있다. 직접 Uvicorn으로 실행할 수도 있다.

```bash
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000
```

## 기본 사용 흐름

### 1. 표적 생성

`POST /api/v1/targets`

```json
{
  "name": "GCN4 example",
  "helix": {
    "sequence": "RMKQLEDKVEELLSKNYHLENEVARLKKLVGER",
    "offset": 6
  }
}
```

응답의 `id`를 다음 요청의 `target_id`로 사용한다. 구조를 이용하려면 `POST /inputs`에 PDB를 업로드하고 `{"name":"target","input_id":"input_...","chain":"A"}`로 표적을 생성한다. FASTA 표적 입력은 record가 정확히 하나여야 한다.

### 2. 스크리닝 또는 설계

`POST /api/v1/analyses/screen`

```json
{"target_id": "target_...", "library_id": "default", "model_id": "default"}
```

`POST /api/v1/runs`

```json
{
  "kind": "design",
  "target_id": "target_...",
  "model_id": "default",
  "seed": 1,
  "parameters": {"n_restarts": 8, "n_steps": 4000}
}
```

설계는 202와 작업 ID를 반환한다. 워커가 꺼져 있으면 작업은 queued로 보존되며, 워커가 시작된 후 처리한다. seed를 생략하면 서버가 생성해 실행 기록에 저장한다.

직교 설계는 `kind=orthogonal`과 `parameters.n_pairs`를 사용한다. 표적 없는 전체 공동 설계도 가능하다.

```json
{
  "kind": "orthogonal",
  "seed": 20,
  "parameters": {"n_pairs": 2, "n_restarts": 1, "n_steps": 2000, "margin": 3.0}
}
```

### 3. 상태와 결과 조회

- `GET /api/v1/runs/{id}`: 상태·진행률·확정 설정·seed·스냅샷.
- `GET /api/v1/runs/{id}/results`: 성공한 작업의 결과. 미완료·실패는 409.
- `GET /api/v1/runs/{id}/artifacts`: JSON/CSV/FASTA/manifest 목록.
- `GET /api/v1/artifacts/{id}/download`: 해당 파일 다운로드.
- `POST /api/v1/runs/{id}/cancel`: 대기 또는 실행 중 작업 취소.
- `POST /api/v1/runs/{id}/retry`: 실패·취소된 작업을 같은 seed·스냅샷으로 다시 제출.

재시도는 새 작업 ID와 `parent_id`를 생성한다. 이전 기록을 덮어쓰지 않으며, 중간 iteration부터 이어가는 기능은 제공하지 않는다. 제출 뒤 소스 파일이 달라졌다면 재시도를 거부하므로 변경된 코드에서는 새 실행을 제출한다.

### 4. 다른 작업 종류

| kind | 필수 값 | 결과 |
|---|---|---|
| `structure` | PDB `input_id`, 선택 `chain` | 나선·배향·레지스터·리간드 분석 |
| `dockprep` | PDB `input_id`, 선택 `chain` | receptor PDB, PDBQT를 참조하는 Vina config, 도킹 박스 |
| `calibration` | CSV `input_id` | 보정 모델과 학습 오차, 모델 catalog 등록 |
| `export` | `source_run_id` | 성공한 design/orthogonal 결과의 ColabFold 입력 재생성 |

도킹 준비 후 receptor PDBQT 변환은 별도로 해야 한다. 도킹이나 GPU 구조 예측은 이 서버가 실행하지 않는다. FASTA 출력은 ColabFold의 콜론 구분 복합체 형식이며 모든 AlphaFold 도구에 그대로 호환된다고 가정하지 않는다.

## 점수와 보정 모델

기본 모델은 보정되지 않은 순위 점수이며 API에서 `predicted_tm=null`을 반환한다. 보정 CSV 열은 `sequence1,sequence2,tm`이다. 최소 5개, 최대 5000개 측정을 받으며 rank가 부족하거나 core 계수가 음수가 아니면 보정을 실패로 기록한다.

보정 완료 후 응답의 `model.id`를 `/analyses/score`, `/analyses/screen`, 설계 요청의 `model_id`에 전달한다. 모델에는 상대 가중치와 Tm slope/intercept가 함께 저장된다. R²/RMSE는 학습 데이터의 값으로 독립 검증 성능이 아니다.

CLI도 전체 보정 JSON과 이전 weight-only JSON을 읽는다.

```bash
python -m lz calibrate measurements.csv --out model.json
python -m lz score SEQUENCE1 SEQUENCE2 --weights model.json --tm
```

스크리닝 결과는 기존 정의인 `hetero - candidate_self`와 양쪽 호모다이머 기준 `specificity_both`를 함께 제공한다. 새 파트너 설계의 specificity는 양쪽 중 더 강한 호모다이머를 기준으로 한다. 직교 세트의 최종 행렬은 허용 shift를 탐색해 재평가하며 탐색 중 고정 shift 행렬도 별도로 남긴다.

`status=succeeded`는 계산 정상 종료를 뜻한다. `evaluation.passed=false`인 직교 설계도 정상 계산 결과로 보관한다. 모델 기준 통과는 실험적 결합·친화도·직교성 검증을 뜻하지 않는다.

## 저장·복구·운영 범위

- SQLite `research.db`는 WAL을 사용한다. 스키마 버전은 `PRAGMA user_version`으로 관리한다.
- 업로드는 불변 ID로 저장하고 파일명으로 서버 경로를 지정하지 않는다.
- 작업마다 입력·모델·설정·코드 해시·의존성·산출물 해시를 manifest에 보관한다.
- 계산은 별도의 spawned process에서 실행되며 API 프로세스 재시작과 독립적이다.
- 워커 기본 제한은 작업당 900초다. `--timeout`으로 변경한다.
- 실행 중 취소는 협력적 중단 후 필요하면 자식 프로세스를 종료한다.
- heartbeat가 30초 이상 끊긴 실행은 다음 워커가 failed/interrupted로 기록한다. 대기 작업은 유지한다.
- 산출물과 보정 모델은 자식 프로세스가 성공한 뒤 DB에 함께 등록한다. 실패·취소된 중간 파일은 다운로드 목록에 공개하지 않는다.
- 디버그 traceback은 해당 실행의 데이터 폴더에만 저장한다. 백업은 API와 워커를 중지한 뒤 데이터 폴더 전체를 복사한다.

초기 운영은 로컬 단일 사용자·단일 호스트를 대상으로 한다. 기본 바인딩은 loopback이며 사용자 인증은 없다. 다중 사용자나 외부 네트워크 배포는 인증·권한·TLS와 PostgreSQL/별도 큐 구성을 추가한 후 진행한다. SQLite DB를 네트워크 파일시스템으로 공유하지 않는다.

입력 제한은 파일당 5 MiB, PDB 20000 atom/16 chain/chain당 500 CA record다. 설계는 길이 14~100, 직교 세트는 최대 4쌍, 전체 탐색은 400000 work-unit으로 제한한다. NMR 다중 모델·큰 구조는 필요한 모델과 구간을 추출해 업로드한다.

동기 스크리닝은 표적 길이 × 라이브러리 전체 잔기 수가 1000000 이하인 경우에 제공한다. 초과하면 라이브러리를 작은 버전으로 나눠 처리한다. 이 버전은 후보 수와 행렬 크기를 제한해 결과를 한 응답으로 반환하며 대규모 결과 pagination은 후속 범위다.

## 테스트

```bash
python -m pip install pytest
python tools/fetch_structure.py 2ZTA
python -m pytest tests -q
```

실제 구조 파일이 없으면 해당 회귀 테스트는 건너뛴다. `tests/test_server.py`는 HTTP 입력부터 실제 별도 계산 프로세스, DB 결과 확정과 다운로드까지 검증한다. 전체 CLI/GUI 회귀도 기존 스위트에 포함되어 있다.
