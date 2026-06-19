# moisture_transport_kernel v0.2.6

> v0.2.5의 per-hop `export_fraction` 기반 전파를 폐기하고, province 면적에서 근사한
> crossing distance 기반 질량 보존 전파로 교체한다.

## 1. 변경 계약

폐기 파라미터:

```text
export_fraction
base_loss
distance_decay_scale
```

신규/유지 파라미터:

```yaml
transport_length_px: 500.0
improvement_epsilon: 0.000001
overflow_to_rainfall_factor: 1.0
max_transport_iterations: 2000
coastal_source_factor: 0.161
```

`coastal_source_factor: 0.161`은 물리 상수가 아니라 현재 generated map 기준 empirical baseline이다.
초기 draft의 `0.6`은 distance-survival kernel 도입 후 해안/ITCZ 강수를 과집중시켰으므로 하향 조정했다.
다른 맵, 실제 province constraints, golden validation set을 적용할 때는 재튜닝 대상이다.
동일한 주석을 `config/climate_rules.yaml`에도 남긴다.

## 2. 거리 기반 생존율

```text
crossing_px[A] = sqrt(area_px[A])
survival[A] = exp(-crossing_px[A] / transport_length_px)
transit_rainfall[A] += delta_A * (1 - survival[A])
```

`area_px >= 1`, `transport_length_px > 0`이어야 한다. `survival` 범위는 `(0, 1)`이다.

## 3. 이웃 분배와 질량 보존

```text
flow_weight_AB = wind_weight_AB * border_weight_AB
flow_total_A = sum(flow_weight_AB)
transfer_AB = delta_A * survival[A] * flow_weight_AB / flow_total_A

delta_A = transit_rainfall[A] + sum(transfer_AB)
```

유효한 이웃이 없으면 `delta_A` 전량을 A의 transit rainfall로 전환한다.
sea와 `exclude_from_sim` province는 목적지에서 제외한다.

`flow_weight`에는 `distance_px`를 넣지 않는다. province split/merge에 따른 해상도 의존성을 줄이기 위해,
거리 감쇠는 source province의 crossing distance에서만 처리한다.

## 4. 산맥과 capacity

`transfer_AB` 직후 v0.3 mountain barrier를 적용한다.

```text
blocked = transfer_AB * barrier_factor
orographic_rain = blocked * windward_efficiency
blocked_dissipated = blocked - orographic_rain
passed = transfer_AB - blocked

space_B = capacity[B] - moisture[B]
absorbed = clamp(passed, 0, space_B)
overflow = passed - absorbed
rainfall[B] += orographic_rain + overflow
moisture[B] += absorbed
```

`blocked_dissipated`는 debug mass ledger에 기록한다. `force_moisture` 적용 위치는 absorption 직후로 유지한다.

## 5. 소스와 override

해안, 습지, `moisture_bonus`, annual recycling source와
`force_temp/force_moisture/force_rainfall/exclude_from_sim` 처리 순서는 v0.2.5와 같다.
계절별 해안 multiplier는 seasonal layer가 전달한다.

## 6. 검증

```text
abs(delta_A - transit_rainfall_A - sum(transfer_AB)) <= 1e-9
moisture >= 0
moisture <= capacity
rainfall >= 0
transport_length_px > 0
resolution split/merge mean rainfall difference < 20%
```

기존 `moisture_transport_kernel_v0.2.5.md`는 이력 문서로 보존한다.

## 7. 순환 그래프 solver

`survival≈0.98`이고 leakage가 있는 순환 graph를 event priority queue로 풀면 중복 재삽입이 지나치게 많아진다.
v0.2.6 구현은 같은 delta wave를 seasonal pass 단위 Jacobi-style iteration으로 계산한다.

```text
pending[0] = initialized source moisture
each iteration:
  pending에서 transit rainfall 계산
  모든 directed edge transfer를 동시에 계산
  destination별 incoming을 합산
  capacity absorption/overflow 적용
  pending_next = absorbed

residual_wave_max = max(pending_next)
transport_converged = residual_wave_max < improvement_epsilon
```

여기서 `pending`은 steady-state moisture가 아니라 아직 전파되지 않은 wave 잔량이다.
따라서 수렴 기준은 “큰 정상상태 moisture가 남아 있느냐”가 아니라
`residual_wave_max`가 `improvement_epsilon` 아래로 떨어졌느냐이다.

`max_transport_iterations`를 초과하면 FATAL이 아니다.
파이프라인은 best-effort partial transport result를 사용하고 아래 metadata/warning을 남긴다.

```text
transport_converged: false
transport_iterations: max_transport_iterations
transport_residual_wave_max: <last residual_wave_max>
warning: moisture transport reached max_transport_iterations
```

edge routing weight와 survival은 spin-up 시작 전에 한 번 전처리한다.
