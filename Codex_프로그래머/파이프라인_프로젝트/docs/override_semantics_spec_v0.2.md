# override_semantics_spec v0.2

> Province Editor에서 내보내는 constraints / overrides의 의미 정의.
> 파이프라인과 Editor UI가 동일한 의미를 참조하기 위한 단일 기준 문서.

---

## 0. 폐기 선언

다음 동작은 구설계 잔재이며 **명시적으로 폐기**한다.

```
[폐기] locked=true → 시뮬레이션 완전 제외
  이유: 기후 구멍 발생. locked province가 빠지면
        이웃이 barrier/비그늘을 받지 못함.

[폐기] effective_mountain_strength = max(auto_from_elevation, user)
  이유: province_graph.metadata.heightmap.authoritative=false. auto 파생 금지.

[폐기] locked province moisture = 0 강제 (시뮬 단계에서)
  이유: 물리 참여 구조와 충돌.
```

현재 구현에 위 동작이 남아 있다면 이 문서 기준으로 교체한다.

---

## 1. 3티어 + 독립 플래그 구조

```
[티어 1] constraints    = 시뮬레이션 입력 재료
[티어 2] locked         = 출력 라벨 강제, 물리는 정상 참여
[티어 3] climate_lock   = 물리값 강제, locked와 독립 플래그
[별도]   exclude_from_sim = 시뮬 참여 자체를 제어, 독립 플래그
```

**핵심 원칙:**
```
override의 "최우선"은 출력 라벨에 대한 것이다.
파이프라인 참여 여부가 아니다.
물리는 끝까지 참여하고, 라벨만 마지막에 덮어쓴다.
단, exclude_from_sim=true면 물리 참여 자체를 제어한다.
```

---

## 2. 티어 1 — constraints

시뮬레이션 계산의 재료. 결과를 직접 강제하지 않는다.

### 2-1. 크기 입력

```yaml
mountain_strength: 0.0   # 0.0~1.0, barrier 강도, user authored only
elevation_hint: none     # none/lowland/upland/highland/mountain
moisture_bonus: 0.0      # raw 단위
temperature_delta: 0.0   # °C
rainfall_delta: 0.0      # raw 단위
```

### 2-2. presence 앵커

```yaml
river_seed: false    # true → 강 존재 강제 (threshold 무시)
river_major: false   # true → 간선하천 우선순위
river_path: []       # 방향 힌트, D8 무시 구간
lake_seed: false     # true → is_flow_sink (국소 sink, 전역 최저점 아님)
wetland_seed: false
```

**채널 독립성:**
```
river_seed=true + force_terrain=desert → 충돌 아님
  river_seed → rivers.png 채널
  force_terrain → terrain 라벨 채널
  나일강(사막 관통 강)이 이 케이스.
  구현자 주의: 충돌 검사 로직 넣지 말 것.
```

### 2-3. 판타지 soft nudge

```yaml
fantasy_zone: null   # biome 라벨 힌트. locked 없으면 파이프라인이 override 가능.
```

---

## 3. 티어 2 — locked

**출력 라벨만 강제. 물리 시뮬레이션은 정상 참여.**

```yaml
locked: false
force_terrain: null    # vic3_terrain 값
force_biome: null      # biome 값
```

**force_biome과 force_terrain 관계:**
```
두 필드는 독립 채널이다.
force_biome만 지정:
  → biome 라벨만 강제
  → terrain은 파이프라인이 계산한 원래 값 유지
  → biome 강제로 terrain을 재계산하지 않음

두 필드를 함께 지정:
  → biome 라벨: force_biome
  → terrain 라벨: force_terrain
  → 판타지 목적으로 biome과 terrain을 독립 설정 가능

biome 강제 후 terrain도 맞추려면 force_terrain을 함께 지정해야 한다.
```

**동작:**
```
locked=true:
  물리 시뮬레이션 정상 실행 (moisture/ET/runoff/barrier)
  이웃에 mountain_strength 등 정상 영향
  STEP 6 normalization도 적용
  최종 판정 후 → force_terrain / force_biome 덮어씀

검증:
  locked=true, force_terrain=null, force_biome=null
  → WARNING: no-op locked

  force_terrain 또는 force_biome이 지정되었지만 locked=false
  → WARNING 후 무시
  이유: force 라벨 값은 locked=true일 때만 의미를 가진다.
       자동으로 locked=true를 활성화하지 않는다.
```

**제외된 책임 — 주 특성/주 모디파이어:**
```
주 특성, 주 모디파이어, scripted modifier 부여/제거는 map_data 기반
기후·지형 파이프라인의 책임이 아니다.
해당 기능은 별도 Vic3 모딩 산출물 도구(common/history/events/scripted_effects)
또는 후속 국가/주 효과 파이프라인에서 다룬다.
```

---

## 4. 티어 3 — climate_lock

**물리값 강제. locked와 독립 플래그.**

```yaml
climate_lock: false
force_temp: null       # °C
force_moisture: null   # raw 단위
force_rainfall: null   # raw 단위
```

### 4-1. 독립 플래그 4조합

| locked | climate_lock | 물리 | 라벨 |
|--------|-------------|------|------|
| false  | false       | 창발 | 창발 |
| true   | false       | 창발 | 강제 |
| false  | true        | 강제 | 창발 |
| true   | true        | 강제 | 강제 |

### 4-2. force 값 적용 시점 (필드별 상이)

세 force 필드는 적용 시점이 다르다. **동일 취급 금지.**

**force_temp:**
```
적용 시점: 매 계절(summer/winter) 온도 계산 완료 직후 재고정
이유: 온도는 계절마다 재계산. 재고정이 없으면 다음 계절에 사라짐.
     이후 capacity 계산은 재고정된 temperature를 기준으로 수행.

의사코드:
  compute_season_temperature(province)
  if province.climate_lock and province.force_temp is not None:
    temperature[province] = province.force_temp   # 계절마다 재고정
  compute_moisture_capacity(province)
```

**force_moisture:**
```
적용 시점: 매 moisture propagation iteration 완료 직후 재고정 (Dirichlet)
이유: moisture는 매 iteration 이웃에서 갱신됨.
     재고정 없으면 루프가 즉시 덮어써서 효과 사라짐.
     "저주받은 한랭 지역이 지속적으로 주변에 영향" 효과의 핵심.

의사코드:
  for each moisture iteration:
    propagate_moisture()
    if province.climate_lock and province.force_moisture is not None:
      moisture[province] = province.force_moisture  # 매 iter 재고정
```

**force_rainfall:**
```
적용 시점: 각 연도·각 계절의 moisture propagation 완료 후 1회만 적용.
           ET/runoff 계산 전, STEP 6 normalization 전.
이유: rainfall은 지형성 강수·ITCZ 보정·transit loss 등이 누적된 결과.
     매 iteration 덮어쓰면 orographic rain 등 물리 강수가 삭제됨.
     각 계절별 단 1회 override로 해당 계절의 최종 raw rainfall을 고정.

정확한 범위:
  annual spin-up 바깥 루프가 여러 번 돌면 매 spin-up year마다 적용.
  summer/winter가 각각 존재하면 각 season마다 적용.
  moisture iteration 내부에서는 적용하지 않음.

의사코드:
  for each annual_spinup_year:
    for each season:
      compute_season_temperature()
      apply_force_temp()
      compute_capacity()
      for each moisture iteration:
        propagate_moisture()
        apply_force_moisture()
      complete_ITCZ_and_orographic_rainfall()
      # → 여기서 force_rainfall 적용
      if province.climate_lock and province.force_rainfall is not None:
        rainfall[province, season] = province.force_rainfall  # 계절별 1회 적용
      compute_ET()
      compute_runoff()
      # → STEP 6 normalization은 raw rainfall 합성 후 수행
```

**force 값 단독 지정 규칙:**
```
force_temp / force_moisture / force_rainfall이 지정되었지만 climate_lock=false
→ WARNING 후 무시

이유:
  자동으로 climate_lock=true를 활성화하면 단순 입력 실수가
  주변 기후를 재조직하는 강한 물리 override로 바뀔 수 있다.
```

### 4-3. force 값 단위

```
force_temp: °C. 양 계절 동일 브로드캐스트 (기본).
force_moisture: raw (루프 내부 단위, capacity 0.35~2.25 범위 내)
force_rainfall: raw (루프 내부 단위, STEP 6 정규화 전)
```

---

## 5. exclude_from_sim — 독립 플래그

**climate_lock의 하위 옵션이 아닌 별도 독립 플래그.**

```yaml
exclude_from_sim: false
```

**참여 여부 상세:**

| 시스템 | exclude_from_sim=true일 때 |
|--------|--------------------------|
| 수분 전파 | 참여 안 함 (moisture 수신/발신 없음) |
| 온도 계산 | 참여 안 함 (이웃 영향 없음) |
| 강수 | 참여 안 함 (rainfall 기여 0) |
| runoff 생성 | 자체 rainfall/runoff 생성 0 |
| flow accumulation | **참여** (상류 유량은 하류로 전달) |
| rivers.png | **참여** (강 경로를 차단하지 않음) |
| terrain 라벨 | 유지 (force_terrain 있으면 적용) |

**수문 동작 명세:**
```
exclude_from_sim=true인 province는 자체 기후 물수지를 만들지 않는다.
  rainfall = 0
  ET = 0
  local_runoff = 0

하지만 지형 셀로는 존재한다.
  upstream discharge를 수신한다.
  받은 discharge를 drainage graph에 따라 downstream으로 전달한다.
  river path / flow accumulation / watershed 연결을 끊지 않는다.

즉, "기후 계산에서는 빈칸"이지만 "수문 네트워크에서는 통과 지형"이다.
```

**climate_lock과의 관계:**
```
exclude_from_sim=true + climate_lock=true → ERROR
  exclude: 물리 참여 없음
  climate_lock: 물리값 강제 (참여 전제)
  논리 모순 → 구현 시 에러 처리

올바른 사용:
  exclude_from_sim=true + locked=true
  → 시뮬 제외 + 라벨 강제
  → "이 province는 물리적으로 존재하지 않음 + 지형만 보여줌"
```

**사용 기준:**
```
일반 locked/climate_lock으로 해결 안 되는 극단 케이스만.
예: "차원문" 같은 물리 법칙 예외 지역.
남용 시 주변 province 기후 왜곡 위험.
```

---

## 6. 출력 채널

| 채널 | 파일 | 담당 |
|------|------|------|
| terrain 라벨 | province_terrains.txt | force_terrain, 자동 biome→terrain |
| biome 라벨 | province_climate.csv | force_biome, Köppen-lite 결과 |
| 수문 | rivers.png | river_seed, flow accumulation |

채널은 독립. 한 채널 강제가 다른 채널에 영향 주지 않음.

---

## 7. 파일 로드 및 적용 시점

```
province_overrides.yaml → 시뮬레이션 시작 전 전체 로드

물리 필드 (climate_lock): 시뮬레이션 중 적용
  force_temp      → 계절 온도 계산 후, capacity 계산 전 재고정
  force_moisture  → 매 moisture iteration 후 재고정
  force_rainfall  → 각 연도·각 계절 전파/강수 완료 후 1회

라벨 필드 (locked): 최종 판정 후 적용
  force_terrain   → terrain 판정 완료 후 덮어씀
  force_biome     → biome 판정 완료 후 덮어씀
```

---

## 8. 전체 적용 순서

```
[로드] province_overrides.yaml 전체 로드

[STEP 1] bootstrap_fields 생성 (constraints 기반)

[STEP 2~5] 시뮬레이션
  매 annual spin-up year:
    매 계절:
      temperature 계산
      if climate_lock: force_temp 재고정
      capacity 계산

      매 moisture iteration:
        moisture propagation
        if climate_lock: force_moisture 재고정

      ITCZ/지형성 강수 완료
      if climate_lock: force_rainfall 1회 적용

      ET 계산
      runoff 계산
      soil_water_storage 이월

[STEP 5] 수문
  river_seed anchor + flow accumulation → rivers.png

[STEP 6] normalization
  raw → final_rainfall

[STEP 7] biome/terrain 판정

[STEP 8 = 마지막] locked 라벨 덮어쓰기
  force_terrain 적용
  force_biome 적용
  exclude_from_sim: terrain 라벨 유지, 기후값 무효 처리
```

**물리 순서 고정 규칙:**
```
계절 온도 계산
→ force_temp
→ capacity 계산
→ moisture propagation
→ force_moisture
→ ITCZ/지형성 강수 완료
→ force_rainfall
→ ET/runoff
```

구현자는 위 순서를 바꾸면 안 된다.
특히 force_temp는 capacity 이전, force_rainfall은 ET/runoff 이전이어야 한다.

---

## 9. 다중 사용자 Export 병합

### 9-1. 기본 원칙

```
merge_rules (add/max/multiply)는 state↔province 계층 병합 규칙이다.
사용자 간 충돌 해결에 직접 적용하면 안 된다.
같은 Export를 두 번 병합하면 delta가 중복 누적된다.
```

### 9-2. Export 메타데이터 필수 필드

Export 메타데이터는 **export_manifest.json**에 담는다.
여러 YAML 파일을 전달하더라도 export 단위의 기준 버전과 편집 범위는
항상 export_manifest.json을 source of truth로 사용한다.

예시:

```json
{
  "export_id": "uuid-v4",
  "base_revision": "sha256:...",
  "editor": "user-id",
  "exported_at": "ISO-8601",
  "edited_provinces": ["xAABBCC"],
  "edited_fields": {
    "xAABBCC": [
      "mountain_strength",
      "elevation_hint"
    ]
  }
}
```

### 9-3. 충돌 정의

```
충돌 = 같은 province, 같은 필드, 다른 값, 다른 editor
충돌 아님 = 다른 province 편집, 또는 같은 값
충돌 아님 = 같은 province라도 서로 다른 필드 편집
```

`edited_provinces`는 빠른 표시용 요약일 뿐 충돌 판정 기준이 아니다.
충돌 판정은 반드시 `edited_fields` 또는 `base_revision`에 해당하는
원본 상태와의 diff를 기준으로 수행한다.
따라서 `base_revision`이 가리키는 기준 snapshot은 병합 도구가 접근 가능한
형태로 반드시 보관해야 한다.

**중복 export 정의:**
```
동일 export_id가 이미 병합된 상태에서 다시 입력됨
→ 중복 export로 판정
→ 병합 제외 또는 ERROR

기본 정책: ERROR
이유: 같은 export를 두 번 병합하면 delta가 중복 누적될 수 있다.
```

### 9-4. 충돌 해결 우선순위

```
기본: 수동 확인 (병합 도구가 충돌 목록 출력)

자동 해결 허용 케이스:
  1. base_revision이 같은 두 export 중 edited_provinces가 겹치지 않음
     → 단순 합집합
  2. 같은 필드에 두 export의 값이 같음
     → 어느 쪽이든 채택
  3. 같은 province라도 edited_fields가 겹치지 않음
     → 필드 단위 합집합
     예: A는 mountain_strength, B는 elevation_hint 편집
         → 둘 다 반영

자동 해결 금지 케이스:
  1. base_revision 불일치
     → 자동 병합 금지
     → 최신 기준으로 rebase하거나 수동 확인
  2. 같은 province, 같은 필드, 다른 값
     → 반드시 수동 확인 또는 designated owner 설정
  3. timestamp만 다르고 값이 다름
     → "나중 편집 우선" 금지 (exported_at 조작 위험)
```

### 9-5. 병합 리포트 출력

```
충돌 목록:
  - province color
  - 충돌 필드
  - export_A 값 (editor, timestamp)
  - export_B 값 (editor, timestamp)
  - 상태: RESOLVED / UNRESOLVED

병합 통과 조건:
  UNRESOLVED 충돌 0개
```

---

## 10. 검증 규칙

```
[ERROR]
  exclude_from_sim=true + climate_lock=true
  → 논리 모순

[WARNING]
  locked=true, force_terrain=null, force_biome=null
  → no-op locked

  force_terrain 또는 force_biome이 지정되었지만 locked=false
  → force 라벨 값 무시

  force_temp / force_moisture / force_rainfall이 지정되었지만 climate_lock=false
  → force 물리값 무시

  lake_seed=true + river_seed=true (같은 province)
  → 흐름 종착점이자 강 시작점. lake_seed 우선.

[허용]
  river_seed=true + force_terrain=desert
  → 다른 채널. 충돌 검사 하지 말 것.

  force_biome=enchanted_forest + force_terrain=plains
  → 의도된 판타지. biome 라벨과 terrain 라벨 독립.

[단위 검증]
  force_moisture / force_rainfall 단위는 값 범위로 검증하지 않는다.
  단위 보장은 UI 스키마 버전으로 처리.
  (raw moisture는 0~2.25 범위일 수 있어 0~1 검사 시 오탐 발생)
```

---

## 11. 파일 위치 및 책임

```
province_constraints.yaml
  위치: 프로빈스_프로젝트/config/
  생성: Province Editor Export
  소비: 파이프라인 시뮬레이션 (입력 재료 + bootstrap_fields)

province_overrides.yaml
  위치: 프로빈스_프로젝트/config/
  생성: Province Editor Export
  소비: 파이프라인 (시작 시 로드, 물리는 중간, 라벨은 마지막)

project_state.json
  위치: 프로빈스_프로젝트/data/
  역할: Editor 작업 상태 전체

export_manifest.json
  위치: Export bundle 루트
  역할: export_id / base_revision / editor / edited_fields 기록
  수합: 다중 사용자 병합의 source of truth
  주의: project_state.json이 아니라 export_manifest.json을 병합 기준으로 사용
```

---

## 12. 추가 수정 기록

```
[수정] force_rainfall 적용 범위를 "각 연도·각 계절 전파 완료 후 1회"로 명확화
[수정] 전체 물리 적용 순서 고정:
       temperature → force_temp → capacity
       → moisture propagation → force_moisture
       → rainfall 완료 → force_rainfall
       → ET/runoff
[수정] export 메타데이터 위치를 export_manifest.json으로 확정
[추가] edited_fields 도입. 필드 단위 충돌 판정 가능
[추가] 같은 province라도 다른 필드 편집이면 자동 합집합 병합 허용
[추가] 동일 export_id 재입력은 중복 export로 판정하고 ERROR 처리
[추가] base_revision 불일치 시 자동 병합 금지
[추가] force 값만 있고 플래그가 false이면 WARNING 후 무시
[수정] exclude_from_sim의 수문 동작 명확화:
       자체 rainfall/runoff 생성 0
       상류 discharge는 하류로 전달
       river path는 차단하지 않음
[정정] exclude_from_sim은 climate_lock 하위 옵션이 아니라 독립 플래그
[정정] 주 특성/주 모디파이어 조정은 map_data 기반 기후·지형 파이프라인
       책임에서 제외. 별도 Vic3 모딩 산출물 도구 영역으로 이동.
```

기존 changelog나 외부 요약 문서가 force_rainfall을 매 iteration 재고정하거나,
exclude_from_sim을 climate_lock 하위 옵션처럼 설명한다면 이 문서 기준으로 갱신한다.
