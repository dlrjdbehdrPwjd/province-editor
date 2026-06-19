# build_province_graph_design v0.2

> `province_graph_schema_v0.2.md`를 실제 `province_graph.json`으로 생성하는 설계 문서.
> 이 문서는 topology / static province graph 생성만 다룬다.

---

## 1. 목적

`build_province_graph.py`는 지도 원본 파일을 읽어 기후·수문 파이프라인이 공통으로 사용할 정적 province graph를 생성한다.

출력 파일:

```text
파이프라인_프로젝트/cache/province_graph.json
```

이 파일의 책임:

```text
province 색상 식별
province별 면적/중심/bbox/perimeter 계산
land/sea 판정
coastal_ratio 계산
latitude 계산
4방향 공유 경계 기반 adjacency 생성
heightmap raw 통계 저장
topology_hash / heightmap_stats_hash 계산
```

이 파일의 책임이 아닌 것:

```text
synthetic_elevation 생성
synthetic_flow_potential 생성
continentality 생성
mountain_strength 자동 생성
수분 전파
산맥 장벽 계산
강 흐름 생성
biome / terrain 판정
```

핵심 원칙:

```text
province_graph.json = topology cache
bootstrap_fields.json = synthetic physical fields cache

두 캐시를 섞지 않는다.
```

---

## 2. 입력

필수 입력:

```text
map_data/provinces.png
map_data/default.map
config/world.yaml
```

선택 입력:

```text
map_data/heightmap.png
map_data/water_mask.png
```

`water_mask.png`는 `default.map`에서 water 후보 전체 목록을 얻을 수 없을 때만 필요하다.
`sea_starts`만 있고 water 후보 전체를 만들 수 없는 경우, `water_mask.png` 없이
sea flood-fill을 추측으로 수행하지 않는다.

`world.yaml`은 지도 원본이 아니라 파이프라인 설정 파일이다.
운영 위치는 `config/world.yaml`로 고정한다.

읽지 말아야 하는 파일:

```text
province_constraints.yaml
province_overrides.yaml
state_constraints.yaml
climate_rules.yaml
bootstrap_fields.json
moisture 결과물
hydrology 결과물
biome / terrain 결과물
```

금지 이유:

```text
province_graph는 지도 원본에서 파생되는 정적 topology 캐시다.
사용자 constraints나 climate rules를 읽으면 캐시 무효화 기준이 섞이고,
graph 재생성 책임과 bootstrap/climate 책임이 불명확해진다.
```

---

## 3. 출력

출력 파일:

```text
파이프라인_프로젝트/cache/province_graph.json
```

최상위 구조:

```json
{
  "schema_version": "province_graph.v0.2",
  "metadata": {},
  "provinces": {},
  "adjacency": {}
}
```

`schema_version`은 최상위에만 둔다. `metadata` 내부에 중복 기록하지 않는다.

---

## 4. 처리 순서

전체 순서:

```text
1. 입력 파일 존재 및 형식 검증
2. provinces.png 로드
3. province color 인코딩
4. default.map 파싱 → sea_starts / lake_starts / water 후보 로드
5. world.yaml 파싱 → 위도/경도 변환 파라미터 로드
6. province별 area / center / bbox 계산
7. province별 perimeter 계산
8. 4방향 스캔으로 shared border / adjacency 생성
9. sea_starts + water_candidates 기반 resolved_sea_set 확정
10. is_sea / is_simulation_target 확정
11. land-sea border 기반 coastal_ratio / is_coastal 계산
12. latitude 계산
13. heightmap.png가 있으면 raw elevation 통계 계산
14. metadata 생성
15. topology_hash / heightmap_stats_hash 계산
16. schema validation
17. province_graph.json 원자적 저장
```

---

## 5. 핵심 알고리즘

### 5-1. province color 인코딩

`provinces.png`의 각 픽셀 RGB를 24비트 정수로 인코딩한다.

```python
color_id = (r << 16) | (g << 8) | b
```

출력 key는 `x` 접두사를 붙인 6자리 대문자 hex다.

```text
color_id = 0xAABBCC
province key = xAABBCC
color_hex = AABBCC
```

규칙:

```text
alpha 채널이 있으면 무시한다.
RGB 기준으로만 province를 식별한다.
동일 RGB는 동일 province다.
```

성능 기준:

```text
8192px급 맵에서 Python 픽셀 중첩 루프 금지.
numpy 배열 연산으로 color_id 배열을 생성한다.
```

---

### 5-2. default.map 기반 water hint 파싱

`default.map`에서 완성된 sea province set을 직접 얻는다고 가정하지 않는다.
Vic3 계열 `default.map`은 바다 전체가 아니라 `sea_starts`, `lakes` 같은
시작 province만 제공할 수 있다.

따라서 이 단계에서는 water 관련 hint를 분리해서 읽는다.

```text
sea_starts   = default.map의 sea 시작 province 후보
lake_starts  = default.map의 lake / inland water 시작 province 후보
water_candidates = default.map 또는 별도 water_mask에서 얻은 전체 water 후보
```

주의:

```text
이 단계에서는 is_sea를 최종 확정하지 않는다.
sea 확정은 adjacency 생성 이후 water_candidates 내부 flood-fill로 수행한다.
lake/inland water는 province_graph.v0.2 schema에 쓰지 않고 debug 후보로만 기록한다.
```

검증:

```text
default.map의 water start가 provinces.png에 없으면 WARNING
water_candidates 없이 sea_starts만 있으면 FATAL
water hint가 하나도 없으면 FATAL
```

---

### 5-3. province별 area / center / bbox

각 province에 대해 계산한다.

```text
area_px = 해당 color 픽셀 수
center.x = mean(x coordinates)
center.y = mean(y coordinates)
bbox.x_min = min(x)
bbox.x_max = max(x)
bbox.y_min = min(y)
bbox.y_max = max(y)
```

center는 float로 저장한다.

이유:

```text
province 중심은 픽셀 평균이므로 정수가 아닐 수 있다.
direction 계산의 정밀도를 위해 float 유지.
```

---

### 5-4. perimeter 계산

province perimeter는 해당 province 픽셀의 4방향 이웃 중 다른 color 또는 맵 외곽과 닿은 변의 수로 계산한다.

```text
perimeter_px =
  north edge count
  + south edge count
  + west edge count
  + east edge count
```

맵 외곽은 외부 경계로 간주해 perimeter에 포함한다.

---

### 5-5. 4방향 shared border / adjacency 생성

인접 관계는 4방향 공유 경계만 인정한다.

```text
인정:
  상하좌우로 서로 다른 province가 맞닿음

인정 안 함:
  대각선 꼭짓점 접촉
```

스캔 방식:

```text
1. color_id 배열에서 오른쪽 이웃과 비교
2. color_id 배열에서 아래쪽 이웃과 비교
3. 서로 다른 color 쌍이면 shared_border_px += 1
4. A-B와 B-A를 모두 기록할 수 있도록 무방향 shared pair를 먼저 누적
5. 최종 출력 시 directed adjacency로 변환
```

directed adjacency가 필요한 이유:

```text
shared_border_px는 A-B 양쪽에서 동일하지만
border_weight = shared_border_px / perimeter_px(A)
이므로 A→B와 B→A 값이 다를 수 있다.
```

출력에는 land-land, land-sea, sea-sea adjacency를 모두 포함한다.

이유:

```text
coastal_ratio 계산
수분 source 경계
향후 해류/항로 확장
debug 검증
```

시뮬레이션에서 sea province를 source로만 쓰거나 전파 대상에서 제외하는 것은 이후 climate 단계 책임이다.

---

### 5-6. sea province set 확정

adjacency 생성 후 `sea_starts`를 시작점으로 flood-fill을 수행해
`resolved_sea_set`만 확정한다.

v0.2 schema에는 `is_lake` 필드가 없다.
따라서 이 단계에서는 lake/inland water를 최종 분류하지 않는다.

중요:

```text
flood-fill은 전체 adjacency에 대해 무제한 수행하면 안 된다.
그렇게 하면 sea_start에서 육지까지 확장되어 전체 대륙이 sea로 오염될 수 있다.

확장은 반드시 water_candidates 내부에서만 수행한다.
water_candidates를 만들 수 없으면 FATAL.
sea_starts만으로 무제한 flood-fill하지 않는다.
```

water 후보 집합 생성 우선순위:

```text
1. default.map에 sea/lake/water province 전체 목록이 있으면 사용
2. 없으면 별도 water_mask 파일을 입력으로 요구
3. 둘 다 없으면 FATAL

provinces.png 색상만으로 water 후보를 추정하지 않는다.
```

기본 절차:

```text
1. default.map 또는 water_mask에서 water_candidates를 만든다.
2. default.map에서 읽은 sea_starts를 queue에 넣는다.
3. water_candidates 내부 adjacency만 따라 연결된 province를 확장한다.
4. sea_starts와 연결된 water component를 resolved_sea_set으로 확정한다.
5. lake_starts 또는 폐쇄 water component는 debug 후보로만 기록한다.
6. resolved_sea_set에 없는 province는 is_sea=false로 저장한다.
```

출력 필드:

```text
is_sea = province_key in resolved_sea_set
is_simulation_target = not is_sea
```

`is_sea=false`는 이 단계에서 "육지 확정"을 의미하지 않는다.
v0.2 schema 한계상 lake/inland water 후보도 `is_sea=false`로 남을 수 있다.
pipeline은 이 값을 lake 판정에 사용하면 안 된다.
lake/inland water의 최종 처리는 `hydrology_spec_v0.5.md`에서 정의한다.

주의:

```text
sea_starts에 들어 있는 province만 sea로 찍으면 안 된다.
반드시 adjacency 기반 확장으로 실제 sea province set을 확정한다.
lake 후보를 province_graph.json에 쓰지 않는다.
```

검증:

```text
sea_starts flood-fill 결과가 0개면 ERROR
water_candidates 누락 → FATAL
sea_starts가 water_candidates 밖에 있으면 FATAL
lake 후보가 발견되어도 province_graph schema에는 쓰지 않고 debug report에만 기록
lake_starts가 resolved_sea_set과 연결되면 WARNING
```

---

### 5-7. border_weight 계산

각 directed edge A→B에 대해:

```text
border_weight = shared_border_px / perimeter_px(A)
```

의미:

```text
A의 전체 둘레 중 B와 닿은 경계 비율
moisture 전파 시 이웃 간 분배 비율
```

주의:

```text
border_weight는 절대 전달량 multiplier가 아니다.
moisture_transport 단계에서 transfer를 이웃들에게 나누는 비율로 사용한다.
mountain barrier 공식에 다시 곱하지 않는다.
```

---

### 5-8. direction / distance 계산

각 directed edge A→B에 대해:

```text
dx = center_B.x - center_A.x
dy = center_B.y - center_A.y
distance_px = sqrt(dx² + dy²)
direction = { x: dx / distance_px, y: dy / distance_px }
```

좌표계:

```text
x 양수 = 동쪽
y 양수 = 남쪽
```

퇴화 케이스:

```text
distance_px = 0이면 direction 정의 불가
→ WARNING 기록
→ 해당 adjacency 출력 제외
→ direction = {0, 0} 출력 금지
```

---

### 5-9. coastal_ratio / is_coastal 계산

land province에 대해 sea province와 맞닿은 shared_border_px를 합산한다.

```text
sea_shared_border_px = sum(shared_border_px to sea neighbors)
coastal_ratio = sea_shared_border_px / perimeter_px
is_coastal = coastal_ratio > 0
```

sea province는 고정값:

```text
coastal_ratio = 0.0
is_coastal = false
```

주의:

```text
sea province의 is_coastal을 true로 만들지 않는다.
해안성은 land province의 속성이다.
```

---

### 5-10. latitude 계산

`world.yaml`에서 위도 범위를 읽어 이미지 y좌표를 위도로 변환한다.

필수 파라미터:

```yaml
latitude:
  north_latitude: 70.0
  south_latitude: -45.0
  equator_y: 2201
  mapping: "piecewise_equator"
```

계산:

```text
if center.y <= equator_y:
  t = center.y / equator_y
  latitude = north_latitude * (1 - t)
else:
  t = (center.y - equator_y) / ((height_px - 1) - equator_y)
  latitude = south_latitude * t
```

검증:

```text
latitude는 -90.0~90.0 범위여야 한다.
범위를 벗어나면 ERROR.
```

---

### 5-11. heightmap raw 통계

`heightmap.png`가 있으면 province별 raw elevation 통계를 계산한다.
`authoritative=false`일 때도 meter로 변환된 참고 통계를 만들 수는 있지만,
이 값은 실제 기후용 고도처럼 취급하지 않는다.

출력:

```json
"elevation": {
  "elevation_m": 450.0,
  "elevation_max_m": 1200.0
}
```

`world.yaml`의 고도 변환 파라미터를 사용해 heightmap 값을 meter로 변환한다.

예시:

```yaml
heightmap:
  present: true
  authoritative: false
  min_m: -500
  max_m: 4000
```

정확한 변환식은 `world.yaml`의 실제 파라미터 이름에 맞춘다.
단, 출력 schema의 의미는 항상 meter로 변환된 통계값이다.

중요:

```text
heightmap.authoritative=false이면 elevation_m / elevation_max_m은 참고용 raw 데이터다.
기후 계산에 직접 사용하지 않는다.
synthetic_elevation은 build_bootstrap_fields.py에서 별도로 생성한다.
```

크기 불일치 처리:

```text
authoritative=true:
  heightmap 크기 != provinces.png 크기 → ERROR

authoritative=false:
  heightmap 크기 != provinces.png 크기 → WARNING
  resample 금지
  elevation 통계 생략
  province.elevation = null
```

이유:

```text
현재 heightmap은 AI 임시 파일일 수 있으므로,
비권위 heightmap 문제 때문에 topology graph 생성을 실패시키면 안 된다.
```

`heightmap.png`가 없으면:

```text
metadata.heightmap.present = false
province.elevation = null
```

---

## 6. metadata / hash

metadata 구조:

```json
{
  "metadata": {
    "generated_at": "ISO-8601",
    "source_files": {
      "provinces_png": "map_data/provinces.png",
      "default_map": "map_data/default.map",
      "water_mask_png": "map_data/water_mask.png",
      "heightmap_png": "map_data/heightmap.png",
      "world_yaml": "config/world.yaml"
    },
    "world": {
      "width_px": "<auto>",
      "height_px": "<auto>",
      "north_latitude": 70.0,
      "south_latitude": -45.0,
      "equator_y": 2201,
      "latitude_mapping": "piecewise_equator",
      "lon_left": -180.0,
      "lon_right": 180.0
    },
    "heightmap": {
      "present": true,
      "authoritative": false,
      "elevation_source": "heightmap.png"
    },
    "hash": {
      "topology_hash": "sha256:...",
      "heightmap_stats_hash": "sha256:..."
    },
    "province_count": {
      "total": "<auto>",
      "land": "<auto>",
      "sea": "<auto>"
    }
  }
}
```

`width_px`, `height_px`, `province_count`는 예시 숫자가 아니라 실행 시 감지·계산되는 값이다.
58829 province는 현재 과분할 맵 규모를 설명하는 참고치일 뿐 고정값이 아니다.

### topology_hash

입력:

```text
schema_version
provinces.png bytes
default.map bytes
water_mask.png bytes (사용한 경우)
world.yaml bytes
```

제외:

```text
heightmap.png
province_constraints.yaml
province_overrides.yaml
state_constraints.yaml
climate_rules.yaml
```

이유:

```text
topology_hash는 province topology와 latitude/coast 판정이 바뀌었는지만 나타낸다.
heightmap.authoritative=false인 현 단계에서 heightmap 변경이 bootstrap cache를 무효화하면 안 된다.
```

### heightmap_stats_hash

입력:

```text
heightmap.png bytes
heightmap 변환 파라미터
```

`heightmap.png`가 없으면:

```text
heightmap_stats_hash = null
```

---

## 7. override / constraints 적용 시점

이 단계에서는 override와 constraints를 적용하지 않는다.

명시적 금지:

```text
province_constraints.yaml 읽기 금지
province_overrides.yaml 읽기 금지
state_constraints.yaml 읽기 금지
mountain_strength 자동 생성 금지
locked / climate_lock / exclude_from_sim 처리 금지
```

각 기능의 담당 단계:

```text
mountain_strength       → province_constraints.yaml, moisture/mountain 단계에서 사용
elevation_hint          → build_bootstrap_fields.py
synthetic_elevation     → build_bootstrap_fields.py
synthetic_flow_potential→ build_bootstrap_fields.py
continentality          → build_bootstrap_fields.py
locked                  → biome/terrain 최종 라벨 단계
climate_lock            → seasonal/moisture 루프 내부
exclude_from_sim        → pipeline 실행 단계
```

---

## 8. 검증 규칙

### ERROR

```text
provinces.png 없음
default.map 없음
world.yaml 없음
provinces.png RGB/RGBA 이미지 아님
province color가 6자리 RGB로 변환 불가
perimeter_px = 0인 province 존재
latitude가 -90~90 범위 밖
schema_version 누락 또는 잘못됨
direction = {0, 0} 출력됨
heightmap.authoritative=true인데 heightmap 크기가 provinces.png와 다름
water_candidates를 default.map과 water_mask 양쪽에서 모두 만들 수 없음
sea_starts가 water_candidates 밖에 있음
```

### WARNING

```text
default.map의 water start가 provinces.png에 없음
heightmap.authoritative=false인데 heightmap 크기가 provinces.png와 다름
lake 후보가 발견됨 (province_graph에는 기록하지 않고 debug report에만 기록)
area_px < 4인 province
distance_px = 0 adjacency 발견 후 제외
land province elevation_m < 0
province_count.land + province_count.sea != province_count.total
border_weight 합산이 1.0 + epsilon 초과
```

### INFO

```text
heightmap 없음 → elevation=null
heightmap.authoritative=false → elevation은 참고용, synthetic_elevation 사용 필요
sea adjacency 포함됨
```

검증 tolerance:

```text
border_weight sum epsilon = 0.01
direction unit length tolerance = ±0.01
```

---

## 9. debug output

권장 debug 출력:

```text
cache/debug/province_graph_build_report.json
cache/debug/province_area_histogram.csv
cache/debug/small_provinces.csv
cache/debug/coastal_provinces.csv
cache/debug/degenerate_adjacency.csv
cache/debug/water_components.csv
cache/debug/unresolved_lake_candidates.csv
```

선택 debug 이미지:

```text
cache/debug/sea_land_mask.png
cache/debug/coastal_ratio_preview.png
cache/debug/adjacency_degree_preview.png
cache/debug/latitude_band_preview.png
```

debug output은 `province_graph.json`의 schema에 포함하지 않는다.

---

## 10. 구현 TODO

예상 구현 파일:

```text
파이프라인_프로젝트/scripts/build_province_graph.py
```

권장 함수 단위:

```python
load_world_config(path)
load_provinces_image(path)
encode_rgb_to_color_id(image)
parse_default_map_water_hints(path)
load_water_mask_optional(path)
compute_province_stats(color_ids)
compute_perimeters(color_ids)
compute_shared_borders(color_ids)
compute_adjacency(province_stats, shared_borders)
resolve_sea_set_from_water_candidates(adjacency, water_hints, water_mask)
compute_coastal_fields(provinces, adjacency)
compute_latitudes(provinces, world_config, height_px)
load_heightmap_optional(path, world_config)
compute_heightmap_stats(color_ids, heightmap, world_config)
compute_topology_hash(paths, schema_version)
compute_heightmap_stats_hash(path, world_config)
validate_province_graph(graph)
atomic_write_json(graph, output_path)
```

성능 요구:

```text
8192px급 맵에서 Python 순수 픽셀 중첩 루프 금지
numpy vectorization 사용
shared border는 오른쪽/아래쪽 비교 방식으로 중복 스캔 최소화
JSON 출력은 ensure_ascii=false, compact 또는 pretty 옵션 CLI 제공
```

CLI 예시:

```bash
python scripts/build_province_graph.py \
  --provinces ../map_data/provinces.png \
  --default-map ../map_data/default.map \
  --water-mask ../map_data/water_mask.png \
  --world config/world.yaml \
  --heightmap ../map_data/heightmap.png \
  --output cache/province_graph.json
```

옵션:

```text
--no-heightmap        heightmap.png 무시
--pretty             사람이 읽기 좋은 JSON 출력
--debug              debug report/image 출력
--fail-on-warning    WARNING도 실패 처리
```

---

## 11. 금지 사항

```text
버전명을 v0.3 등으로 임의 변경 금지
province_graph_schema.v0.2와 다른 필드명 사용 금지
climate_rules.yaml 읽기 금지
province_constraints.yaml 읽기 금지
province_overrides.yaml 읽기 금지
state_constraints.yaml 읽기 금지
synthetic_elevation 생성 금지
synthetic_flow_potential 생성 금지
continentality 생성 금지
mountain_strength 자동 생성 금지
heightmap.authoritative=false인데 elevation을 기후용 고도로 취급 금지
heightmap에서 mountain barrier 자동 파생 금지
diagonal adjacency 생성 금지
sea province를 is_coastal=true로 표시 금지
border_weight를 절대 전달량처럼 해석 금지
debug output을 province_graph schema 안에 섞기 금지
```

---

## 12. 완료 기준

이 문서 기준 구현이 완료되려면:

```text
1. province_graph_schema.v0.2에 맞는 JSON을 생성한다.
2. resolved_sea_set / coastal_ratio / latitude / adjacency 검증을 통과한다.
3. heightmap.authoritative=false 상태에서 elevation이 참고용으로만 기록된다.
4. topology_hash와 heightmap_stats_hash가 분리된다.
5. bootstrap_fields 관련 값이 province_graph.json에 들어가지 않는다.
6. 58829개 province급 맵에서 실용 시간 내 생성된다.
7. debug report로 작은 province, degenerate adjacency, border_weight 이상을 확인할 수 있다.
```
