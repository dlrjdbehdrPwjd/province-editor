# [ARCHIVED] seasonal_climate_spec v0.4

> **Superseded:** 구현 기준은 `seasonal_climate_spec_v0.4.1.md`이다.
> 이 문서는 이력 보존용이며 신규 구현 기준으로 사용하지 않는다.

> v0.3 mountain_barrier까지 확정된 커널을 계절별로 재실행하여
> summer/winter 기후 필드와 연간 합산값을 생성하는 단계.
> 이 단계 출력은 모두 정규화 전 raw seasonal값이며 v0.5~v0.7의 입력이 됨.

---

## 0. 이 문서의 범위

```
포함:
  v0.2.5+v0.3 커널 season별 재실행 구조
  vertical_motion_index (ITCZ + 아열대 통합)
  아열대 고압대 gaussian drain
  ITCZ gaussian 강수 보정 (v0.2.5 hard band 교체)
  2-season pass (summer / winter)
  continentality 계절 기온 진폭
  foehn 기온 보정 (선택 구현, 이 단계)
  ET / PET 계산 (lake_fraction 없이)
  ET 기반 수분 재순환 (annual 단위 주입)
  재순환 댐핑
  annual spin-up 루프
  soil_water_storage 이월

포함하지 않음:
  lake_fraction / open_water_evap → hydrology_spec_v0.5
  강/호수/습지 생성               → hydrology_spec_v0.5
  rainfall 정규화                 → rainfall_normalization_spec_v0.6
  biome 판정                      → koppen_biome_terrain_spec_v0.7
```

---

## 1. 핵심 구조 결정

**책임 경계: v0.4 seasonal layer vs v0.2.5 moisture kernel**

```
v0.4 seasonal layer 소유:
  season_temperature 계산 (base_temp + lapse + temperature_delta + continentality + force_temp)
  capacity 계산 (계절 온도 기반)
  ITCZ gaussian 보정
  아열대 고압대 drain
  force_moisture / force_rainfall 최종 재고정 (최종 권한)
  ET / 물수지 / recycling

  force_rainfall 우선순위:
    v0.2.5 kernel 내부에서 force_rainfall을 1회 적용하더라도,
    ITCZ/drain 이후 seasonal layer가 최종값을 다시 덮어쓴다.
    seasonal layer의 force_rainfall 재고정이 항상 최종 권한을 가진다.

v0.2.5 moisture kernel 역할 (v0.4 호출 시):
  수분 전파만 담당
  v0.4에서 precomputed capacity를 입력으로 받아 사용
  temperature_delta를 내부에서 다시 계산하지 않음 (v0.4가 이미 온도에 반영)
  v0.2.5 hard ITCZ 보정 비활성화 (v0.4 ITCZ layer가 전담)
```

**v0.4는 province_moisture.json을 최종 입력으로 소비하지 않는다.**

```
이유:
  v0.2.5/v0.3 커널은 단일 계절 온도/capacity로 실행됨.
  여름/겨울은 온도가 다르므로 capacity가 달라지고 moisture 분포도 달라짐.
  → v0.4가 계절별로 v0.2.5+v0.3 커널을 재실행해야 올바른 계절 기후가 나옴.

  province_moisture.json:
    debug/비교용으로만 활용 가능.
    v0.4 입력으로 직접 소비 금지.
```

**용어:**
```
v0.4 출력 rainfall은 모두 "normalization 전 raw seasonal rainfall"임.
이하 annual_rainfall_raw / summer_rainfall_raw / winter_rainfall_raw로 표기.
(v0.6 normalization 후 final_rainfall과 구분)
```

---

## 2. 입력

### 2-1. v0.4 직접 사용

| 파일 | 사용 데이터 |
|------|------------|
| `cache/bootstrap_fields.json` | synthetic_elevation_m, continentality, coast_distance_normalized |
| `cache/province_graph.json` | latitude, coastal_ratio, is_sea, area_px |
| `province_constraints.yaml` | temperature_delta |
| `province_overrides.yaml` | climate_lock, force_temp, force_moisture, force_rainfall, exclude_from_sim |
| `climate_rules.yaml` | seasonal_climate 섹션 파라미터 |

### 2-2. v0.2.5+v0.3 커널 실행 시 전달

| 파일 | 사용 데이터 |
|------|------------|
| `province_constraints.yaml` | moisture_bonus, wetland_seed, mountain_strength |
| `province_overrides.yaml` | climate_lock, force_moisture, force_rainfall, exclude_from_sim |
| `cache/province_graph.json` | adjacency, border_weight, coastal_ratio |

---

## 3. 출력

```
모든 rainfall 값은 normalization 전 raw seasonal rainfall.
v0.6 normalization 없이 biome 판정에 사용 금지.

출력 필드:
  annual_rainfall_raw
  summer_rainfall_raw
  winter_rainfall_raw
  wet_season_rainfall_raw   (max of summer/winter)
  dry_season_rainfall_raw   (min of summer/winter)
  dry_season_strength       (0.0~1.0)
  rainfall_seasonality
  mean_temperature
  summer_temperature
  winter_temperature
  annual_ET
  annual_runoff
  soil_water_storage_final  (spin-up 마지막 winter pass 완료 후 상태)

출력 파일: cache/seasonal_climate.json
downstream:
  hydrology_spec_v0.5: annual_rainfall_raw, soil_water_storage_final, annual_runoff
  rainfall_normalization_spec_v0.6: *_rainfall_raw 전체
  koppen_biome_terrain_spec_v0.7: 모든 출력값
```

---

## 4. vertical_motion_index

ITCZ(상승기류)와 아열대 고압대(하강기류)를 하나의 인덱스로 통합.

```
vertical_motion_index < 0: 상승기류 → 강수 증가 (ITCZ)
vertical_motion_index > 0: 하강기류 → 건조화 (아열대 고압대)
```

### ITCZ 성분

```
itcz_strength = exp(-(abs_lat^2) / (2 × itcz_sigma^2))
  itcz_sigma = 5.0
itcz_component = -itcz_strength × itcz_scale
```

### 아열대 고압대 성분

```
subtropical_strength = exp(-((abs_lat - subtropical_center)^2) /
                           (2 × subtropical_width^2))
  subtropical_center = 25.0
  subtropical_width  = 10.0
subtropical_component = +subtropical_strength × subtropical_scale
```

### 최종 VMI

```
vertical_motion_index[color] = itcz_component + subtropical_component

예시:
  위도  0°: VMI ≈ -1.00  (강한 ITCZ)
  위도 25°: VMI ≈ +1.00  (강한 아열대 고압대)
  위도 50°: VMI ≈  0.00  (중립)
```

---

## 5. 계절 온도 계산

### 5-1. base temperature

```
base_temp = equator_temp + (pole_temp - equator_temp) × (abs_lat / 90)
  equator_temp = 28.0, pole_temp = -20.0

base_temp -= lapse_rate × (synthetic_elevation_m / 1000.0)
  lapse_rate = 6.5

base_temp += temperature_delta  (province_constraints.yaml)
```

### 5-2. continentality 계절 진폭 적용

```
continentality = bootstrap_fields[color]['continentality']
latitude_factor = clamp(sin(abs_lat × π / 180), 0.0, 1.0)
seasonal_amplitude = base_seasonal_amplitude × latitude_factor × continentality

local_summer_temperature = base_temp + seasonal_amplitude
local_winter_temperature = base_temp - seasonal_amplitude

계절 정의:
  local summer = 해당 반구의 여름
  북반구: local_summer ≈ 7월 기준
  남반구: local_summer ≈ 1월 기준
  → 양 반구 모두 local_summer_temperature >= local_winter_temperature

이 문서에서 "summer" = local summer, "winter" = local winter.
```

### 5-3. force_temp 적용 (seasonal 재고정)

```
# seasonal amplitude 적용 후, capacity 계산 전
if climate_lock[color] and force_temp[color] is not None:
  local_summer_temperature[color] = force_temp[color]
  local_winter_temperature[color] = force_temp[color]
  # mean_temperature도 force_temp가 됨

이유:
  force_temp는 "연중 온도 강제" 의미.
  양 계절 모두 같은 값으로 재고정.
  capacity 계산 전에 적용해야 force_temp가 capacity에 반영됨.
```

### 5-4. foehn 기온 보정 (선택 구현)

```
v0.3에서 blocked_dissipated가 계산됨.
v0.4에서 leeward province 온도를 올림:

  foehn_warming = blocked × foehn_warming_factor
  leeward_province_temperature += foehn_warming

leeward province 판정:
  B가 산맥(mtn_B >= foehn_mtn_threshold)이면
  B의 이웃 중 바람이 내려가는 방향의 province = leeward
  상세 알고리즘은 구현 시 확정 (현재 구현 보류)

v0.4 완료 기준에서 제외 (선택 구현).
foehn 미구현 시 leeward 온도 보정 없이 진행.
영향: leeward 건조지 온도가 약간 낮게 나올 수 있음 (known bias).
leeward 탐지 알고리즘은 구현 시 확정 — 현재 미정.
```

---

## 6. 아열대 고압대 drain

moisture relaxation 완료 후, ITCZ 보정과 같은 단계에서:

```
if vertical_motion_index[color] > 0:
  drain_factor = vertical_motion_index[color] × drain_strength
  moisture[color] = max(0.0, moisture[color] × (1.0 - drain_factor))
  rainfall[color] = max(0.0, rainfall[color] × (1.0 - suppression_factor × drain_factor))

# drain 후 force 재고정은 단계 7에서 ITCZ/drain 통합 후 한 번에 처리.

순서 요약:
  moisture kernel → ITCZ gaussian → subtropical drain
  → force_moisture / force_rainfall 최종 재고정 (단 1회, 중앙화)
  → ET 계산

이유:
  ITCZ/drain 각각 후에 재고정하면 중복 코드 발생.
  모든 moisture 수정 완료 후 한 번에 재고정하는 게 명확.
  force_rainfall은 seasonal rainfall_raw를 최종 덮어씀.
```

---

## 7. ITCZ gaussian 강수 보정

v0.2.5 hard band를 gaussian으로 교체:

```
# v0.2.5 (폐기): hard band 0~10°
# v0.4: gaussian

itcz_weight = exp(-(abs_lat^2) / (2 × itcz_sigma^2))

if vertical_motion_index[color] < 0:   # ITCZ 구역만 적용
  condensation = moisture[color] × itcz_conversion_rate × itcz_weight
  rainfall[color] += condensation
  moisture[color] = max(0.0, moisture[color] - condensation)

# ITCZ 후 재고정은 아래 6번 drain과 함께 단계 7에서 통합 처리
```

---

## 8. ET 계산 (lake_fraction 없이)

### 8-1. PET

```
PET[color] = max(0.0, season_temperature + 5.0) × pet_coefficient
  season_temperature: 해당 계절 온도
```

### 8-2. ET (2성분. open_water_evap은 v0.5 이후)

```
available_water = rainfall_season[color] + soil_water_storage[color]
  soil_water_storage 단위 = rainfall과 동일 raw 단위

vegetation_proxy = clamp(moisture[color] / max(capacity[color], epsilon), 0.0, 1.0)
  # capacity가 0이면 ZeroDivision 방지 (max로 epsilon 보호)

bare_soil_evap = PET × bare_soil_coeff × (1 - vegetation_proxy)
transpiration   = PET × transpiration_coeff × vegetation_proxy

# open_water_evap: v0.5 hydrology 이후 lake_fraction 확정 후 추가
# v0.4에서는 lake_fraction=0.0 고정, open_water_evap 비활성화

ET[color] = min(available_water, bare_soil_evap + transpiration)
```

---

## 9. 물수지

```
storage_input = rainfall_season[color] + soil_water_storage[color]
runoff[color] = max(0.0, storage_input - ET[color] - storage_capacity)
soil_water_storage_next[color] = clamp(
  storage_input - ET[color] - runoff[color],
  0.0,
  storage_capacity
)

단위:
  storage_capacity = 100.0 (rainfall_raw와 동일 raw 단위)
```

---

## 10. ET 기반 수분 재순환

### 10-1. recycling_source 계산

```
raw_recycling = ET[color] × recycling_fraction
capped = min(raw_recycling, ET[color] × max_recycling_share)
recycling_source[color] = lerp(prev_recycling_source[color], capped, relaxation_alpha)
```

### 10-2. 재순환 주입 시점

```
recycling_source는 다음 annual_spinup year의 seasonal pass 시작 시 moisture source에 추가한다.
moisture relaxation 내부 iteration에는 직접 주입하지 않는다.

이유:
  iteration 내 직접 주입은 안정성 조건을 강하게 요구함.
  annual 단위 주입이 댐핑 효과와 자연스럽게 결합됨.
```

### 10-3. 폭주 방지

```
양성 피드백 경로:
  비 증가 → vegetation_proxy 증가 → transpiration 증가
  → ET 증가 → recycling 증가 → 비 증가

댐핑: lerp(prev, capped, alpha)로 급격한 변화 방지
상한: capped ≤ ET × max_recycling_share
```

---

## 11. 2-season pass 구조

```
for season in [SUMMER, WINTER]:

  # 1. 계절별 온도 설정
  season_temperature[color] = (local_summer_temperature if SUMMER
                               else local_winter_temperature)

  # 2. moisture_capacity 재계산 (계절 온도 기반)
  capacity[color] = clamp(
    base_capacity × exp(k × (season_temperature - T_ref)),
    capacity_min, capacity_max
  )

  # 2a. force_moisture 범위 검증 (season capacity 기준, 계절마다 재검증)
  if climate_lock[color] and force_moisture[color] is not None:
    if force_moisture[color] < 0:
      → ERROR: "force_moisture 음수 ({color})"
    if force_moisture[color] > capacity[color]:
      → ERROR: "force_moisture > season capacity ({color}: {force_moisture} > {capacity})"
  # 검증 실패 시 해당 season pass 중단

  # 3. moisture source 초기화 (recycling_source 포함)
  initialize_moisture_sources(season_temperature, capacity, recycling_source)
  # recycling_source는 annual spin-up year 시작 시 전달된 값만 사용.
  # non-sea province moisture_init에 더함.
  # moisture relaxation iteration 내부에서는 갱신하지 않음.

  # 4. moisture relaxation (v0.2.5 + v0.3 barrier)
  # 주의: v0.2.5 ITCZ hard band는 이 호출에서 비활성화됨.
  #       ITCZ/drain은 v0.4 seasonal layer가 아래 5~6번에서 전담.
  run_moisture_kernel_for_season(
    season,
    season_temperature,
    capacity,           # v0.4가 precomputed한 계절 capacity
    recycling_source,   # annual year 시작 시 전달
    constraints,
    overrides,
    disable_itcz=True   # v0.2.5 ITCZ hard band 비활성화 플래그
  )
  # returns:
  #   moisture[color]       (전파 완료)
  #   rainfall_season[color] (transit loss + overflow 포함)
  #   debug fields (barrier_strength, orographic_rain 등)

  # 5. ITCZ gaussian 보정
  apply_itcz_gaussian()

  # 6. 아열대 drain
  apply_subtropical_drain()

  # 7. force_moisture / force_rainfall 최종 재고정 (중앙화)
  #    moisture kernel + ITCZ + drain 모두 완료 후 한 번만 수행
  for each climate_lock province:
    if force_moisture: moisture[color] = force_moisture[color]
    if force_rainfall: rainfall_season[color] = force_rainfall[color]

  # 8. ET 계산
  compute_ET(season_temperature, soil_water_storage)

  # 9. 물수지
  compute_water_balance()

  # 10. 계절 결과 저장
  summer/winter_rainfall_raw[color] = rainfall[color]
  summer/winter_temperature[color]  = season_temperature[color]
```

---

## 12. annual spin-up 루프

### 12-1. 정규 초기 상태

```
매 spin-up 시작 전 동일한 초기 상태에서 출발:
  recycling_source = 0 (land recycling OFF)
  vegetation_proxy = 0.0 (최솟값)
  soil_water_storage = 0.0 (dry baseline)
  ocean/coastal/wetland source만 사용

이유: 동일 입력에서 재현 가능한 결과 보장.
known bias: 반건조 경계 지역이 현실보다 건조하게 수렴할 수 있음.
```

### 12-2. 루프

```
for year in range(1, max_spinup_years + 1):
  start_storage = copy(soil_water_storage)

  # 여름 계절 pass
  run_season(SUMMER, recycling_source=recycling_source)
  soil_water_storage = soil_water_storage_next  # 이월

  # 겨울 계절 pass
  run_season(WINTER, recycling_source=recycling_source)
  soil_water_storage = soil_water_storage_next  # 이월

  # 다음 year 재순환 source 갱신 (annual_ET 기준)
  annual_ET_year = summer_ET + winter_ET   # 해당 spin-up year 합산
  recycling_source = compute_recycling(annual_ET_year, recycling_source)
  # ET는 summer + winter 합산 annual 기준. 계절별 분리 아님.

  # 수렴 확인
  annual_residual = max(|soil_water_storage - start_storage|)
  if annual_residual < annual_epsilon:
    break
```

### 12-3. 실맵 진단용 기간 연장

정규 실행의 기본값은 `max_spinup_years: 20`으로 유지한다.
다만 전체 실맵에서 발산이 아니라 저온 지역의 느린 토양수분 축적으로 인해
20년 제한에 도달한 경우, 진단 실행에 한해 CLI로 기간을 연장할 수 있다.

```bash
python scripts/run_climate_pipeline.py \
  --max-spinup-years 1200 \
  --output cache/seasonal_climate.test.json \
  --debug
```

고정 규칙:

```text
--max-spinup-years는 진단용 override이다.
annual_epsilon은 변경하지 않는다.
override된 실제 기간은 params_hash와 output.spinup.max_years에 포함한다.
연장된 기간 안에서도 수렴하지 않으면 기존과 동일하게 FATAL 처리한다.
정규 캐시와 혼동하지 않도록 진단 출력은 *.test.json 사용을 권장한다.
```

파라미터 튜닝처럼 장기 soil storage 수렴이 필요 없는 진단에서는
`--allow-nonconverged`를 함께 사용할 수 있다. 이 옵션은 미수렴 상태를
`output.spinup.converged=false`로 명시하고 결과를 저장한다. 정규 출력과
golden test에서는 사용 금지이며, 해당 플래그도 params_hash에 포함한다.

장기 진단 실행 최적화:

```text
정규 실행에서는 recycling_source 변화가
moisture_transport.improvement_epsilon 미만이면
summer/winter 수분 전파 결과를 재사용할 수 있다.
단, ET / runoff / soil_water_storage는 매년 다시 계산한다.
누적 recycling_source 차이가 epsilon 이상이 되면 수분 커널을 다시 실행한다.
이 최적화는 수분 커널 자체의 수치 해상도 안에서만 허용한다.

기간 연장 진단에서는 장기 실행 비용을 제한하기 위해
reuse_epsilon = max(improvement_epsilon, annual_epsilon)을 사용한다.
이 값은 effective seasonal params와 params_hash에 포함한다.
따라서 진단 캐시는 정규 캐시와 동일한 것으로 취급하지 않는다.
```

---

## 13. 계절 결과 합산

```
annual_rainfall_raw[color] = summer_rainfall_raw[color] + winter_rainfall_raw[color]
wet_season_rainfall_raw    = max(summer_rainfall_raw, winter_rainfall_raw)
dry_season_rainfall_raw    = min(summer_rainfall_raw, winter_rainfall_raw)

dry_season_strength[color] = clamp(
  1.0 - dry_season_rainfall_raw / max(annual_rainfall_raw / 2, epsilon),
  0.0,
  1.0
)
# epsilon: ZeroDivision 및 음수 방지
# annual_rainfall_raw=0이면 dry_season_strength=1.0으로 수렴

rainfall_seasonality = abs(summer - winter) / (annual_rainfall_raw + epsilon)

mean_temperature = (summer_temperature + winter_temperature) / 2
annual_ET = summer_ET + winter_ET
annual_runoff = summer_runoff + winter_runoff
```

---

## 14. climate_rules.yaml 추가 섹션

```yaml
seasonal_climate:
  # vertical_motion_index
  itcz_sigma: 5.0
  itcz_scale: 1.0
  subtropical_center: 25.0
  subtropical_width: 10.0
  subtropical_scale: 1.0

  # subtropical drain
  drain_strength: 0.06
  suppression_factor: 0.20

  # ITCZ gaussian
  itcz_conversion_rate: 0.30

  # continentality
  base_seasonal_amplitude: 15.0

  # foehn (선택 구현)
  foehn_warming_factor: 0.5
  foehn_mtn_threshold: 0.3

  # ET (lake 없이)
  pet_coefficient: 0.1
  bare_soil_coeff: 0.3
  transpiration_coeff: 0.7
  storage_capacity: 100.0

  # recycling
  recycling_fraction: 0.3
  max_recycling_share: 0.5
  relaxation_alpha: 0.3

  # spin-up
  max_spinup_years: 20
  annual_epsilon: 0.01

  # 수치 안정성
  numeric_epsilon: 0.000001   # ZeroDivision 방지용 (capacity, annual_rainfall 분모)
```

---

## 15. 금지 사항

```
[금지 1] province_moisture.json을 v0.4 최종 입력으로 소비
  v0.4는 계절별 커널을 재실행해야 함.

[금지 2] continentality를 humidity 감쇠에 사용
  계절 기온 진폭 전용.

[금지 3] v0.2.5 hard band ITCZ 유지
  반드시 gaussian으로 교체.

[금지 4] *_rainfall_raw를 biome 판정에 직접 사용
  v0.6 normalization 필수.

[금지 5] recycling_source를 moisture relaxation iteration 내부에 직접 주입
  annual spin-up year 단위로만 주입.

[금지 6] lake_fraction을 v0.4에서 계산
  open_water_evap는 hydrology v0.5 이후.
  v0.4 ET: lake_fraction=0.0 고정.

[금지 7] ITCZ/drain 후 force_moisture / force_rainfall 재고정 생략
  moisture/rainfall을 수정한 뒤에는 반드시 둘 다 최종 재고정해야 한다.
  단계 7 중앙화 재고정에서 처리.
```

---

## 16. 검증 체크리스트

```
□ vertical_motion_index
  - 위도 0°: VMI < 0 (ITCZ)
  - 위도 25°: VMI > 0 (아열대)
  - 위도 50°: VMI ≈ 0

□ 계절 온도
  - summer_temperature >= winter_temperature (local summer 기준, 양반구)
  - force_temp이면 summer=winter=force_temp

□ ITCZ + subtropical drain 완료 후 force_moisture / force_rainfall 최종 재고정 확인
  (단계 7 중앙화 재고정. ITCZ/drain 각각 후 별도 재고정 불필요)

□ ET ≤ available_water (모든 province)

□ soil_water_storage: 0 ≤ value ≤ storage_capacity

□ recycling_source ≤ ET × max_recycling_share

□ annual spin-up 수렴 iterations 수 기록

□ 계절 합산
  - annual = summer + winter
  - dry_season_strength: 0.0~1.0
  - mean_temperature = (summer + winter) / 2

□ *_rainfall_raw 출력에 sea province 미포함
```
