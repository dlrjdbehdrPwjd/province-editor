# mountain_barrier_pseudocode v0.3

> moisture_transport_kernel_v0.2.5의 transfer 단계에 산맥 장벽 레이어를 삽입.
> 풍상 강수(orographic rain) / 풍하 비그늘(leeward rain shadow) 구현.
> foehn 기온 보정은 seasonal_climate_spec_v0.4에서 처리.

---

## 0. 이 문서의 범위

```
포함:
  effective_mountain_strength 계산
  barrier 공식
  blocked / passed 분리
  orographic_rain → rainfall[B]
  leeward shadow 발생 원리
  v0.2.5 transfer 루프에 삽입 위치

포함하지 않음:
  foehn 기온 보정           → seasonal_climate_spec_v0.4
  heightmap 기반 auto 산맥  → 폐기됨 (아래 참조)
  barrier와 elevation 연결  → 분리됨 (아래 참조)
```

---

## 1. 폐기 선언

```
[폐기] mountain_threshold_m / high_mountain_threshold_m 기반 auto 산맥 파생
  변경 전: auto = clamp((elevation_max_m - 1200) / (2500 - 1200), 0, 1)
  변경 후: 없음. mountain_strength는 user authored only.
  이유: heightmap.authoritative=false. elevation 기반 자동 파생 금지.

[폐기] effective_mountain_strength = max(auto, user)
  변경 후: effective_mountain_strength = province_constraints.mountain_strength
  이유: auto 파생 경로 자체가 제거됨.
```

---

## 2. 역할 분리 확인

```
mountain_strength (이 문서):
  → 산맥 장벽 강도 전용
  → barrier, crossing_barrier, ridge_continuity 계산에 사용
  → 온도 계산에 사용 금지

synthetic_elevation (bootstrap_fields.json):
  → 온도 고도 보정(lapse rate) 전용
  → moisture_capacity 계산에 사용
  → 장벽 계산에 사용 금지

둘을 합산하거나 대체하는 것 모두 금지.
```

---

## 3. 입력 추가

| 소스 | 필드 | 용도 |
|------|------|------|
| `province_constraints.yaml` | `mountain_strength` (0.0~1.0) | 장벽 강도. user authored only. |
| `climate_rules.yaml` | `mountain_barrier` 섹션 | 장벽 계산 파라미터 |

---

## 4. climate_rules.yaml 추가 섹션

```yaml
mountain_barrier:
  barrier_scale: 3.0          # exp 감쇠 계수. 클수록 산맥이 강하게 막음.
  ridge_bonus: 0.5            # ridge 연속성 추가 강도
  windward_efficiency: 0.7    # blocked moisture 중 orographic rain 비율
  barrier_factor_max: 0.95    # barrier_factor 상한 (완전 차단 방지)
```

---

## 5. effective_mountain_strength

```
# province_constraints.yaml에서 읽음
# 기본값 0.0 (제약 없으면 산맥 아님)

effective_mountain_strength[color] =
  province_constraints.get(color, {}).get('mountain_strength', 0.0)

범위: 0.0~1.0
  0.0: 평지 (장벽 없음)
  1.0: 최고 강도 산맥
  범위 밖(< 0.0 또는 > 1.0) → ERROR: "mountain_strength 범위 초과"
  자동 clamp 금지. 오류를 숨기지 않는다.

heightmap elevation에서 자동 파생 금지.
```

---

## 6. barrier 공식

edge A → B 기준:

```
mtn_A = effective_mountain_strength[A]
mtn_B = effective_mountain_strength[B]
# border_weight는 barrier 강도에 포함하지 않음
# 이유: transfer 계산 시 flow_weight에 이미 border_weight 반영됨
#       barrier에 다시 곱하면 과분할 맵에서 이중 약화 발생

# 6-1. crossing_barrier: edge를 넘어갈 때의 기본 장벽
crossing_barrier = max(mtn_A, mtn_B)

# 6-2. ridge_continuity: 양쪽 모두 산맥일 때 추가 장벽
#      산맥이 연속으로 이어진 경우 우회 불가 → 추가 강화
ridge_continuity = mtn_A × mtn_B × ridge_bonus

# 6-3. 최종 barrier
barrier = crossing_barrier + ridge_continuity
```

**예시:**

```
평지(0.0) → 산맥(0.8):
  crossing  = max(0.0, 0.8) = 0.8
  ridge     = 0.0 × 0.8 × 0.5 = 0.0
  barrier   = 0.8

산맥(0.8) → 산맥(0.9):
  crossing  = max(0.8, 0.9) = 0.9
  ridge     = 0.8 × 0.9 × 0.5 = 0.36
  barrier   = 0.9 + 0.36 = 1.26  (ridge group 효과)

평지(0.0) → 평지(0.0):
  barrier = 0.0  (장벽 없음, v0.2.5와 동일 동작)
```

---

## 7. v0.2.5 transfer 루프에 삽입 위치

moisture_transport_kernel_v0.2.5의 transfer 계산 직후에 삽입:

```
# ── [v0.2.5에서 받은 transfer] ────────────────────────────────
# transfer는 이미 wind_weight / border_weight / distance_decay 반영됨
flow_weight = wind_weight × border_weight × distance_decay
transfer = delta_A × export_fraction × (flow_weight / flow_total)

# ── [v0.3 추가: barrier 계산] ────────────────────────────────
# 주의: exclude_from_sim[A] / exclude_from_sim[B] 체크는
#       v0.2.5 transfer 루프에서 이미 continue 처리됨.
#       barrier 함수는 valid edge에 대해서만 호출되므로
#       exclude edge는 입력으로 들어오지 않는다.
#       방어적으로 들어올 경우: barrier=0, orographic_rain=0 처리.
mtn_A = effective_mountain_strength[A]
mtn_B = effective_mountain_strength[B]

crossing_barrier = max(mtn_A, mtn_B)
ridge_continuity = mtn_A × mtn_B × ridge_bonus
barrier = crossing_barrier + ridge_continuity

barrier_factor = clamp(
  1.0 - exp(-barrier × barrier_scale),
  0.0,
  barrier_factor_max   # 기본값 0.95
)
# barrier_factor_max = 0.95 권장: 완전 차단 시 풍하측 수분이 너무 소멸됨

blocked = transfer × barrier_factor      # 산맥이 막은 양
passed  = transfer - blocked             # 장벽을 통과한 양

# ── 풍상 강수 (orographic rain) → rainfall[B] ─────────────────
# 막힌 습기 → B의 풍상측 사면에 강수
orographic_rain = blocked × windward_efficiency
rainfall[B] += orographic_rain

# ── blocked 잔여분 소산 ────────────────────────────────────────
blocked_dissipated = blocked × (1.0 - windward_efficiency)
# 이 값은 전파에서 제거되고 rainfall에도 포함되지 않는다.
# 장벽에 의해 기계적으로 소산된 수분으로 처리한다.
# (windward_efficiency=1.0이면 소산 없음, 전량 orographic_rain)

# ── passed에 기존 v0.2.5 loss/net 처리 적용 ─────────────────
area_factor = sqrt(area_px[B] / median_area_px)
loss     = min(passed, passed × base_loss × area_factor)
net      = max(0.0, passed - loss)
rainfall[B] += loss

space    = capacity[B] - moisture[B]
absorbed = max(0.0, min(net, space))
overflow = max(0.0, net - absorbed)
rainfall[B] += overflow × overflow_to_rainfall_factor
moisture[B] += absorbed

# ── force_moisture 재고정 (v0.2.5와 동일 위치 유지) ─────────────
if province_overrides[B].climate_lock and province_overrides[B].force_moisture is not None:
  moisture[B] = province_overrides[B].force_moisture
# 이유: barrier 삽입 후에도 force_moisture 재고정 순서는 absorption 직후로 유지
```

**barrier = 0일 때 v0.2.5와 동일:**

```
barrier_factor = 1 - exp(0) = 0
blocked = 0
passed  = transfer (전량 통과)
→ 기존 v0.2.5 동작 그대로
```

---

## 8. leeward shadow 발생 원리

별도 rain shadow 계산 불필요. 자연 발생:

```
A (풍상 평지) → B (산맥) → C (풍하 평지)

1. A→B: barrier_factor 높음 → blocked 많음 → B에 orographic_rain 집중
         passed 적음 → moisture[B] 증가량 적음

2. B→C: moisture[B]가 낮음 → delta_B 작음 → transfer(B→C) 작음
         → C의 moisture 낮음 = rain shadow 자연 발생

3. C→D→...: 계속 낮은 moisture 전파 → 비그늘 지역 형성
```

---

## 9. orographic_rain 위치

```
풍상측(windward)은 B (목적지):
  A에서 B 방향으로 공기가 이동 중 B의 산맥에 부딪힘
  강수는 B의 풍상 사면에 내림 → rainfall[B] += orographic_rain

windward_efficiency = 0.7:
  blocked 중 70%만 강수로 전환
  나머지 30%는 소산/기타

foehn 효과 (v0.4):
  이 단계에서 처리하지 않음.
  산맥 풍하측 기온 상승은 seasonal_climate_spec_v0.4에서 추가.
```

---

## 10. debug 출력 추가 3종

```
outputs/debug/barrier_strength.png
  province별 effective_mountain_strength 시각화
  0.0 = 흰색, 1.0 = 짙은 갈색/녹색

outputs/debug/orographic_rain.png
  province별 누적 orographic_rain 시각화
  산맥 풍상측에 집중되는지 확인

outputs/debug/blocked_moisture.png
  province별 누적 blocked 총량 시각화
  (= orographic_rain + blocked_dissipated 합산)
  orographic_rain.png와 비교하면 소산 비율 파악 가능

outputs/debug/rain_shadow.png  [선택 debug]
  v0.3 moisture - v0.2.5 moisture 차이값
  음수(파란색) = 비그늘 구역
  산맥 풍하측에 파란 띠가 보여야 정상
  주의: 비교 실행(v0.2.5 재실행)이 필요하므로 선택 출력으로 분류
```

---

## 11. 검증 체크리스트

```
□ barrier_strength.png
  - mountain_strength > 0 province는 갈색/녹색
  - mountain_strength = 0 province는 흰색

□ orographic_rain.png
  - 주풍 방향 기준 산맥의 windward side에 강수 집중
  - 무역풍 구역: 산맥 동쪽 사면
  - 편서풍 구역: 산맥 서쪽 사면

□ rain_shadow.png
  - 산맥 leeward side에 moisture 감소 구역 명확히 존재
  - 감소 구역이 주풍 방향과 직교

□ barrier = 0인 province는 v0.2.5와 동일한 moisture/rainfall 결과

□ 전체 moisture 수치 안정성
  - 0 ≤ moisture ≤ capacity (모든 province)
  - rainfall ≥ 0

□ exclude_from_sim province: orographic_rain도 0 (전파 미참여)
```

---

## 12. 금지 사항

```
[금지 1] heightmap elevation → mountain_strength 자동 파생
  mountain_strength는 user authored only.
  province_constraints.yaml 값만 사용.

[금지 2] border_weight를 barrier 강도에 곱하기
  이유: transfer의 flow_weight에 이미 border_weight 반영됨.
       barrier에 다시 곱하면 과분할 맵에서 이중 약화.

[금지 3] foehn 기온 보정을 v0.3에서 처리
  foehn → seasonal_climate_spec_v0.4 이후.

[금지 4] synthetic_elevation을 barrier 계산에 사용
  synthetic_elevation = lapse rate 전용.
  barrier = mountain_strength 전용.

[금지 5] exclude_from_sim province에 barrier 계산 수행
  v0.2.5 루프에서 이미 exclude edge는 transfer 전에 continue됨.
  barrier 함수가 exclude edge를 받으면 barrier=0, orographic_rain=0.

[금지 6] leeward shadow를 별도 계산으로 처리
  rain shadow는 moisture[B] 감소로 자연 발생.
  별도 shadow 패치 금지.
```

---

## 12-1. 파라미터 범위 검증

```
mountain_strength: 0.0~1.0. 범위 밖 → ERROR (자동 clamp 금지)
barrier_scale: >= 0. 음수 → ERROR
ridge_bonus: >= 0. 음수 → ERROR
windward_efficiency: 0.0~1.0. 범위 밖 → ERROR
barrier_factor_max: 0.0 < value <= 1.0. 범위 밖 → ERROR
```

---

## 13. v0.4 예정 사항 (참고)

```
foehn effect:
  leeward province temperature += blocked × foehn_warming_factor
  (산맥 풍하측 하강기류 → 단열 가열 → 기온 상승)
  참고: B가 산맥이면 leeward는 B의 반대쪽 province. 상세 정의는 v0.4에서.

ITCZ gaussian 전환:
  현재 hard band → gaussian 분포

아열대 고압대 drain:
  subtropical_strength = gaussian(abs_lat, center=25, width=10)
  moisture *= 1 - drain_strength × subtropical_strength
```
