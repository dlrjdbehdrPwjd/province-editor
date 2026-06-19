# 파이프라인 프로젝트

Victoria 3 지도용 province graph 기반 기후·수문·강수 정규화·쾨펜/바이옴/지형 자동 산출 파이프라인이다.

현재 기준 상태는 **MVP baseline**이다. STEP 0~5까지 구현되어 있고, 빈 `province_constraints.yaml` 기준으로 최종 `koppen/biome/terrain` 산출까지 실행 확인했다.

## 현재 구현 단계

```text
STEP 0  scripts/build_province_graph.py
STEP 1  scripts/build_bootstrap_fields.py
STEP 2  scripts/run_climate_pipeline.py
STEP 3  scripts/build_hydrology.py
STEP 4  scripts/build_rainfall_normalization.py
STEP 5  scripts/build_koppen_biome_terrain.py
```

보조 진단 스크립트:

```text
scripts/diagnose_latitude_koppen.py
scripts/diagnose_aridity.py
scripts/diagnose_et_world_scale_grid.py
scripts/diagnose_b_band_breakdown.py
```

## 주요 폴더

```text
config/      입력 설정, 룰, terrain lookup
docs/        설계 명세와 canonical 문서 목록
scripts/     실행 스크립트
tests/       단위 테스트
revisions/   dev_empty 등 revision별 constraints/overrides
cache/       재생성 가능한 중간 산출물
outputs/     재생성 가능한 debug 이미지
```

## MVP baseline 검증 상태

```text
테스트: 46 tests passed
입력 상태: constraints-empty baseline
fallback_priority_1: 318개, 비블로커
최종 산출: cache/koppen_biome_terrain.json
```

fallback 318개는 모두 `Cfb/Cwb + temperate_forest + lowland` 조합이며, `soil_moisture < 0.4` 조건으로 `plains` terrain fallback을 탄 케이스다.

## 현재 결과의 해석

현재 산출물은 산맥, 고도 힌트, 강 seed, 호수 seed, rain shadow 입력이 거의 없는 자동 baseline이다.

따라서 아래 항목은 아직 최종 월드 품질 문제가 아니라 입력 데이터 부재에 따른 known limitation으로 본다.

```text
synthetic_elevation_m = 0.0 ~ 0.0
D climate = 0%
BWh hot desert = 0개
subtropical B-class 비율 낮음
hydrology 강망은 지형 seed 없는 자동 초안
```

## 기본 실행 순서

PowerShell에서 프로젝트 폴더로 이동한 뒤 실행한다.

```powershell
cd "C:\Users\kimsiyeol\Documents\빅씹타치 맵 자동 파이프라인\Codex_프로그래머\파이프라인_프로젝트"

& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\build_province_graph.py --debug
& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\build_bootstrap_fields.py --debug
& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\run_climate_pipeline.py --pretty --debug
& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\build_hydrology.py --debug
& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\build_rainfall_normalization.py --debug
& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" scripts\build_koppen_biome_terrain.py --debug
```

테스트:

```powershell
& "C:\Users\kimsiyeol\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe" -m unittest discover -s tests -q
```

## 다음 작업

```text
1. Git 추적 범위 확정
2. canonical 문서 기준 유지
3. pipeline_run_manifest 구현
4. province_constraints.yaml 실제 작성
```
