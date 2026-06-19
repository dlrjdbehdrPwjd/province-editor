# Canonical docs

이 문서는 MVP baseline 기준으로 어떤 문서를 최종 기준으로 볼지 고정한다.

## Canonical

```text
STEP 0 province graph:
  docs/build_province_graph_design_v0.2.md
  docs/province_graph_schema_v0.2.md

STEP 1 bootstrap fields:
  docs/bootstrap_fields_build_design_v0.1.md
  docs/bootstrap_fields_spec_v0.1.md

STEP 2 seasonal climate / moisture transport:
  docs/seasonal_climate_spec_v0.4.1.md
  docs/moisture_transport_kernel_v0.2.6.md

STEP 3 hydrology:
  docs/hydrology_spec_v0.5.md

STEP 4 rainfall normalization:
  docs/rainfall_normalization_spec_v0.6.md

STEP 5 Koppen / biome / terrain:
  docs/koppen_biome_terrain_spec_v0.7.md

Override semantics:
  docs/override_semantics_spec_v0.2.md

Pipeline orchestration:
  docs/pipeline_orchestration_spec_v0.1.md

Validation / golden tests:
  docs/validation_and_golden_tests_spec_v0.1.md

Change history:
  docs/climate_algorithm_full_changelog.md
```

## Deprecated / historical

아래 문서는 삭제하지 않고 보관한다. 단, 구현 기준은 위 canonical 문서가 우선한다.

```text
docs/seasonal_climate_spec_v0.4.md
  replaced by docs/seasonal_climate_spec_v0.4.1.md

docs/moisture_transport_kernel_v0.2.5.md
  replaced by docs/moisture_transport_kernel_v0.2.6.md
```

## Notes

```text
docs/mountain_barrier_pseudocode_v0.3.md
  supporting design note. STEP 2 moisture/barrier 구현 참고 문서로 유지.
```
