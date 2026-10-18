# Protein Lab 웹 클라이언트

류신 지퍼 연구용 FastAPI에 연결되는 TypeScript/Vite 클라이언트다. 별도 프론트엔드 서버 없이 빌드 파일을 FastAPI가 제공할 수 있다.

## 실행

Node.js 22.12 이상을 권장한다. 이번 구현은 Node.js 26에서 검증했다.

```bash
cd client
npm ci
npm run build
cd ..
source .venv/bin/activate
python -m lz serve --port 8001
```

다른 터미널에서 같은 데이터 폴더를 사용하는 워커를 실행한다.

```bash
python -m server.worker
```

http://127.0.0.1:8001/ 에서 클라이언트를 연다. API 문서는 `/docs`에 유지된다. 클라이언트 빌드가 없으면 루트 주소는 API 문서로 이동한다. 최초 빌드 뒤에는 API 서버를 재시작한다.

개발 모드:

```bash
cd client
npm run dev
```

개발 주소는 http://127.0.0.1:5173 이며 `/api` 요청을 기본 http://127.0.0.1:8001 로 프록시한다. 다른 서버에는 `LZ_API_PROXY=http://127.0.0.1:8000 npm run dev`처럼 지정한다. 운영 빌드는 동일 출처의 `/api/v1`을 사용한다.

## 화면과 동작

- 파트너 탐색: 직접 서열, 단일 FASTA 또는 PDB 입력, 시작 레지스터와 chain 선택.
- 탐색 설정: 점수 모델·라이브러리 선택, 다중 탐색, 단계 수·seed·직교 쌍 수·마진 설정.
- 후보 결과: 점수·특이성 비교, 후보 정렬·선택, 실제 계산값의 비교 그래프, 서열과 FASTA 복사.
- 직교 결과: 최종 shift 재평가 행렬, 의도된 쌍, 최강 경쟁자와 최종 마진.
- 실행 관리: 진행률 자동 갱신, 취소·재시도, 이력 검색·결과 재열기.
- 내보내기: 선택한 후보 CSV 및 서버에서 생성한 FASTA/JSON/manifest 다운로드.
- 서열 라이브러리: 출처·recall 확인, FASTA/JSON 가져오기.
- 모델 보정: Tm CSV 업로드, 보정 실행, 학습 지표·가중치 확인.
- 구조 표적: 분석 근거·경고 확인, 구조 재분석·도킹 입력 준비.

화면의 계산값은 API 결과를 사용한다. GCN4 예제는 DEMO로 표시하고 자동 등록하거나 실험 데이터로 취급하지 않는다. 입력 폼의 서열은 **표적 등록 · 분석**을 눌러 저장한 뒤 탐색에 사용한다. 스크리닝은 양쪽 호모다이머 기준도 별도 열로 표시한다. 보정 모델의 오차는 학습 성능이며 독립 검증 성능이 아니다.

## 디자인과 글꼴

사용자가 지정한 `artifact-template-protein-lab` 스킬의 기준 이미지와 토큰을 적용했다. 흰색 연구 패널, 코발트 블루 포인트, 조밀한 표, 실제 점수 그래프, 반응형 탐색으로 구성한다.

- 제목: 로컬에 설치된 기계연구원체 원본 `KIMM_Bold.ttf`, 실제 내부 family `KIMMBold` 확인.
- 본문: Pretendard 1.3.9 Regular/SemiBold, SIL OFL 원문 포함.
- 서열: 고정폭 글꼴.

글꼴은 `public/fonts/`에서 직접 제공하므로 렌더링에 외부 CDN이 필요하지 않다. 좌측 이중나선은 설명용 도식이며 실제 단백질 구조 예측이 아니다.

## 검증

```bash
npm run build
npx playwright install chromium
npm run test:e2e
```

브라우저 테스트는 별도 임시 데이터 폴더에서 API와 CPU 워커를 시작한다. 실제 연구 데이터의 `var/`에는 테스트 레코드를 쓰지 않는다. 서버 테스트에는 Python 가상환경과 pytest가 필요하다. 데스크톱 1440px 및 모바일 390px에서 글꼴 로드·가로 넘침·폼·결과·다운로드를 검증하며 캡처는 `test-results/`에 생성한다.
