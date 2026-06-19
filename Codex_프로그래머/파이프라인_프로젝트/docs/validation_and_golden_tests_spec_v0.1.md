# validation_and_golden_tests_spec v0.1

> 기후·지형 생성 파이프라인의 결과를 검증하는 기준 문서.
> 이 문서는 새 알고리즘을 추가하지 않고, 사전 등록된 합격선과 실패 귀속 절차를 정의한다.
>
> 목표는 "그럴듯해 보이는 지도"가 아니라,
> 어떤 층이 틀렸는지 재현 가능하게 판정할 수 있는 검증 체계를 만드는 것이다.

---

## 0. 이 문서의 범위

포함:

```text
golden test 실행 원칙
사전 등록 합격선
지구 재현 테스트
백지 판게아 창발 테스트
층별 검증 순서
실패 귀속 프로토콜
debug artifact 필수 보존
예상 실패 목록
과적합 방지 규칙
test manifest 출력
```

포함하지 않음:

```text
파이프라인 실행 순서              → pipeline_orchestration_spec_v0.1
Koppen-lite / terrain 판정식       → koppen_biome_terrain_spec_v0.7
수문 / 강 / 호수 생성              → hydrology_spec_v0.5
rainfall normalization 계산        → rainfall_normalization_spec_v0.6
실제 지구 기준 데이터 제작         → 별도 data preparation script
Vic3 map_data 최종 export          → final export spec
```

---

## 1. 핵심 설계 원칙

```text
1. 합격선은 실행 전에 사전 등록한다.
2. 결과를 본 뒤 합격선을 수정하지 않는다.
3. 테스트는 위도 띠(zonal) → 지역 패턴 → 최종 terrain 순서로 본다.
4. 지구 재현 테스트만 통과하면 충분하지 않다.
5. 백지 판게아 창발 테스트를 함께 통과해야 한다.
6. 실패하면 먼저 어느 stage가 틀렸는지 귀속한다.
7. 원인 귀속 전에는 threshold 튜닝 금지.
8. 모든 golden run은 debug map과 통계 파일을 함께 보존한다.
```

검증 철학:

```text
사하라가 맞았는데 위도별 강수 띠가 틀렸다면 운이다.
위도 띠가 맞고 특정 대륙만 틀리면 지형/수문/해류 문제일 가능성이 높다.

따라서 특수 지역 디버깅보다 zonal baseline을 먼저 본다.
```

---

## 2. 테스트 종류

### 2-1. smoke test

목적:

```text
파이프라인이 끝까지 실행되는지 확인.
정확도 평가가 아니라 실행 가능성 검증.
```

입력:

```text
작은 synthetic map
최소 province_constraints.yaml
최소 province_overrides.yaml
기본 climate_rules.yaml
기본 terrain_lookup.csv
```

합격:

```text
FATAL 없음
모든 stage output 생성
cache/koppen_biome_terrain.json 생성
NaN / Infinity 없음
```

### 2-2. unit fixture test

목적:

```text
각 stage 계약이 깨지지 않았는지 검증.
```

예:

```text
force_rainfall 적용 시점 fixture
exclude_from_sim local_runoff=0 통과 노드 fixture
lake_seed sink hint fixture
terrain_lookup 중복 매칭 ERROR fixture
rainfall seasonal sum 보존 fixture
```

### 2-3. earth golden test

목적:

```text
현실 지구의 큰 기후 구조를 재현하는지 검증.
```

입력:

```text
지구 기반 provinces.png
지구 기반 default.map / world.yaml
지구 기준 province_constraints.yaml
지구 기준 province_overrides.yaml
고정 climate_rules.yaml
고정 terrain_lookup.csv
```

### 2-4. blank pangaea emergence test

목적:

```text
사용자 손튜닝 없이도 대륙 스케일 패턴이 창발하는지 검증.
```

입력:

```text
단순 초대륙 provinces.png
최소 default.map / world.yaml
빈 province_constraints.yaml
빈 province_overrides.yaml
고정 climate_rules.yaml
고정 terrain_lookup.csv
```

기대 패턴:

```text
서안 건조대 또는 해안 사막 후보
내륙 스텝 / 내륙 건조대
동안 습윤대
적도 주변 습윤대
아열대 고압대 건조대
강/분지 후보가 지형장과 일관되게 생성
```

주의:

```text
백지 판게아는 정답 지도가 없다.
정량 metric보다 구조적 sanity check와 debug map 비교가 핵심이다.
```

---

## 3. 사전 등록

golden test 실행 전 다음 파일을 만든다.

```text
validation/golden_runs/{test_id}/pre_registration.yaml
```

필수 항목:

```yaml
test_id: earth_golden_v0_1
pipeline_version: pipeline_orchestration.v0.1
input_revision: sha256:...
pipeline_input_manifest: validation/golden_runs/earth_golden_v0_1/pipeline_input_manifest.json
climate_rules_hash: sha256:...
terrain_lookup_hash: sha256:...
reference_bundle_hash: sha256:...
expected_metrics:
  zonal_temperature_rmse_max: 8.0
  zonal_rainfall_rmse_max: 0.35
  koppen_major_group_accuracy_min: 0.45
  dry_zone_precision_min: 0.55
  dry_zone_recall_min: 0.40
  tropical_wet_recall_min: 0.50
holdout_policy:
  tuning_regions: ["Africa", "Europe", "South America"]
  holdout_regions: ["Asia", "Oceania", "North America"]
known_expected_failures:
  - sahel_too_dry_bias
  - wadi_absent
  - ice_sheet_dynamics_absent
```

규칙:

```text
pre_registration.yaml은 golden run 시작 후 수정 금지.
결과를 본 뒤 합격선을 바꾸려면 새 test_id를 만든다.
```

`input_revision` 의미:

```text
input_revision은 pipeline_run_manifest의 inputs_hash 묶음과 일치해야 한다.
즉 검증 대상 pipeline run이 사용한 map_data / province_constraints /
province_overrides / climate_rules / terrain_lookup 입력 묶음의 canonical hash다.

golden runner가 임의로 입력 파일을 다시 해석해서 input_revision을 만들지 않는다.
pipeline_orchestration이 기록한 input hash 묶음을 기준으로 한다.
```

`pipeline_input_manifest` 의미:

```text
--run-pipeline 사용 시 golden runner가 pipeline_orchestration에 전달할 입력 manifest다.
golden runner는 map_data / province_constraints / province_overrides /
climate_rules / terrain_lookup 경로를 개별 CLI 옵션으로 다시 받지 않는다.

pipeline_input_manifest는 pipeline_orchestration CLI 입력을 감싼 고정 파일이며,
해당 파일의 canonical hash가 input_revision과 연결되어야 한다.
```

---

## 4. 기준 데이터

### 4-1. 기준 데이터 종류

필수:

```text
reference/zonal_temperature.csv
reference/zonal_rainfall.csv
reference/koppen_reference_by_province.csv
reference/region_tags_by_province.csv
```

선택:

```text
reference/major_river_basins_by_province.csv
reference/desert_mask_by_province.csv
reference/rainforest_mask_by_province.csv
reference/monsoon_region_mask_by_province.csv
```

주의:

```text
기준 데이터 출처와 해상도는 pre_registration에 기록한다.
출처 미기록 기준 데이터는 golden test에 사용하지 않는다.
```

reference hash:

```text
reference_bundle_hash = golden test에 사용한 모든 reference 파일의 canonical hash.
파일명 정렬 → 파일별 canonical hash 계산 → 해시 목록을 다시 hash한다.

golden_test_report에는 reference_bundle_hash와 reference_hashes를 모두 기록한다.
```

예:

```json
{
  "reference_bundle_hash": "sha256:...",
  "reference_hashes": {
    "zonal_temperature": "sha256:...",
    "zonal_rainfall": "sha256:...",
    "koppen_reference_by_province": "sha256:...",
    "region_tags_by_province": "sha256:..."
  }
}
```

### 4-2. province 매핑

기준 데이터는 province 단위로 매핑한다.

필수 컬럼:

```csv
province_key,reference_value,source_dataset,source_resolution,mapping_method
```

허용 mapping_method:

```text
area_majority
area_weighted_mean
center_point
manual_label
```

권장:

```text
기후 연속값: area_weighted_mean
Koppen class: area_majority
작은 하천/특수 권역: manual_label 또는 별도 mask
```

금지:

```text
테스트 실패 후 province label을 임의 수정
source_dataset이 섞인 reference를 하나의 metric으로 비교
```

---

## 5. 테스트 실행 순서

기본 모드:

```text
golden test runner는 기존 pipeline_run을 검증한다.
기본 모드에서는 pipeline을 재실행하지 않는다.
```

pipeline 재실행 모드:

```text
--run-pipeline 옵션이 명시된 경우에만 pipeline_orchestration을 실행할 수 있다.
이 경우 새 pipeline_run_id가 생성된다.
golden_test_report는 새 pipeline_run_id에 연결된다.
```

golden run 순서:

```text
1. pre_registration 로드
2. 입력 파일 hash 검증
3. pipeline_run_manifest 로드
4. pipeline_run_id와 input_revision 검증
5. debug artifact 목록 검증
6. stage output schema validation
7. zonal metric 계산
8. regional metric 계산
9. Koppen / biome / terrain metric 계산
10. failure attribution 실행
11. golden_test_report.json 저장
```

중요:

```text
특정 지역 metric보다 zonal metric을 먼저 평가한다.
zonal metric이 실패하면 지역 metric이 일부 맞아도 golden pass로 보지 않는다.
golden test runner는 pipeline 산출물을 수정하지 않는다.
새 pipeline run이 필요하면 --run-pipeline 명시 옵션으로 새 run_id를 만든다.
```

---

## 6. 층별 검증 순서

### 6-1. Stage 0: graph/topology

확인:

```text
resolved_sea_set
coastal_ratio
latitude
adjacency coverage
land target count
```

실패 귀속:

```text
바다/해안이 틀림 → build_province_graph_design.v0.2
latitude가 틀림 → world.yaml 또는 latitude formula
adjacency가 틀림 → province_graph scan
```

### 6-2. Stage 1: bootstrap fields

확인:

```text
continentality map
synthetic_elevation_m map
synthetic_flow_potential map
is_flow_sink 후보
```

실패 귀속:

```text
내륙/해안 구배가 없음 → coast_distance / continentality
산지 terrain이 전부 낮음 → mountain_strength / elevation_hint / bootstrap mapping
강 흐름이 이상함 → synthetic_flow_potential 또는 lake_seed
```

### 6-3. Stage 2: seasonal climate

확인:

```text
mean_temperature
summer_temperature
winter_temperature
vertical_motion_index
annual_rainfall_raw
summer_rainfall_raw
winter_rainfall_raw
dry_season_strength
rainfall_seasonality
annual_ET
annual_runoff
```

실패 귀속:

```text
위도별 기온이 틀림 → base temp / lapse / continentality
25도 부근이 너무 습함 → subtropical descent / vertical_motion
적도권이 너무 건조함 → ITCZ / recycling / moisture capacity
내륙 전체가 죽음 → ET recycling / spin-up / ocean source
계절성이 없음 → 2-season pass / ITCZ shift / dry_season_strength
```

### 6-4. Stage 3: hydrology

확인:

```text
flow_direction
discharge
is_river
is_lake
is_salt_flat
is_wetland
corrected_ET
river_bonus
lake_fraction
```

실패 귀속:

```text
해안 강이 즉시 끊김 → sea neighbor outlet rule
호수 seed가 바다로 빠짐 → lake_seed 선처리
분지가 전부 호수 → corrected_ET / lake_threshold / storage capacity
나일강형 외래하천이 사라짐 → flow accumulation / river_seed / upstream pass-through
exclude_from_sim에서 강이 끊김 → override hydrology contract 위반
```

### 6-5. Stage 4: rainfall normalization

확인:

```text
final_rainfall
rainfall_percentile
rainfall_absolute_scaled
rainfall_relative_scaled
final_summer_rainfall
final_winter_rainfall
```

실패 귀속:

```text
전체가 숲/사막으로 쏠림 → world_scale / relative_weight / final_max
final_summer + final_winter 불일치 → seasonal share 보존 버그
건조 세계에서 숲이 강제됨 → relative_weight 과다 또는 absolute 축 약함
```

### 6-6. Stage 5: Koppen / biome / terrain

확인:

```text
corrected_ET_scaled
river_bonus_scaled
aridity_index
soil_moisture
koppen_base_class
koppen_class
biome_climate_base
biome_physical
biome
vic3_terrain
hydrology_overlay
```

실패 귀속:

```text
사막/스텝 경계가 틀림 → Koppen B threshold
지중해/몬순이 구분 안 됨 → dry_season_strength / seasonal rainfall
강 주변 terrain이 과습함 → river_bonus_scaled clamp
호수 주변이 과습/과건조 → lake_fraction / corrected_ET_scaled
locked terrain이 안 먹힘 → override final label stage
fantasy_zone이 terrain까지 바꿈 → fantasy contract 위반
```

---

## 7. Metric 정의

### 7-0. metric 대상 province

기본 대상:

```text
province_graph.is_sea = false
AND province_overrides.exclude_from_sim != true
```

exclude_from_sim:

```text
exclude_from_sim=true province는 기본 metric에서 제외한다.
별도 excluded_province_count / excluded_region_report로 보고한다.
이유: 기후 계산 제외 노드이므로 자동 기후/terrain 결과를 정답 비교에 넣으면 metric을 오염시킨다.
```

주의:

```text
exclude_from_sim 제외 정책은 pre_registration에 기록한다.
```

### 7-1. zonal temperature RMSE

```text
위도 band 단위로 mean_temperature 평균 계산
reference/zonal_temperature.csv와 RMSE 비교
```

기본 band:

```text
5도 단위
```

예:

```text
zonal_temperature_rmse_max = 8.0
```

### 7-2. zonal rainfall RMSE

```text
위도 band 단위로 final_rainfall 평균 계산
reference/zonal_rainfall.csv와 RMSE 비교
```

주의:

```text
final_rainfall은 mm가 아니라 normalized index다.
reference/zonal_rainfall.csv는 이미 normalized index 단위여야 한다.
raw mm 단위 reference를 golden runner가 즉석 변환하지 않는다.
reference 변환은 별도 data preparation script 책임이다.
```

### 7-3. Koppen major group accuracy

major group:

```text
A, B, C, D, E, H
```

계산:

```text
accuracy = matched_major_group / compared_land_provinces
```

주의:

```text
세부 class(Aw/Am/Af 등)보다 major group을 먼저 본다.
v0.1에서 세부 class accuracy는 참고 metric이다.
```

### 7-4. dry zone precision / recall

dry zone:

```text
koppen_class startswith B
또는 biome in hot_desert/cold_desert/hot_steppe/cold_steppe
```

metric:

```text
precision = predicted_dry ∩ reference_dry / predicted_dry
recall = predicted_dry ∩ reference_dry / reference_dry
```

### 7-5. tropical wet recall

tropical wet:

```text
koppen_class in Af/Am
또는 biome in rainforest/monsoon_forest
```

metric:

```text
recall = predicted_tropical_wet ∩ reference_tropical_wet / reference_tropical_wet
```

### 7-6. hydrology sanity metrics

```text
river_count
top_percent_discharge_river_ratio
endorheic_basin_count
lake_count
salt_flat_count
wetland_count
sea_discharge_total
```

v0.1에서는 hard pass/fail보다 warning threshold 중심으로 사용한다.

---

## 8. 사전 합격선 기본값

기본값:

```yaml
earth_golden:
  zonal_temperature_rmse_max: 8.0
  zonal_rainfall_rmse_max: 0.35
  koppen_major_group_accuracy_min: 0.45
  dry_zone_precision_min: 0.55
  dry_zone_recall_min: 0.40
  tropical_wet_recall_min: 0.50

pangaea_emergence:
  require_equatorial_wet_band: true
  require_subtropical_dry_band: true
  require_interior_dry_gradient: true
  require_east_west_asymmetry_report: true
  require_debug_maps: true
```

pangaea sanity 판정:

```text
equatorial_wet_band:
  abs_lat <= 10° land 평균 final_rainfall >
  전체 land 평균 final_rainfall

subtropical_dry_band:
  20° <= abs_lat <= 35° land 평균 final_rainfall <
  abs_lat <= 10° land 평균 final_rainfall

interior_dry_gradient:
  coast_distance_normalized 상위 30% land 평균 final_rainfall <
  coast_distance_normalized 하위 30% land 평균 final_rainfall

east_west_asymmetry_report:
  같은 위도 band 안에서 대륙 서안/동안 final_rainfall 평균 차이를 보고서에 기록한다.
  v0.1에서는 hard fail보다 diagnostic metric으로 사용한다.
```

주의:

```text
pangaea test는 정답 지도 비교가 아니다.
위 조건은 창발 패턴의 방향성 sanity check다.
```

주의:

```text
수치는 v0.1 초기 기준이다.
결과를 본 뒤 같은 test_id에서 바꾸지 않는다.
기준을 바꾸면 새 test_id로 다시 등록한다.
```

---

## 9. Hold-out 정책

지구 테스트에서 과적합 방지를 위해 region split을 사용한다.

예:

```yaml
tuning_regions:
  - Africa
  - Europe
  - South America
holdout_regions:
  - Asia
  - Oceania
  - North America
```

규칙:

```text
tuning_regions 결과를 보고 climate_rules를 조정할 수 있다.
holdout_regions 결과를 보고 같은 test_id에서 추가 튜닝 금지.
holdout 실패를 고치려면 새 test_id와 새 pre_registration을 만든다.
```

주의:

```text
지구 전체에 상수 15개를 맞추는 방식은 금지.
지구 golden 통과 + pangaea emergence 통과를 동시에 봐야 한다.
```

---

## 10. 예상 실패 목록

다음 실패는 v0.1 모델 한계로 사전 등록 가능하다.

```text
sahel_too_dry_bias:
  dry-start canonical initialization 때문에 반건조 경계가 현실보다 건조할 수 있음.

wadi_absent:
  계절 평균 수문 모델이라 사막 일시하천/돌발홍수 표현 불가.

ice_sheet_dynamics_absent:
  빙상 동역학 없음. snowline/ice cap은 약식.

coastal_current_missing_or_manual:
  해류 자동 경로가 없거나 수동 보정이면 서안/동안 비대칭이 약할 수 있음.

substrate_absent:
  암질/토양 레이어가 없어 화산토/카르스트/뢰스 기반 비옥도 차이 표현 불가.

fire_regime_absent:
  사바나/지중해 관목림의 fire-maintained biome 구분 약함.
```

규칙:

```text
예상 실패로 등록된 항목은 golden fail 원인 분석에서 known limitation으로 분류할 수 있다.
단, 예상 실패가 아닌 metric까지 같이 망가지면 튜닝/버그 대상으로 본다.
```

---

## 11. 실패 귀속 프로토콜

실패 발생 시 순서:

```text
1. 어떤 metric이 실패했는지 기록
2. 해당 metric이 참조하는 stage output 확인
3. upstream debug map부터 역순이 아닌 순방향으로 확인
4. 최초로 어긋난 stage를 primary_fault_layer로 기록
5. threshold 튜닝 전 bug / contract violation / model limitation 구분
6. golden_test_report.json에 귀속 결과 저장
```

예:

```text
증상: 사하라가 너무 습함
확인 순서:
  latitude / sea / coastal_ratio
  vertical_motion_index 25N
  annual_rainfall_raw
  final_rainfall
  aridity_index
  Koppen B threshold

판정:
  vertical_motion_index에서 하강이 약하면 seasonal_climate 문제.
  raw는 건조한데 final_rainfall이 습하면 rainfall_normalization 문제.
  aridity까지 건조한데 Koppen이 B가 아니면 koppen_biome_terrain 문제.
```

---

## 12. Golden run debug artifact

golden run은 다음 artifact를 반드시 보존한다.

필수:

```text
cache/pipeline_runs/{run_id}.json
cache/pipeline_run_manifest.json
validation/golden_runs/{test_id}/pre_registration.yaml
validation/golden_runs/{test_id}/golden_test_report.json
```

stage debug:

```text
cache/debug/*
outputs/debug/*
```

필수 map:

```text
outputs/debug/resolved_sea_set_map.png
outputs/debug/continentality_map.png
outputs/debug/synthetic_flow_potential_map.png
outputs/debug/vertical_motion_index_map.png
outputs/debug/annual_rainfall_raw_map.png
outputs/debug/final_rainfall_map.png
outputs/debug/discharge_map.png
outputs/debug/corrected_ET_scaled_map.png
outputs/debug/river_bonus_scaled_map.png
outputs/debug/aridity_index_map.png
outputs/debug/soil_moisture_map.png
outputs/debug/koppen_class_map.png
outputs/debug/biome_map.png
outputs/debug/terrain_map.png
```

규칙:

```text
debug map은 실패 후 재실행해서 만들지 않는다.
golden test가 검증하는 pipeline_run_id에 포함된 debug artifact만 사용한다.
report 작성 중 누락된 debug map을 새로 만들기 위해 stage를 재실행하지 않는다.
golden run 당시 산출물을 그대로 보존한다.
```

---

## 13. golden_test_report.json

출력:

```text
validation/golden_runs/{test_id}/golden_test_report.json
```

예시:

```json
{
  "schema_version": "validation_golden_tests.v0.1",
  "test_id": "earth_golden_v0_1",
  "pipeline_run_id": "2026-06-17T21-20-00Z_abcd1234",
  "status": "failed",
  "pre_registration_hash": "sha256:...",
  "input_hashes": {
    "pipeline_run_manifest": "sha256:...",
    "input_revision": "sha256:...",
    "reference_bundle_hash": "sha256:..."
  },
  "reference_hashes": {
    "zonal_temperature": "sha256:...",
    "zonal_rainfall": "sha256:...",
    "koppen_reference_by_province": "sha256:...",
    "region_tags_by_province": "sha256:..."
  },
  "evaluated_outputs": {
    "seasonal_climate": {
      "path": "cache/seasonal_climate.json",
      "hash": "sha256:..."
    },
    "hydrology": {
      "path": "cache/hydrology.json",
      "hash": "sha256:..."
    },
    "rainfall_normalized": {
      "path": "cache/rainfall_normalized.json",
      "hash": "sha256:..."
    },
    "koppen_biome_terrain": {
      "path": "cache/koppen_biome_terrain.json",
      "hash": "sha256:..."
    }
  },
  "metric_target_policy": {
    "include_sea": false,
    "include_exclude_from_sim": false,
    "excluded_province_count": 12
  },
  "metrics": {
    "zonal_temperature_rmse": 6.2,
    "zonal_rainfall_rmse": 0.41,
    "koppen_major_group_accuracy": 0.48,
    "dry_zone_precision": 0.58,
    "dry_zone_recall": 0.36,
    "tropical_wet_recall": 0.52
  },
  "metrics_by_split": {
    "tuning": {
      "koppen_major_group_accuracy": 0.51
    },
    "holdout": {
      "koppen_major_group_accuracy": 0.42
    }
  },
  "failed_metrics": [
    "zonal_rainfall_rmse",
    "dry_zone_recall"
  ],
  "primary_fault_layer": "seasonal_climate",
  "known_limitations_triggered": [
    "sahel_too_dry_bias"
  ],
  "debug_artifacts": [
    "outputs/debug/vertical_motion_index_map.png",
    "outputs/debug/final_rainfall_map.png"
  ]
}
```

status:

```text
passed
failed
invalid_test_setup
known_limitation_only
```

`known_limitation_only` 조건:

```text
실패한 metric이 모두 pre_registration.known_expected_failures에 귀속되고,
FATAL / contract violation / bug로 분류된 실패가 없을 때만 사용한다.
```

exit code:

```text
passed → 0
failed → nonzero
invalid_test_setup → nonzero
known_limitation_only → 기본 nonzero
known_limitation_only + --allow-known-limitations → 0
```

---

## 14. CLI 계약

기본:

```bash
python run_golden_tests.py \
  --test-id earth_golden_v0_1 \
  --pipeline-run cache/pipeline_runs/{run_id}.json \
  --pre-registration validation/golden_runs/earth_golden_v0_1/pre_registration.yaml \
  --reference-dir validation/reference/ \
  --output-dir validation/golden_runs/earth_golden_v0_1/
```

선택:

```bash
--create-pre-registration
--validate-reference-only
--run-pipeline
--fail-fast
--allow-known-limitations
--no-tune
```

`--create-pre-registration`:

```text
기준값과 합격선을 생성하되 golden metric 계산은 하지 않는다.
이미 pre_registration이 있으면 덮어쓰기 금지.
```

`--no-tune`:

```text
golden test 실행 중 climate_rules.yaml 수정 금지.
테스트 runner는 입력 파일 hash만 기록하고 수정하지 않는다.
```

`--run-pipeline`:

```text
golden test runner가 pipeline_orchestration을 먼저 실행하도록 허용한다.
새 pipeline_run_id가 생성되며 golden_test_report는 그 새 run_id에 연결된다.
이 옵션이 없으면 기존 --pipeline-run만 검증한다.

--run-pipeline 사용 시:
  golden runner는 pre_registration.pipeline_input_manifest를 읽어
  pipeline_orchestration을 실행한다.
  golden runner가 직접 map_data / constraints / climate_rules / terrain_lookup
  경로를 재해석하지 않는다.
```

---

## 15. 금지 사항

```text
[금지 1] 결과 확인 후 같은 test_id의 합격선 수정

[금지 2] zonal metric 실패를 무시하고 지역 사례만 보고 pass 처리

[금지 3] 지구 golden에 과적합한 뒤 pangaea test 생략

[금지 4] debug map을 실패 후 재실행으로 생성

[금지 5] reference dataset 출처/해상도 미기록

[금지 6] pipeline 출력 대신 중간 원본 파일을 직접 읽어 metric 계산
  예: v0.7 검증에서 annual_rainfall_raw를 직접 biome 판정처럼 사용

[금지 7] known limitation으로 등록되지 않은 실패를 임의로 예외 처리

[금지 8] holdout region 결과를 보고 같은 test_id에서 튜닝

[금지 9] --run-pipeline 없이 golden runner가 pipeline을 재실행

[금지 10] raw mm reference rainfall을 golden runner가 즉석 normalized index로 변환
```

---

## 16. 완료 기준

```text
1. pre_registration.yaml 형식이 정의되어 있다.
2. earth golden test와 pangaea emergence test가 분리되어 있다.
3. zonal → regional → final terrain 순서가 명시되어 있다.
4. metric 기본값이 사전 등록 가능하다.
5. known expected failure 목록이 있다.
6. failure attribution 절차가 있다.
7. debug artifact 필수 보존 목록이 있다.
8. golden_test_report.json 형식이 정의되어 있다.
9. 결과 확인 후 합격선 수정이 금지되어 있다.
10. holdout 정책이 정의되어 있다.
```

---

## 17. 이후 이관 항목

```text
실제 기준 데이터 다운로드/전처리 스크립트
province reference mapping builder
interactive debug dashboard
Vic3 terrain visual QA
monthly/seasonal extended climate validation
future substrate / fire regime validation
```
