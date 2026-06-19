# bootstrap_fields_build_design v0.1

> `bootstrap_fields_spec_v0.1.md`의 합성 필드 3개를 실제 `bootstrap_fields.json`으로 생성하는 설계 문서.
> 이 문서는 `province_graph.json` 이후, climate/moisture/hydrology 이전에 실행된다.
> 직렬화 스키마, 입력 정규화, 해시, 저장 및 debug 동작은 이 문서를
> authoritative contract로 둔다. 필드의 물리적 의미는 `bootstrap_fields_spec_v0.1.md`를 따른다.

---

## 1. 목적

`build_bootstrap_fields.py`는 `province_graph.json`과 사용자 constraints를 입력으로 받아,
현재 비권위 heightmap 상태에서 필요한 임시 물리 필드를 생성한다.

출력 파일:

```text
파이프라인_프로젝트/cache/bootstrap_fields.json
```

생성 필드:

```text
synthetic_elevation_m
synthetic_flow_potential
continentality
coast_distance_normalized
is_flow_sink
```

핵심 원칙:

```text
province_graph.json은 topology cache
bootstrap_fields.json은 synthetic physical fields cache

province_graph.json에 bootstrap 필드를 끼워 넣지 않는다.
```

---

## 2. 입력

필수 입력:

```text
파이프라인_프로젝트/cache/province_graph.json
merged 또는 작업 대상 province_constraints.yaml
bootstrap 파라미터 파일
```

주의:

```text
province_constraints.yaml 위치는 CLI 인자로 받는다.
프로빈스_프로젝트/config/ 같은 고정 경로를 전제하지 않는다.

입력 YAML은 다음 중 하나일 수 있다.
  - Editor Export ZIP에서 꺼낸 province_constraints.yaml
  - multi-user merge 결과 revisions/{revision_dir_name}/province_constraints.yaml
  - 단일 작업용 임시 province_constraints.yaml
```

bootstrap 파라미터 파일은 구현 위치에 따라 다음 중 하나로 둘 수 있다.

```text
파이프라인_프로젝트/config/climate_rules.yaml 의 bootstrap_fields 섹션
또는
파이프라인_프로젝트/config/bootstrap_fields.yaml
```

v0.1 기본값:

```yaml
bootstrap_fields:
  mountain_average_elevation_m: 1500
  mountain_flow_bonus: 0.5
  max_coast_distance_hops: auto
```

v0.1에서 읽지 않는 입력:

```text
state_constraints.yaml
```

이유:

```text
Province Editor State Mode는 하위 province의 province_constraints에 직접 기록한다.
따라서 bootstrap_fields_build v0.1은 state_constraints를 읽지 않는다.
외부 state_constraints 저작 도구 연동은 별도 spec에서 필드별 merge_rule을 확정한 뒤 추가한다.
```

읽지 말아야 하는 파일:

```text
province_overrides.yaml
state_constraints.yaml
project_state.json
export_manifest.json
heightmap.png
moisture 결과물
hydrology 결과물
biome / terrain 결과물
```

금지 이유:

```text
bootstrap_fields는 원인값 기반 임시 물리장이다.
override, UI 상태, 후속 시뮬레이션 결과를 읽으면 캐시 책임이 섞인다.
```

---

## 3. 출력

출력 파일:

```text
파이프라인_프로젝트/cache/bootstrap_fields.json
```

최상위 구조:

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
    }
  }
}
```

`state_constraints.yaml`은 v0.1에서 읽지 않으므로 `source_constraints`에도 기록하지 않는다.

v0.1 출력에는 별도 `metadata`나 `validation` 블록을 넣지 않는다. 빌더는 전체
검증을 통과한 결과만 원자적으로 저장하며, 상세 validation status와 warning은
`cache/debug/bootstrap_fields_build_report.json`에 기록한다. 오케스트레이터는
이 스키마에 존재하지 않는 validation 필드를 요구하지 않고 stage validator를 실행한다.

출력 대상:

```text
province_graph.provinces의 모든 is_sea=false province
```

주의:

```text
province_graph.v0.2에는 is_lake 필드가 없다.
is_sea=false가 완전한 육지 확정을 뜻하지 않을 수 있다.
이 빌더는 lake/inland water를 graph에서 추론하지 않는다.
lake_seed=true인 사용자 입력만 is_flow_sink로 처리한다.
```

sea province 처리:

```text
is_sea=true province는 bootstrap_fields.provinces에 넣지 않는다.
해안거리 BFS의 경계로만 사용한다.
```

v0.1 land_targets 정의:

```text
land_targets = province_graph.provinces 중 is_sea=false province

단, 이 집합은 "확정된 육지"만을 뜻하지 않는다.
province_graph.v0.2에는 is_lake가 없으므로 lake/inland water 후보가 포함될 수 있다.
bootstrap 단계는 lake 후보를 자동 제외하지 않는다.
lake_seed=true만 flow sink로 처리하며,
실제 inland water 제외/처리는 hydrology_spec_v0.5.md에서 담당한다.
```

---

## 4. 처리 순서

전체 순서:

```text
1. province_graph.json 로드 및 schema/hash 확인
2. province_constraints.yaml 로드
3. bootstrap 파라미터 로드
4. constraints 정규화 및 기본값 보정
5. v0.1 land_targets 구성 (is_sea=false)
6. coast_distance 계산
7. coast_distance_normalized 계산
8. synthetic_elevation_m 계산
9. synthetic_flow_potential 계산
10. lake_seed 기반 is_flow_sink 계산
11. continentality 계산
12. constraints_hash / params_hash 계산
13. validation
14. bootstrap_fields.json 원자적 저장
15. debug output 저장
```

---

## 5. 핵심 알고리즘

### 5-1. constraints 기본값

province별 constraints 기본값:

```yaml
mountain_strength: 0.0
elevation_hint: none
lake_seed: false
```

사용하지 않는 필드:

```text
river_seed
river_major
river_path
wetland_seed
moisture_bonus
temperature_delta
rainfall_delta
fantasy_zone
```

이 필드들은 hydrology/climate/moisture/biome 단계에서 소비한다.
bootstrap_fields_build 단계에서 소비하지 않는다.

---

### 5-2. coast_distance 계산

coast_distance는 land-only multi-source BFS로 계산한다.

시작점:

```text
province_graph.provinces[color].is_coastal = true
AND
province_graph.provinces[color].is_sea = false
```

전파 대상:

```text
province_graph.provinces[color].is_sea = false
```

전파 edge:

```text
adjacency의 이웃 중 is_sea=false인 province로만 이동
```

sea province는 BFS node가 아니다.

```text
sea province:
  coast_distance 계산 대상 제외
  bootstrap_fields.provinces 출력 제외
```

거리 정의:

```text
coast_distance_hops = 가장 가까운 coastal land province까지의 graph hop 수
coastal land province = 0
```

정규화:

```text
if max_coast_distance_hops = auto:
  max_hop = max(coast_distance_hops over reachable land)
else:
  max_hop = configured max_coast_distance_hops

coast_distance_normalized = clamp(coast_distance_hops / max_hop, 0.0, 1.0)
```

검증:

```text
coastal land province가 0개면 ERROR
max_hop = 0이면 모든 land province가 coastal이라는 뜻이므로 normalized=0.0 허용
도달 불가능 land province는 WARNING 후 coast_distance_normalized=1.0
```

주의:

```text
continentality와 synthetic_flow_potential은 같은 coast_distance_normalized를 공유한다.
별도 해안거리 계산을 중복 구현하지 않는다.
```

---

### 5-3. synthetic_elevation_m 계산

source 선택:

```text
heightmap.authoritative=false
→ synthetic_elevation_m을 constraints 기반으로 생성

heightmap.authoritative=true
→ 옵션 지원 시 province_graph.provinces[color].elevation.elevation_m을 synthetic_elevation_m 대체값으로 사용 가능
```

비권위 heightmap 경로의 계산식:

```text
mountain_component = mountain_strength × mountain_average_elevation_m
hint_component = elevation_hint_elevation_m[elevation_hint]

synthetic_elevation_m = max(mountain_component, hint_component)
```

기본 매핑:

```text
none:          0m
lowland:     100m
upland:      500m
highland:   1200m
mountain:   2000m
```

기본 파라미터:

```text
mountain_average_elevation_m = 1500
```

중요:

```text
mountain_strength를 기온 감률에 직접 넣지 않는다.
반드시 synthetic_elevation_m 공식 안에서만 사용한다.

mountain_strength와 elevation_hint를 add하지 않는다.
max만 사용한다.
```

authoritative heightmap 업그레이드 경로:

```text
province_graph.metadata.heightmap.authoritative=true이고
province.elevation.elevation_m이 존재하면,
real elevation_m을 synthetic_elevation_m 대체값으로 사용할 수 있다.

단, authoritative=true여도 mountain_strength는 자동 파생하지 않는다.
mountain_strength는 계속 user-authored barrier 강도다.
```

v0.1 기본 운용:

```text
현재 프로젝트 기본값은 heightmap.authoritative=false다.
따라서 기본 실행에서는 constraints 기반 synthetic_elevation_m을 사용한다.
authoritative=true 지원은 옵션이다.
지원할 경우 graph_hash에 heightmap_stats_hash를 포함한다.
```

---

### 5-4. synthetic_flow_potential 계산

계산식:

```text
synthetic_flow_potential =
  coast_distance_normalized
  + mountain_strength × mountain_flow_bonus
  + elevation_hint_flow_bonus[elevation_hint]
```

기본 매핑:

```text
none:       0.00
lowland:    0.05
upland:     0.15
highland:   0.35
mountain:   0.60
```

기본 파라미터:

```text
mountain_flow_bonus = 0.5
```

기본 범위:

```text
min = 0.0
max = 1.0 + 0.5 + 0.60 = 2.10
```

의미:

```text
값이 낮은 방향으로 물이 흐르는 임시 potential.
해안에 가까울수록 낮고, 산맥/고지 힌트가 있을수록 높다.
```

주의:

```text
synthetic_flow_potential은 실제 DEM flow direction이 아니다.
hydrology_spec_v0.5 확정 전 임시 흐름장이다.
향후 hydrology 단계에서 river_path가 확정되면, hydrology는 river_path를
synthetic_flow_potential보다 우선할 수 있다.
이 빌더는 river_path를 읽지 않는다.
```

---

### 5-5. lake_seed / is_flow_sink 처리

`lake_seed=true` province는 flow sink 후보로 표시한다.

```text
is_flow_sink = lake_seed
```

v0.1 정책:

```text
is_flow_sink 플래그만 저장한다.
synthetic_flow_potential 값은 낮추지 않는다.
```

이유:

```text
bootstrap_fields_build는 필드 생성 단계다.
실제 강 라우팅과 flow sink 적용은 hydrology_spec_v0.5.md 책임이다.
이 단계에서 potential을 직접 낮추면 coast_distance 기반 흐름장이 과도하게 찢길 수 있다.
```

주의:

```text
province_graph의 unresolved lake 후보를 is_flow_sink로 자동 변환하지 않는다.
오직 province_constraints.yaml의 lake_seed=true만 사용한다.
is_flow_sink는 hydrology용 hint이며 continentality/coast_distance를 바꾸지 않는다.
```

한계:

```text
lake_seed가 너무 많으면 hydrology 단계에서 흐름장이 과도하게 쪼개질 수 있다.
v0.1은 개수 제한을 적용하지 않고 debug report에 lake_seed 개수만 기록한다.
경고 기준은 hydrology_spec_v0.5.md에서 확정한다.
```

river 관련 충돌:

```text
bootstrap_fields_build v0.1은 river_seed / river_major / river_path를 읽지 않는다.
lake_seed와 river 관련 입력의 충돌은 hydrology_spec_v0.5.md에서 처리한다.
```

---

### 5-6. continentality 계산

계산식:

```text
continentality = coast_distance_normalized
```

담당:

```text
계절 기온 진폭
```

비담당:

```text
습도 감쇠
수분 전파 차단
강수량 직접 보정
연평균 기온 보정
```

중요:

```text
continentality를 moisture multiplier로 사용하지 않는다.
내륙 건조화는 moisture propagation과 pressure/seasonal climate 단계에서 처리한다.
```

계절 기온 공식은 이 빌더에서 계산하지 않는다.
이 빌더는 `continentality` 값만 저장하고, 적용은 `seasonal_climate_spec_v0.4.md`에서 정의한다.

---

## 6. override / constraints 적용 시점

이 단계에서 읽는 constraints:

```text
mountain_strength
elevation_hint
lake_seed
```

실제로 계산에 쓰는 필드:

```text
mountain_strength
elevation_hint
lake_seed
```

읽지 않는 constraints:

```text
river_seed
river_major
river_path
wetland_seed
moisture_bonus
temperature_delta
rainfall_delta
fantasy_zone
```

주의:

```text
bootstrap_fields_build는 river_seed / river_major / river_path / wetland_seed를
보존하거나 출력하지 않는다.
또한 출력에 영향이 없으므로 constraints_hash에도 포함하지 않는다.
```

읽지 않는 override:

```text
locked
force_terrain
force_biome
climate_lock
force_temp
force_moisture
force_rainfall
exclude_from_sim
```

이유:

```text
bootstrap_fields는 physical baseline cache다.
locked/climate_lock/exclude_from_sim은 pipeline 실행 단계에서 적용한다.
```

`exclude_from_sim` 주의:

```text
이 빌더는 province_overrides.yaml을 읽지 않으므로 exclude_from_sim을 반영하지 않는다.
exclude_from_sim province의 bootstrap field가 존재할 수 있지만,
실제 사용 여부는 pipeline 실행 단계 책임이다.
```

`state_constraints.yaml` 주의:

```text
v0.1에서는 state_constraints.yaml을 읽지 않는다.
province와 state가 같은 필드를 가질 때의 merge_rule이 아직 이 문서 범위에 없기 때문이다.
외부 state_constraints 저작 도구 연동은 별도 문서에서 확정한다.
```

---

## 7. 캐시 / 해시

`bootstrap_fields.json`에는 3개 hash를 기록한다.

```text
graph_hash
constraints_hash
params_hash
```

### graph_hash

값:

```text
heightmap.authoritative=false:
  province_graph.metadata.hash.topology_hash

heightmap.authoritative=true:
  canonical JSON {
    "heightmap_stats_hash": province_graph.metadata.hash.heightmap_stats_hash,
    "topology_hash": province_graph.metadata.hash.topology_hash
  }의 sha256
```

용도:

```text
province_graph topology가 바뀌면 bootstrap_fields cache 무효화
authoritative=true에서 real elevation을 사용하는 경우 heightmap stats 변경도 cache 무효화
```

주의:

```text
heightmap.authoritative=false 상태에서 heightmap 변경은 bootstrap_fields 재생성 이유가 아니다.
heightmap.authoritative=true 상태에서 heightmap_stats_hash가 없으면 ERROR.
```

### constraints_hash

입력:

```text
province_constraints.yaml의 bootstrap 관련 논리 데이터
```

포함 필드:

```text
mountain_strength
elevation_hint
lake_seed
```

제외 필드:

```text
river_seed
river_major
river_path
wetland_seed
moisture_bonus
temperature_delta
rainfall_delta
fantasy_zone
```

정규화:

```text
대상은 graph의 is_sea=false land_targets
graph에 없는 입력 color는 WARNING 후 hash 입력에서 제외
모든 land target에 mountain_strength / elevation_hint / lake_seed 3개 필드를 기록
누락 및 null은 각각 0.0 / none / false 기본값으로 정규화
province key와 필드 key를 알파벳 순으로 정렬한 canonical JSON 사용
배열 필드는 v0.1 constraints_hash 입력에 없음
```

### params_hash

입력:

```text
mountain_average_elevation_m
mountain_flow_bonus
max_coast_distance_hops
elevation_hint_elevation_m mapping
elevation_hint_flow_bonus mapping
```

파라미터가 바뀌면 bootstrap_fields는 재생성되어야 한다.

---

## 8. 검증 규칙

### ERROR

```text
province_graph.json 없음
province_graph.schema_version != province_graph.v0.2
province_graph.metadata.hash.topology_hash 없음
heightmap.authoritative=true인데 heightmap_stats_hash 없음
heightmap.authoritative=true인데 province.elevation.elevation_m 없음
province_constraints.yaml 파싱 실패
bootstrap 파라미터 파싱 실패
coastal land province가 0개
mountain_strength가 0.0~1.0 범위 밖
elevation_hint가 허용 목록 밖
synthetic_elevation_m < 0
continentality가 0.0~1.0 범위 밖
coast_distance_normalized가 0.0~1.0 범위 밖
```

### WARNING

```text
province_constraints에 graph에 없는 province color 존재
graph에 있는 province가 constraints에 없음 → 기본값 사용
is_sea=false province 중 coast BFS 도달 불가 → coast_distance_normalized=1.0
synthetic_flow_potential이 예상 범위 0.0~2.10을 벗어남
```

### INFO

```text
heightmap.authoritative=false → constraints 기반 synthetic_elevation 사용
state_constraints.yaml 미사용 → province_constraints만 사용
river_seed / river_major / river_path / wetland_seed는 이 단계에서 읽지 않음
sea province는 bootstrap_fields.provinces 출력에서 제외
```

---

## 9. debug output

권장 debug 출력:

```text
cache/debug/bootstrap_fields_build_report.json
cache/debug/coast_distance.csv
cache/debug/unreachable_land_provinces.csv
cache/debug/flow_sinks.csv
cache/debug/bootstrap_warnings.csv
```

선택 debug 이미지:

```text
cache/debug/coast_distance_preview.png
cache/debug/synthetic_elevation_preview.png
cache/debug/synthetic_flow_potential_preview.png
cache/debug/continentality_preview.png
cache/debug/flow_sink_preview.png
```

debug output은 `bootstrap_fields.json` schema 안에 넣지 않는다.

---

## 10. 구현 TODO

예상 구현 파일:

```text
파이프라인_프로젝트/scripts/build_bootstrap_fields.py
```

권장 함수 단위:

```python
load_province_graph(path)
validate_province_graph_for_bootstrap(graph)
load_province_constraints(path)
load_bootstrap_params(path)
normalize_constraints(constraints, graph)
build_land_targets(graph)
compute_coast_distance(graph, land_targets)
normalize_coast_distance(coast_distance, params)
compute_synthetic_elevation(constraints, params, graph)
compute_synthetic_flow_potential(coast_distance_norm, constraints, params)
compute_is_flow_sink(constraints)
compute_continentality(coast_distance_norm)
compute_constraints_hash(constraints)
compute_params_hash(params)
validate_bootstrap_fields(fields)
atomic_write_json(fields, output_path)
write_debug_outputs(fields, diagnostics)
```

CLI 예시:

```bash
python scripts/build_bootstrap_fields.py \
  --province-graph cache/province_graph.json \
  --province-constraints path/to/province_constraints.yaml \
  --params config/climate_rules.yaml \
  --output cache/bootstrap_fields.json
```

옵션:

```text
--pretty                   사람이 읽기 좋은 JSON 출력
--debug                    debug report/image 출력
--fail-on-warning          WARNING도 실패 처리
```

---

## 11. 금지 사항

```text
버전명을 v0.2 등으로 임의 변경 금지
province_graph.json에 bootstrap 필드 쓰기 금지
heightmap.png 직접 읽기 금지
heightmap.authoritative=false인데 province.elevation을 기후용 고도로 사용 금지
mountain_strength에서 mountain barrier 자동 계산 금지
mountain_strength를 synthetic_elevation 공식 밖에서 lapse rate에 직접 사용 금지
mountain_strength와 elevation_hint를 add해서 고도 과증폭 금지
continentality를 습도 감쇠에 사용 금지
province_overrides.yaml 읽기 금지
state_constraints.yaml 읽기 금지
locked / climate_lock / exclude_from_sim 적용 금지
graph debug의 unresolved lake 후보를 is_flow_sink로 자동 변환 금지
sea province를 bootstrap_fields.provinces에 출력 금지
debug output을 bootstrap_fields.json schema 안에 섞기 금지
```

---

## 12. 완료 기준

이 문서 기준 구현이 완료되려면:

```text
1. bootstrap_fields_spec.v0.1에 맞는 JSON을 생성한다.
2. graph_hash / constraints_hash / params_hash를 기록한다.
3. coast_distance_normalized가 land-only BFS로 계산된다.
4. synthetic_elevation_m이 max(mountain_strength × 1500m, elevation_hint) 원칙을 따른다.
5. synthetic_flow_potential이 coast_distance + mountain + hint 조합으로 계산된다.
6. continentality가 coast_distance_normalized와 동일하게 저장된다.
7. lake_seed=true province만 is_flow_sink=true가 된다.
8. province_graph.json에는 어떤 bootstrap 필드도 쓰지 않는다.
9. heightmap.authoritative=false 상태에서 heightmap raw elevation을 사용하지 않는다.
10. debug report로 unreachable land, lake_seed 기반 is_flow_sink 후보, 범위 이상을 확인할 수 있다.
```
