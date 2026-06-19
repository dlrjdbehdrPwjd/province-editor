# pipeline_orchestration_spec v0.1

> 기후·지형 생성 파이프라인의 실행 순서, 입력 계약, 캐시 재사용, 해시 검증,
> 실패 시 중단 정책을 정의하는 오케스트레이션 문서.
>
> 이 문서는 개별 알고리즘을 다시 정의하지 않는다.
> 각 단계의 세부 계산은 해당 단계 spec을 authoritative로 둔다.

---

## 0. 이 문서의 범위

포함:

```text
전체 실행 DAG
공통 입력 경로 계약
단계별 입력 / 출력 연결
캐시 hit / miss 판정
해시 검증
스키마 검증
실패 시 중단 정책
원자적 저장 정책
run manifest 출력
debug artifact 수집
CLI 실행 모드
```

포함하지 않음:

```text
province_graph 생성 세부 알고리즘       → build_province_graph_design_v0.2
bootstrap synthetic field 계산          → bootstrap_fields_build_design_v0.1
moisture transport 세부 커널             → moisture_transport_kernel_v0.2.5
mountain barrier 세부 계산               → mountain_barrier_pseudocode_v0.3
seasonal climate / spin-up               → seasonal_climate_spec_v0.4
hydrology / river / lake 생성            → hydrology_spec_v0.5
rainfall normalization                   → rainfall_normalization_spec_v0.6
Koppen / biome / terrain 판정            → koppen_biome_terrain_spec_v0.7
golden test 기준                         → validation_and_golden_tests_spec_v0.1
Province Editor export/merge 의미        → province_editor_spec / multi_user_export_merge_spec
```

---

## 1. 핵심 설계 원칙

```text
1. 각 단계는 자기 입력만 읽는다.
2. downstream 단계가 upstream 입력 파일을 몰래 재해석하지 않는다.
3. 캐시는 schema_version + input hash + params hash가 일치할 때만 재사용한다.
4. hash 불일치 캐시는 silent reuse 금지.
5. 실패한 단계 이후 downstream 단계는 실행하지 않는다.
6. 출력 파일은 원자적으로 저장한다.
7. run manifest는 모든 실행/스킵/실패 사유를 기록한다.
```

오케스트레이터의 책임:

```text
실행 순서 결정
입력 파일 위치 전달
캐시 유효성 검사
단계 실행/스킵 판단
실패 전파
공통 manifest 생성
```

오케스트레이터의 책임이 아닌 것:

```text
각 단계 내부 물리 계산
override 의미 재해석
province/state edit merge
terrain lookup 내용 보정
golden test 판정
```

---

## 2. 전체 실행 DAG

기본 실행 순서:

```text
[STEP 0] build_province_graph
    ↓
[STEP 1] build_bootstrap_fields
    ↓
[STEP 2] seasonal_climate
    └─ 내부 호출: moisture_transport_kernel_v0.2.5 + mountain_barrier_v0.3
    ↓
[STEP 3] hydrology
    ↓
[STEP 4] rainfall_normalization
    ↓
[STEP 5] koppen_biome_terrain
```

stage 경계:

```text
moisture_transport_kernel_v0.2.5와 mountain_barrier_v0.3은 독립 stage가 아니다.
두 문서는 seasonal_climate stage 내부에서 호출되는 kernel 계약이다.

오케스트레이터는 별도 cache/province_moisture.json을 stage output으로 요구하지 않는다.
province_moisture.json이 존재하더라도 debug/비교용으로만 취급한다.
```

출력 연결:

```text
province_graph.json
  → bootstrap_fields
  → seasonal_climate
  → hydrology
  → rainfall_normalization
  → koppen_biome_terrain

bootstrap_fields.json
  → seasonal_climate
  → hydrology
  → koppen_biome_terrain

seasonal_climate.json
  → hydrology
  → rainfall_normalization
  → koppen_biome_terrain

hydrology.json
  → rainfall_normalization
  → koppen_biome_terrain

rainfall_normalized.json
  → koppen_biome_terrain
```

금지:

```text
koppen_biome_terrain이 annual_rainfall_raw를 직접 사용 금지
rainfall_normalization이 province_overrides.yaml 재해석 금지
hydrology가 rivers.png를 입력으로 사용 금지
seasonal_climate가 final_rainfall을 입력으로 사용 금지
bootstrap_fields가 province_overrides.yaml을 읽는 것 금지
province_graph가 constraints / climate_rules를 읽는 것 금지
```

---

## 3. 공통 입력 계약

### 3-1. 지도 원본 입력

필수:

```text
map_data/provinces.png
map_data/default.map
config/world.yaml
```

선택:

```text
map_data/heightmap.png
map_data/water_mask.png
```

`world.yaml`은 지도 이미지 원본이 아니라 파이프라인 설정 파일이다.
운영 위치는 `config/world.yaml`로 고정한다.
구문서의 지도 원본 하위 world 위치 표현은 v0.1 기준 잔재로 취급한다.

주의:

```text
heightmap.png는 현재 heightmap.authoritative=false 경로에서 참고 통계용이다.
mountain_strength 자동 생성에 사용하지 않는다.
```

### 3-2. 사용자 원인값 / override 입력

필수:

```text
province_constraints.yaml
province_overrides.yaml
```

보존 대상:

```text
state_constraints.yaml
```

v0.1 파이프라인 처리:

```text
state_constraints.yaml은 현재 실행 단계에서 읽지 않는다.
pipeline CLI 입력으로 받지 않는다.
Province Editor State Mode는 하위 province_constraints에 직접 기록한다.
외부 state_constraints 저작 도구 연동은 별도 merge/spec 이후 추가한다.
```

입력 위치:

```text
province_constraints.yaml / province_overrides.yaml 위치는 CLI 인자로 받는다.
프로빈스_프로젝트/config 같은 고정 경로를 전제하지 않는다.
```

허용 입력 예:

```text
Editor Export ZIP에서 꺼낸 YAML
multi-user merge 결과 revisions/{revision_dir_name}/ YAML
단일 작업용 임시 YAML
```

읽지 말아야 하는 파일:

```text
project_state.json
export_manifest.json
```

이유:

```text
project_state.json은 UI 복원용이다.
export_manifest.json은 Editor export/merge 추적용이다.
기후·지형 파이프라인의 물리 입력이 아니다.
```

### 3-3. 규칙 입력

필수:

```text
climate_rules.yaml
terrain_lookup.csv
```

`climate_rules.yaml` 사용 섹션:

```text
bootstrap_fields
seasonal_climate
moisture_transport
mountain_barrier
hydrology
rainfall_normalization
koppen_biome_terrain
```

주의:

```text
각 단계는 자기 섹션만 params_hash에 포함한다.
다른 단계 섹션 변경 때문에 불필요하게 모든 캐시를 무효화하지 않는다.
```

---

## 4. 표준 경로

기본 cache 출력:

```text
cache/province_graph.json
cache/bootstrap_fields.json
cache/seasonal_climate.json
cache/hydrology.json
cache/rainfall_normalized.json
cache/koppen_biome_terrain.json
```

debug 출력:

```text
cache/debug/
outputs/debug/
```

선택 출력:

```text
outputs/draft_rivers.png
```

run manifest:

```text
cache/pipeline_run_manifest.json
```

run lock:

```text
cache/.pipeline_run.lock
```

주의:

```text
pipeline_run_manifest.json은 Editor export_manifest.json과 다른 파일이다.
export_manifest.json을 수정하거나 대체하지 않는다.
```

동시 실행 정책:

```text
같은 cache-dir에 대해 동시에 두 pipeline run을 실행하지 않는다.
실행 시작 시 cache/.pipeline_run.lock을 생성한다.
lock이 이미 존재하면 FATAL 또는 --allow-stale-lock-cleanup 옵션으로만 정리한다.
정상 종료 또는 실패 처리 후 lock을 제거한다.
```

---

## 5. 단계별 실행 계약

### STEP 0 — build_province_graph

spec:

```text
build_province_graph_design_v0.2.md
province_graph_schema_v0.2.md
```

입력:

```text
map_data/provinces.png
map_data/default.map
config/world.yaml
optional map_data/heightmap.png
optional map_data/water_mask.png
```

출력:

```text
cache/province_graph.json
```

rerun 조건:

```text
province_graph.json 없음
schema_version 불일치
topology_hash 불일치
--force-stage build_province_graph
--force-all
```

heightmap hash 정책:

```text
v0.1 기본 경로에서는 topology_hash를 graph cache 핵심 기준으로 사용한다.
heightmap.authoritative=false이면 heightmap_stats_hash는 metadata 참고값이며
downstream cache invalidation 기준이 아니다.

authoritative=false:
  heightmap_stats_hash 불일치 → build_province_graph rerun 가능/권장.
  단 topology_hash가 같으면 downstream stage의 graph_hash invalidation 기준에는 포함하지 않는다.

heightmap.authoritative=true가 도입되면:
  heightmap_stats_hash 불일치 → graph rerun
  bootstrap/seasonal downstream cache도 무효화 가능
```

FATAL:

```text
필수 지도 원본 누락
water 후보 없이 sea_starts만 존재하여 sea 확정 불가
province color 파싱 실패
adjacency 생성 실패
schema validation 실패
```

### STEP 1 — build_bootstrap_fields

spec:

```text
bootstrap_fields_build_design_v0.1.md
bootstrap_fields_spec_v0.1.md
```

입력:

```text
cache/province_graph.json
province_constraints.yaml
climate_rules.yaml bootstrap_fields 섹션
```

출력:

```text
cache/bootstrap_fields.json
```

rerun 조건:

```text
bootstrap_fields.json 없음
schema_version 불일치
graph_hash 불일치
constraints_hash 불일치
params_hash 불일치
--force-stage build_bootstrap_fields
--force-all
```

FATAL:

```text
province_graph.json 없음 또는 invalid
province_constraints.yaml 파싱 실패
stage runner가 state_constraints.yaml을 필수 입력으로 요구함
schema validation 실패
```

constraints_hash 입력:

```text
mountain_strength
elevation_hint
lake_seed
```

### STEP 2 — seasonal_climate

spec:

```text
seasonal_climate_spec_v0.4.1.md
moisture_transport_kernel_v0.2.6.md
mountain_barrier_pseudocode_v0.3.md
override_semantics_spec_v0.2.md
```

입력:

```text
cache/province_graph.json
cache/bootstrap_fields.json
province_constraints.yaml
province_overrides.yaml
climate_rules.yaml seasonal_climate / moisture_transport / mountain_barrier 섹션
```

출력:

```text
cache/seasonal_climate.json
```

실행 책임:

```text
summer/winter pass 실행
annual spin-up 실행
force_temp / force_moisture / force_rainfall 적용 시점 보장
ET / runoff / soil_water_storage_final raw 결과 생성
```

rerun 조건:

```text
seasonal_climate.json 없음
schema_version 불일치
graph_hash 불일치
bootstrap_hash 불일치
constraints_hash 불일치
overrides_hash 불일치
params_hash 불일치
--force-stage seasonal_climate
--force-all
```

FATAL:

```text
moisture iteration 발산
annual spin-up 수렴 실패가 허용 횟수 초과
NaN / Infinity 발생
schema validation 실패
```

주의:

```text
force_rainfall은 각 연도·각 계절 moisture propagation 완료 후 1회 적용.
orchestrator가 force_rainfall을 직접 적용하지 않는다.
seasonal_climate 단계 내부 책임이다.

전체 실맵 진단에서 느린 soil_water_storage 축적 때문에 기본 20년 제한을
초과한 경우 --max-spinup-years N 진단 override를 허용한다.
effective N은 params_hash에 포함하며, 진단 출력은 *.test.json 사용을 권장한다.
연장된 N 안에서도 미수렴이면 FATAL 정책은 유지한다.
```

params_hash 입력:

```text
seasonal_climate
moisture_transport
mountain_barrier
```

overrides_hash 입력:

```text
climate_lock
force_temp
force_moisture
force_rainfall
exclude_from_sim
```

constraints_hash 입력:

```text
temperature_delta
moisture_bonus
wetland_seed
mountain_strength
```

### STEP 3 — hydrology

spec:

```text
hydrology_spec_v0.5.md
override_semantics_spec_v0.2.md
```

입력:

```text
cache/seasonal_climate.json
cache/bootstrap_fields.json
cache/province_graph.json
province_constraints.yaml
province_overrides.yaml
climate_rules.yaml hydrology 섹션
```

출력:

```text
cache/hydrology.json
optional outputs/draft_rivers.png
```

rerun 조건:

```text
hydrology.json 없음
schema_version 불일치
seasonal_hash 불일치
bootstrap_hash 불일치
graph_hash 불일치
constraints_hash 불일치
overrides_hash 불일치
params_hash 불일치
--force-stage hydrology
--force-all
```

FATAL:

```text
river_path cycle
flow graph topological sort 실패
필수 upstream cache 누락
schema validation 실패
```

주의:

```text
exclude_from_sim=true는 local_runoff=0인 통과 노드다.
orchestrator가 exclude_from_sim province를 graph에서 제거하면 안 된다.
```

overrides_hash 입력:

```text
exclude_from_sim
force_terrain
locked
```

constraints_hash 입력:

```text
river_seed
river_major
river_path
lake_seed
wetland_seed
```

### STEP 4 — rainfall_normalization

spec:

```text
rainfall_normalization_spec_v0.6.md
```

입력:

```text
cache/seasonal_climate.json
cache/hydrology.json
cache/province_graph.json
climate_rules.yaml rainfall_normalization 섹션
```

출력:

```text
cache/rainfall_normalized.json
```

rerun 조건:

```text
rainfall_normalized.json 없음
schema_version 불일치
seasonal_hash 불일치
hydrology_hash 불일치
graph_hash 불일치
params_hash 불일치
--force-stage rainfall_normalization
--force-all
```

FATAL:

```text
hydrology.json 누락
corrected_ET / river_bonus / lake_fraction 누락
final_summer_rainfall + final_winter_rainfall 보존 실패
schema validation 실패
```

overrides_hash:

```text
없음.
rainfall_normalization 단계는 province_overrides.yaml을 읽지 않으므로
overrides_hash를 계산하지 않는다.
province_overrides.yaml 변경은 rainfall_normalization cache를 무효화하지 않는다.
```

주의:

```text
rainfall_normalization은 province_overrides.yaml을 읽지 않는다.
force_rainfall은 v0.4 raw 결과에 이미 반영되어 있어야 한다.
```

### STEP 5 — koppen_biome_terrain

spec:

```text
koppen_biome_terrain_spec_v0.7.md
override_semantics_spec_v0.2.md
```

입력:

```text
cache/rainfall_normalized.json
cache/seasonal_climate.json
cache/hydrology.json
cache/bootstrap_fields.json
cache/province_graph.json
province_constraints.yaml
province_overrides.yaml
climate_rules.yaml koppen_biome_terrain 섹션
terrain_lookup.csv
```

출력:

```text
cache/koppen_biome_terrain.json
```

rerun 조건:

```text
koppen_biome_terrain.json 없음
schema_version 불일치
rainfall_normalized_hash 불일치
seasonal_hash 불일치
hydrology_hash 불일치
bootstrap_hash 불일치
graph_hash 불일치
constraints_hash 불일치
overrides_hash 불일치
terrain_lookup_hash 불일치
params_hash 불일치
--force-stage koppen_biome_terrain
--force-all
```

FATAL:

```text
terrain_lookup.csv 미매칭
terrain_lookup.csv 중복 매칭
Koppen-lite class 미분류
hydrology pass-through 불일치
schema validation 실패
```

overrides_hash 입력:

```text
locked
force_biome
force_terrain
exclude_from_sim
```

constraints_hash 입력:

```text
fantasy_zone
```

---

## 6. 캐시 hit / miss 판정

캐시 재사용 가능 조건:

```text
1. 출력 파일 존재
2. schema_version 일치
3. 모든 source hash 일치
4. params_hash 일치
5. 현재 stage의 output validator 통과
6. 해당 output schema가 validation status를 정의하면 status = success
7. --force 옵션 없음
```

validation_status 위치:

```text
validation status의 내장 여부와 위치는 각 stage output schema가 결정한다.
오케스트레이터가 모든 출력에 공통 필드를 임의로 강제하지 않는다.

province_graph.v0.2:
  metadata.validation_status 사용

bootstrap_fields.v0.1:
  내장 validation status 없음
  stage validator 통과 + schema/hash 일치로 판정
  상세 상태는 cache/debug/bootstrap_fields_build_report.json에 기록

예:
  "validation": {
    "status": "success",
    "validated_at": "...",
    "warnings": 0
  }
```

주의:

```text
pipeline_run_manifest.json은 참고 로그다.
cache hit의 유일 근거로 사용하지 않는다.
manifest에 기록이 없더라도 output 자체 metadata가 유효하면 cache hit 가능.
```

하나라도 실패하면:

```text
cache miss → 해당 단계 재실행
```

validation status 처리:

```text
schema가 validation status를 요구하는데 누락되면 cache miss다.
schema가 validation status를 정의하지 않으면 누락 자체는 오류가 아니다.
이 경우 stage별 output validator가 실패하면 일반 실행은 cache miss,
--validate-only는 ERROR와 nonzero exit code를 반환한다.
```

hash mismatch 정책:

```text
hash 불일치 캐시를 fallback으로 사용 금지.
캐시가 존재하더라도 stale로 표시하고 재실행한다.
```

upstream 재실행 전파:

```text
어떤 단계가 재실행되어 출력 hash가 바뀌면,
그 downstream 단계는 모두 hash mismatch로 재실행 대상이 된다.
```

---

## 7. 실패 정책

### 7-1. FATAL

FATAL 발생 시:

```text
현재 단계 즉시 중단
downstream 단계 실행 금지
pipeline_run_manifest.json에 실패 기록
기존 성공 캐시는 삭제하지 않음
이번 실행의 임시 출력은 폐기
exit code != 0
```

FATAL 예:

```text
필수 입력 파일 없음
schema_version 미지원
hash 불일치인데 재실행 불가
cycle 있는 river_path
terrain_lookup 미매칭
NaN / Infinity
원자적 저장 실패
```

### 7-2. WARNING

WARNING 발생 시:

```text
단계 실행은 계속
출력 JSON의 warnings 또는 debug report에 기록
pipeline_run_manifest.json에 warning count 기록
```

WARNING 예:

```text
locked=true no-op
force 값이 플래그 없이 존재하여 무시
exclude_from_sim=true 자동 terrain 신뢰 불가
natural pit 감지
soil_moisture clamp 발생
```

### 7-3. INFO

INFO:

```text
정상 동작이지만 검토에 유용한 상태.
debug report와 manifest에만 기록.
```

---

## 8. 원자적 저장 정책

각 단계 출력은 다음 순서로 저장한다.

```text
1. 같은 filesystem 안의 임시 파일에 출력 작성
2. JSON/YAML/CSV 형식 재파싱 검증
3. schema validation
4. hash 재계산
5. 최종 경로로 atomic rename
```

임시 경로:

```text
{final_output_parent}/.tmp_{stage}_{run_id}/
```

예:

```text
cache/province_graph.json
  → cache/.tmp_build_province_graph_{run_id}/province_graph.json

outputs/draft_rivers.png
  → outputs/.tmp_hydrology_{run_id}/draft_rivers.png
```

금지:

```text
기존 출력 파일에 직접 덮어쓰기
다른 filesystem 간 rename을 atomic write로 간주
부분 생성된 JSON을 cache 정식 출력으로 남기기
```

실패 시:

```text
임시 디렉터리는 삭제 또는 failed tmp로 격리
기존 성공 cache는 유지
manifest에는 write_failed 기록
```

---

## 9. pipeline run manifest

출력 위치:

```text
cache/pipeline_runs/{run_id}.json
cache/pipeline_run_manifest.json
```

정책:

```text
cache/pipeline_runs/{run_id}.json은 불변 실행 기록이다.
cache/pipeline_run_manifest.json은 최신 실행 manifest의 copy다.

새 실행이 완료되면:
  1. cache/pipeline_runs/{run_id}.json 생성
  2. 같은 내용을 cache/pipeline_run_manifest.json에 복사해 latest manifest로 갱신
```

예시:

```json
{
  "schema_version": "pipeline_orchestration.v0.1",
  "run_id": "2026-06-17T21-20-00Z_abcd1234",
  "started_at": "2026-06-17T21:20:00Z",
  "finished_at": "2026-06-17T21:25:00Z",
  "status": "success",
  "inputs": {
    "map_data": {
      "map_data_dir": "../map_data/",
      "provinces_png": "../map_data/provinces.png",
      "default_map": "../map_data/default.map",
      "world_yaml": "config/world.yaml",
      "heightmap_png": "../map_data/heightmap.png",
      "water_mask_png": null
    },
    "inputs": {
      "province_constraints": "revisions/sha256_abcd/province_constraints.yaml",
      "province_overrides": "revisions/sha256_abcd/province_overrides.yaml",
      "climate_rules": "config/climate_rules.yaml",
      "terrain_lookup": "config/terrain_lookup.csv"
    },
    "runtime": {
      "cache_dir": "cache/",
      "outputs_dir": "outputs/"
    }
  },
  "stages": [
    {
      "name": "build_province_graph",
      "status": "skipped_cache_hit",
      "output": "cache/province_graph.json",
      "reason": "schema/hash/params match",
      "validation": "success"
    },
    {
      "name": "build_bootstrap_fields",
      "status": "executed",
      "output": "cache/bootstrap_fields.json",
      "reason": "constraints_hash changed",
      "warnings": 0,
      "validation": "success"
    }
  ],
  "final_outputs": {
    "terrain": "cache/koppen_biome_terrain.json"
  }
}
```

status 값:

```text
success
failed
partial_failed
dry_run
validate_only
```

stage status 값:

```text
executed
skipped_cache_hit
skipped_by_range
failed
not_started_due_to_upstream_failure
```

주의:

```text
pipeline_run_manifest.json은 최신 실행을 쉽게 찾기 위한 latest copy다.
과거 run 추적은 cache/pipeline_runs/{run_id}.json을 사용한다.
multi-user merge의 merge_manifest.json이나 Editor export_manifest.json과 섞지 않는다.
```

---

## 10. CLI 계약

기본 명령:

```bash
python run_climate_pipeline.py \
  --input-manifest config/pipeline_input_manifest.json
```

`pipeline_input_manifest.json`은 다음 구조를 표준으로 한다.

```json
{
  "schema_version": "pipeline_input_manifest.v0.1",
  "pipeline_version": "pipeline_orchestration.v0.1",
  "map_data": {
    "map_data_dir": "../map_data/",
    "provinces_png": "../map_data/provinces.png",
    "default_map": "../map_data/default.map",
    "world_yaml": "config/world.yaml",
    "heightmap_png": "../map_data/heightmap.png",
    "water_mask_png": null
  },
  "inputs": {
    "province_constraints": "revisions/{revision_dir_name}/province_constraints.yaml",
    "province_overrides": "revisions/{revision_dir_name}/province_overrides.yaml",
    "climate_rules": "config/climate_rules.yaml",
    "terrain_lookup": "config/terrain_lookup.csv"
  },
  "runtime": {
    "cache_dir": "cache/",
    "outputs_dir": "outputs/"
  },
  "cache": {
    "province_graph": "cache/province_graph.json",
    "bootstrap_fields": "cache/bootstrap_fields.json",
    "seasonal_climate": "cache/seasonal_climate.json",
    "hydrology": "cache/hydrology.json",
    "rainfall_normalized": "cache/rainfall_normalized.json",
    "koppen_biome_terrain": "cache/koppen_biome_terrain.json"
  },
  "manifest": {
    "run_manifest_latest": "cache/pipeline_run_manifest.json",
    "run_manifest_history_dir": "cache/pipeline_runs/"
  },
  "outputs": {
    "draft_rivers_png": "outputs/draft_rivers.png",
    "debug_dir": "outputs/debug/"
  }
}
```

선택:

```bash
--from-stage seasonal_climate
--to-stage rainfall_normalization
--force-stage hydrology
--force-all
--validate-only
--dry-run
--allow-stale-lock-cleanup
--run-id manual_name
```

`--from-stage`:

```text
지정 단계부터 실행한다.
단, upstream cache는 모두 유효해야 한다.
upstream cache가 없거나 stale이면 FATAL.

--from-stage는 지정 stage 이전을 실행하지 않는다.
따라서 --force-all 또는 --force-stage와 함께 쓰더라도
from-stage 이전 upstream cache가 stale이면 FATAL.

--force-all은 from-stage 이후 실행 범위에만 적용된다.
```

`--to-stage`:

```text
지정 단계까지 실행하고 이후 단계는 skipped_by_range 처리.
```

`--validate-only`:

```text
입력과 기존 cache의 schema/hash만 검증.
새 출력 생성 금지.
stale cache 발견 시 ERROR로 보고 nonzero exit code를 반환한다.
```

`--dry-run`:

```text
어떤 단계가 executed/skipped/failed 될지 계획만 출력.
새 출력 생성 금지.
stale cache는 ERROR가 아니라 해당 stage가 executed 예정이라고 표시한다.
```

---

## 11. 단계 이름 표준화

CLI와 manifest에서 사용하는 stage name:

```text
build_province_graph
build_bootstrap_fields
seasonal_climate
hydrology
rainfall_normalization
koppen_biome_terrain
```

금지:

```text
문서마다 다른 stage alias 사용
예: graph_build, province_graph_build, koppen_stage 등
```

이유:

```text
from-stage / to-stage / force-stage / manifest / debug report가 같은 이름을 써야 한다.
```

stage output schema_version:

| stage name | output | schema_version |
|------------|--------|----------------|
| `build_province_graph` | `cache/province_graph.json` | `province_graph.v0.2` |
| `build_bootstrap_fields` | `cache/bootstrap_fields.json` | `bootstrap_fields.v0.1` |
| `seasonal_climate` | `cache/seasonal_climate.json` | `seasonal_climate.v0.4.1` |
| `hydrology` | `cache/hydrology.json` | `hydrology.v0.5` |
| `rainfall_normalization` | `cache/rainfall_normalized.json` | `rainfall_normalization.v0.6` |
| `koppen_biome_terrain` | `cache/koppen_biome_terrain.json` | `koppen_biome_terrain.v0.7` |

---

## 12. debug artifact 수집

각 단계는 자기 debug output을 생성할 수 있다.
각 stage runner는 생성한 debug artifact 목록을 orchestrator에 반환한다.
오케스트레이터는 반환된 목록을 manifest에 수집한다.

필수 수집:

```text
stage runner가 반환한 debug_artifacts[]
```

glob 기반 수집:

```text
cache/debug/*_warnings.csv
cache/debug/*_stats.csv
outputs/debug/*.png
```

주의:

```text
glob은 fallback이다.
정확한 목록은 stage runner가 반환한 debug_artifacts[]를 우선한다.
```

golden run일 때:

```text
debug map을 항상 저장한다.
성공/실패와 무관하게 manifest에 경로를 기록한다.
```

이유:

```text
실패 후 재실행하면 튜닝값이 달라져 원인 귀속이 어려울 수 있다.
```

---

## 13. 검증 계층

오케스트레이터 검증은 3층이다.

### 13-1. input validation

```text
파일 존재
확장자 / 포맷
schema_version
필수 필드
```

### 13-2. cache validation

```text
source hash 일치
params_hash 일치
upstream output hash 일치
stage별 output validator 통과
schema가 정의한 경우 validation status success
```

### 13-3. output validation

```text
단계별 schema validation
NaN / Infinity 없음
land target coverage
필수 output field coverage
```

주의:

```text
golden test 통과 여부는 orchestration의 기본 validation이 아니다.
golden test는 validation_and_golden_tests_spec_v0.1에서 별도 실행한다.
```

---

## 14. 금지 사항

```text
[금지 1] stale cache silent reuse
  hash 불일치 캐시는 반드시 재실행 또는 FATAL.

[금지 2] downstream 단계에서 upstream 원본 입력 재해석
  예: v0.7이 annual_rainfall_raw 직접 사용.

[금지 3] project_state.json을 pipeline input으로 사용
  UI 상태 파일이다.

[금지 4] export_manifest.json을 pipeline input으로 사용
  Editor/merge 추적 파일이다.

[금지 5] state_constraints.yaml을 v0.1 단계에 전달
  현재 단계 spec들이 state_constraints를 읽지 않도록 확정됨.

[금지 6] force_rainfall을 orchestrator에서 직접 적용
  seasonal_climate 내부 책임.

[금지 7] exclude_from_sim province를 orchestrator가 graph에서 제거
  hydrology에서 local_runoff=0 통과 노드로 처리.

[금지 8] 부분 출력 파일을 정식 cache로 남김
  원자적 저장 필수.

[금지 9] rivers.png를 hydrology 또는 v0.7 입력으로 사용
  rivers.png는 선택 출력.

[금지 10] terrain_lookup.csv 미매칭을 fallback terrain으로 대체
  미매칭은 ERROR.
```

---

## 15. 완료 기준

```text
1. 전체 DAG 순서가 고정되어 있다.
2. 각 stage의 입력/출력/해시 계약이 명시되어 있다.
3. cache hit / miss 기준이 명시되어 있다.
4. stale cache silent reuse가 금지되어 있다.
5. FATAL / WARNING / INFO 정책이 분리되어 있다.
6. 원자적 저장 정책이 정의되어 있다.
7. pipeline_run_manifest.json 구조가 정의되어 있다.
8. CLI stage 이름이 표준화되어 있다.
9. project_state / export_manifest / state_constraints 책임 경계가 명시되어 있다.
10. 최종 출력 `cache/koppen_biome_terrain.json`까지 실행 가능하다.
```

---

## 16. 이후 이관 항목

```text
final Vic3 map_data export spec
rivers_format_spec
terrain whitelist / game data validator
golden test runner
parallel execution scheduler
incremental per-province recompute
external state_constraints authoring pipeline
```
