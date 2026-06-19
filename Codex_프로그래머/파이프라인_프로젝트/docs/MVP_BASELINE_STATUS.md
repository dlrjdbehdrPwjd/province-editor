# MVP baseline status

작성 기준: 2026-06-19

## Summary

기후·지형 파이프라인 MVP는 STEP 0~5까지 구현 및 실행 확인된 상태다.

```text
STEP 0: build_province_graph.py
STEP 1: build_bootstrap_fields.py
STEP 2: run_climate_pipeline.py
STEP 3: build_hydrology.py
STEP 4: build_rainfall_normalization.py
STEP 5: build_koppen_biome_terrain.py
```

## Verification

```text
tests: 46 passed
land_province_count: 58,376
sea_province_count: 453
total_province_count: 58,829
```

최종 STEP 5 실행 결과:

```text
schema_version: koppen_biome_terrain.v0.7
land_province_count: 58376
terrain_classes: 7
fallback_priority_0: 0
fallback_priority_1: 318
warnings: 0
debug_artifacts: 12
```

## Current baseline character

현재 결과는 `revisions/dev_empty/` 기준의 constraints-empty baseline이다.

```text
synthetic_elevation_m range: 0.0 ~ 0.0
mountain/rain-shadow constraints: not authored yet
river/lake/wetland seed constraints: not authored yet
terrain/biome result: automatic baseline
```

## Final Koppen group ratio

```text
A: 34968 / 58376 = 59.90%
B:  5281 / 58376 =  9.05%
C: 16483 / 58376 = 28.24%
D:     0 / 58376 =  0.00%
E:  1644 / 58376 =  2.82%
H:     0 / 58376 =  0.00%
```

## fallback_priority_1 check

`fallback_priority_1` 318개는 현재 블로커가 아니다.

```text
koppen_class:
  Cfb: 284
  Cwb: 34

biome:
  temperate_forest: 318

elevation_class:
  lowland: 318

vic3_terrain:
  plains: 318

soil_moisture:
  min: 0.12652199
  p25: 0.16755938
  p50: 0.20876072
  p75: 0.26689120
  max: 0.39641996
```

해석: 건조한 온대림 후보가 `terrain_lookup.csv`에서 priority 1 fallback을 통해 `plains`로 매핑된 상태다.

## Known limitations

```text
D climate = 0%
  고위도 land가 0.66% 수준이라 현재 baseline에서는 구조적 한계.

BWh hot desert = 0개
  아열대 평균기온/ET와 constraints 부재 영향.

subtropical B-class low
  docs/koppen_biome_terrain_spec_v0.7.md known limitation 참고.

hydrology river network
  constraints 없는 automatic baseline. river_seed/mountain/rain-shadow 입력 후 재평가 필요.
```

## Next work

```text
1. Git tracking scope 정리
2. pipeline_run_manifest 구현
3. province_constraints.yaml 실제 작성
4. constraints 입력 후 STEP 1~5 재실행 및 baseline 비교
```
