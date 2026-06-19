# pipeline_run_manifest_spec v0.1

이 문서는 기후/지형 파이프라인 실행 결과를 재현 가능한 기록으로 남기는 `pipeline_run_manifest.json`의 계약을 정의한다.

## 1. 목적

`pipeline_run_manifest`는 파이프라인을 다시 실행하지 않는다. 이미 생성된 STEP 0~5 산출물을 읽고, 다음 정보를 한 번에 묶어 기록한다.

```text
실행 시각
git commit / branch / project dirty 여부
입력 파일 경로와 sha256
단계별 출력 파일 경로와 sha256
단계별 schema_version
단계별 warning count
핵심 요약 지표
대표 debug output 경로와 sha256
```

## 2. 출력 위치

최신 실행 기록:

```text
cache/pipeline_run_manifest.json
```

불변 history 기록:

```text
cache/pipeline_runs/{run_id}.json
```

`cache/` 아래 파일이므로 Git 추적 대상이 아니다. 재현성/운영 확인용 산출물로 취급한다.

## 3. 실행 방식

기본 명령:

```powershell
python scripts/write_pipeline_run_manifest.py --pretty --require-existing-outputs
```

revision 이름을 명시할 때:

```powershell
python scripts/write_pipeline_run_manifest.py --revision-dir-name dev_empty --pretty
```

## 4. 입력

기본 입력 manifest:

```text
config/pipeline_input_manifest.json
```

이 파일에서 다음 경로를 읽는다.

```text
map_data.*
inputs.province_constraints
inputs.province_overrides
inputs.climate_rules
inputs.terrain_lookup
```

`{revision_dir_name}` placeholder는 CLI의 `--revision-dir-name` 값으로 치환한다.

## 5. 단계 목록

v0.1에서 기록하는 단계:

```text
build_province_graph
build_bootstrap_fields
seasonal_climate
hydrology
rainfall_normalization
koppen_biome_terrain
```

각 단계는 `output`과 가능한 경우 `report`를 기록한다.

## 6. 대표 debug outputs

baseline 확인용 대표 이미지를 별도 기록한다.

```text
outputs/draft_rivers.png
outputs/debug/annual_rainfall_raw_map.png
outputs/debug/annual_rainfall_log_map.png
outputs/debug/zonal_mean_rainfall.png
outputs/debug/koppen_class_map.png
outputs/debug/biome_map.png
outputs/debug/terrain_map.png
outputs/debug/aridity_index_map.png
outputs/debug/soil_moisture_map.png
outputs/debug/corrected_ET_scaled_map.png
outputs/debug/river_bonus_scaled_map.png
```

대표 이미지가 없으면 manifest에는 `exists=false`로 기록한다. 이것만으로 실행 실패로 보지는 않는다.

## 7. 실패 정책

`--require-existing-outputs`가 켜져 있으면 STEP 0~5 필수 output이 하나라도 없을 때 실패한다.

필수 output:

```text
cache/province_graph.json
cache/bootstrap_fields.json
cache/seasonal_climate.json
cache/hydrology.json
cache/rainfall_normalized.json
cache/koppen_biome_terrain.json
```

report/debug 파일 누락은 실패가 아니라 기록 누락으로 처리한다.

## 8. 금지 사항

```text
manifest writer가 파이프라인 단계를 재실행하지 않는다.
manifest writer가 cache 산출물을 수정하지 않는다.
manifest writer가 province_constraints / province_overrides 내용을 해석해 병합하지 않는다.
manifest writer가 debug 이미지를 새로 생성하지 않는다.
manifest writer가 Git commit/push를 수행하지 않는다.
```

## 9. 완료 기준

```text
cache/pipeline_run_manifest.json이 생성된다.
cache/pipeline_runs/{run_id}.json이 생성된다.
두 파일의 내용이 같다.
각 필수 stage output의 sha256이 기록된다.
git commit hash가 기록된다.
warning 총합이 기록된다.
테스트에서 누락 output 실패 정책을 검증한다.
```
