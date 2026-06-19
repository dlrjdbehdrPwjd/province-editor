# rainfall_normalization_spec v0.6

> `seasonal_climate_spec_v0.4`의 raw rainfall을 biome 판정 가능한 `final_rainfall`로 변환하는 단계.
> raw rainfall은 시뮬레이션 내부 단위이며, 이 문서를 거치기 전에는 biome / terrain 판정에 사용 금지.

---

## 0. 이 문서의 범위

포함:

```text
annual_rainfall_raw 정규화
seasonal rainfall raw 정규화
절대값 + 백분위 혼합
dry/wet season normalized field 생성
rainfall percentile/debug field 생성
v0.7 aridity/soil_moisture용 준비값 출력
```

포함하지 않음:

```text
Köppen-lite 최종 기후 분류        → koppen_biome_terrain_spec_v0.7
biome / terrain 판정              → koppen_biome_terrain_spec_v0.7
final soil_moisture 계산          → koppen_biome_terrain_spec_v0.7
aridity_index 최종 판정           → koppen_biome_terrain_spec_v0.7
hydrology corrected_ET 재계산      → hydrology_spec_v0.5
force_rainfall 적용               → seasonal_climate_spec_v0.4에서 이미 완료
```

---

## 1. 핵심 설계 원칙

```text
raw rainfall은 중간 계산값이다.
biome / terrain 판정에 직접 사용 금지.

순수 백분위 normalization 금지.
절대값 일부를 보존해야 전체적으로 건조하거나 습한 세계를 표현할 수 있다.

순수 절대값 normalization도 금지.
raw 단위는 세계마다 스케일이 달라서 그대로 쓰면 대부분 사막 또는 습윤으로 쏠릴 수 있다.

따라서 v0.6은:
  final_rainfall = mix(absolute_scaled, percentile_scaled, relative_weight)
```

v0.6의 책임:

```text
rainfall을 비교 가능한 최종 강수 축으로 변환한다.
aridity_index와 soil_moisture를 확정하지 않는다.
```

v0.7의 책임:

```text
final_rainfall + corrected_ET + river_bonus + lake_fraction + temperature
→ aridity_index / soil_moisture / Köppen-lite / biome / terrain 판정
```

---

## 2. 입력

필수 입력:

| 파일 | 사용 데이터 |
|------|------------|
| `cache/seasonal_climate.json` | annual_rainfall_raw, summer_rainfall_raw, winter_rainfall_raw, wet_season_rainfall_raw, dry_season_rainfall_raw, dry_season_strength, rainfall_seasonality, mean_temperature, summer_temperature, winter_temperature, annual_ET |
| `cache/hydrology.json` | corrected_ET, river_bonus, lake_fraction |
| `cache/province_graph.json` | is_sea, latitude, area_px |
| `climate_rules.yaml` | rainfall_normalization 섹션 파라미터 |

입력 책임:

```text
hydrology.json은 v0.6 필수 입력이다.
corrected_ET / river_bonus / lake_fraction 누락 시 ERROR.

v0.6은 corrected_ET를 계산하지 않는다.
다만 v0.7 입력 번들을 완성하기 위해 hydrology 값을 pass-through 한다.
```

읽지 말아야 하는 파일:

```text
province_constraints.yaml
province_overrides.yaml
state_constraints.yaml
project_state.json
export_manifest.json
rivers.png
biome / terrain 결과물
```

이유:

```text
v0.6은 이미 완료된 v0.4/v0.5 결과를 정규화하는 단계다.
사용자 원인값이나 최종 라벨 override를 다시 해석하지 않는다.
```

---

## 3. 출력

필수 출력:

```text
cache/rainfall_normalized.json
```

출력 필드:

| 필드 | 형태 | 설명 |
|------|------|------|
| `final_rainfall` | dict[color → float] | biome/aridity 입력용 최종 연강수 |
| `final_summer_rainfall` | dict[color → float] | 정규화된 여름 강수 |
| `final_winter_rainfall` | dict[color → float] | 정규화된 겨울 강수 |
| `final_wet_season_rainfall` | dict[color → float] | 정규화된 우기 강수 |
| `final_dry_season_rainfall` | dict[color → float] | 정규화된 건기 강수 |
| `rainfall_percentile` | dict[color → float] | annual_rainfall_raw 백분위 0~1 |
| `rainfall_absolute_scaled` | dict[color → float] | world_scale 적용 절대 강수 |
| `rainfall_relative_scaled` | dict[color → float] | percentile 기반 상대 강수 |
| `dry_season_strength` | dict[color → float] | v0.4 값 전달 |
| `rainfall_seasonality` | dict[color → float] | v0.4 값 전달 |
| `corrected_ET` | dict[color → float] | v0.5 값 전달 |
| `river_bonus` | dict[color → float] | v0.5 값 전달 |
| `lake_fraction` | dict[color → float] | v0.5 값 전달 |

예시:

```json
{
  "schema_version": "rainfall_normalization.v0.6",
  "source": {
    "seasonal_climate": "cache/seasonal_climate.json",
    "hydrology": "cache/hydrology.json",
    "province_graph": "cache/province_graph.json"
  },
  "hash": {
    "seasonal_hash": "sha256:...",
    "hydrology_hash": "sha256:...",
    "graph_hash": "sha256:...",
    "params_hash": "sha256:..."
  },
  "provinces": {
    "xAABBCC": {
      "final_rainfall": 0.73,
      "final_summer_rainfall": 0.48,
      "final_winter_rainfall": 0.25,
      "final_wet_season_rainfall": 0.48,
      "final_dry_season_rainfall": 0.25,
      "rainfall_percentile": 0.82,
      "rainfall_absolute_scaled": 0.60,
      "rainfall_relative_scaled": 0.82,
      "dry_season_strength": 0.32,
      "rainfall_seasonality": 0.44,
      "corrected_ET": 0.51,
      "river_bonus": 0.08,
      "lake_fraction": 0.0
    }
  }
}
```

주의:

```text
corrected_ET / river_bonus / lake_fraction은 v0.7 전달용이다.
v0.6은 이 값들로 soil_moisture를 확정하지 않는다.
```

---

## 4. 처리 순서

```text
1. seasonal_climate.json 로드 및 schema 검증
2. hydrology.json 로드 및 schema 검증
3. province_graph.json 로드
4. land target 목록 구성
5. raw rainfall 음수/NaN 검증 및 clamp
6. annual_rainfall_raw 백분위 계산
7. absolute_scaled 계산
8. relative_scaled 계산
9. final_rainfall 계산
10. summer/winter/wet/dry seasonal rainfall 정규화
11. dry_season_strength / rainfall_seasonality 전달
12. corrected_ET / river_bonus / lake_fraction 전달
13. hash 및 metadata 생성
14. validation
15. rainfall_normalized.json 원자적 저장
16. debug output 저장
```

---

## 5. 핵심 알고리즘

### 5-1. 대상 province

대상:

```text
province_graph.provinces[color].is_sea = false
```

sea province:

```text
normalization 대상 제외
rainfall_normalized.provinces에 출력하지 않음
```

주의:

```text
province_graph.v0.2의 is_sea=false는 lake/inland water 후보를 포함할 수 있다.
v0.6은 lake 후보를 제외하지 않는다.
lake_fraction은 hydrology.json에서 전달받아 v0.7에서 소비한다.
```

---

### 5-2. raw rainfall 전처리

각 rainfall raw 필드에 대해:

```text
raw = max(0.0, raw)
NaN / Infinity → ERROR
```

대상 필드:

```text
annual_rainfall_raw
summer_rainfall_raw
winter_rainfall_raw
wet_season_rainfall_raw
dry_season_rainfall_raw
```

주의:

```text
force_rainfall은 v0.4에서 raw 단위로 이미 적용됨.
v0.6은 force_rainfall을 다시 적용하거나 재해석하지 않는다.
```

---

### 5-3. percentile 계산

백분위는 land target의 `annual_rainfall_raw` 기준으로 계산한다.

```text
rainfall_percentile[color] = rank(annual_rainfall_raw[color]) / (N - 1)
```

동률 처리:

```text
같은 raw rainfall 값은 평균 rank 사용.
같은 기후값을 가진 province는 같은 rainfall_percentile을 받는다.
color id tie-break는 사용하지 않는다.
```

N=1 처리:

```text
rainfall_percentile = 0.5
```

주의:

```text
sea province는 percentile 분포에 포함하지 않는다.
exclude_from_sim 여부는 v0.6에서 직접 읽지 않는다.
필요한 기후값 무효화는 v0.4/v0.5에서 이미 반영되어 있어야 한다.
```

---

### 5-4. absolute_scaled 계산

```text
rainfall_absolute_scaled = annual_rainfall_raw × world_scale
```

기본 파라미터:

```text
world_scale = 1.0
absolute_clamp_min = 0.0
absolute_clamp_max = 1.5
```

clamp:

```text
rainfall_absolute_scaled = clamp(
  annual_rainfall_raw × world_scale,
  absolute_clamp_min,
  absolute_clamp_max
)
```

의미:

```text
전체적으로 건조한 세계 / 습한 세계 표현을 보존하는 축.
```

---

### 5-5. relative_scaled 계산

```text
rainfall_relative_scaled = rainfall_percentile
```

선택 파라미터:

```text
relative_curve_gamma = 1.0
```

적용:

```text
rainfall_relative_scaled = pow(rainfall_percentile, relative_curve_gamma)
```

의미:

```text
지도 내부에서 상대적으로 습한 지역과 건조한 지역을 안정적으로 분리하는 축.
```

---

### 5-6. final_rainfall 계산

```text
final_rainfall = mix(
  rainfall_absolute_scaled,
  rainfall_relative_scaled,
  relative_weight
)
```

동일식:

```text
final_rainfall =
  rainfall_absolute_scaled × (1.0 - relative_weight)
  + rainfall_relative_scaled × relative_weight
```

권장값:

```text
relative_weight = 0.7
허용 범위: 0.0~1.0
권장 범위: 0.6~0.8
```

최종 clamp:

```text
final_rainfall = clamp(final_rainfall, final_min, final_max)
```

기본:

```text
final_min = 0.0
final_max = 1.5
```

단위:

```text
final_rainfall은 0~1 고정값이 아니다.
biome 판정용 상대 강수 지수이며 기본 범위는 0.0~1.5다.
```

이유:

```text
순수 percentile이면 전체적으로 건조한 세계에서도 상위 지역이 강제로 숲이 될 수 있다.
순수 absolute이면 raw scale 튜닝 실패 시 지도 대부분이 사막/우림으로 쏠릴 수 있다.
absolute_clamp_max는 absolute_scaled 축의 과도한 raw scale 폭주를 막는다.
final_max는 혼합 후 최종 biome 입력 범위를 제한한다.
두 값은 기본값이 같지만 튜닝 목적이 다르다.
```

---

### 5-7. seasonal rainfall normalization

계절별 final rainfall은 summer/winter raw 합 기준 비율로 분배한다.
`annual_rainfall_raw`는 percentile/absolute 기준값으로만 사용한다.

```text
season_total_raw = summer_rainfall_raw + winter_rainfall_raw

if season_total_raw > epsilon:
  season_share_summer = summer_rainfall_raw / season_total_raw
  season_share_winter = winter_rainfall_raw / season_total_raw
else:
  season_share_summer = 0.0
  season_share_winter = 0.0

final_summer_rainfall = final_rainfall × season_share_summer
final_winter_rainfall = final_rainfall × season_share_winter
```

보존 조건:

```text
final_summer_rainfall + final_winter_rainfall = final_rainfall
```

wet/dry:

```text
final_wet_season_rainfall = max(final_summer_rainfall, final_winter_rainfall)
final_dry_season_rainfall = min(final_summer_rainfall, final_winter_rainfall)
```

season_total_raw=0 처리:

```text
final_summer_rainfall = 0.0
final_winter_rainfall = 0.0
final_wet_season_rainfall = 0.0
final_dry_season_rainfall = 0.0
```

주의:

```text
dry_season_strength와 rainfall_seasonality는 v0.4 값을 전달한다.
v0.6에서 계절성 지표를 재계산하지 않는다.
```

---

## 6. aridity / soil_moisture와의 관계

v0.6은 aridity_index와 soil_moisture를 최종 계산하지 않는다.

v0.7 예정:

```text
PET_or_corrected_ET = hydrology.corrected_ET
aridity_index = final_rainfall / max(PET_or_corrected_ET, epsilon)

soil_moisture =
  final_rainfall
  + river_bonus
  + basin_bonus
  - corrected_ET
```

주의:

```text
위 공식은 v0.7에서 확정한다.
v0.6은 final_rainfall, corrected_ET, river_bonus, lake_fraction을 전달만 한다.
```

---

## 7. override / constraints 적용 시점

이 단계에서 읽지 않는 파일:

```text
province_constraints.yaml
province_overrides.yaml
state_constraints.yaml
```

force_rainfall:

```text
seasonal_climate_spec.v0.4에서 각 연도·각 계절 raw rainfall 최종값으로 이미 적용됨.
v0.6은 force_rainfall을 다시 적용하지 않는다.
```

locked / force_terrain / force_biome:

```text
v0.6에서 사용하지 않는다.
최종 biome/terrain 라벨 단계에서만 적용한다.
```

exclude_from_sim:

```text
v0.6에서 province_overrides.yaml을 읽지 않는다.
exclude_from_sim에 따른 raw 기후값 무효화는 v0.4/v0.5에서 반영되어 있어야 한다.
```

---

## 8. 캐시 / 해시

출력 metadata hash:

```text
seasonal_hash
hydrology_hash
graph_hash
params_hash
```

### seasonal_hash

입력:

```text
cache/seasonal_climate.json의 정규화 데이터
```

### hydrology_hash

입력:

```text
cache/hydrology.json의 corrected_ET / river_bonus / lake_fraction
```

주의:

```text
hydrology.json 전체를 hash에 포함할 수도 있지만,
v0.6이 소비하는 필드를 명시적으로 제한하는 것이 캐시 책임을 더 명확하게 한다.
```

### graph_hash

입력:

```text
province_graph.metadata.hash.topology_hash
```

용도:

```text
land target 구성에 province_graph.is_sea를 사용하므로,
graph topology 또는 sea 판정이 바뀌면 rainfall_normalized cache도 무효화된다.
```

### params_hash

입력:

```text
world_scale
relative_weight
relative_curve_gamma
absolute_clamp_min
absolute_clamp_max
final_min
final_max
numeric_epsilon
```

---

## 9. 검증 규칙

### ERROR

```text
seasonal_climate.json 없음
hydrology.json 없음
province_graph.json 없음
province_graph.metadata.hash.topology_hash 없음
필수 rainfall raw 필드 누락
corrected_ET / river_bonus / lake_fraction 누락
NaN / Infinity 값 존재
relative_weight가 0.0~1.0 범위 밖
relative_curve_gamma <= 0
final_min > final_max
land target이 0개
final_summer_rainfall + final_winter_rainfall이 final_rainfall과 epsilon 이상 차이
```

### WARNING

```text
annual_rainfall_raw가 모두 0
final_rainfall이 final_max에 많이 clamp됨
final_rainfall이 0인 province 비율이 매우 높음
rainfall_percentile 동률 다수
```

### INFO

```text
sea province는 normalization 대상 제외
dry_season_strength / rainfall_seasonality는 v0.4 값 전달
hydrology corrected_ET는 v0.7 입력으로 전달
soil_moisture는 v0.7에서 계산하며 v0.6에서는 미계산
```

---

## 10. debug output

권장 debug 출력:

```text
cache/debug/rainfall_normalization_report.json
cache/debug/rainfall_distribution.csv
cache/debug/rainfall_percentiles.csv
cache/debug/rainfall_clamped.csv
```

선택 debug 이미지:

```text
cache/debug/annual_rainfall_raw_preview.png
cache/debug/rainfall_percentile_preview.png
cache/debug/final_rainfall_preview.png
cache/debug/dry_season_strength_preview.png
cache/debug/rainfall_seasonality_preview.png
```

debug output은 `rainfall_normalized.json` schema 안에 넣지 않는다.

---

## 11. 구현 TODO

예상 구현 파일:

```text
파이프라인_프로젝트/scripts/rainfall_normalization.py
```

권장 함수 단위:

```python
load_seasonal_climate(path)
load_hydrology(path)
load_province_graph(path)
load_normalization_params(path)
build_land_targets(graph)
sanitize_raw_rainfall(seasonal, land_targets)
compute_percentile(values)
compute_absolute_scaled(raw, params)
compute_relative_scaled(percentile, params)
compute_final_rainfall(absolute_scaled, relative_scaled, params)
compute_seasonal_final_rainfall(final_rainfall, seasonal_raw, params)
build_v07_inputs(final_rainfall, hydrology, seasonal)
compute_hashes(inputs, params)
validate_rainfall_normalized(output)
atomic_write_json(output, path)
write_debug_outputs(output, diagnostics)
```

CLI 예시:

```bash
python scripts/rainfall_normalization.py \
  --seasonal cache/seasonal_climate.json \
  --hydrology cache/hydrology.json \
  --province-graph cache/province_graph.json \
  --params config/climate_rules.yaml \
  --output cache/rainfall_normalized.json
```

옵션:

```text
--pretty
--debug
--fail-on-warning
```

---

## 12. climate_rules.yaml 추가 섹션

```yaml
rainfall_normalization:
  world_scale: 1.0
  relative_weight: 0.7
  relative_curve_gamma: 1.0
  absolute_clamp_min: 0.0
  absolute_clamp_max: 1.5
  final_min: 0.0
  final_max: 1.5
  numeric_epsilon: 0.000001
```

---

## 13. 금지 사항

```text
[금지 1] raw rainfall을 biome / terrain 판정에 직접 사용
  반드시 v0.6 final_rainfall을 거친다.

[금지 2] 순수 percentile normalization만 사용
  전체적으로 건조한 세계 표현이 사라진다.

[금지 3] 순수 absolute normalization만 사용
  raw scale 튜닝 실패 시 전체 지도가 사막/우림으로 쏠린다.

[금지 4] force_rainfall 재적용
  v0.4에서 이미 raw rainfall에 적용됨.

[금지 5] corrected_ET / river_bonus / lake_fraction 무시
  v0.6은 soil_moisture를 계산하지 않지만 v0.7 입력으로 반드시 전달한다.

[금지 6] v0.6에서 soil_moisture 확정
  최종 soil_moisture는 v0.7 책임.

[금지 7] province_overrides.yaml 다시 읽기
  locked / climate_lock / exclude_from_sim을 이 단계에서 재해석하지 않는다.

[금지 8] dry_season_strength / rainfall_seasonality 재계산
  v0.4 seasonal 결과를 전달한다.
```

---

## 14. 완료 기준

```text
1. cache/rainfall_normalized.json을 생성한다.
2. final_rainfall이 절대값 + 백분위 혼합으로 계산된다.
3. relative_weight 기본값 0.7, 권장 범위 0.6~0.8이 명시된다.
4. raw rainfall 직접 biome 판정 금지가 명시된다.
5. final_summer/winter/wet/dry rainfall이 annual final_rainfall 비율 기준으로 생성된다.
6. final_summer_rainfall + final_winter_rainfall = final_rainfall을 보장한다.
7. corrected_ET / river_bonus / lake_fraction이 v0.7 입력으로 전달된다.
8. soil_moisture를 v0.6에서 확정하지 않는다.
9. force_rainfall을 재적용하지 않는다.
10. sea province는 normalization 대상에서 제외된다.
11. graph_hash를 기록해 is_sea 변경에 따른 cache 무효화를 보장한다.
12. debug report로 raw 분포, percentile, clamp 비율을 확인할 수 있다.
```
