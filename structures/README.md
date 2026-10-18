# structures/

구조 파일은 저장소에 포함되지 않습니다. 남의 데이터이고, RCSB가 정본이며,
받아오는 것이 재현 가능하기 때문입니다.

```bash
python tools/fetch_structure.py 2ZTA
```

`tests/test_real_structure.py`가 `2ZTA.pdb`를 쓰고, 파일이 없으면 자동으로
건너뜁니다. 그래서 오프라인에서도 전체 테스트 스위트가 돌아갑니다.

류신 지퍼 관련해서 볼 만한 엔트리:

| 코드 | 내용 |
|---|---|
| **2ZTA** | GCN4 류신 지퍼 — 평행 이중나선의 표준 참조 구조 |
| 1YSA | GCN4 bZIP + DNA (염기성 영역까지 포함) |
| 1FOS | Fos/Jun 이종이량체 + DNA |
| 1GU4 | Max 동종이량체 (bHLH-Zip) |
| 1U0I | 설계된 역평행 coiled coil — 음성 대조군으로 유용 |
