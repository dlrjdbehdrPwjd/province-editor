# province_graph_schema v0.2

> province_graph.json의 데이터 구조 정의.
> 지도 topology와 선택적 heightmap 통계를 담는 정적 캐시 파일.
> 합성 필드(synthetic_elevation, synthetic_flow_potential, continentality)는
> 이 파일에 없음 → cache/bootstrap_fields.json 참조.

---

## 1. 파일 위치 및 생성

```
위치: 파이프라인_프로젝트/cache/province_graph.json
생성: build_province_graph.py (1회 실행, 아래 조건 변경 시 재생성)
소비: 파이프라인 모든 단계, bootstrap_fields 빌더

필수 재생성 조건:
  provinces.png 변경
  default.map 변경
  world.yaml 변경

선택 재생성 조건:
  heightmap.png 변경
    단, heightmap.authoritative=false이면 elevation 통계 참고값만 갱신됨.
    기후 계산 결과를 바꾸는 입력으로 취급하지 않는다.
    bootstrap_fields는 topology_hash(provinces.png + default.map + world.yaml) 기준으로 사용.
```

---

## 2. 파일 최상위 구조

```json
{
  "schema_version": "province_graph.v0.2",
  "metadata": { ... },
  "provinces": { ... },
  "adjacency": { ... }
}
```

`schema_version`은 최상위에만 존재한다. metadata 안에 중복 금지.

---

## 3. metadata

```json
{
  "metadata": {
    "generated_at": "ISO-8601",
    "validation_status": "success",
    "source_files": {
      "provinces_png": "../map_data/provinces.png",
      "default_map": "../map_data/default.map",
      "heightmap_png": "../map_data/heightmap.png",
      "world_yaml": "config/world.yaml"
    },
    "world": {
      "width_px": 8192,
      "height_px": 3616,
      "north_latitude": 70.0,
      "south_latitude": -45.0,
      "equator_y": 2201,
      "latitude_mapping": "piecewise_equator",
      "lon_left": -180.0,
      "lon_right": 180.0,
      "wrap_x": true
    },
    "heightmap": {
      "present": true,
      "authoritative": false,
      "elevation_source": "ai_generated_placeholder"
    },
    "hash": {
      "topology_hash": "sha256:...",
      "heightmap_stats_hash": "sha256:..."
    },
    "province_count": {
      "total": "<provinces.png에서 감지한 실제 수>",
      "land": "<auto>",
      "sea": "<auto>"
    }
  }
}
```

**source_files 비고:**
```
heightmap_png: heightmap이 없으면 null. present=false이면 heightmap 관련 필드 생략 가능.
default_map: is_sea 판정에 직접 사용. is_coastal/coastal_ratio 계산의 기반 입력. topology_hash 입력에 포함.
world_yaml: `config/world.yaml`. 위도 변환 공식과 heightmap 변환 파라미터 포함.
```

**world 비고:**
```
width_px / height_px는 provinces.png에서 감지한 실제 값을 기록한다.
예시 숫자(8192 × 3616)는 고정값이 아니라 샘플이다.
north_latitude / south_latitude / equator_y는 config/world.yaml 값을 기록한다.
lat_top / lat_bottom 필드는 v0.2에서 사용하지 않는다.
province_count 예시: 현재 맵 기준 total=58829 (land/sea 비율은 default.map 판정에 따름)
```

### heightmap.authoritative 플래그

```
true:
  elevation_m / elevation_max_m 값이 신뢰 가능
  파이프라인이 실제 고도값 사용 가능
  단, authoritative=true여도 mountain_strength는 자동 파생하지 않는다.
  산맥 장벽은 province_constraints.yaml의 사용자 입력을 우선한다.

false (현재):
  AI 임시 heightmap 또는 검증되지 않은 DEM
  elevation_m / elevation_max_m은 참고용 raw 데이터
  기후 계산에 직접 사용 금지
  → synthetic_elevation (bootstrap_fields.json) 사용

present=false (heightmap 없음):
  metadata.heightmap.present = false
  mode / width_px / height_px / raw_min / raw_max = null
  elevation 필드 → null
```

### hash 분리

```
topology_hash:
  입력: schema_version + provinces.png + default.map + world.yaml
  용도: bootstrap_fields cache 유효성 판단

heightmap_stats_hash:
  입력: heightmap.png + config/world.yaml의 heightmap 변환 파라미터
       (present=true일 때만, 없으면 null)
  용도: heightmap 변경 감지 (별도 트래킹)

이유: AI 임시 heightmap이 바뀌어도 topology_hash는 유지 →
      bootstrap_fields cache가 불필요하게 무효화되지 않음.
```

---

## 4. provinces

province별 정적 데이터. topology 권위: provinces.png.

```json
{
  "provinces": {
    "xAABBCC": {
      "color_hex": "AABBCC",
      "is_sea": false,
      "is_simulation_target": true,
      "center": { "x": 1024.5, "y": 512.3 },
      "area_px": 340,
      "perimeter_px": 80,
      "bbox": { "x_min": 1000, "x_max": 1050, "y_min": 500, "y_max": 530 },
      "latitude": 42.3,
      "coastal_ratio": 0.25,
      "is_coastal": true,
      "elevation": {
        "elevation_m": 450.0,
        "elevation_max_m": 1200.0
      }
    }
  }
}
```

### elevation 케이스별 동작

```
heightmap.present=false:
  "elevation": null

heightmap.present=true, authoritative=false:
  elevation 객체 생성 (참고용)
  기후 계산 직접 사용 금지 → synthetic_elevation 사용

heightmap.present=true, authoritative=true:
  elevation 객체 생성
  기후 계산 사용 가능
  단, mountain_strength 자동 파생 금지
```

### 필드 정의

| 필드 | 타입 | 설명 |
|------|------|------|
| color_hex | string | RGB 16진수 (6자리) |
| is_sea | bool | true면 바다 province (default.map 기반) |
| is_simulation_target | bool | graph 단계 기본 시뮬 대상 (land=true, sea=false). province_overrides.exclude_from_sim과 별개. exclude_from_sim은 파이프라인 실행 단계에서 별도 적용. |
| center.x / center.y | float | province 픽셀 좌표 평균 중심 (소수점 가능) |
| area_px | int | province 픽셀 면적 |
| perimeter_px | int | province 픽셀 둘레 |
| bbox | object | 경계 사각형 (x_min, x_max, y_min, y_max) |
| latitude | float | 중심 위도 (도, 북위 +) |
| coastal_ratio | float | sea_shared_border_px / perimeter_px (0.0~1.0). is_sea=true province는 0.0 고정. |
| is_coastal | bool | land province: coastal_ratio > 0. sea province: false 고정. |
| elevation.elevation_m | float | heightmap 기반 평균 고도 (m). authoritative=false이면 기후 계산 사용 금지. |
| elevation.elevation_max_m | float | heightmap 기반 최대 고도 (m). 동일 제약. |

### 합성 필드는 여기에 없음

```
synthetic_elevation        → bootstrap_fields.json
synthetic_flow_potential   → bootstrap_fields.json
continentality             → bootstrap_fields.json
mountain_strength          → province_constraints.yaml (user authored)
```

---

## 5. adjacency (인접 관계)

### adjacency 범위

```
adjacency는 모든 province 간 4방향 공유 경계를 기록한다.
land-land, land-sea, sea-sea 모두 포함.

이유: 해안 coastal_ratio 계산, 수분 source 경계,
      향후 해류/항로 확장에 필요.

시뮬레이션 전파 단계에서 sea province를 source로만 쓰고
전파 대상에서 제외하는 것은 파이프라인 코드의 책임이며,
graph 자체는 모든 인접 정보를 보존한다.
```

```json
{
  "adjacency": {
    "xAABBCC": {
      "xBBCCDD": {
        "shared_border_px": 24,
        "border_weight": 0.30,
        "direction": { "x": 0.71, "y": 0.71 },
        "distance_px": 18.4
      },
      "xCCDDEE": {
        "shared_border_px": 12,
        "border_weight": 0.15,
        "direction": { "x": -1.0, "y": 0.0 },
        "distance_px": 22.1
      }
    }
  }
}
```

### 필드 정의

| 필드 | 타입 | 설명 |
|------|------|------|
| shared_border_px | int | A-B 공유 픽셀 경계 길이 |
| border_weight | float | shared_border_px / A.perimeter_px |
| direction.x / direction.y | float | normalize(center_B - center_A), 이미지 좌표계 |
| distance_px | float | center_A → center_B 픽셀 거리 |

### direction 퇴화 케이스

```
distance_px = 0이면 direction 벡터 정의 불가 (center가 동일한 province).
→ build 단계 WARNING으로 기록하고, 출력 adjacency에는 포함하지 않는다.
  direction = [0.0, 0.0] 금지.
  발생 원인: province가 1픽셀이거나 center 계산 오류.
```

### 방향 좌표계

```
이미지 좌표계 기준:
  x 양수 = 동쪽
  y 양수 = 남쪽 (이미지 아래 방향)

예시:
  direction = { x: 1.0, y: 0.0 } → 정동
  direction = { x: 0.0, y: 1.0 } → 정남
  direction = { x: 0.0, y: -1.0} → 정북
```

### border_weight 정의

```
border_weight = shared_border_px / A.perimeter_px

의미: A에서 B로 가는 경계가 A 전체 둘레에서 차지하는 비율
범위: 0.0~1.0
용도: moisture 전파 시 이웃 간 분배 비율 (절대 전달량 아님)

주의: 58829개 과분할 맵에서 border_weight는 개별적으로 작을 수 있음.
      transfer 공식에서 border_weight를 절대 전달량에 직접 곱하지 말 것.
      (moisture_transport_kernel_v0.2.5 참조)
```

---

## 6. v0.1 대비 변경 사항

| 항목 | v0.1 | v0.2 |
|------|------|------|
| heightmap 신뢰 여부 | 명시 없음 (항상 신뢰) | present / authoritative 플래그 추가 |
| elevation → mountain barrier 연결 | 직접 연결 (auto_strength) | 연결 제거. barrier는 user mountain_strength 전용 |
| authoritative=true 제약 | 없음 | mountain_strength 자동 파생 명시 금지 |
| synthetic 필드 위치 | 없음 | bootstrap_fields.json으로 분리 |
| schema_version | 없음 또는 중복 | 최상위 하나만 |
| elevation 필드 | 최상위 | elevation 객체 + 케이스별 null 처리 |
| hash | 없음 | topology_hash / heightmap_stats_hash 분리 |
| default.map | source_files 미포함 | 필수 입력으로 추가 |
| center 타입 | int | float (픽셀 평균) |
| adjacency 범위 | 불명확 | land/sea 모두 포함 명시 |

---

## 7. 생성 책임 분리

```
province_graph.json 생성 책임 (build_province_graph.py):
  provinces.png → topology, center(float), area, perimeter, bbox
  provinces.png + default.map → is_sea, is_coastal, coastal_ratio
  provinces.png + world.yaml → latitude
  provinces.png (4방향 스캔) → adjacency (land+sea 모두)
  heightmap.png (선택) → elevation_m, elevation_max_m (raw, 비권위 명시)

province_graph.json 생성 책임 없음 (별도 도구):
  synthetic_elevation       → build_bootstrap_fields.py
  synthetic_flow_potential  → build_bootstrap_fields.py
  continentality            → build_bootstrap_fields.py
  mountain_strength         → province_constraints.yaml (Editor)
```

---

## 8. 검증 규칙

```
[필수]
  schema_version은 최상위에만 존재. metadata 안에 중복 없을 것.
  모든 province color가 6자리 16진수 형식
  border_weight 합산 ≤ 1.0 + epsilon (epsilon=0.01)
    이유: 픽셀 스캔 및 외곽 경계 처리로 소수점 오차 발생 가능
  direction 벡터 단위 길이 (|x|² + |y|² ≈ 1.0 ± 0.01)
  direction = [0.0, 0.0] 금지 (퇴화 케이스 → adjacency 제외)
  latitude 범위: -90.0 ~ 90.0
  land province: coastal_ratio 범위 0.0~1.0, is_coastal = (coastal_ratio > 0)
  sea province: coastal_ratio = 0.0, is_coastal = false

[경고]
  elevation.elevation_m < 0 (바다 아닌 province)
  area_px < 4 (너무 작은 province, 노이즈 가능성)
  distance_px = 0 (build 단계 WARNING 기록 후 adjacency 미포함)
  province_count.land + province_count.sea ≠ province_count.total

[정보]
  heightmap.authoritative = false 상태로 생성됨
  → synthetic_elevation을 bootstrap_fields.json에서 사용할 것
```

---

## 9. 파일 크기 참고

```
58829 province, 평균 이웃 8개 기준:
  adjacency 항목: ~470,000개
  예상 파일 크기: 압축 전 ~150MB, 압축 후 ~30MB

운용 권고:
  JSON 그대로 사용 (파싱 속도 우선)
  또는 MessagePack 등 바이너리 포맷 고려 (파일 크기 우선)
  현재: JSON 기준으로 설계
```
