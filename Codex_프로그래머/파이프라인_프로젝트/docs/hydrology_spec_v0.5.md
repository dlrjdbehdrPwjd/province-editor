# hydrology_spec v0.5

> seasonal_climate(v0.4) 결과를 기반으로 강/호수/습지/유역 시스템을 생성하는 단계.
> user river_seed anchor + synthetic_flow_potential 기반 자동 생성을 결합.
> rivers.png를 파이프라인 출력으로 생성한다 (입력 아님).

---

## 0. 이 문서의 범위

```
포함:
  flow_direction 계산 (synthetic_flow_potential 기반)
  river_path topological sort + cycle 검증
  rainfall-weighted flow accumulation
  강 판정 (threshold + user anchor)
  호수/salt_flat 판정 (pit + is_flow_sink)
  배수 유형 결정 (exorheic / endorheic)
  discharge 계산
  river_bonus → soil_moisture 보정 (v0.7 소비)
  lake_fraction 확정 → corrected_ET 별도 출력
  rivers.png 초안 출력 (Vic3 포맷 최종 검증은 별도)

포함하지 않음:
  depression fill     → 사용 안 함 (pit = 호수 처리)
  DEM 자동 pit 탐지  → 실제 DEM 확정 후
  biome 판정          → koppen_biome_terrain_spec_v0.7
  rainfall 정규화     → rainfall_normalization_spec_v0.6
  Vic3 최종 rivers.png 포맷 검증 → 별도 rivers_format_spec
```

---

## 1. 핵심 설계 원칙

```
rivers.png는 파이프라인 출력. 입력으로 사용 금지.

강 생성 우선순위:
  river_path  → 최우선 (user가 직접 지정한 경로)
  river_seed  → anchor (threshold 무시, 무조건 강)
  synthetic   → filler (나머지 소하천 자동 생성)

pit 처리:
  depression fill 없음.
  lake_seed=true → is_flow_sink=true (수동 지정, flow sink hint).
  lake_seed=false natural pit → is_flow_sink=true (WARNING 후 종착점 처리).
  DEM 기반 자동 pit 탐지: 실제 heightmap 확정 후.

lake_seed 의미:
  = flow sink hint (호수 후보, 물이 충분해야 is_lake=true)
  ≠ 호수 강제 (물 없어도 호수가 되는 것 아님)

sea neighbor 처리:
  sea province는 synthetic_flow_potential 없음.
  → 즉시 outlet이 아니라 outlet 후보.
  → 더 낮은 non-sea downstream 후보가 없을 때만 sea로 유출.

river_major 의미:
  rivers.png 시각화/폭 우선순위에만 영향.
  discharge, rainfall, moisture, terrain 판정에 직접 영향 없음.

v0.4 ET 수정 금지:
  v0.5는 corrected_ET를 별도 출력.
  cache/seasonal_climate.json 직접 수정 금지.

soil_moisture 책임:
  v0.5는 soil_moisture를 확정하지 않음.
  corrected_ET, river_bonus, lake_fraction만 v0.7로 전달.
  최종 soil_moisture는 koppen_biome_terrain_spec_v0.7에서 계산.
```

---

## 2. 입력

| 파일 | 사용 데이터 |
|------|------------|
| `cache/seasonal_climate.json` | annual_rainfall_raw, annual_runoff, soil_water_storage_final, annual_ET |
| `cache/bootstrap_fields.json` | synthetic_flow_potential, coast_distance_normalized |
| `cache/province_graph.json` | adjacency, is_sea, area_px, center |
| `province_constraints.yaml` | river_seed, river_major, river_path, lake_seed, wetland_seed |
| `province_overrides.yaml` | exclude_from_sim, force_terrain, locked |

**province_overrides.yaml 사용 방식:**
```
exclude_from_sim:
  기후 계산 제외.
  hydrology에서는 local_runoff=0으로 처리.
  단, flow graph node로는 유지.
  upstream discharge를 수신하고 downstream으로 전달.
  river_path / flow accumulation / watershed 연결 차단 금지.
force_terrain: 나일강 케이스 확인용 참고 (desert + river_seed 동시 허용)
locked: 물리 시뮬레이션 참여 유지 → hydrology에서 라벨 참고만. 흐름 계산에 영향 없음.
```

---

## 3. 출력

**v0.5 필수 출력: `cache/hydrology.json`**

| 필드 | 형태 | 설명 |
|------|------|------|
| `discharge` | dict[color → float] | province별 누적 유량 |
| `is_river` | dict[color → bool] | 강 판정 결과 |
| `is_lake` | dict[color → bool] | 호수 판정 결과 |
| `is_salt_flat` | dict[color → bool] | 염전/건조 분지 판정 |
| `is_wetland` | dict[color → bool] | 습지 판정 결과 |
| `lake_fraction` | dict[color → float] | 호수 비율 (ET 보정용) |
| `river_bonus` | dict[color → float] | 강 인접 soil_moisture 보정 (v0.7 소비) |
| `corrected_ET` | dict[color → float] | lake_fraction 반영 ET (v0.4 수정 아닌 별도 출력) |

**soil_moisture 책임 경계:**
```
v0.5는 soil_moisture를 확정하지 않는다.
v0.5 출력은 corrected_ET / river_bonus / lake_fraction을 v0.7에 전달하는 역할이다.
최종 soil_moisture는 koppen_biome_terrain_spec_v0.7에서 계산한다.
```

**v0.5 선택 출력: `outputs/draft_rivers.png`**
```
초안 rivers.png. Vic3 포맷 최종 검증 전.
v0.5 완료 기준에 포함하지 않음.
Vic3 호환 rivers.png 확정은 별도 rivers_format_spec에서.
```

---

## 4. flow_direction 계산

```
각 non-sea province에 대해:

# 0. lake_seed 선처리
if lake_seed[color]:
  is_flow_sink[color] = true
  flow_direction[color] = None
  continue

# 1. 후보 분리
valid_neighbors = [n for n in neighbors if not is_sea(n)]
sea_neighbors = [n for n in neighbors if is_sea(n)]

# 2. 더 낮은 non-sea downstream 후보 우선
if valid_neighbors:
  best = min(valid_neighbors, key=(synthetic_flow_potential, distance_px, color_id))
  if synthetic_flow_potential[best] < synthetic_flow_potential[color]:
    flow_direction[color] = best
    continue

# 3. 더 낮은 non-sea 후보가 없을 때만 sea outlet 선택
if sea_neighbors:
  flow_direction[color] = choose_sea_outlet(sea_neighbors)
  continue

# 4. 유출 후보 없음 → pit
flow_direction[color] = None
```

**sea outlet 선택:**
```
sea neighbor가 여러 개면 deterministic tie-break:
  1순위: shared_border_px 큰 sea neighbor
  2순위: distance_px 짧은 sea neighbor
  3순위: province color id 정렬 기준
```

**pit 처리:**
```
flow_direction[color] = None:
  lake_seed=true → 이미 선처리되어 is_flow_sink=true
  lake_seed=false → is_flow_sink=true + WARNING: "natural pit 감지: {color}"
```

**lake_seed 처리 순서:**
```
lake_seed=true province는 flow_direction 계산 전에 is_flow_sink=true로 확정한다.
is_flow_sink=true province는 flow_direction=None으로 고정한다.
나머지 province만 downstream을 계산한다.
```

기존 즉시 outlet 방식 폐기:
```
해안에 닿은 모든 province를 즉시 sea로 유출시키면
해안 평야를 따라 흐르는 하류 구간, 삼각주, 대형 강 하구가 잘려나간다.
따라서 sea는 마지막 배출구 후보로만 사용한다.
```

**direction 퇴화 케이스 — deterministic tie-break:**
```
동률 (potential 동일한 neighbor 여럿):
  1순위: distance_px 짧은 neighbor
  2순위: province color id 정렬 기준 (재현성 보장)
  WARNING: "tie-break 발생: {color}"
```

---

## 5. river_path 적용 및 flow graph 검증

river_path는 flow_direction을 덮어쓰므로 accumulation 전에 처리한다.

### 5-1. river_path 적용

```
for each province with river_path:
  for i in range(len(river_path) - 1):
    flow_direction[river_path[i]] = river_path[i+1]
```

### 5-2. cycle 검증

```
cycle 검사 (DFS 기반):
  flow graph에서 cycle 발견 시 → ERROR: "river_path cycle 발견: {경로}"
  cycle이 있으면 accumulation이 무한/오염됨
```

### 5-3. topological sort (accumulation 정렬 재계산)

```
river_path 적용 후 flow graph 기준 topological sort 재수행.
이유:
  synthetic_flow_potential 내림차순 정렬은 river_path가 potential 역방향을
  포함할 수 있으므로 보장되지 않음.
  flow graph 기반 topological sort가 upstream → downstream 순서를 보장.

sort_order = topological_sort(flow_graph)
  # cycle 없음을 cycle 검증에서 보장
```

---

## 6. rainfall-weighted flow accumulation

```
# 초기화
accumulated_water[color] = 0.0

# topological sort 순서대로 (upstream → downstream)
for color in sort_order:
  incoming = accumulated_water[color]

  if exclude_from_sim[color]:
    local = 0.0
  else:
    local = annual_runoff[color]

  accumulated_water[color] = incoming + local

  downstream = flow_direction[color]
  if downstream is not None and not is_sea(downstream):
    accumulated_water[downstream] += accumulated_water[color]

# sea로 유출
sea_discharge = sum(accumulated_water[color]
                    for color where flow_direction[color] is sea)
```

**exclude_from_sim 처리:**
```
exclude_from_sim=true province:
  local_runoff = 0
  rainfall/ET/local hydrology 기여 = 0
  flow graph node로는 유지
  upstream discharge 수신 가능
  downstream으로 전달 가능
  river_path / flow accumulation / watershed 연결 차단 금지

문서 내 금지 의미:
  수문 그래프에서 제외한다고 쓰면 안 됨
  상류에서 받은 물을 삭제한다고 쓰면 안 됨
  river_path / watershed 연결을 끊는다고 쓰면 안 됨
```

**is_flow_sink 처리:**
```
is_flow_sink=true province:
  upstream으로부터 accumulated_water 수신
  downstream으로 전달 안 함 (유출 없음)
  호수/분지 누적 기준값으로 사용
```

---

## 7. 강 판정

### 7-1. threshold 계산

```
river_threshold = percentile(accumulated_water_land, 85~90)
  percentile 범위는 climate_rules.yaml의 river_threshold_percentile로 조정
  이유: median × factor는 분포 치우침 시 강이 너무 많거나 적게 생성됨
```

### 7-2. user anchor 통합

```
river_path (최우선):
  해당 province: is_river=true, threshold 무시
  flow_direction: topological sort로 이미 반영

river_seed=true:
  is_river=true, threshold 무시
  river_seed=true + is_flow_sink=true:
    WARNING: "river_seed가 pit province에 설정됨: {color}"
    → is_river=true 유지, 내륙하천 또는 호수 유입으로 처리

river_major=true:
  river_seed=true 또는 river_path 있을 때만 유효
  없으면 WARNING: "river_major는 river_seed 또는 river_path 필요"
  rivers.png 시각화 폭/우선순위에만 영향

synthetic filler:
  accumulated_water >= river_threshold → is_river=true
```

---

## 8. 호수 / salt_flat / 습지 판정

### 8-1. 호수 (lake_seed = flow sink hint)

```
is_lake 판정 조건:
  is_flow_sink=true
  AND accumulated_water[color] >= lake_threshold

lake_seed=true이면 is_flow_sink=true이지만,
물이 부족하면 (accumulated_water < lake_threshold) is_lake=false.
  → salt_flat 또는 건조 sink 후보로 처리

이유: lake_seed는 "호수 강제"가 아닌 "sink hint"
      물이 있어야 호수가 됨
```

**lake_fraction:**
```
if is_lake[color]:
  lake_fraction[color] = clamp(
    accumulated_water[color] / lake_full_threshold,
    0.0, 1.0
  )
else:
  lake_fraction[color] = 0.0
```

### 8-2. salt_flat

```
is_salt_flat 판정:
  is_flow_sink=true
  AND is_lake=false
  AND annual_runoff[color] < salt_flat_runoff_threshold
```

### 8-3. 습지

```
is_wetland 판정:
  wetland_seed=true (user 지정, threshold 무관)
  OR (is_river=true AND annual_rainfall_raw >= wetland_rainfall_threshold
      AND soil_water_storage_final >= wetland_storage_threshold)
```

### 8-4. lake_fraction → corrected_ET (별도 출력)

```
# v0.4 seasonal_climate.json 직접 수정 금지
# corrected_ET를 hydrology.json에 별도 출력

corrected_ET[color] = annual_ET[color]  # v0.4 기준값

if is_lake[color]:
  PET_season = (summer_PET + winter_PET) / 2   # 근사값
  open_water_correction = PET_season × open_water_factor × lake_fraction[color]
  corrected_ET[color] = annual_ET[color] + open_water_correction

# v0.7에서 soil_moisture 계산 시 corrected_ET / river_bonus / lake_fraction 사용
```

**soil_moisture 미확정:**
```
v0.5는 hydrology_moisture_index, corrected_soil_water_storage,
final soil_moisture를 출력하지 않는다.
최종 soil_moisture는 koppen_biome_terrain_spec_v0.7에서 계산한다.
```

---

## 9. 배수 유형 결정

```
exorheic (외류):
  강이 sea에 도달하는 province → 정상 강 시스템

endorheic (내류):
  is_flow_sink=true에서 흐름 종료 → 호수 또는 salt_flat

나일강 케이스:
  river_seed=true + force_terrain=desert 동시 설정 허용
  is_river=true, biome은 별도 채널 (terrain 라벨)
  river_seed + force_terrain은 다른 채널이므로 충돌 없음
```

---

## 10. discharge 및 river_bonus

```
discharge[color] = accumulated_water[color]

river_bonus (강 인접 soil_moisture 보정, v0.7에서 소비):
  for each is_river province:
    for each land neighbor of this province:
      distance = adjacency[province][neighbor]['distance_px']
      river_bonus[neighbor] += discharge[province] × river_bonus_factor
                               × exp(-distance / river_bonus_decay)

river_bonus 적용 방식:
  v0.7 soil_moisture = corrected_ET 기반값 + river_bonus
  직접 rainfall/moisture에 더하지 않음 (별도 보정 채널)
```

---

## 11. rivers.png 초안 생성

```
v0.5 선택 출력 (완료 기준 미포함):

1. is_river=true province 픽셀 → 강 색상 마킹
2. river_major=true → 굵은 강 시각화 우선
3. river_path 경로 우선 적용
4. sea 경계에서 종료
5. draft_rivers.png 출력

Vic3 포맷 최종 검증 (별도 일정):
  강 연결성 (단절 없는지)
  source 픽셀 위치
  색상 코드 유효성 (Vic3 규격)
  → rivers_format_spec에서 처리
```

---

## 12. climate_rules.yaml 추가 섹션

```yaml
hydrology:
  river_threshold_percentile: 87  # accumulated_water 분위수 기반 threshold
  lake_threshold: 50.0            # is_lake 최소 accumulated_water
  lake_full_threshold: 200.0      # lake_fraction=1.0 기준
  salt_flat_runoff_threshold: 5.0
  wetland_rainfall_threshold: 30.0
  wetland_storage_threshold: 20.0
  river_bonus_factor: 0.05
  river_bonus_decay: 50.0
  open_water_factor: 1.0
```

---

## 13. 금지 사항

```
[금지 1] rivers.png를 입력으로 사용
  rivers.png는 이 단계의 출력.

[금지 2] depression fill 수행
  pit은 is_flow_sink로 처리.

[금지 3] DEM 기반 자동 pit 탐지 (실제 DEM 없이)
  lake_seed=true 수동 지정이 현재 유일한 명시적 sink 방법.

[금지 4] river_bonus를 rainfall/moisture에 직접 더하기
  별도 보정 채널. v0.7 soil_moisture에서만 사용.

[금지 5] river_major=true를 river_seed 없이 단독 사용
  WARNING 처리. 효과 없음.

[금지 6] lake_seed=true를 호수 강제로 처리
  lake_seed = flow sink hint. 물이 부족하면 is_lake=false.

[금지 7] synthetic_flow_potential을 온도/moisture 계산에 사용
  강 흐름 방향 전용.

[금지 8] v0.4 seasonal_climate.json 직접 수정
  corrected_ET는 hydrology.json에 별도 출력.

[금지 9] cycle 있는 river_path 허용
  cycle → ERROR.

[금지 10] river_path 후 synthetic_flow_potential 내림차순으로만 정렬
  river_path 적용 후 flow graph 기준 topological sort 재수행 필수.

[금지 11] exclude_from_sim province에서 upstream discharge 삭제
  exclude_from_sim은 local_runoff=0인 통과 노드.
  flow graph / river_path / watershed 연결을 차단하지 않는다.

[금지 12] sea neighbor를 즉시 outlet으로 강제
  sea는 outlet 후보.
  더 낮은 non-sea downstream 후보가 있으면 non-sea 우선.

[금지 13] v0.5에서 soil_moisture 확정
  corrected_ET / river_bonus / lake_fraction만 v0.7로 전달.
```

---

## 14. 검증 체크리스트

```
□ flow_direction
  - sea neighbor는 outlet 후보일 뿐, 즉시 outlet 아님
  - 더 낮은 non-sea downstream 후보가 있으면 non-sea 우선
  - 더 낮은 non-sea 후보가 없을 때만 sea 유출
  - lake_seed=true는 downstream 계산 전 is_flow_sink=true로 선처리
  - is_flow_sink=true는 flow_direction=None 고정
  - 동률: deterministic tie-break (distance → color id 순)
  - pit province: WARNING 기록됨

□ cycle 검증
  - river_path 적용 후 cycle=0 확인
  - cycle 발견 시 ERROR 처리됨

□ topological sort
  - river_path 적용 후 재수행됨
  - upstream이 항상 downstream보다 먼저 처리됨

□ flow accumulation
  - exclude_from_sim province: local_runoff=0
  - exclude_from_sim province: upstream discharge 수신 및 downstream 전달
  - exclude_from_sim province: river_path / watershed 연결 차단 없음
  - is_flow_sink province: upstream 수신, downstream 전달 없음
  - 일반 province: accumulated_water >= annual_runoff (자기 runoff + upstream)
  - exclude_from_sim province: accumulated_water는 upstream 유량만 반영

□ 강 판정
  - river_path province: is_river=true
  - river_seed=true: is_river=true
  - river_seed=true + is_flow_sink=true: WARNING 기록됨
  - river_major=true + river_seed=false: WARNING 기록됨

□ 호수/salt_flat
  - lake_seed=true + 물 부족: is_lake=false, salt_flat 또는 건조 sink 후보
  - is_lake=true 동시에 is_salt_flat=true 금지
  - lake_fraction: 0.0~1.0

□ ET 보정
  - corrected_ET 별도 출력
  - seasonal_climate.json 수정 없음
  - v0.5에서 soil_moisture 확정 없음
  - corrected_ET / river_bonus / lake_fraction은 v0.7 입력

□ 나일강 케이스
  - river_seed=true + force_terrain=desert 동시 허용 확인

□ river_bonus
  - 음수 없음
  - 강 없는 province에 bonus=0
```
