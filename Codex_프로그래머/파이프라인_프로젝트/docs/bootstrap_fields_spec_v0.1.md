# bootstrap_fields_spec v0.1

> 실제 heightmap이 없을 때 물리 계산에 사용하는 합성 필드 정의.
> v0.4~v0.7 문서가 이 파일을 참조한다.
> 실제 DEM 확정 후 교체 경로도 여기에 명시한다.
>
> 계약 우선순위: 이 문서는 필드의 물리적 의미를 정의한다. 직렬화 스키마,
> 입력 정규화, 해시, 저장 및 debug 동작은
> `bootstrap_fields_build_design_v0.1.md`를 authoritative contract로 둔다.

---

## 1. 배경 및 목적

현재 상태:
```
AI 임시 heightmap 존재
province_graph.metadata.heightmap.authoritative = false
→ elevation 기반 물리 계산에 원본 heightmap 직접 사용 금지
```

문제:
```
elevation 없이 불가능한 기능:
  기온 고도 감률 (lapse rate)
  강 흐름 방향 (flow direction)
  mountain barrier (자동 파생 불가 — 장벽은 사용자 mountain_strength 입력 전용)
  유역/호수 판정
```

해결:
```
elevation 역할을 3개 독립 합성 필드로 분리
각 필드는 한 가지 물리량만 담당
실제 DEM 도입 시 해당 필드만 교체
```

---

## 2. 3개 합성 필드

### 2-1. synthetic_elevation

**담당:** 기온 고도 감률(lapse rate)만 담당.

**계산식:**
```
synthetic_elevation = max(
  mountain_strength × mountain_average_elevation,
  elevation_hint_elevation
)

mountain_average_elevation = 1500m  (봉우리가 아닌 산맥 평균 고도)
```

**elevation_hint 값:**
```
none:          0m
lowland:     100m
upland:       500m
highland:   1200m
mountain:   2000m
```

**max 병합 이유:**
```
mountain_strength: 산맥 장벽 강도 (0~1)
elevation_hint: 지형 범주 (categorical)
둘 중 더 높은 값이 실제 고도에 가까움
add 방식은 이중 증폭 위험 (1.0 × 1500 + 2000 = 3500m 과증폭)
```

**온도 계산 적용:**
```
lapse_rate = 6.5°C / 1000m
temperature -= lapse_rate × (synthetic_elevation / 1000.0)
```

**mountain barrier와의 분리:**
```
synthetic_elevation → lapse rate만
mountain_strength  → barrier만
둘을 합산하거나 대체하지 않음
```

---

### 2-2. synthetic_flow_potential

**담당:** 임시 강 흐름 방향만 담당.

**계산식:**
```
synthetic_flow_potential =
  coast_distance_normalized              (0~1, 해안=0, 내륙 최대=1)
  + mountain_strength × mountain_flow_bonus   # 기본값: 0.5 (climate_rules.yaml)
  + elevation_hint_flow_bonus

범위:
  최소: 0.0 (해안 육지, mountain_strength=0, hint=none)
  최대: 1.0 + mountain_flow_bonus + max(elevation_hint_flow_bonus)
        = 1.0 + 0.5 + 0.60 = 2.10 (내륙 최원거리, mountain_strength=1.0, hint=mountain)
```

**elevation_hint_flow_bonus 값:**
```
none:       0.00
lowland:    0.05
upland:     0.15
highland:   0.35
mountain:   0.60
```

**climate_rules.yaml 파라미터:**
```yaml
bootstrap_fields:
  mountain_flow_bonus: 0.5
  max_coast_distance_hops: auto  # BFS 최대 거리, 자동 감지
```

**강 흐름 방향:**
```
낮은 synthetic_flow_potential 방향으로 흐름
= "해안 방향 + 산맥에서 멀어지는 방향"

우선순위:
  river_path  → 최우선 (유저가 직접 지정한 경로)
  river_seed  → anchor (threshold 무시, 무조건 강)
  synthetic   → filler (나머지 소하천 자동 생성)
```

**coast_distance_normalized 계산:**
```
land-only BFS (다중 시작점)
  시작점: is_coastal=true인 육지 province (거리 = 0)
  대상: province_graph.provinces 중 is_sea=false인 province
  바다 province: 계산 대상 제외 (is_sea=true 제외)
  각 육지 province에서 가장 가까운 해안까지 hop 수
  max_hop으로 나눠 0~1 정규화
  바다에 바로 닿은 해안 province = 0.0
```

**왜 elevation 아닌 coast_distance 기반인가:**
```
continent center = 무조건 최고 고도 오판 방지
내륙 평원 = 고원으로 오판 방지
평원을 관통하는 강(나일강 케이스)은 river_path로 처리
```

---

### 2-3. continentality

**담당:** 계절 기온 진폭만 담당.

**계산식:**
```
continentality = normalized_coast_distance  (= coast_distance_normalized)

latitude_factor = clamp(sin(abs(latitude) × π / 180), 0.0, 1.0)

seasonal_amplitude = base_seasonal_amplitude × latitude_factor × continentality

summer_temperature += seasonal_amplitude
winter_temperature -= seasonal_amplitude
```

**위도 변조 이유:**
```
적도(위도 0°): sin(0) = 0 → 계절 진폭 없음 (적도는 계절 없음)
중위도(위도 45°): sin(45°) ≈ 0.71 → 중간 진폭
고위도(위도 70°): sin(70°) ≈ 0.94 → 강한 진폭
```

**담당 범위:**
```
담당: 계절 기온 진폭 (여름 더 덥고 겨울 더 춥게)
비담당: 습도 감쇠 (수분 전파가 전담)
비담당: 연평균 기온 (위도 기반 계산이 전담)
```

**왜 분리하는가:**
```
continentality를 습도에도 적용하면:
  해안 → 고습 (맞음)
  내륙 → 저습 (부분적으로 맞음이나 수분 전파로 이미 처리됨)
  이중 반영으로 내륙이 과도하게 건조해질 위험
```

---

## 3. 필드 간 역할 정리

| 기능 | 담당 필드 |
|---|---|
| 강 흐름 방향 | synthetic_flow_potential |
| 기온 고도 보정 | synthetic_elevation |
| 계절 기온 진폭 | continentality |
| 산맥 수분 차단 | mountain_strength (barrier 전용) |
| 수분 전파 | moisture propagation (별도 시스템) |
| 습도 내륙 감쇠 | moisture propagation 자연 감소 |

**금지 조합:**
```
synthetic_elevation × mountain_strength → 합산 금지 (대체·합산 모두 금지)
continentality → 습도 개입 금지
mountain_strength → lapse rate 개입 금지
```

---

## 4. Province Editor 입력 필드 (이 spec 관련)

```yaml
province_constraints:
  xAABBCC:
    elevation_hint: none      # none/lowland/upland/highland/mountain
    mountain_strength: 0.0   # 0.0~1.0, barrier 강도, user authored only
    river_seed: false         # true → 강 anchor
    river_major: false        # true → 간선하천 우선순위
    river_path: []            # 방향 힌트 (D8 무시 구간)
    lake_seed: false          # true → 호수 지정 (실제 DEM 전까지)
```

---

## 5. 캐시 파일 위치

```
province_graph.json         → topology, coastal, center, area (정적)
cache/bootstrap_fields.json → synthetic 필드 (constraints 변경 시 재생성)
```

**bootstrap_fields.json은 province_graph.json과 분리한다.**

이유:
```
province_graph.json: topology는 provinces.png에서 파생
                     heightmap은 선택적 metadata이며 authoritative일 때만 물리값에 사용
bootstrap_fields.json: constraints에서 파생 (province_constraints.yaml)
입력 소스가 다르므로 캐시를 합치면 재생성 단위가 불명확해짐
```

**bootstrap_fields.json 구조:**
```json
{
  "schema_version": "bootstrap_fields.v0.1",
  "graph_hash": "sha256:...",
  "constraints_hash": "sha256:...",
  "params_hash": "sha256:...",
  "source_constraints": {
    "province_constraints": "path/to/province_constraints.yaml"
  },
  "provinces": {
    "xAABBCC": {
      "synthetic_elevation_m": 1500.0,
      "synthetic_flow_potential": 0.72,
      "continentality": 0.45,
      "coast_distance_normalized": 0.45,
      "is_flow_sink": false
    },
    "xA1B2C3": {
      "synthetic_elevation_m": 100.0,
      "synthetic_flow_potential": 0.18,
      "continentality": 0.18,
      "coast_distance_normalized": 0.18,
      "is_flow_sink": true
    }
  }
}
```

`provinces`에는 `is_sea=false`인 항목만 들어간다. sea province는 해안거리
경계를 정하는 데만 사용하며 `coast_distance_normalized=0` 같은 출력 항목을
별도로 만들지 않는다.

---

## 6. 업그레이드 경로

```
현재 (bootstrap):
  synthetic_flow_potential → 강 흐름 방향
  synthetic_elevation      → 기온 고도 보정
  continentality           → coast_distance 기반

실제 heightmap 완성 후 (선택적 교체):
  real DEM flow direction  → synthetic_flow_potential 대체
  real elevation_m         → synthetic_elevation 대체
  continentality           → coast_distance 계속 사용 (교체 불필요)

교체 트리거:
  province_graph.json의 metadata.heightmap.authoritative = true
  → 파이프라인이 자동으로 real 값 사용
```

---

## 7. 검증 규칙

```
synthetic_elevation_m >= 0m
synthetic_flow_potential: 0.0~2.10
  (= 1.0 + mountain_flow_bonus(0.5) + max elevation_hint_flow_bonus(0.60))
continentality: 0.0~1.0
coast_distance_normalized: 0.0~1.0 (출력 대상 육지만, 해안=0, 내륙 최대=1)

elevation_hint 없는 province:
  elevation_hint = none → elevation_hint_m = 0m
  synthetic_elevation = mountain_strength × 1500m (또는 0m)
  none과 lowland는 다름: none=0m, lowland=100m

lake_seed=true province:
  is_flow_sink = true
  bootstrap 단계에서는 synthetic_flow_potential을 변경하지 않음
  실제 flow_direction 중단과 국소 sink 적용은 hydrology.v0.5가 담당
```
