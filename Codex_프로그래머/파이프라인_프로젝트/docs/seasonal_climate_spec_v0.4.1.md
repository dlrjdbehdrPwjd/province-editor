# seasonal_climate_spec v0.4.1

> v0.4에 전역 July/January forcing, 계절 이동 ITCZ, 계절별 해안 증발,
> climate convergence와 analytical soil equilibrium 분리를 추가한다.

## 1. 실행 pass와 local season

물리 계산은 전역 `JULY`와 `JANUARY` 두 pass로 실행한다.

기본 위도 온도는 선형 보간이 아니라 cosine insolation 근사를 사용한다.

```text
base_temp =
  pole_temp + (equator_temp - pole_temp) * cos(radians(abs(latitude)))
```

초기 선형식 `equator_temp + (pole_temp - equator_temp) * abs(latitude) / 90`은
35~55도 중위도 여름 온도를 과도하게 낮춰 온대 province 대부분을 ET/EF로 분류시키는 문제가 있었다.
cosine 근사는 위도별 평균 일사량에 비례하는 단순 에너지수지 근사이며, 중위도 온도 붕괴를 완화한다.

현재 generated-map 1차 기준값:

```yaml
equator_temp_c: 24.0
pole_temp_c: -26.0
```

```text
JULY temperature:
  north = base + amplitude
  south = base - amplitude

JANUARY temperature:
  north = base - amplitude
  south = base + amplitude
```

출력의 summer/winter는 local season이다.

```text
north: summer=JULY, winter=JANUARY
south: summer=JANUARY, winter=JULY
```

적도(`latitude=0`)는 북반구 규칙을 사용한다.

## 2. ITCZ 계절 이동

```text
JULY itcz_center_lat = +northern_summer_itcz_offset
JANUARY itcz_center_lat = -northern_summer_itcz_offset

itcz_weight = exp(-((latitude - itcz_center_lat)^2) / (2 * itcz_sigma^2))
```

기본 offset은 `5.0°`이다. offset에 sigma를 곱하지 않는다.
subtropical component는 기존처럼 `abs(latitude)` 기준으로 적용한다.

## 3. 계절별 해안 source

각 province의 local season에 따라 적용한다.

```text
local summer: coastal_source_factor * 1.1
local winter: coastal_source_factor * 0.9
```

`coastal_source_factor` 자체는 `moisture_transport_kernel_v0.2.6.md`의 empirical baseline 정책을 따른다.

## 4. Phase 1: climate convergence

초기 상태는 `recycling=0`이다. 최대 50년 동안 July/January를 실행한다.

Phase 1은 장기 토양 storage를 채우기 위한 단계가 아니다. 매 climate year 시작 시 `storage=0`으로 리셋하고,
같은 year 안의 July → January 계절 이월만 허용한다. 장기 storage가 ET와 recycling 수렴 목표를 계속 움직이는 것을 막기 위한 경계다.

```text
moisture_residual =
  max(abs(current seasonal moisture - previous seasonal moisture)) /
  max(max(current seasonal moisture), numeric_epsilon)

recycling_residual =
  max(abs(current recycling - previous recycling)) /
  max(max(current recycling), numeric_epsilon)

converged when:
  moisture_residual < climate_moisture_epsilon
  AND recycling_residual < climate_recycling_epsilon
```

기본 epsilon은 각각 `0.005`이다. storage 변화량은 climate convergence에 사용하지 않는다.

50년 안에 수렴하지 않아도 FATAL이 아니다.
파이프라인은 50년차 best-effort result를 사용하고 아래 metadata/warning을 남긴다.

```text
climate_converged: false
spinup_years_used: 50
warning: climate spin-up did not converge; using best-effort result
```

ET recycling fixed-point 완화계수는 50년 이내 수렴을 위해 `relaxation_alpha=0.5`를 사용한다.

거리 기반 transport 적용 후 recycling `0.3`은 deep-inland 평균 강수를 해안보다 높게 만들고 raw rainfall 상한 `3.0`을 초과했다.
현재 baseline은 `recycling_fraction=0.018`, `max_recycling_share=0.1`이다.
이 값은 최종 물리 상수가 아니라 임시 empirical baseline이며, real constraints/golden tests 적용 후 재검토한다.
동일한 주석을 `config/climate_rules.yaml`에도 남긴다.

## 5. Phase 2: analytical soil equilibrium

```text
net_input = max(0, annual_rainfall_raw - annual_ET)
storage_unclamped = net_input * soil_storage_time_years
soil_water_storage_final = clamp(storage_unclamped, 0, storage_capacity)
```

기본값은 `soil_storage_time_years=5`, `storage_capacity=10`이다.
capacity clamp는 정상 포화이며 미수렴 오류가 아니다.

## 6. 출력

```text
schema_version: seasonal_climate.v0.4.1
기존 v0.4 필드 유지
annual_transit_rainfall_raw 추가
summer_vertical_motion_index 추가
winter_vertical_motion_index 추가
vertical_motion_index는 local season 값의 평균으로 유지
spinup.climate_converged 추가
spinup.spinup_years_used 추가
spinup.transport_converged 추가
spinup.transport_nonconverged_passes 추가
spinup.transport_residual_wave_max 추가
spinup.warnings 추가
```

## 7. acceptance 기준

```text
coast_distance_normalized > 0.28: positive rainfall fraction >= 0.40
coast_distance_normalized > 0.60: positive rainfall fraction >= 0.20
coastal mean / deep-inland mean >= 5.0
seasonality > 0.05 province fraction >= 0.30
|latitude| < 20 and seasonality > 0.1 fraction >= 0.50
annual_rainfall_raw <= 4.0
negative moisture/rainfall count = 0

equatorial_to_midlat_ratio =
  mean rainfall(abs(latitude) <= 10) /
  mean rainfall(30 <= abs(latitude) <= 50)
equatorial_to_midlat_ratio < 10.0
```

`equatorial_to_midlat_ratio`는 ITCZ 과집중을 정량화하기 위한 acceptance 항목이다.
이 항목이 없으면 전체 양수 강수율이 통과해도 적도 피크가 과도하게 남을 수 있다.

`annual_rainfall_raw <= 4.0`은 완전한 폭주 방지 상한이다.
`rainfall_normalization_spec_v0.6`의 `absolute_clamp_max=1.5`와 percentile 기반 최종 압축이
raw 강수값을 후속 단계에서 정규화하므로, raw 단계 상한은 정밀 제어가 아니라 비정상 폭주 감지 목적이다.
현재 generated map full spin-up 실측값은 `max_rainfall_raw=3.7886936`이다.
