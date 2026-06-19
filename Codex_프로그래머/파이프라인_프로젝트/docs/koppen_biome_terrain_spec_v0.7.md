# koppen_biome_terrain_spec v0.7

> `rainfall_normalization_spec_v0.6`의 `final_rainfall`과
> `hydrology_spec_v0.5`의 보정 수문 필드를 사용해
> `aridity_index`, `soil_moisture`, `Koppen-lite`, `biome`, `vic3_terrain`을 확정하는 단계.
>
> 이 단계는 기후·수문 계산의 최종 소비자이며,
> raw rainfall이나 force_rainfall을 다시 해석하지 않는다.

---

## 0. 이 문서의 범위

포함:

```text
aridity_index 최종 계산
soil_moisture 최종 계산
Koppen-lite climate class 산출
biome 산출
vic3_terrain 산출
hydrology overlay 반영 (lake / wetland / salt_flat / river corridor)
synthetic elevation 기반 highland / mountain terrain 반영
fantasy_zone 라벨 처리
locked / force_biome / force_terrain 최종 라벨 override
terrain_lookup.csv 기반 최종 Vic3 terrain 매핑
```

포함하지 않음:

```text
raw rainfall 정규화             → rainfall_normalization_spec_v0.6
rainfall / ET / runoff 계산      → seasonal_climate_spec_v0.4
강 / 호수 / 습지 생성            → hydrology_spec_v0.5
heightmap 직접 해석              → build_province_graph_design_v0.2 / 향후 DEM 단계
mountain_strength 자동 파생      → 금지
force_rainfall 적용              → seasonal_climate_spec_v0.4에서 이미 완료
주 특성 / 주 모디파이어 생성       → 별도 Vic3 모딩 산출물 도구
```

---

## 1. 핵심 설계 원칙

```text
v0.7은 raw rainfall을 읽거나 사용하지 않는다.
biome / terrain 판정은 반드시 final_rainfall 이후에만 수행한다.

Koppen-lite는 직접 만든 8축 if문이 아니라
검증 가능한 기후구분 anchor 역할을 한다.

Koppen-lite class와 최종 terrain은 분리한다.
기후 class가 Af여도 synthetic elevation이 높으면 terrain은 highland/mountain일 수 있다.

soil_moisture는 v0.7에서 처음 확정한다.
v0.5/v0.6의 corrected_ET / river_bonus / lake_fraction은 v0.7 입력값일 뿐이다.
corrected_ET / river_bonus는 final_rainfall 축으로 변환한 뒤 사용한다.

locked / force_biome / force_terrain은 최종 라벨 단계에서만 적용한다.
물리값을 되감거나 rainfall / hydrology를 재계산하지 않는다.
```

책임 경계:

```text
v0.6:
  final_rainfall 생성
  seasonal final rainfall 생성
  corrected_ET / river_bonus / lake_fraction pass-through

v0.7:
  final_rainfall을 소비
  corrected_ET / river_bonus를 scaled field로 변환
  aridity_index / soil_moisture / Koppen-lite / biome / terrain 확정
```

---

## 2. 입력

필수 입력:

| 파일 | 사용 데이터 |
|------|------------|
| `cache/rainfall_normalized.json` | final_rainfall, final_summer_rainfall, final_winter_rainfall, final_wet_season_rainfall, final_dry_season_rainfall, dry_season_strength, rainfall_seasonality, corrected_ET, river_bonus, lake_fraction |
| `cache/seasonal_climate.json` | mean_temperature, summer_temperature, winter_temperature |
| `cache/hydrology.json` | discharge, is_river, is_lake, is_salt_flat, is_wetland, lake_fraction, river_bonus, corrected_ET |
| `cache/bootstrap_fields.json` | synthetic_elevation_m, continentality |
| `cache/province_graph.json` | is_sea, latitude, area_px |
| `province_constraints.yaml` | fantasy_zone |
| `province_overrides.yaml` | locked, force_biome, force_terrain, exclude_from_sim |
| `climate_rules.yaml` | koppen_biome_terrain 섹션 파라미터 |
| `terrain_lookup.csv` | biome / overlay / elevation class → Vic3 terrain 매핑 |

`bootstrap_fields.json`을 읽는 이유:

```text
현재 heightmap.authoritative=false가 기본이다.
따라서 v0.7은 heightmap.png나 graph의 참고 elevation을 직접 terrain 판정에 쓰지 않는다.
highland / mountain 판정은 bootstrap_fields.synthetic_elevation_m을 사용한다.
```

읽지 말아야 하는 파일:

```text
heightmap.png
rivers.png
project_state.json
export_manifest.json
state_constraints.yaml
raw moisture output
province_moisture.json
```

주의:

```text
rivers.png는 v0.5의 선택 출력이며 v0.7 입력이 아니다.
강/호수/습지 여부는 hydrology.json만 기준으로 한다.
```

hydrology pass-through 검증:

```text
rainfall_normalized.json의 corrected_ET / river_bonus / lake_fraction은
v0.6이 hydrology.json에서 전달한 pass-through 값이다.

v0.7은 hydrology.json 원본과 rainfall_normalized pass-through 값이
일치하는지 검증한다.

불일치 시 v0.6 산출물 무결성 오류로 보고 ERROR 처리한다.
```

---

## 3. 출력

필수 출력:

```text
cache/koppen_biome_terrain.json
```

출력 필드:

| 필드 | 형태 | 설명 |
|------|------|------|
| `corrected_ET_scaled` | float | final_rainfall 축으로 변환한 ET |
| `river_bonus_scaled` | float | final_rainfall 축으로 변환한 river_bonus |
| `aridity_index` | float | final_rainfall / corrected_ET_scaled |
| `soil_moisture` | float | 최종 토양수분 지수 |
| `koppen_base_class` | string | elevation override 전 기후 class |
| `koppen_class` | string | highland 반영 후 최종 Koppen-lite class |
| `biome_climate_base` | string | Koppen 기반 1차 biome |
| `biome_physical` | string | hydrology overlay 반영 후 biome |
| `biome` | string | 최종 biome 라벨 |
| `vic3_terrain_base` | string | locked 전 terrain |
| `vic3_terrain` | string | 최종 Vic3 terrain |
| `elevation_class` | string | lowland/upland/highland/mountain |
| `hydrology_overlay` | string/null | lake/wetland/salt_flat/river_corridor |
| `fantasy_zone` | string/null | 입력 fantasy_zone |
| `is_locked_override_applied` | bool | locked 라벨 override 적용 여부 |
| `warnings` | list[string] | province별 경고 |

예시:

```json
{
  "schema_version": "koppen_biome_terrain.v0.7",
  "source": {
    "rainfall_normalized": "cache/rainfall_normalized.json",
    "seasonal_climate": "cache/seasonal_climate.json",
    "hydrology": "cache/hydrology.json",
    "bootstrap_fields": "cache/bootstrap_fields.json",
    "province_graph": "cache/province_graph.json",
    "province_constraints": "path/to/province_constraints.yaml",
    "province_overrides": "path/to/province_overrides.yaml",
    "terrain_lookup": "config/terrain_lookup.csv"
  },
  "hash": {
    "rainfall_normalized_hash": "sha256:...",
    "seasonal_hash": "sha256:...",
    "hydrology_hash": "sha256:...",
    "bootstrap_hash": "sha256:...",
    "graph_hash": "sha256:...",
    "constraints_hash": "sha256:...",
    "overrides_hash": "sha256:...",
    "terrain_lookup_hash": "sha256:...",
    "params_hash": "sha256:..."
  },
  "provinces": {
    "xAABBCC": {
      "corrected_ET_scaled": 0.89,
      "river_bonus_scaled": 0.06,
      "aridity_index": 0.82,
      "soil_moisture": 0.46,
      "koppen_base_class": "Aw",
      "koppen_class": "Aw",
      "biome_climate_base": "savanna",
      "biome_physical": "river_corridor",
      "biome": "river_corridor",
      "vic3_terrain_base": "savanna",
      "vic3_terrain": "savanna",
      "elevation_class": "lowland",
      "hydrology_overlay": "river_corridor",
      "fantasy_zone": null,
      "is_locked_override_applied": false,
      "warnings": []
    }
  }
}
```

sea province:

```text
province_graph.provinces[color].is_sea=true인 province는 출력 대상에서 제외한다.
```

주의:

```text
province_graph.v0.2에는 is_lake가 없다.
lake / salt_flat / wetland 여부는 hydrology.json만 기준으로 한다.
```

---

## 4. 처리 순서

```text
1. 입력 파일 로드 및 schema/hash 검증
2. land target 목록 구성 (province_graph.is_sea=false)
3. v0.6 final rainfall 필드 검증
4. v0.5 hydrology 필드 검증
5. temperature 필드 검증
6. corrected_ET_scaled 계산
7. river_bonus_scaled 계산
8. aridity_index 계산
9. soil_moisture 계산
10. elevation_class 계산
11. Koppen-lite base class 계산
12. highland class 보정
13. biome_climate_base 계산
14. hydrology overlay 반영 → biome_physical 계산
15. terrain_lookup.csv로 vic3_terrain_base 계산
16. fantasy_zone 라벨 처리
17. locked / force_biome / force_terrain 최종 override 적용
18. validation
19. koppen_biome_terrain.json 원자적 저장
20. debug output 저장
```

중요 순서:

```text
locked override는 가장 마지막.
fantasy_zone은 locked override보다 먼저.
hydrology overlay는 terrain_lookup 전에 biome 후보에 반영.
```

---

## 5. 파생 기후 지표

### 5-0. 단위 정렬

`final_rainfall`은 v0.6의 정규화 강수 지수다.
반면 `corrected_ET`와 `river_bonus`는 v0.5 hydrology에서 온 raw/수문 계열 값이다.

따라서 v0.7은 다음 값을 먼저 계산한다.

```text
corrected_ET_scaled
river_bonus_scaled
```

주의:

```text
corrected_ET를 final_rainfall로 직접 나누거나 빼지 않는다.
river_bonus를 final_rainfall에 직접 더하지 않는다.

aridity_index와 soil_moisture는 항상 scaled 값을 사용한다.
```

#### corrected_ET_scaled

```text
corrected_ET_scaled = clamp(
  corrected_ET × et_world_scale,
  et_clamp_min,
  et_clamp_max
)
```

기본:

```text
et_world_scale = 1.0
et_clamp_min = 0.0
et_clamp_max = 1.5
```

의미:

```text
corrected_ET_scaled는 final_rainfall과 같은 판정 축으로 변환한 ET 지수다.
기본 범위는 final_rainfall의 기본 범위와 맞춰 0.0~1.5로 둔다.
```

#### river_bonus_scaled

```text
river_bonus_scaled = clamp(
  river_bonus × river_bonus_world_scale,
  river_bonus_clamp_min,
  river_bonus_clamp_max
)
```

기본:

```text
river_bonus_world_scale = 1.0
river_bonus_clamp_min = 0.0
river_bonus_clamp_max = 0.5
```

의미:

```text
river_bonus_scaled는 soil_moisture 보정 전용 지수다.
강 보정이 biome 전체를 강제로 습윤화하지 않도록 기본 상한은 final_rainfall보다 낮게 둔다.
```

### 5-1. aridity_index

```text
aridity_index = final_rainfall / max(corrected_ET_scaled, epsilon)
```

입력:

```text
final_rainfall: rainfall_normalized.json
corrected_ET: hydrology.json 또는 rainfall_normalized pass-through 값
corrected_ET_scaled: v0.7에서 계산한 ET 지수
```

동일성 검증:

```text
rainfall_normalized.corrected_ET[color] != hydrology.corrected_ET[color]
→ ERROR
```

0 처리:

```text
if corrected_ET_scaled <= epsilon and final_rainfall <= epsilon:
  aridity_index = 0.0
elif corrected_ET_scaled <= epsilon:
  aridity_index = aridity_cap
else:
  aridity_index = final_rainfall / corrected_ET_scaled
```

기본:

```text
epsilon = 1e-6
aridity_cap = 3.0
```

### 5-2. soil_moisture

기본식:

```text
soil_moisture_raw =
  final_rainfall
  + river_bonus_scaled
  + lake_fraction × lake_moisture_bonus
  + wetland_bonus
  - corrected_ET_scaled
```

wetland_bonus:

```text
if hydrology.is_wetland[color]:
  wetland_bonus = wetland_seed_soil_bonus
else:
  wetland_bonus = 0.0
```

정규화:

```text
soil_moisture = clamp(
  (soil_moisture_raw - soil_moisture_min) /
  (soil_moisture_max - soil_moisture_min),
  0.0,
  soil_moisture_cap
)
```

기본 파라미터:

```text
lake_moisture_bonus = 0.25
wetland_seed_soil_bonus = 0.20
soil_moisture_min = -1.0
soil_moisture_max = 1.0
soil_moisture_cap = 1.5
```

주의:

```text
river_bonus는 rainfall에 더하지 않는다.
soil_moisture 보정 채널에서만 사용한다.
soil_moisture 계산에는 river_bonus 원값이 아니라 river_bonus_scaled를 사용한다.

corrected_ET 원값은 soil_moisture에서 직접 빼지 않는다.
soil_moisture 계산에는 corrected_ET_scaled를 사용한다.

lake_fraction은 기후 강수를 늘리지 않는다.
토양수분 / 수면 인접 효과만 반영한다.

basin_bonus는 v0.7 입력에 없으므로 사용하지 않는다.
향후 basin_detection 도입 시 별도 필드로 추가한다.
```

---

## 6. elevation_class

입력:

```text
bootstrap_fields.synthetic_elevation_m
```

기본 분류:

```text
if synthetic_elevation_m >= mountain_threshold_m:
  elevation_class = "mountain"
elif synthetic_elevation_m >= highland_threshold_m:
  elevation_class = "highland"
elif synthetic_elevation_m >= upland_threshold_m:
  elevation_class = "upland"
else:
  elevation_class = "lowland"
```

기본 파라미터:

```text
upland_threshold_m = 500
highland_threshold_m = 1200
mountain_threshold_m = 1800
```

주의:

```text
이 값은 현재 synthetic elevation 기준 threshold다.
현실 절대 고도 임계값이 아니다.
heightmap.authoritative=true가 도입되면 threshold를 재검토한다.
```

---

## 7. Koppen-lite 분류

### 7-1. 목적

Koppen-lite는 최종 biome의 기후 anchor다.
직접 만든 임의 8축 규칙 대신 다음 입력만 사용한다.

```text
mean_temperature
summer_temperature
winter_temperature
final_rainfall
final_summer_rainfall
final_winter_rainfall
final_dry_season_rainfall
dry_season_strength
aridity_index
```

주의:

```text
이 문서의 Koppen-lite는 v0.6 normalized rainfall 단위를 사용한다.
실제 mm 기반 Koppen-Geiger 공식과 1:1 동일하지 않다.
단, 계절 강수, 건조 B threshold, 온도 class의 구조는 Koppen-Geiger를 anchor로 한다.
```

### 7-2. 처리 우선순위

```text
1. B: dry climates
2. E: polar / tundra
3. A: tropical
4. C: temperate
5. D: continental / boreal
6. fallback: ERROR
```

이유:

```text
Koppen 계열에서 B(건조)는 온도대보다 먼저 판정해야 한다.
그렇지 않으면 더운 사막이 tropical/temperate로 오분류된다.
```

### 7-3. B dry threshold

계절 강수 분포에 따라 건조 판정 임계값을 조정한다.

```text
summer_share = final_summer_rainfall / max(final_rainfall, epsilon)
winter_share = final_winter_rainfall / max(final_rainfall, epsilon)
```

임계 보정:

```text
if summer_share >= summer_dominant_threshold:
  b_threshold = b_base_threshold × b_summer_rain_multiplier
elif winter_share >= winter_dominant_threshold:
  b_threshold = b_base_threshold × b_winter_rain_multiplier
else:
  b_threshold = b_base_threshold × b_even_rain_multiplier
```

기본 파라미터:

```text
b_base_threshold = 0.50
b_summer_rain_multiplier = 1.15
b_even_rain_multiplier = 1.00
b_winter_rain_multiplier = 0.85
summer_dominant_threshold = 0.70
winter_dominant_threshold = 0.70
```

판정:

```text
if aridity_index < b_threshold × desert_fraction:
  group = "BW"  # desert
elif aridity_index < b_threshold:
  group = "BS"  # steppe
else:
  not B
```

기본:

```text
desert_fraction = 0.50
```

hot/cold suffix:

```text
if mean_temperature >= b_hot_threshold_c:
  suffix = "h"
else:
  suffix = "k"
```

기본:

```text
b_hot_threshold_c = 18.0
```

예시:

```text
BWh = hot desert
BWk = cold desert
BSh = hot steppe
BSk = cold steppe
```

주의:

```text
B threshold는 v0.7 검증의 핵심이다.
사하라/아라비아/호주 내륙/중앙아시아 테스트에서 가장 먼저 확인한다.
```

### 7-4. E polar / tundra

```text
if summer_temperature < ice_cap_summer_threshold:
  koppen_base_class = "EF"
elif summer_temperature < tundra_summer_threshold:
  koppen_base_class = "ET"
```

기본:

```text
ice_cap_summer_threshold = 0.0
tundra_summer_threshold = 10.0
```

### 7-5. A tropical

```text
if winter_temperature >= tropical_coldest_threshold:
  group = "A"
```

기본:

```text
tropical_coldest_threshold = 18.0
```

subtype:

```text
if dry_season_strength <= tropical_af_dry_strength_max:
  koppen_base_class = "Af"
elif final_dry_season_rainfall >= tropical_monsoon_dry_rain_min:
  koppen_base_class = "Am"
else:
  koppen_base_class = "Aw"
```

기본:

```text
tropical_af_dry_strength_max = 0.25
tropical_monsoon_dry_rain_min = 0.15
```

### 7-6. C temperate / D continental

group:

```text
if summer_temperature >= temperate_warmest_min:
  if winter_temperature > continental_winter_threshold:
    group = "C"
  else:
    group = "D"
```

기본:

```text
temperate_warmest_min = 10.0
continental_winter_threshold = 0.0
```

precipitation subtype:

```text
if dry_season_strength <= no_dry_season_strength_max:
  precip_suffix = "f"
elif final_summer_rainfall < final_winter_rainfall:
  precip_suffix = "s"  # dry summer / winter rain, Mediterranean type
else:
  precip_suffix = "w"  # dry winter / summer rain, monsoon-like type
```

temperature subtype:

```text
if summer_temperature >= hot_summer_threshold:
  temp_suffix = "a"
elif summer_temperature >= warm_summer_threshold:
  temp_suffix = "b"
else:
  temp_suffix = "c"
```

기본:

```text
no_dry_season_strength_max = 0.25
hot_summer_threshold = 22.0
warm_summer_threshold = 10.0
```

결과:

```text
Cfa, Cfb, Csa, Csb, Cwa, Cwb
Dfa, Dfb, Dfc, Dsa, Dsb, Dsc, Dwa, Dwb, Dwc
```

### 7-7. highland 보정

Koppen climate base와 highland terrain을 모두 보존한다.

```text
koppen_base_class = 위 7-3~7-6에서 계산한 class

if elevation_class == "mountain":
  koppen_class = "H"
elif elevation_class == "highland" and summer_temperature < highland_cool_summer_threshold:
  koppen_class = "H"
else:
  koppen_class = koppen_base_class
```

기본:

```text
highland_cool_summer_threshold = 18.0
```

이유:

```text
열대 고산이 단순 Af/Aw로만 남는 문제를 방지한다.
단, 원래 기후 class는 koppen_base_class에 남겨 검증 가능하게 한다.
```

---

## 8. biome 판정

### 8-1. climate base biome

`koppen_class`를 1차 biome인 `biome_climate_base`로 매핑한다.

기본 매핑:

| Koppen-lite | biome_climate_base |
|-------------|------------|
| `Af` | rainforest |
| `Am` | monsoon_forest |
| `Aw` | savanna |
| `BWh` | hot_desert |
| `BWk` | cold_desert |
| `BSh` | hot_steppe |
| `BSk` | cold_steppe |
| `Csa`, `Csb` | mediterranean |
| `Cfa`, `Cwa` | temperate_forest |
| `Cfb`, `Cwb` | temperate_forest |
| `Dfa`, `Dfb`, `Dwa`, `Dwb` | boreal_forest |
| `Dfc`, `Dsc`, `Dwc` | taiga |
| `ET` | tundra |
| `EF` | ice |
| `H` | highland |

주의:

```text
이 표는 기본 fallback이다.
최종 Vic3 terrain은 terrain_lookup.csv가 authoritative하다.
```

### 8-2. hydrology overlay

hydrology overlay 우선순위:

```text
1. is_lake
2. is_salt_flat
3. is_wetland
4. is_river
5. none
```

판정:

```text
if is_lake:
  hydrology_overlay = "lake"
elif is_salt_flat:
  hydrology_overlay = "salt_flat"
elif is_wetland:
  hydrology_overlay = "wetland"
elif is_river and soil_moisture >= river_corridor_soil_min:
  hydrology_overlay = "river_corridor"
else:
  hydrology_overlay = null
```

기본:

```text
river_corridor_soil_min = 0.35
```

overlay 적용:

```text
lake:
  biome_physical = "lake"

salt_flat:
  biome_physical = "salt_flat"

wetland:
  biome_physical = "wetland"

river_corridor:
  biome_climate_base가 desert/steppe 계열이면 biome_physical = "river_corridor"
  그 외에는 biome_physical = biome_climate_base
```

이유:

```text
강은 기후 강수를 바꾸지 않는다.
하지만 사막 관통 강 주변의 토양수분/회랑림/농업 가능성은 terrain 판정에 반영할 수 있다.
```

### 8-3. soil_moisture 보정

같은 Koppen class 안에서도 soil_moisture로 세부 biome을 조정한다.

```text
if biome_climate_base in ["savanna", "hot_steppe", "cold_steppe"]:
  if soil_moisture < dry_steppe_soil_max:
    keep steppe/desert-side label
  elif soil_moisture >= grassland_soil_min:
    shift toward grassland/plains
```

기본:

```text
dry_steppe_soil_max = 0.25
grassland_soil_min = 0.45
```

주의:

```text
soil_moisture는 Koppen class를 되돌리지 않는다.
biome_physical 세부 라벨과 terrain lookup 보조축으로만 사용한다.
```

---

## 9. terrain_lookup.csv

최종 Vic3 terrain은 코드에 하드코딩하지 않고 lookup으로 결정한다.

lookup 입력 biome:

```text
terrain_lookup.csv에는 biome_physical을 넣는다.
fantasy_zone으로 변경된 최종 biome은 terrain lookup에 다시 넣지 않는다.
이유: fantasy_zone은 biome 라벨만 바꾸고 terrain은 유지한다는 기존 계약을 지키기 위함.
```

필수 컬럼:

```csv
priority,koppen_class,biome_physical,elevation_class,soil_moisture_min,soil_moisture_max,vic3_terrain
```

예시:

```csv
priority,koppen_class,biome_physical,elevation_class,soil_moisture_min,soil_moisture_max,vic3_terrain
100,*,*,mountain,0.0,1.5,mountain
90,*,wetland,*,0.0,1.5,wetland
89,*,salt_flat,*,0.0,1.5,desert
88,*,river_corridor,*,0.35,1.5,savanna
85,Af,rainforest,*,0.0,1.5,jungle
70,BWh,hot_desert,*,0.0,1.5,desert
64,BSk,cold_steppe,*,0.0,1.5,plains
```

lookup 우선순위:

```text
priority가 높은 행부터 매칭한다.
koppen_class / biome_physical / elevation_class는 "*" wildcard를 허용한다.
soil_moisture_min <= soil_moisture <= soil_moisture_max 범위만 매칭한다.
같은 priority에서 2개 이상 행이 동시에 매칭되면 ERROR.
어떤 행에도 매칭되지 않으면 ERROR.
단, priority 0 catch-all 행은 MVP 임시 안전장치로 허용한다.
```

중복 처리:

```text
같은 priority에서 2개 이상 행이 매칭되면 ERROR.
같은 koppen_class/biome_physical/elevation_class key 안에서 soil_moisture_min/max 범위가 겹치면 ERROR.
wildcard elevation은 반드시 "*" 문자열로 표기한다.
```

catch-all 처리:

```text
priority 0:
  임시 MVP 안전장치.
  정상 terrain 분류로 간주하지 않는다.
  매칭 province는 WARNING/debug report에 기록한다.

priority 1:
  lowland 전용 안전 fallback.
  새 biome_physical 라벨이 추가됐지만 아직 lookup에 명시되지 않은 경우를 흡수한다.
  매칭 province는 WARNING/debug report에 기록한다.

golden test 안정화 후:
  priority 0 / priority 1 fallback 매칭 province 수 0을 목표로 한다.
```

주의:

```text
MVP에서는 terrain_lookup.csv에 등장하는 vic3_terrain 값만 유효값으로 본다.
별도 Vic3 terrain whitelist 파일은 v0.7 입력으로 사용하지 않는다.
향후 game data validator가 추가되면 terrain_lookup.csv 값 자체를 별도 검증한다.
```

허용 terrain:

```text
plains
forest
hills
mountain
jungle
wetland
desert
tundra
savanna
snow
```

제외 terrain:

```text
ocean / lakes / river
farmland / pasture / plantation / cleared_land
mining / forestry
urban / docks
판타지 전용 terrain
```

lake 처리:

```text
biome_physical="lake"는 terrain_lookup.csv에서 Vic3 terrain으로 매핑하지 않는다.
호수/내륙수면은 hydrology_spec_v0.5의 lake output과 후속 map/rivers 처리 책임이다.
terrain_lookup.csv에는 lake 행과 vic3_terrain=lake 값을 넣지 않는다.
```

---

## 10. fantasy_zone 처리

`fantasy_zone`은 province_constraints.yaml에서 읽는다.

기본 원칙:

```text
fantasy_zone은 물리 계산 결과를 바꾸지 않는다.
Koppen class, aridity_index, soil_moisture는 그대로 유지한다.
terrain도 기본적으로 유지한다.
```

처리:

```text
if fantasy_zone is not null:
  biome_before_fantasy = biome_physical
  biome = apply_fantasy_label(biome_physical, fantasy_zone)
  vic3_terrain은 변경하지 않는다.
else:
  biome = biome_physical
```

예외:

```text
locked=true + force_terrain 지정 시에는 force_terrain이 최종 terrain을 덮어쓴다.
fantasy_zone만으로 terrain을 바꾸지 않는다.
```

주의:

```text
fantasy_zone은 soft label/nudge다.
사막을 강제로 숲 terrain으로 바꾸려면 locked=true + force_terrain을 사용해야 한다.
```

---

## 11. locked / override 최종 적용

읽는 필드:

```yaml
locked: false
force_biome: null
force_terrain: null
exclude_from_sim: false
```

적용 순서:

```text
1. 자동 biome / terrain 계산 완료
2. fantasy_zone 라벨 처리 완료
3. locked override 적용
```

규칙:

```text
if locked=true:
  if force_biome is not null:
    biome = force_biome
  if force_terrain is not null:
    vic3_terrain = force_terrain
  is_locked_override_applied = true
```

독립 채널:

```text
force_biome만 지정:
  biome만 덮어쓴다.
  terrain은 자동 계산값을 유지한다.
  biome 변경 후 terrain을 재계산하지 않는다.

force_terrain만 지정:
  terrain만 덮어쓴다.
  biome은 자동 계산값을 유지한다.

둘 다 지정:
  biome과 terrain을 각각 독립적으로 덮어쓴다.
```

force 값 단독 지정:

```text
locked=false인데 force_biome 또는 force_terrain이 존재:
  WARNING 후 무시.
  자동으로 locked=true를 활성화하지 않는다.
```

exclude_from_sim:

```text
exclude_from_sim은 최종 라벨 override가 아니다.
v0.7에서 자동 biome/terrain 계산을 금지하지 않는다.

단, exclude_from_sim=true인 province는 기후값이 인위적으로 0에 가까울 수 있으므로:
  locked=false이고 force_biome/force_terrain도 없으면 WARNING.
  이 경우 자동 biome/terrain 결과는 생성하지만 신뢰 불가로 표시한다.
  사용자가 명시 라벨을 원하면 locked=true + force_biome/force_terrain을 사용한다.
```

금지:

```text
force_rainfall을 v0.7에서 읽거나 적용하지 않는다.
climate_lock을 v0.7에서 재해석하지 않는다.
locked=true를 물리 계산 제외로 취급하지 않는다.
```

---

## 12. climate_rules.yaml 추가 섹션

```yaml
koppen_biome_terrain:
  epsilon: 0.000001
  aridity_cap: 3.0

  soil_moisture:
    et_world_scale: 1.0
    et_clamp_min: 0.0
    et_clamp_max: 1.5

    river_bonus_world_scale: 1.0
    river_bonus_clamp_min: 0.0
    river_bonus_clamp_max: 0.5

    lake_moisture_bonus: 0.25
    wetland_seed_soil_bonus: 0.20
    soil_moisture_min: -1.0
    soil_moisture_max: 1.0
    soil_moisture_cap: 1.5
    river_corridor_soil_min: 0.35
    dry_steppe_soil_max: 0.25
    grassland_soil_min: 0.45

  elevation:
    upland_threshold_m: 500
    highland_threshold_m: 1200
    mountain_threshold_m: 1800
    highland_cool_summer_threshold: 18.0

  koppen:
    b_base_threshold: 0.50
    b_summer_rain_multiplier: 1.15
    b_even_rain_multiplier: 1.00
    b_winter_rain_multiplier: 0.85
    summer_dominant_threshold: 0.70
    winter_dominant_threshold: 0.70
    desert_fraction: 0.50
    b_hot_threshold_c: 18.0

    ice_cap_summer_threshold: 0.0
    tundra_summer_threshold: 10.0
    tropical_coldest_threshold: 18.0
    tropical_af_dry_strength_max: 0.25
    tropical_monsoon_dry_rain_min: 0.15

    temperate_warmest_min: 10.0
    continental_winter_threshold: 0.0
    no_dry_season_strength_max: 0.25
    hot_summer_threshold: 22.0
    warm_summer_threshold: 10.0
```

---

## 13. 캐시 / 해시

출력 metadata hash:

```text
rainfall_normalized_hash
seasonal_hash
hydrology_hash
bootstrap_hash
graph_hash
constraints_hash
overrides_hash
terrain_lookup_hash
params_hash
```

hash 입력:

```text
rainfall_normalized_hash:
  cache/rainfall_normalized.json 정규화 hash

seasonal_hash:
  cache/seasonal_climate.json 정규화 hash

hydrology_hash:
  cache/hydrology.json 정규화 hash

bootstrap_hash:
  cache/bootstrap_fields.json 정규화 hash

graph_hash:
  province_graph.metadata.hash.topology_hash

constraints_hash:
  province_constraints.yaml 중 fantasy_zone만 정규화한 hash

overrides_hash:
  province_overrides.yaml 중 locked / force_biome / force_terrain / exclude_from_sim만 정규화한 hash

terrain_lookup_hash:
  terrain_lookup.csv 정규화 hash

params_hash:
  climate_rules.yaml의 koppen_biome_terrain 섹션 hash
```

주의:

```text
province_constraints.yaml의 mountain_strength / elevation_hint는 v0.7에서 직접 hash하지 않는다.
해당 값은 bootstrap_fields.json에 이미 반영되어야 한다.
```

---

## 14. 검증 규칙

### 14-1. ERROR

```text
필수 입력 파일 누락
schema_version 불일치
land target에 final_rainfall 누락
land target에 corrected_ET 누락
hydrology.corrected_ET과 rainfall_normalized.corrected_ET 불일치
hydrology.river_bonus와 rainfall_normalized.river_bonus 불일치
hydrology.lake_fraction과 rainfall_normalized.lake_fraction 불일치
final_rainfall / corrected_ET / corrected_ET_scaled / river_bonus_scaled / temperature에 NaN 또는 Infinity 존재
final_summer_rainfall + final_winter_rainfall != final_rainfall (epsilon 초과)
is_lake=true와 is_salt_flat=true 동시 발생
terrain_lookup.csv에 priority 0 catch-all 행이 없거나 catch-all까지 적용했는데도 matching terrain 없음
terrain_lookup.csv에서 같은 priority에 2개 이상 매칭
terrain_lookup.csv의 같은 key 안에서 soil_moisture range 겹침
Koppen-lite class 미분류
force_terrain 값이 terrain_lookup.csv에 등장하지 않음
```

### 14-2. WARNING

```text
locked=true인데 force_biome / force_terrain 둘 다 없음
locked=false인데 force_biome / force_terrain 존재 → 무시
exclude_from_sim=true인데 locked force label 없음
exclude_from_sim=true 자동 biome/terrain 결과는 신뢰 불가 표시
lake_fraction > 0인데 is_lake=false
is_river=true인데 discharge=0
soil_moisture가 clamp 상한/하한에 걸림
highland 보정으로 koppen_base_class와 koppen_class가 달라짐
```

### 14-3. INFO

```text
fantasy_zone이 biome label만 변경하고 terrain은 유지됨
river_corridor overlay가 desert/steppe biome에 적용됨
soil_moisture는 v0.7에서 새로 계산됨
```

---

## 15. debug output

권장 출력:

```text
cache/debug/koppen_class_counts.csv
cache/debug/biome_counts.csv
cache/debug/terrain_counts.csv
cache/debug/aridity_index_stats.csv
cache/debug/soil_moisture_stats.csv
cache/debug/et_scaling_stats.csv
cache/debug/river_bonus_scaling_stats.csv
cache/debug/hydrology_overlay_counts.csv
cache/debug/locked_override_report.csv
cache/debug/koppen_biome_terrain_warnings.csv
```

맵 덤프:

```text
outputs/debug/koppen_class_map.png
outputs/debug/biome_map.png
outputs/debug/terrain_map.png
outputs/debug/aridity_index_map.png
outputs/debug/soil_moisture_map.png
outputs/debug/corrected_ET_scaled_map.png
outputs/debug/river_bonus_scaled_map.png
```

주의:

```text
골든테스트에서는 위 debug map을 매 실행마다 함께 덤프한다.
실패 후 재실행하면 튜닝값이 달라져 원인 귀속이 어려울 수 있다.
```

---

## 16. 금지 사항

```text
[금지 1] annual_rainfall_raw / summer_rainfall_raw를 biome 판정에 직접 사용
  반드시 v0.6 final_rainfall 계열만 사용.

[금지 2] v0.7에서 rainfall normalization 재계산
  v0.6 출력만 소비.

[금지 3] force_rainfall 재적용
  v0.4에서 이미 raw rainfall에 반영됨.

[금지 4] climate_lock 재해석
  v0.7은 climate_lock 물리값을 읽지 않는다.

[금지 5] force_biome 후 terrain 자동 재계산
  force_biome / force_terrain은 독립 채널.

[금지 6] force_terrain 후 biome 자동 재계산
  독립 채널.

[금지 7] locked=true를 시뮬레이션 제외로 취급
  locked는 최종 라벨 override.

[금지 8] heightmap.png 직접 사용
  현재 highland/mountain 판정은 bootstrap_fields.synthetic_elevation_m 기준.

[금지 9] river_bonus를 rainfall에 더하기
  soil_moisture에서만 소비.

[금지 10] is_river만으로 terrain을 무조건 river terrain으로 변경
  river는 hydrology overlay이며 terrain lookup에서 조건부 처리.

[금지 11] 주 특성 / 주 모디파이어 생성
  Province terrain pipeline 책임 밖.
```

---

## 17. 완료 기준

```text
1. 모든 land target이 정확히 하나의 koppen_class를 가진다.
2. 모든 land target이 정확히 하나의 biome과 vic3_terrain을 가진다.
3. raw rainfall 필드를 읽지 않는다.
4. final_summer_rainfall + final_winter_rainfall = final_rainfall 검증을 통과한다.
5. corrected_ET / river_bonus / lake_fraction 원값이 v0.5/v0.6과 일치한다.
6. corrected_ET_scaled / river_bonus_scaled가 생성된다.
7. soil_moisture와 aridity_index가 finite 값이다.
8. terrain_lookup.csv 중복 매칭이 없다.
9. priority 0 / priority 1 fallback 매칭 province 수를 debug report에 기록한다.
10. golden test 안정화 후 fallback 매칭 수 0을 목표로 한다.
11. locked / force_biome / force_terrain override가 override_semantics_spec_v0.2와 일치한다.
12. fantasy_zone은 terrain을 바꾸지 않는다.
13. debug counts와 map이 매 실행 함께 출력된다.
```

---

## 18. known limitation: subtropical B-class underproduction

```text
Current v0.7 tuning uses:
  world.climate_reference.equator_temp_c = 24.0
  world.climate_reference.pole_temp_c = -26.0
  koppen_biome_terrain.soil_moisture.et_world_scale = 12.0

Known limitation:
  subtropical band (23.5 <= |latitude| < 35) currently produces a low
  B/desert-class ratio compared with Earth desert-belt analogs.

Cause:
  After the cosine latitude-temperature correction, the subtropical band center
  is approximately:

    cos(29 deg) ~= 0.875
    temp = -26 + 50 * 0.875 ~= 17.75 C

  This is cooler than Earth hot-desert belt analogs such as Sahara/Arabia
  annual mean temperatures (~25-30 C). Lower temperature also lowers corrected
  ET, so aridity_index = final_rainfall / corrected_ET_scaled does not fall
  below the B threshold often enough in the subtropical band.

Current handling:
  et_world_scale = 12.0 is used to restore global dry-climate coverage while
  keeping tropical aridity above the current diagnostic safety margin.

Future review:
  Revisit after province_constraints.yaml adds mountain/rain-shadow constraints,
  or if a later temperature model introduces a separate subtropical heat boost.
```

---

## 19. v0.7 이후 이관 항목

```text
정식 DEM 기반 highland/mountain 판정
substrate / soil type 레이어
basin_bonus
fire regime
ecotone / biome mosaic
Vic3 최종 terrain game data validator
주 특성 / 주 모디파이어 별도 산출물
```
