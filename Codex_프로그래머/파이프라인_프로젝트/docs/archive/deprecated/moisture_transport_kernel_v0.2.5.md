# [ARCHIVED] moisture_transport_kernel v0.2.5

> **Superseded:** 구현 기준은 `moisture_transport_kernel_v0.2.6.md`이다.
> 이 문서는 이력 보존용이며 신규 구현 기준으로 사용하지 않는다.

> 수분 전파 커널 설계 문서.
> 바다/해안/습지에서 생성된 수분이 province graph를 따라 내륙으로 퍼지고
> 어디서 강수로 변환되는지를 정의한다.
> mountain_barrier(v0.3)는 이 커널의 transfer 단계에 삽입된다.
> ITCZ/vertical_motion/아열대 고압대 상세는 seasonal_climate_spec(v0.4)에서 확장된다.

---

## 0. 이 문서의 범위

```
포함:
  주풍 계산
  수분 source 초기화
  province adjacency 기반 수분 전파
  강수(rainfall) 변환
  override 적용 규칙
  debug 출력

포함하지 않음 (별도 문서):
  mountain_barrier    → mountain_barrier_pseudocode_v0.3.md
  ITCZ gaussian       → seasonal_climate_spec_v0.4.md
  아열대 고압대 drain → seasonal_climate_spec_v0.4.md
  해류 path 투영      → seasonal_climate_spec_v0.4.md
  rivers.png 생성     → hydrology_spec_v0.5.md
  rainfall 정규화     → rainfall_normalization_spec_v0.6.md
  biome 판정          → koppen_biome_terrain_spec_v0.7.md
```

---

## 1. 입력

| 파일 | 사용 데이터 |
|------|------------|
| `cache/province_graph.json` | provinces, adjacency, coastal_ratio, is_sea, latitude |
| `cache/bootstrap_fields.json` | synthetic_elevation_m, coast_distance_normalized, continentality |
| `province_constraints.yaml` | moisture_bonus, wetland_seed, temperature_delta |
| `province_overrides.yaml` | climate_lock, force_temp, force_moisture, force_rainfall, exclude_from_sim |
| `climate_rules.yaml` | moisture_transport 파라미터 (아래 섹션 10 참조) |

**heightmap 직접 사용 금지:**
```
province_graph.json의 elevation 필드는 authoritative=false이면 사용 금지.
온도 계산은 synthetic_elevation(bootstrap_fields.json) 사용.
```

---

## 2. 출력

| 출력 | 형태 | 설명 |
|------|------|------|
| `moisture_raw` | dict[color → float] | land province별 최종 수분값 (0.0~capacity). sea province 미포함. |
| `rainfall_raw` | dict[color → float] | non-sea province별 누적 강수 (raw 단위, 정규화 전). sea province 미포함. |
| `moisture_capacity` | dict[color → float] | province별 수분 용량 |
| `cache/province_moisture.json` | 캐시 | moisture_raw + rainfall_raw 캐시 파일 |

**debug 출력 (선택):**
```
outputs/debug/moisture_raw.png      moisture 분포 이미지
outputs/debug/rainfall_raw.png      rainfall 분포 이미지
outputs/debug/moisture_source.png   source province 표시
outputs/debug/wind_band.png         주풍 방향 시각화
```

**downstream 금지:**
```
rainfall_raw → biome 판정 직접 사용 금지
rainfall_normalization_spec_v0.6 거친 final_rainfall만 biome 판정에 사용
```

---

## 3. 온도 및 moisture_capacity 계산

### 3-1. 온도 (synthetic_elevation 기반)

```
base_temperature = 위도 기반 보간
  equator_temp = 28°C, pole_temp = -20°C
  base_temp = equator_temp + (pole_temp - equator_temp) × (abs_lat / 90)

온도 고도 보정:
  lapse_rate = 6.5°C / 1000m
  temperature = base_temp - lapse_rate × (synthetic_elevation_m / 1000.0)
  synthetic_elevation_m: bootstrap_fields.json에서 읽음
  heightmap elevation 직접 사용 금지

temperature_delta (province_constraints.yaml):
  temperature += temperature_delta

climate_lock.force_temp 적용 (capacity 계산 전):
  if climate_lock[color] and force_temp[color] is not None:
    temperature[color] = force_temp[color]
  이유: force_temp가 moisture_capacity에 실제 영향을 주려면
        capacity 계산 전에 온도를 재고정해야 함.
```

### 3-2. moisture_capacity (Clausius-Clapeyron 근사)

```
capacity = base_capacity × exp(k × (temperature - T_ref))
  base_capacity = 1.0
  k             = 0.07
  T_ref         = 15.0

clamp(capacity, capacity_min, capacity_max)
  capacity_min = 0.35
  capacity_max = 2.25
```

---

## 4. 주풍 계산

### 4-1. wind band 정의

```
위도대별 기본 풍향 (이미지 좌표계: x=동, y=남):

ITCZ (0~10°):
  raw_direction = [0.0, 1.0]  (수직 대류 우세, 실제 전파보다 ITCZ 보정으로 처리)
  directionality = 0.20

무역풍 (10~30°):
  raw_direction = [-1.0, 0.25]  (동→서 + 약한 적도 방향)
  directionality = 0.85

편서풍 (30~60°):
  raw_direction = [1.0, -0.15]  (서→동 + 약한 극 방향)
  directionality = 0.75

극편동풍 (60°+):
  raw_direction = [-1.0, 0.0]   (동→서)
  directionality = 0.65
```

### 4-2. 경계 보간 (hard cutoff 금지)

```
경계 ±4도에서 인접 band 벡터를 선형 보간.

예: 위도 28°
  무역풍 band: 10~30°
  편서풍 band: 30~60°
  transition zone: 26~34°
  t = (28 - 26) / (34 - 26) = 0.25
  wind_vector = lerp(무역풍 벡터, 편서풍 벡터, t)

경계 밖: 해당 band 벡터 그대로 사용
```

### 4-3. wind_vector 계산

```
raw_normalized = normalize(raw_direction)
wind_vector = raw_normalized × directionality
  → 방향은 단위벡터, 강도는 directionality
```

### 4-4. wind_weight 계산

```
A → B 방향 기준:
  dir_AB = normalize(center_B - center_A)
  dot_A = dot(wind_vector[A], dir_AB)
  dot_B = dot(wind_vector[B], dir_AB)
  wind_weight = max(leakage_min, min(dot_A, dot_B))

leakage_min = 0.05
  이유: 역풍 방향도 0.05 최소 전파 허용
        완전 차단 시 풍향 수직 방향 수분 이동이 불가능해 비현실적

효과:
  같은 wind band 내부 forward 방향: wind_weight ≈ 0.6~0.85
  30도 경계 cross: 한쪽 dot가 낮아져 자연스러운 수분 억제 발생
  역풍 방향: leakage_min = 0.05
```

---

## 5. 수분 source 초기화

```
sea province:
  moisture[color] = 1.0  (내부 source 기준값으로만 사용)
  priority queue에 넣지 않는다.
  최종 moisture_raw 출력에 sea province 값은 포함하지 않는다.
  이유: sea는 coastal province가 moisture_init을 계산할 때 인접 기준으로만 쓰임.

exclude_from_sim=true province:
  moisture=0, rainfall=0, queue 삽입 금지
  전파 루프: 발신(A) 차단 + 수신(B) 차단
  flow accumulation에는 참여 (지형 존재, hydrology_spec_v0.5)

모든 non-sea province (공통 초기화 공식):
  # 적용 순서
  base_init = 0.0
  if is_coastal[color]:
    base_init += coastal_ratio × coastal_source_factor
  if wetland_seed[color]:
    base_init += wetland_moisture_bonus
  if moisture_bonus[color] is not None:
    base_init += moisture_bonus[color]   # 음수 허용 (건조 효과)
  moisture_init = clamp(base_init, 0.0, capacity[color])

  # queue 삽입
  if moisture_init > 0 and not exclude_from_sim[color]:
    queue.push(color, priority=moisture_init)
    moisture[color] = moisture_init

lake_seed=true province:
  moisture source 아님. is_flow_sink=true는 hydrology_spec_v0.5에서 처리.
  이 단계에서는 non-sea land 공식 동일 적용.

warm/cold current:
  v0.2.5에서 current_type을 읽지 않는다.
  current 처리는 seasonal_climate_spec_v0.4에서 정의한다.
  온도 간접 보정 필요 시 temperature_delta만 사용.
```

---

## 6. 수분 전파 (delta priority queue)

### 6-0. 전파 시작 전 사전 검증

```
capacity 계산 완료 후, 전파 루프 시작 전 실행:

for each province with climate_lock=true:
  if force_moisture is not None:
    if force_moisture < 0:
      → ERROR: "force_moisture 음수 금지 ({color}: {value})"
    if force_moisture > capacity[color]:
      → ERROR: "force_moisture가 capacity 초과 ({color}: {force_moisture} > {capacity})"

검증 실패 시 루프를 시작하지 않는다.
이유: 루프 중간에 재고정하다가 터지면 부분 상태가 남아 디버깅이 어려움.
```

### 6-1. 전파 루프 구조

```
priority queue: max-heap (moisture 높은 province 우선)
초기 상태: 아래 source 공식으로 계산한 값으로 큐에 삽입

while queue not empty:
  A = queue.pop()

  if exclude_from_sim[A]:
    continue  # 발신도 차단

  delta_A = moisture[A] - propagated[A]   ← 새로 증가한 양만 전파

  if delta_A < improvement_epsilon:
    continue

  for each neighbor B of A:
    if exclude_from_sim[B]:
      continue  # 수신도 차단
    if B is sea:
      continue  # sea는 propagation 목적지 아님

    compute transfer(A → B)
    apply to moisture[B], rainfall[B]
    if moisture[B] increased:
      re-insert B into queue

  propagated[A] = moisture[A]
```

### 6-2. transfer 계산

```
# flow_weight
flow_weight = wind_weight × border_weight × distance_decay
  distance_decay = exp(-distance_px / distance_decay_scale)

# 이웃 분배 비율 정규화
flow_total = sum of flow_weight over all valid neighbors of A
if flow_total == 0: skip

# 전달량
transfer = delta_A × export_fraction × (flow_weight / flow_total)

border_weight 역할:
  절대 전달량 결정이 아닌 이웃 간 분배 비율
  이유: 과분할 맵(58829 province)에서 border_weight가 작아
        절대값에 직접 곱하면 내륙 전파 불가능
```

### 6-3. loss / overflow / absorption 처리

```
# transit 강수 손실
area_factor = sqrt(area_px / median_area_px)
loss = min(transfer, transfer × base_loss × area_factor)
net = max(0.0, transfer - loss)
rainfall[B] += loss

# capacity 처리
space = capacity[B] - moisture[B]
absorbed = max(0.0, min(net, space))
overflow = max(0.0, net - absorbed)

rainfall[B] += overflow × overflow_to_rainfall_factor
moisture[B] += absorbed
```

### 6-4. climate_lock.force_moisture 재고정 (Dirichlet)

```
각 province update 직후 적용:
  if province.climate_lock and province.force_moisture is not None:
    moisture[province] = province.force_moisture

이유: moisture는 매 iteration 이웃에서 갱신됨.
     재고정 없으면 루프가 덮어써서 force 효과 사라짐.
```

---

## 7. ITCZ 강수 보정 (현재 버전)

```
현재(v0.2.5): 위도대 기반 ITCZ 보정
  위도 0~10° 구역에서 moisture의 일부를 rainfall로 변환

itcz_weight = clamp((10 - abs_lat) / 10, 0.0, 1.0)
  (0도 = 1.0, 10도 = 0.0, 10도 이상 = 0.0)

condensation = moisture[color] × itcz_conversion_rate × itcz_weight
rainfall[color] += condensation
moisture[color] -= condensation

v0.4에서 교체 예정:
  gaussian(abs_lat, center=0, sigma=5) 방식으로 전환
  vertical_motion_index 통합
  아열대 고압대 drain 추가
  이 단계에서는 단순 위도 기반 보정만 적용
```

---

## 8. force_rainfall 적용 (전파 완료 후 1회)

```
전파 루프 완료 + ITCZ 보정 완료 후:
  for each province:
    if province.climate_lock and province.force_rainfall is not None:
      rainfall[province] = province.force_rainfall

적용 시점:
  전파 완료 후
  ET/runoff 계산 전
  rainfall normalization(v0.6) 전

이유: rainfall은 orographic rain/ITCZ 보정/transit loss 등이 누적된 결과.
     매 iteration 덮어쓰면 물리 강수가 삭제됨.
     단 1회 override.
```

---

## 9. override 처리 요약

| override | 적용 시점 | 동작 |
|----------|----------|------|
| `locked=true` | - | 물리 정상 참여. 라벨은 파이프라인 최종 단계에서 덮어씀. 이 단계 영향 없음. |
| `climate_lock.force_moisture` | 매 iteration | Dirichlet 재고정 |
| `climate_lock.force_rainfall` | 전파 완료 후 1회 | ET/normalization 전 적용 |
| `climate_lock.force_temp` | temperature_delta 적용 후, capacity 계산 전 | moisture_capacity에 반영 |
| `exclude_from_sim=true` | source 초기화 전 | moisture 수신/발신 0. rainfall 기여 0. |

---

## 10. climate_rules.yaml 파라미터 (moisture_transport 관련)

```yaml
moisture_transport:
  coastal_source_factor: 0.6
  wetland_moisture_bonus: 0.15
  leakage_min: 0.05
  export_fraction: 0.85
  base_loss: 0.02
  distance_decay_scale: 800.0
  overflow_to_rainfall_factor: 0.8
  improvement_epsilon: 0.00001
  base_capacity: 1.0
  k_clausius: 0.07
  T_ref: 15.0
  capacity_min: 0.35
  capacity_max: 2.25
  itcz_conversion_rate: 0.30
  # Replace with measured province_graph stats after graph build.
  median_area_px: 90
  numeric_epsilon: 0.000001

  wind_bands:
    transition_width_deg: 4.0
    bands:
      - name: itcz
        lat_min: 0
        lat_max: 10
        direction: [0.0, 1.0]
        directionality: 0.20
      - name: trade_winds
        lat_min: 10
        lat_max: 30
        direction: [-1.0, 0.25]
        directionality: 0.85
      - name: westerlies
        lat_min: 30
        lat_max: 60
        direction: [1.0, -0.15]
        directionality: 0.75
      - name: polar_easterlies
        lat_min: 60
        lat_max: 90
        direction: [-1.0, 0.0]
        directionality: 0.65
```

`wind_bands`는 `climate_rules.yaml`의 `moisture_transport.wind_bands`에서 읽는다.
별도 루트 섹션으로 분리하지 않는다.

**실맵 1차 튜닝 기록:**

```text
province graph의 측정 최대 해안거리는 35 hops이다.
export_fraction=0.3 / improvement_epsilon=0.0001 조합은 약 8 hops 이후
전파가 사실상 중단되어 land province 61.6%의 annual rainfall이 0이 되었다.

기본 입력(constraints 없음)에서도 내륙까지 background moisture가 도달하도록
1차로 export_fraction=0.8 / improvement_epsilon=0.00001을 검증한 뒤,
깊은 내륙의 0 강수 비율을 더 줄이기 위해 export_fraction=0.85로 확정한다.
이 값은 golden/reference 데이터 확정 전 1차 실맵 튜닝값이다.
```

---

## 11. 금지 사항

```
[금지 1] rainfall_raw → biome 판정 직접 사용
  반드시 rainfall_normalization_spec_v0.6 거친 final_rainfall 사용

[금지 2] continentality를 humidity 감쇠에 사용
  continentality = 계절 기온 진폭 전용
  수분 감쇠는 moisture 전파 자연 감소로만

[금지 3] mountain barrier를 이 커널에 완성
  mountain barrier는 v0.3 문서에서 transfer 단계에 삽입
  이 문서는 transfer 공식까지만 정의

[금지 4] heightmap 직접 사용
  elevation 기반 온도 보정은 synthetic_elevation 사용
  province_graph.json elevation 필드는 authoritative=false이면 사용 금지

[금지 5] border_weight를 절대 전달량에 직접 곱하기
  border_weight = 이웃 간 분배 비율
  절대 전달량은 export_fraction × delta × (flow_weight / flow_total)

[금지 6] sea province를 propagation 목적지로 처리
  sea = moisture source만. 전파 수신 대상 아님.

[금지 7] lake_seed를 moisture source로 처리
  lake_seed=true는 is_flow_sink. 이 단계에서 일반 land와 동일.
  lake moisture 피드백은 hydrology_spec_v0.5에서 처리.
```

---

## 12. mountain_barrier v0.3 삽입 위치

```
v0.3에서 transfer 계산 직후에 barrier 계산을 끼워 넣는다:

# [v0.2.5 현재]
transfer = delta_A × export_fraction × (flow_weight / flow_total)
loss = ...
moisture[B] += absorbed

# [v0.3에서 추가]
transfer = ... (동일)
barrier_factor = compute_barrier(A, B)         ← v0.3 삽입
blocked = transfer × barrier_factor
orographic_rain = blocked × windward_efficiency
rainfall[B] += orographic_rain
passed = transfer - blocked                    ← 이후 loss/net 처리
loss = min(passed, ...)
...

이 문서(v0.2.5)는 transfer 공식까지만 정의.
barrier 계산 상세는 mountain_barrier_pseudocode_v0.3.md 참조.
```

---

## 12-1. force 값 범위 검증

```
force_moisture:
  < 0 → ERROR: 음수 moisture 금지
  > capacity[color] → ERROR: capacity 초과 금지
  이유: clamp 대신 ERROR로 처리해 의도치 않은 과잉 설정을 조기에 발견

force_rainfall:
  < 0 → ERROR: 음수 rainfall 금지

force_temp:
  범위 제한 없음 (판타지 세계 허용)
  다만 극단값은 capacity를 capacity_min/max로 clamp되므로 실질 영향 제한됨
```

---

## 13. 검증 체크리스트

```
□ sea province: 내부 source 기준값 1.0, queue 미삽입, moisture_raw 미포함 확인
□ coastal province: moisture = coastal_ratio × 0.6 범위 확인
□ exclude_from_sim province: moisture/rainfall = 0 (전파 미참여)
□ locked province: 일반 province와 동일하게 moisture 계산 (라벨 변경 없음)
□ moisture가 capacity 초과하지 않음
□ rainfall 음수 없음
□ wind_weight >= leakage_min (0.05)
□ force_moisture: 매 iteration 재고정 확인
□ force_rainfall: 전파 완료 후 1회만 적용 확인
□ coastal province의 moisture > 동일 위도 inland province moisture
□ debug 이미지 4종 정상 생성
□ force_temp가 capacity 계산 전에 적용됨
□ force_moisture > capacity인 province는 루프 전 ERROR로 차단됨
```
