# 기후·지형 생성 알고리즘 전체 변경 기록
## Codex 구현자를 위한 상세 설계 문서

> 이 문서는 초기 설계에서 현재 설계까지 모든 피드백과 변경 이유를 기록한다.
> 구현 중 "왜 이렇게 되어 있지?"라는 의문이 생기면 여기를 먼저 확인할 것.
> **변경 금지 사항 섹션을 반드시 읽을 것.**

---

## 목차

1. 초기 설계 (출발점)
2. 변경 이력 (피드백 → 이유 → 결과)
3. 최종 확정 알고리즘
4. 최종 스키마
5. 파이프라인 버전 순서
6. 검증 규칙
7. 변경 금지 사항
8. 알려진 한계

---

## 1. 초기 설계 (출발점)

처음 설계는 단순한 룩업테이블 기반이었다.

```
위도 → pressure_band → rainfall_base 조회
고도 → 기온 보정
temperature × rainfall × altitude → terrain_lookup.csv → biome → vic3_terrain
```

**초기 입력 파일:**
```
provinces.png     (유저 제작)
heightmap.png     (유저 제작)
rivers.png        (유저 제공 고정 입력)
climate_rules.yaml
world.yaml
province_overrides.yaml (terrain 직접 지정)
```

**초기 Province Editor 역할:**
```
province 클릭 → terrain/biome 직접 칠하기
= "결과값 직접 입력" 방식
```

**초기 파이프라인:**
```
각 province를 독립적으로 계산
위도 → 기온, 기압대 → 강수, 고도 → terrain
옆 province가 뭔지 전혀 영향 없음
```

---

## 2. 변경 이력

---

### [변경 01] Province Editor 역할 전환

**피드백:**
Province Editor에서 terrain을 직접 칠하면 자동 기후 생성의 의미가 없어진다.
"이 province는 forest"를 직접 지정하면 파이프라인이 계산할 게 없어진다.

**이유:**
판타지 모드의 목표는 "유저가 세계의 원인을 정하면 파이프라인이 결과를 계산하는 것".
결과를 직접 입력하면 기후 시뮬레이션의 존재 이유가 없어진다.

**변경 결과:**
```
변경 전: province 클릭 → terrain/biome 직접 지정 (결과값 입력)
변경 후: province 클릭 → mountain_strength, river_seed 등 지정 (원인값 입력)

올바른 입력 예시:
  mountain_strength=1.0  → "여기는 높은 산맥이다"
  river_seed=true        → "여기서 강이 시작된다"
  wetland_seed=true      → "여기는 습지 후보다"

잘못된 입력 (force/locked로만 허용):
  "이 province는 forest로 만들어라"
```

---

### [변경 02] 계산 방식: 룩업테이블 → 물리 시뮬레이션

**피드백:**
위도 기반 룩업테이블은 각 province를 독립 계산한다.
산맥이 옆 province에 비그늘을 만드는 효과, 해안에서 내륙으로 수분이 이동하는 효과가 전혀 없다.

**이유:**
"사막은 왜 여기 있는가"를 설명하려면 주변 지형이 서로 영향을 주는 시뮬레이션이 필요하다.
지구과학적으로: 사막은 산맥 비그늘이나 아열대 고압대 때문에 생기며, 이는 인접 관계에서 나온다.

**변경 결과:**
```
변경 전: province별 독립 계산 (위도 → 기온, 기압대 → 강수)
변경 후: province graph 위에서 moisture 전파 시뮬레이션
         바다 → 바람 방향 → 산맥 → 내륙으로 수분이 흐름
         인접 province가 서로 영향을 줌
```

---

### [변경 03] province_graph.json 전처리 캐시 추가

**피드백:**
moisture 시뮬레이션을 하려면 province 간 연결 정보(인접 관계, 경계 길이, 방향)가 필요하다.
provinces.png를 매번 스캔하면 느리다.

**이유:**
58829개 province의 인접 관계를 매 실행마다 계산하면 수십 초 소요.
전처리로 1회 계산 후 캐시하면 시뮬레이션이 즉시 시작 가능.

**변경 결과:**
```
추가된 파일: province_graph.json (파이프라인 캐시)
생성 스크립트: build_province_graph.py (1회 실행)

province_graph.json에 포함된 정보:
  - province별: center, area, perimeter, latitude, elevation_m, elevation_max_m
  - province별: coastal_ratio, is_coastal, is_sea, is_simulation_target
  - 이웃 관계: shared_border_px, border_weight, direction, distance_px

border_weight = shared_border_px / perimeter_px (A 기준)
direction = normalize(center_B - center_A) [이미지 좌표계: x=동, y=남]
heightmap: I;16 포맷, 2x2 평균 다운샘플, convert('L') 금지
```

---

### [변경 04] wind_weight에 leakage_min 추가

**피드백:**
`wind_weight = max(0, min(dot_A, dot_B))` 방식으로 역풍을 완전 차단하면
바람 방향과 수직인 경로로 수분이 전혀 이동하지 않아 비현실적 결과 발생.

**검증:**
coastal moisture: 0.2085, inland moisture: 0.0014 (비율 150:1)
파라미터 튜닝(base_loss 0.02, decay 800)으로도 변화 없음 → 구조적 문제

**이유:**
실제 대기는 난류와 국지풍으로 인해 주풍 외 방향으로도 약한 수분 이동이 존재한다.
완전 차단은 물리적으로 과도한 단순화다.

**변경 결과:**
```
변경 전: wind_weight = max(0, min(dot_A, dot_B))
변경 후: wind_weight = max(leakage_min, min(dot_A, dot_B))
         leakage_min = 0.05  (climate_rules.yaml의 propagation 섹션)
```

---

### [변경 05] wind band 경계 ±4도 선형 보간

**피드백:**
위도 10°/30°/60°에서 기후 로직이 계단식으로 즉시 전환된다.
실제 moisture_raw.png에서 수평 절단선 형태의 인공물이 보였다.

**이유:**
자연의 기후대 경계는 점진적으로 변화한다.
hard boundary는 지도에 가로줄처럼 보이는 비현실적 경계를 만든다.

**변경 결과:**
```
변경 전: 위도 30.000°에서 즉시 무역풍 → 편서풍 전환
변경 후: 위도 26~34° 구간에서 두 벡터를 선형 보간 (transition_width=4도)
         경계값 t = clamp((abs_lat - band_min) / transition_width, 0, 1)
         wind_vector = lerp(band_a_vector, band_b_vector, t)
```

---

### [변경 06] border_weight 역할 변경

**피드백:**
58829개 province 과분할 환경(median_area=90px)에서
hop당 전달량 = wind_weight × border_weight ≈ 0.5 × 0.10 = 0.05
3 hop이면 (0.05)^3 ≈ 0.000125 → 내륙 도달 불가

**이유:**
정상 Vic3 맵(~3000 province)에서는 province가 크고 border_weight도 자연스럽게 크다.
58829개 과분할 맵에서는 구조적으로 border_weight가 너무 작아진다.
border_weight를 절대 전달량에 직접 곱하면 내륙 전파가 원천 차단된다.

**변경 결과:**
```
변경 전:
  transfer = delta_A × wind_weight × border_weight × distance_decay

변경 후:
  flow_weight = wind_weight × border_weight × distance_decay
  transfer = delta_A × export_fraction × (flow_weight / flow_total)

  border_weight: 절대 전달량 결정 → 이웃 간 분배 비율로만 사용
  export_fraction: 절대 전달량 결정 (별도 파라미터)
```

---

### [변경 07] Mountain barrier 추가 (v0.3)

**피드백:**
초기 설계에는 elevation_hint만 있어 산맥이 옆 province에 미치는 영향이 없었다.
산맥이 있어도 비그늘이 생기지 않고 풍상 강수도 없었다.

**이유:**
지구과학적으로 산맥은 바람에 실린 수분을 차단한다.
풍상측: 강제 상승 → 냉각 → 강수 (orographic rain)
풍하측: 하강 → 가열 → 건조 (rain shadow)
이것이 없으면 사막은 오직 위도 기반으로만 생성된다.

**변경 결과:**
```
추가된 처리 (전파 루프 내부):
  mountain_strength = province_constraints.mountain_strength (user authored, 0.0~1.0)
  [auto_from_elevation 제거: AI 임시 heightmap 신뢰 불가. 변경 21 참조]

  crossing_barrier = max(mtn_A, mtn_B)
  ridge_continuity = mtn_A × mtn_B × ridge_bonus
  barrier = crossing_barrier + ridge_continuity

  barrier_factor = 1 - exp(-barrier × barrier_scale)
  blocked = transfer × barrier_factor
  passed  = transfer - blocked

  orographic_rain = blocked × windward_efficiency → rainfall[B] 추가
  leeward shadow: moisture[B] 감소로 자연 발생 (별도 처리 불필요)
```

---

### [변경 08] barrier 공식에서 border_weight 제거

**피드백:**
초기 barrier 공식: `crossing_barrier = max(mtn_A, mtn_B) × border_weight`
transfer 단계에서 이미 border_weight가 분배 비율에 반영됨.
barrier에서도 곱하면 과분할 맵에서 산맥 장벽이 이중으로 약해진다.

**이유:**
border_weight가 [변경 06]에서 이미 분배 비율 역할로 변경됐다.
같은 값을 두 번 반영하면 과분할 맵에서 mountain barrier가 거의 무의미해진다.

**변경 결과:**
```
변경 전:
  crossing_barrier = max(mtn_A, mtn_B) × border_weight
  ridge_continuity = mtn_A × mtn_B × border_weight

변경 후:
  crossing_barrier = max(mtn_A, mtn_B)
  ridge_continuity = mtn_A × mtn_B × ridge_bonus
  barrier = crossing_barrier + ridge_continuity
  [border_weight 완전 제거]
```

---

### [변경 09] mountain_strength merge 방식: add → max  ⚠️ [변경 21로 폐기]

**피드백:**
초기 설계에서 `effective = auto + user_boost` 방식.
auto가 높은 산(0.8)에 user_boost(0.5)를 더하면 1.3 → 과증폭.

**이유:**
merge_rules에서 `mountain_strength: max`로 정의했다.
add 방식은 이 원칙과 모순되며 1.0 초과를 허용한다.

**변경 결과:**
```
변경 전: effective = clamp(auto + user_boost, 0.0, 1.0)
변경 후 (당시): effective = max(auto, user_strength)

⚠️ 변경 21에 의해 폐기됨:
  auto_from_elevation 자체가 제거됨 (metadata.heightmap.authoritative=false)
  현재: mountain_strength = user authored only
```

---

### [변경 10] 아열대 고압대 moisture drain 추가

**피드백:**
사하라, 아라비아, 호주 내륙 같은 대형 사막은 산맥 비그늘만으로 생기지 않는다.
핵심 원인: 적도에서 상승한 공기가 위도 20~30도에서 하강하면서 건조해진다.
현재 모델은 30도 경계 차단만 있어 이 효과가 없다.

**이유:**
하강기류는 구름 형성을 억제하고 대기를 안정화한다.
이것이 없으면 사막 생성이 산맥 위치에만 의존하게 된다.
산맥이 없는 대륙에서는 사막이 생기지 않는 비현실적 결과가 나온다.

**변경 결과:**
```
추가된 처리 (STEP 4, pressure_bands 연결):
  subtropical_strength = gaussian(abs_lat, center=25, width=10)
  moisture  *= 1 - (drain_strength × subtropical_strength)
  rainfall  *= 1 - (suppression_strength × subtropical_strength)

초기값:
  drain_strength: 0.06
  suppression_strength: 0.20

적용 위도: 15~35° (gaussian으로 자연스러운 경계)
```

---

### [변경 11] ITCZ와 아열대 고압대 통합: vertical_motion_index

**피드백:**
ITCZ(적도 상승기류)와 아열대 고압대(하강기류)를 별도 STEP에서 패치형으로 처리하면
같은 Hadley 순환의 양끝을 쪼개는 구조가 된다.
"STEP 2에서 압력대 효과, STEP 4에서 ITCZ 보정"은 통일성이 없다.

**이유:**
물리적으로 둘은 하나의 대기 순환 현상이다.
통합하면 코드가 단순해지고 경계가 자연스러워진다.

**변경 결과:**
```
추가된 개념: vertical_motion_index
  < 0: 상승기류 → 강수 증가 (ITCZ, 위도 0~10°)
  > 0: 하강기류 → 건조화 (아열대 고압대, 위도 15~35°)

ITCZ gaussian:
  이전: hard rectangular band (위도 0~10° 균일 적용)
  이후: gaussian(abs_lat, center=0, sigma=5) → 적도 중심에서 자연스럽게 감소
```

---

### [변경 12] 2-season pass 추가 (여름/겨울)

**피드백:**
사바나, 몬순, 지중해성 기후는 연평균 강수량만으로 구분할 수 없다.
예: 사바나(우기/건기 뚜렷) vs 열대우림(연중 강수)은 연평균이 비슷해도 기후가 완전히 다르다.

**이유:**
월별 시뮬레이션은 게임 모드에서 오버킬.
하지만 여름/겨울 2계절만으로도 계절성의 핵심을 포착할 수 있다.

**변경 결과:**
```
추가된 계산:
  summer pass: 여름 온도, 강수, moisture 계산
  winter pass: 겨울 온도, 강수, moisture 계산

추가된 출력값:
  annual_rainfall
  summer_rainfall
  winter_rainfall
  wet_season_rainfall
  dry_season_rainfall
  rainfall_seasonality
  dry_season_strength
  mean_temperature
  summer_temperature
  winter_temperature
```

---

### [변경 13] rainfall normalization 추가 (v0.6)

**피드백:**
v0.2.5 실행 결과:
  rainfall 중앙값: 0.00045
  rainfall 90% 지점: 0.0275
  기존 threshold: desert < 0.25
  결과: 57,995 / 58,376 province = 99.35% 사막

이 수치로 biome을 판정하면 맵 전체가 사막이 된다.

**이유:**
raw rainfall은 시뮬레이션 중간 계산값이지 최종 강수량이 아니다.
province별 상대적 습도 차이가 중요하며, 절대값은 파라미터 튜닝으로 스케일이 달라진다.

**변경 결과:**
```
추가된 단계 (v0.6):
  rainfall_absolute = raw_rainfall × world_scale
  rainfall_relative = percentile_rank(raw_rainfall)
  final_rainfall = mix(rainfall_absolute, rainfall_relative, relative_weight)
  relative_weight 권장: 0.6~0.8

순수 백분위 금지 이유:
  의도적으로 건조한 세계에서도 상위 20%가 강제로 숲이 되어버림
  절대값을 일부 유지해야 "전체적으로 건조한 세계"가 표현 가능

raw rainfall → biome 직접 판정 절대 금지
반드시 v0.6 normalization 거친 후 판정
```

---

### [변경 14] aridity_index 추가

**피드백:**
같은 강수량(예: 300mm/year)이어도:
  사하라(평균기온 30°C) → 사막
  시베리아(평균기온 -5°C) → 냉대 건조지 또는 타이가
rainfall 단독으로는 이 구분이 불가능하다.

**이유:**
사막은 비가 적어서 생기는 게 아니라, 비에 비해 증발산이 너무 크기 때문에 생긴다.
같은 강수량이어도 더운 지역은 사막, 추운 지역은 툰드라/타이가가 된다.

**변경 결과:**
```
추가된 계산:
  PET = max(0, temperature + 5) × pet_coefficient  (단순 근사)
  aridity_index = final_rainfall / PET

  aridity < 0.2:    desert
  0.2~0.5:          steppe/savannah (온도로 세분)
  0.5~1.0:          grassland/plains
  1.0+:             forest/rainforest (온도로 세분)

soil_moisture = final_rainfall + river_bonus + basin_bonus - PET
  (biome 최종 판정 직전 레이어)
```

---

### [변경 15] Köppen-lite 중간 분류 추가

**피드백:**
직접 biome if문을 만들면:
  - 조건 겹침 (두 조건을 동시에 만족하는 province)
  - 빈틈 (어느 조건도 만족하지 않는 province)
  - 경계 province 처리 모호

**이유:**
계절별 온도×강수 기반 분류는 Köppen-Geiger가 이미 풀어놓은 문제다.
직접 구현하면 같은 문제를 다시 풀게 된다.

**변경 결과:**
```
biome 판정 순서 변경:
  변경 전: temperature × rainfall → biome (직접 if문)
  변경 후: temperature × rainfall × seasonality → Köppen-lite → biome → vic3_terrain

주요 Köppen-lite 클래스:
  Af:  열대우림  (연중 다습)
  Am:  몬순
  Aw:  사바나    (건기 있음)
  BWh: 고온 사막
  BWk: 한랭 사막
  BSh: 고온 스텝
  BSk: 한랭 스텝
  Csa: 지중해성
  Cfa: 온난 습윤
  Dfa: 냉대 습윤
  ET:  툰드라
  EF:  빙설
```

---

### [변경 16] rivers.png → 파이프라인 출력물로 변경

**피드백:**
초기 설계: rivers.png = 유저가 제공하는 고정 입력 파일
실제 상황: rivers.png는 AI가 임시 생성한 것이며 고정 입력이 아님
유저가 원하는 것: 주요 강은 직접 지정하고, 나머지는 자동 생성

**이유:**
강은 지형과 기후의 결과물이다.
유저가 모든 강을 직접 그리는 것은 과도한 작업이다.
anchor + 자동 보충이 가장 자연스럽다.

**변경 결과:**
```
rivers.png 위치 변경:
  변경 전: 사용자 입력 파일 (map_data/rivers.png)
  변경 후: 파이프라인 출력 파일 (outputs/rivers.png)

강 생성 알고리즘 (v0.5):
  1. flow_direction: synthetic_flow_potential 낮은 방향 (실제 DEM 없으면 합성값 사용)
     synthetic_flow_potential = coast_distance_normalized
                              + mountain_strength × mountain_flow_bonus
                              + elevation_hint_flow_bonus
  2. rainfall-weighted accumulation:
       synthetic_flow_potential 내림차순 정렬
       높은 potential → 낮은 potential 방향 1패스
       각 province: (자기 rainfall + 받은 물) → 하류 전달
  3. threshold → 강 (하나의 노브로 강 밀도 조절)
  4. lake_seed=true province → is_flow_sink (흐름 종착점)
     [pit 자동 탐지는 실제 DEM 확정 후. 현재는 lake_seed 수동 지정만 사용]
  5. river_seed anchor: threshold 무시, 무조건 강

depression fill 생략 이유:
  depression fill은 DEM 처리에서 유일하게 복잡한 부분
  pit을 메우는 대신 호수로 처리하면 이 단계가 사라짐
  게다가 호수는 콘텐츠로 자연스럽다 (카스피해 케이스)

performance:
  province_graph 위에서 실행 (래스터가 아님)
  정렬 O(n log n) + 선형 1패스 = 58829 province에서 1초 미만
```

---

### [변경 17] 3티어 override 시스템

**피드백:**
초기 설계: locked=true → 시뮬에서 완전 제외
문제: locked 산맥 province가 시뮬에서 빠지면 이웃의 비그늘/barrier가 작동하지 않음
= "기후 구멍" 발생

추가 피드백:
locked와 climate_lock을 위계(ladder)가 아닌 독립 플래그로 봐야 함
  locked=false, climate_lock=true 조합이 매우 유용하기 때문
  ("물리는 강제하되 라벨은 창발" = "강제로 춥게 하되 biome은 자연히 tundra로")

**이유:**
override의 "최우선"은 출력 라벨에 대한 것이지 파이프라인 참여 여부가 아니다.
물리는 끝까지 참여하고, 라벨만 마지막에 덮어써야 주변 province가 올바른 기후를 받는다.

**변경 결과:**
```
3티어 시스템:

[티어 1] constraints (입력 재료)
  ├─ 크기 입력: mountain_strength, moisture_bonus, temperature_delta
  │   → 계산 재료. 라벨 강제 없음.
  └─ presence 앵커: river_seed, wetland_seed
      → 존재 자체를 강제. 주변 기후는 창발.
      → river_seed: threshold 무시, 무조건 강
      → river_seed + force_terrain=desert = 가능! (나일강 케이스)
         강은 rivers.png 채널, terrain은 라벨 채널 → 독립

[티어 2] locked (라벨 강제, 물리 참여)
  → 파이프라인 정상 계산 (barrier/ET/runoff 이웃에 영향)
  → 최종 terrain/biome 라벨만 force 값으로 덮어씀
  → "마법으로 평평하지만 바람은 막는 산" 가능:
     mountain_strength=1.0 + locked=true + force_terrain=plains
     = 라벨은 plains, 이웃 비그늘은 정상 작동

[티어 3] climate_lock (물리 강제, locked와 독립 플래그)
  → 기본: force_temp/moisture/rainfall로 물리값 강제 후 이웃에 영향
  → 판타지에서 강력: "저주받은 한랭 지역이 주변을 얼림"

[별도 플래그] exclude_from_sim (시뮬레이션 참여 제어)
  → climate_lock의 하위 옵션이 아님
  → 기후 계산에는 참여하지 않지만 수문 graph에서는 상류 유량을 하류로 전달
  → climate_lock=true와 동시 사용하면 ERROR

4가지 조합:
  locked=false, climate_lock=false  → 순수 constraint (입력 재료)
  locked=true,  climate_lock=false  → 라벨 강제, 물리 창발
  locked=false, climate_lock=true   → 물리 강제, 라벨 창발  ← 강력한 조합
  locked=true,  climate_lock=true   → 전부 강제
```

---

### [변경 18] climate_lock 동작 규칙 확정

세 force 필드는 적용 시점이 서로 다르다. 동일하게 처리하면 안 된다.

**규칙 1: force_temp는 각 계절 온도 계산 후, capacity 계산 전에 재고정**
```
summer/winter 양쪽에 동일값을 브로드캐스트한다.
temperature를 강제한 뒤 해당 온도로 moisture capacity를 계산한다.
```

**규칙 2: force_moisture는 매 moisture iteration 후 재고정**
```
Dirichlet 경계조건으로 작동한다.
1회만 설정하면 다음 iteration에서 이웃 전파가 값을 덮어쓰므로 매번 재고정한다.
```

**규칙 3: force_rainfall은 각 spin-up year·각 계절 강수 계산 완료 후 1회 적용**
```
ITCZ/지형성 강수/transit loss 계산 완료 후 적용한다.
moisture iteration 내부에서는 적용하지 않는다.
ET/runoff 계산 전, rainfall normalization 전에 raw 단위로 적용한다.
매 iteration 덮어쓰면 지형성 강수 등 누적 물리 결과가 삭제된다.
```

**규칙 4: 활성 플래그 없는 force 값은 자동 활성화하지 않음**
```
force_temp/moisture/rainfall이 있지만 climate_lock=false → WARNING 후 무시
force_terrain/biome이 있지만 locked=false → WARNING 후 무시
입력 실수를 강력한 override로 자동 승격시키지 않는다.
```

---

### [변경 19] ET 기반 재순환

**피드백:**
초기안: recycling_source = rainfall × recycling_efficiency
실제로 대기로 돌아가는 물은 rainfall이 아니라 증발산(ET)에서 나온다.
rainfall → recycling 경로는 물수지와 맞지 않는다.

**이유:**
증발산(ET)이 대기 수분의 재공급원이다.
rainfall을 직접 재순환하면 물수지가 맞지 않고 폭주 위험이 있다.

**변경 결과:**
```
변경 전: recycling_source = rainfall × recycling_efficiency
변경 후: recycling_source = ET × recycling_fraction

ET 계산:
  available_water = rainfall + soil_water_storage
  bare_soil_evap = PET × coeff × (1 - vegetation_proxy) × (1 - lake_fraction)
  transpiration  = PET × coeff × vegetation_proxy
  open_water_evap = PET × factor × lake_fraction
  ET = min(available_water, bare_soil_evap + transpiration + open_water_evap)

재순환 댐핑 (폭주 방지):
  raw_recycling = ET × recycling_fraction
  capped = min(raw_recycling, ET × max_recycling_share)
  recycling_source = lerp(prev_recycling_source, capped, relaxation_alpha)
```

---

### [변경 20] 연간 spin-up 루프 추가

**피드백:**
단순히 summer → winter → summary를 1회 실행하면
첫 번째 여름의 토양수분 초기값에 결과가 의존한다.
정상적인 기후는 매년 같은 패턴으로 반복되는 정상 궤도여야 한다.

**이유:**
초기값 의존성을 제거해야 "녹색 사하라 vs 사막 사하라" 같은 다중 평형 문제를 피할 수 있다.
정규 초기조건에서 출발해 수렴까지 반복하면 재현 가능한 결과를 얻는다.

**변경 결과:**
```
추가된 구조:
  for annual_spinup in 1..max_years:
    start_storage = soil_water_storage
    summer 계산 → soil_water_storage 이월
    winter 계산 → soil_water_storage 이월
    annual_residual = |soil_water_storage - start_storage|
    if annual_residual < annual_epsilon: break

정규 초기 상태 (canonical initial state):
  land recycling OFF
  vegetation_proxy 최소값
  soil_water_storage dry baseline
  ocean/coastal/lake/wetland source만 사용
  → "건조한 맨땅에서 녹색으로 자라는 방향"으로 일관되게 출발
```

---

## 3. 최종 확정 알고리즘

```
[STEP 0] province_graph 생성 (1회 전처리)
  provinces.png → province_graph.json (topology, coastal, center, area)
                  topology 권위: provinces.png / heightmap은 선택적 metadata
heightmap.png → 로드 후 metadata.heightmap.authoritative=false 기록
                  기후 계산 직접 사용 금지 (AI 임시 heightmap)

[STEP 1] bootstrap_fields 생성 (constraints 변경 시 재생성)
  coast_distance_normalized:
    해안 육지 province 기점 land-only BFS → 정규화
    바다 province는 계산 대상 제외 / 해안 육지 province = 거리 0 기점
  synthetic_elevation:
    max(mountain_strength × 1500m, elevation_hint_m)
    none=0m / lowland=100m / upland=500m / highland=1200m / mountain=2000m
  synthetic_flow_potential:
    coast_dist_normalized + mountain_strength × mountain_flow_bonus
    + elevation_hint_flow_bonus
    최대 범위: 1.0 + mountain_flow_bonus + max(elevation_hint_flow_bonus)
  continentality: coast_distance_normalized (계절 기온 진폭 전용)
  lake_seed province: is_flow_sink=true (국소 sink, 전역 최저점 아님)
  출력: cache/bootstrap_fields.json (graph_hash + constraints_hash + params_hash 포함)

[STEP 2] 기본 기후 필드 초기화
  base_temperature = 위도 기반
  temperature -= lapse_rate × synthetic_elevation  [DEM 아닌 합성 고도]
  moisture_capacity = exp(0.07 × (temp - 15))
  mountain_strength = province_constraints.mountain_strength  [user authored only]
  [auto_from_elevation 폐기: 변경 21 참조]

[STEP 3] 정규 초기 상태 (canonical initial state)
  dry baseline에서 출발

[STEP 4] 연간 spin-up 루프 (수렴까지)
  for each year:
    summer pass + winter pass
    soil_water_storage 이월
    if converged: break

[STEP 5-내부] 계절별 계산
  season_temperature
  vertical_motion_index (ITCZ 상승 + 아열대 하강 통합)
  wind_vector (위도대별, ±4도 보간)
  subtropical_drain (위도 15~35°, gaussian)

[STEP 6-내부] moisture relaxation (수렴까지 반복)
  moisture source (바다/해안/호수/ET 재순환)
  moisture 전파 (delta priority queue)
    wind_weight = max(0.05, min(dot_A, dot_B))
    transfer = delta_A × export_fraction × (flow_weight / flow_total)
    mountain barrier 삽입
    blocked → orographic_rain → rainfall[B]
    passed → transit loss → rainfall[B], net → moisture[B]
  ET 계산
  runoff 계산
  recycling damping

[STEP 7] 계절 결과 합성
  annual_rainfall, summer/winter_rainfall, dry_season_strength 등

[STEP 8] river/lake 생성 (v0.5)
  synthetic_flow_potential 기반 flow direction
  rainfall-weighted flow accumulation
  우선순위: river_path > river_seed > synthetic filler
  lake_seed=true → is_flow_sink 처리 (pit 자동 탐지는 실제 DEM 후)
  rivers.png 출력

[STEP 9] rainfall normalization (v0.6)
  final_rainfall = mix(absolute, percentile, weight)

[STEP 10] aridity_index + soil_moisture (v0.7)
  PET = max(0, temp + 5) × coeff
  aridity_index = final_rainfall / PET
  soil_moisture = final_rainfall + river_bonus + basin_bonus - PET

[STEP 11] Köppen-lite → biome → vic3_terrain (v0.7)
  온도 × 강수 × 계절성 → Köppen-lite class
  aridity_index + soil_moisture → 보정
  terrain_lookup.csv → vic3_terrain

[STEP 12] fantasy / override 최종 적용
  locked: 라벨만 덮어씀
  climate_lock:
    force_temp → 각 계절 온도 계산 후, capacity 계산 전
    force_moisture → 매 moisture iteration 후 Dirichlet 재고정
    force_rainfall → 각 계절 강수 완료 후 1회, ET/runoff 전
  exclude_from_sim:
    기후 계산 제외, 자체 rainfall/ET/runoff=0
    수문 graph에서는 상류 discharge를 하류로 전달
```

---

## 4. 최종 스키마

```yaml
# province_constraints.yaml
province_constraints:
  xAABBCC:
    # 크기 입력 (계산 재료, 라벨 강제 없음)
    mountain_strength: 0.0   # 0.0~1.0, user authored only, auto 파생 금지
    elevation_hint: none     # none/lowland/upland/highland/mountain → synthetic_elevation
    moisture_bonus: 0.0      # raw 단위
    temperature_delta: 0.0   # °C, raw (정규화 전)
    rainfall_delta: 0.0      # raw 단위

    # presence 앵커 (존재 강제, 기후는 창발)
    river_seed: false        # true → threshold 무시, 무조건 강
    river_major: false       # true → 간선하천 우선순위
    river_path: []           # 방향 힌트 (D8 무시 구간)
    lake_seed: false         # true → is_flow_sink, 실제 DEM 전까지 수동 지정
    wetland_seed: false

    # 판타지 soft nudge
    fantasy_zone: null       # biome 라벨 힌트

# province_overrides.yaml
province_overrides:
  xAABBCC:
    # 라벨 강제 (물리는 정상 참여)
    locked: false
    force_terrain: null      # vic3_terrain 값
    force_biome: null        # biome 값

    # 물리 강제 (locked와 독립 플래그)
    climate_lock: false
    force_temp: null         # °C, 각 계절 temperature 계산 후 재고정
    force_moisture: null     # raw 단위, 매 moisture iteration 후 재고정
    force_rainfall: null     # raw 단위, 각 계절 강수 완료 후 1회

    # 시뮬레이션 참여 제어 (climate_lock과 독립)
    exclude_from_sim: false  # 기후 제외, 수문 유량은 통과
```

---

## 5. 파이프라인 버전 순서

```
v0.1  province_graph 생성 (전처리 캐시)               ✓ 완료
v0.2  moisture 전파 (delta priority queue)            ✓ 완료 (v0.2.5)
v0.3  mountain barrier (orographic rain / leeward)    ✓ 문서 완료
v0.4  pressure_bands + subtropical drain + 2-season + vertical_motion
v0.5  river/lake 생성 (flow accumulation + anchor)
v0.6  rainfall normalization (절대값 + 백분위 혼합)
v0.7  aridity_index + Köppen-lite + soil_moisture + biome → terrain
v0.8+ ocean_reach / rain_shadow_memory / basin_detection
         [continentality는 STEP 1 bootstrap_fields에서 처리 — v0.4 이전]
```

---

## 6. 검증 규칙

```
1. locked=true인데 force_terrain/biome 둘 다 없음 → WARNING (no-op)

2. exclude_from_sim=true province:
   - temperature/moisture/rainfall/ET 계산에 참여하지 않음
   - 자체 local_runoff = 0
   - flow accumulation에는 참여
   - 상류 discharge를 수신하여 하류로 전달
   - climate_lock=true와 함께 사용하면 ERROR

3. river_seed=true + force_terrain=desert → 충돌 아님
   강(rivers.png)과 terrain 라벨은 독립 출력 채널

4. 단위/범위:
   mountain_strength: 0.0~1.0
   force_temp: °C
   force_moisture/rainfall: raw 단위 (STEP 6 정규화 전)
   moisture_capacity: 0.35~2.25

5. raw rainfall → biome 직접 판정 금지
   반드시 v0.6 normalization 후 판정

6. force 값은 필드별 지정 시점에 적용
   - force_temp: 각 계절 temperature 계산 후
   - force_moisture: 매 moisture iteration 후
   - force_rainfall: 각 계절 강수 완료 후 1회만
   - 활성 플래그가 false이면 WARNING 후 무시

7. barrier 계산 시 border_weight 곱하기 금지
   (transfer 단계에서 이미 반영됨)

8. 주 특성/주 모디파이어 부여·제거는 본 기후·지형 파이프라인의
   입력/출력 책임이 아니다.
   해당 기능은 별도 Vic3 모딩 산출물 도구에서 처리한다.
```

---

## 7. 변경 금지 사항

```
[금지 1] raw rainfall → biome 직접 판정
  이유: 99%가 사막이 됨 (v0.2.5에서 검증됨)

[금지 2] locked province 시뮬에서 완전 제외
  이유: 기후 구멍 발생, 이웃 province가 잘못된 기후를 받음
  올바른 방법: 물리 참여, 최종 라벨만 덮어씀

[금지 3] force 값 1회 세팅 후 방치
  이유: 루프가 덮어써서 드리프트 발생
  올바른 방법: 매 iteration 끝마다 Dirichlet 재고정

[금지 4] barrier 계산에 border_weight 곱하기
  이유: transfer 단계에서 이미 반영, 이중 약화 발생
  올바른 방법: crossing_barrier = max(mtn_A, mtn_B) (border_weight 없음)

[금지 5] wind band 경계 hard cutoff
  이유: 지도에 수평 절단선 인공물 발생
  올바른 방법: ±4도 선형 보간

[금지 6] moisture 전파에 border_weight 직접 곱하기 (절대 전달량)
  이유: 58829 과분할 맵에서 내륙 전파 불가
  올바른 방법: border_weight = 분배 비율, export_fraction = 절대 전달량

[금지 7] mountain_strength auto 파생 (heightmap → auto_strength)
  이유: AI 임시 heightmap 신뢰 불가. metadata.heightmap.authoritative=false 상태.
  올바른 방법: mountain_strength = user authored only (province_constraints)
  올바른 방법: 고도 기온 보정은 synthetic_elevation 사용
```

---

## 8. 알려진 한계 (Known Bias)

```
dry-start 편향:
  정규 초기 상태가 건조한 맨땅에서 출발
  반건조 경계 지역이 현실보다 건조하게 나올 수 있음
  → known issue, 문서화 완료

사막 wadi:
  계절평균 모델이라 돌발홍수/일시하천 표현 약함

biome 경계 인공성:
  province 단위 판정이라 경계선이 부드럽지 않음

강 경로 정밀도:
  depression carving 없어 강 경로가 약간 덜 자연스러울 수 있음
  → 중요한 강은 user river_seed anchor로 보완
```

---

### [변경 21] 합성 고도·흐름·대륙성 필드 분리 (C++ 설계)

**피드백:**
AI 임시 heightmap 사용 금지 정책으로 인해 elevation 기반 기능이 전면 의존성 충돌 발생.
`coast_distance`를 elevation proxy로 단순 사용하면:
- 대륙 중심 = 무조건 최고 고도 오판
- 내륙 평원 = 고원으로 오판
- 모든 강이 가장 가까운 해안으로 방사형 하강

**이유:**
continentality(대륙성)와 elevation(고도)은 물리적으로 다른 개념이다.
하나의 합성값으로 합치면 강 방향, 기온 보정, 대륙성 효과가 서로 오염된다.
각 기능에 전용 합성 필드를 만들어야 실제 DEM 확정 후 교체도 깔끔하다.

**변경 결과: 3개 필드 분리**

```
synthetic_flow_potential   → 강 흐름 방향 전용
synthetic_elevation        → lapse rate 기온 보정 전용
continentality             → 계절 기온 진폭 전용
```

**synthetic_flow_potential:**
```
= coast_distance_normalized
  + mountain_strength × mountain_flow_bonus
  + elevation_hint_flow_bonus

낮은 방향으로 강 흐름
우선순위: river_path > river_seed > synthetic filler
```

**synthetic_elevation:**
```
= max(
    mountain_strength × 1500m,   (mountain_average_elevation = 1500m)
    elevation_hint_elevation
  )

elevation_hint 값:
  none:          0m
  lowland:     100m
  upland:      500m
  highland:   1200m
  mountain:   2000m

max 병합 이유:
  mountain_strength는 봉우리 강도, elevation_hint는 지형 범주
  둘 중 더 높은 값이 실제 고도에 가까움
  add 방식은 이중 증폭 위험
```

**continentality:**
```
= normalized_coast_distance

계절 기온 적용:
  latitude_factor = clamp(sin(abs(latitude) × π / 180), 0.0, 1.0)
  seasonal_amplitude = base_seasonal_amplitude × latitude_factor × continentality
  summer_temperature += seasonal_amplitude
  winter_temperature -= seasonal_amplitude

역할 경계:
  담당: 계절 기온 진폭
  비담당: 습도 감쇠 (수분 전파가 전담)
```

**Province Editor 추가 필드:**
```
elevation_hint: none / lowland / upland / highland / mountain
lake_seed: bool   (실제 DEM 전까지 수동 지정)
```

**업그레이드 경로:**
```
기본: synthetic elevation/flow 사용
선택: 사용자가 실제 heightmap 제작했을 때만 DEM 교체
      synthetic_flow_potential → 실제 DEM flow
      synthetic_elevation      → 실제 평균 고도
      continentality           → coast_distance 계속 사용
```

**합성 필드 설계 닫힘. 다음: 구현 + 골든 테스트.**
