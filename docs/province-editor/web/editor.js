const MANIFEST_SCHEMA_VERSION = "province_editor_export_manifest.v0.1";
const PROJECT_STATE_SCHEMA_VERSION = "province_editor_project_state.v0.2";
const SNAPSHOT_SCHEMA_VERSION = "pipeline_config_snapshot.v0.1";
const AUTOSAVE_KEY_PREFIX = "province_editor.autosave.v0.2";
const AUTOSAVE_DEBOUNCE_MS = 1000;
const AUTOSAVE_INTERVAL_MS = 10000;
const SET_ARRAY_FIELDS = new Set(["tags"]);
const VALID_FORCE_TERRAINS = new Set([
  "plains", "forest", "hills", "mountain", "jungle",
  "wetland", "desert", "tundra", "savanna", "snow",
]);
const STATE_BATCH_FIELDS = [
  "elevation_hint", "mountain_strength", "moisture_bonus",
  "temperature_delta", "rainfall_delta", "fantasy_zone",
];

const state = {
  mode: "province",
  scale: 1,
  data: null,
  image: null,
  previewScale: 1,
  selectedColor: null,
  selectedState: null,
  selectedStates: [],
  countryOverlayVisible: false,
  countryBordersImage: null,
  assetVersion: Date.now(),
  baseRevision: null,
  constraints: { states: {}, provinces: {}, overrides: {} },
  editedFields: {},
  editedStateFields: {},
  autosaveTimer: null,
  autosaveInterval: null,
  suppressAutosave: false,
  riverPathRecording: false,
  riverPathOwner: null,
  riverPathDraft: [],
};

const canvas = document.getElementById("mapCanvas");
const overlay = document.getElementById("overlayCanvas");
const ctx = canvas.getContext("2d", { willReadFrequently: true });
const octx = overlay.getContext("2d");
const pickCanvas = document.createElement("canvas");
const pickCtx = pickCanvas.getContext("2d", { willReadFrequently: true });
const wrap = document.getElementById("canvasWrap");
const $ = (id) => document.getElementById(id);

function setStatus(text) { $("loadStatus").textContent = text; }
function cacheBust(path) { return `${path}${path.includes("?") ? "&" : "?"}v=${state.assetVersion}`; }

async function loadJson(path) {
  const response = await fetch(cacheBust(path));
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json();
}

async function loadOptionalJson(path) {
  try {
    return await loadJson(path);
  } catch (error) {
    console.warn(`optional data unavailable: ${path}`, error);
    return null;
  }
}

async function init() {
  try {
    const [provinceIndex, stateIndex, countryIndex] = await Promise.all([
      loadJson("../data/province_index.json"),
      loadJson("../data/state_index.json"),
      loadOptionalJson("../data/country_index.json"),
    ]);
    state.data = { provinceIndex, stateIndex, countryIndex };
    state.previewScale = Number(provinceIndex.preview_scale || 1);
    await Promise.all([
      loadDisplayImage("../data/map_preview.png"),
      loadPickImage("../data/province_pick.png"),
      loadOptionalDisplayImage("../data/country_borders.png", (image) => { state.countryBordersImage = image; }),
    ]);
    bindEvents();
    state.baseRevision = await hashSnapshot(emptySnapshot());
    $("baseRevision").textContent = shortRevision(state.baseRevision);
    updateModeUi();
    updateTrackingUi();
    updateValidation();
    fitView();
    setStatus(`프로빈스 ${Object.keys(provinceIndex.provinces).length.toLocaleString()}개`);
    startAutosaveLoop();
    offerAutosaveRestore();
  } catch (error) {
    setStatus(`불러오기 실패: ${error.message}`);
    console.error(error);
  }
}

function loadDisplayImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      state.image = image;
      canvas.width = image.width;
      canvas.height = image.height;
      overlay.width = image.width;
      overlay.height = image.height;
      ctx.drawImage(image, 0, 0);
      resolve();
    };
    image.onerror = reject;
    image.src = cacheBust(src);
  });
}

function loadPickImage(src) {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => {
      pickCanvas.width = image.width;
      pickCanvas.height = image.height;
      pickCtx.drawImage(image, 0, 0);
      resolve();
    };
    image.onerror = reject;
    image.src = cacheBust(src);
  });
}

function loadOptionalDisplayImage(src, onLoad) {
  return new Promise((resolve) => {
    const image = new Image();
    image.onload = () => {
      onLoad(image);
      resolve();
    };
    image.onerror = () => {
      console.warn(`optional image unavailable: ${src}`);
      resolve();
    };
    image.src = cacheBust(src);
  });
}

function bindEvents() {
  $("provinceMode").addEventListener("click", () => setMode("province"));
  $("stateMode").addEventListener("click", () => setMode("state"));
  $("countryOverlay").addEventListener("click", toggleCountryOverlay);
  $("provinceSearchButton").addEventListener("click", runProvinceSearch);
  $("provinceSearch").addEventListener("keydown", (event) => {
    if (event.key === "Enter") runProvinceSearch();
  });
  $("zoomIn").addEventListener("click", () => setZoom(state.scale * 1.25));
  $("zoomOut").addEventListener("click", () => setZoom(state.scale / 1.25));
  $("zoom1").addEventListener("click", () => setZoom(1));
  $("zoom2").addEventListener("click", () => setZoom(2));
  $("zoom4").addEventListener("click", () => setZoom(4));
  $("zoom8").addEventListener("click", () => setZoom(8));
  $("resetView").addEventListener("click", fitView);
  $("clearSelection").addEventListener("click", clearSelection);
  $("applyConstraint").addEventListener("click", applyConstraint);
  $("clearConstraint").addEventListener("click", clearConstraint);
  $("applyOverride").addEventListener("click", applyOverride);
  $("clearOverride").addEventListener("click", clearOverride);
  $("downloadProject").addEventListener("click", downloadProject);
  $("uploadProjectButton").addEventListener("click", () => $("projectFileInput").click());
  $("projectFileInput").addEventListener("change", handleProjectFile);
  $("clearAutosave").addEventListener("click", clearAutosave);
  $("exportBundle").addEventListener("click", beginExport);
  $("toggleRiverPath").addEventListener("click", toggleRiverPathRecording);
  $("undoRiverPath").addEventListener("click", undoRiverPathPoint);
  $("clearRiverPath").addEventListener("click", clearRiverPath);
  $("editorId").addEventListener("input", () => scheduleAutosave(AUTOSAVE_DEBOUNCE_MS));
  $("mountainStrength").addEventListener("input", updateMountainLabel);
  $("mountainEnabled").addEventListener("change", updateMountainControl);
  $("locked").addEventListener("change", updateOverrideControls);
  $("climateLock").addEventListener("change", updateOverrideControls);
  $("excludeFromSim").addEventListener("change", confirmExclude);
  ["riverSeed", "riverMajor", "lakeSeed", "wetlandSeed", "locked", "forceTerrain", "forceBiome",
    "climateLock", "forceTemp", "forceMoisture",
    "forceRainfall", "excludeFromSim"].forEach((id) => $(id).addEventListener("change", updateValidation));
  wrap.addEventListener("mousemove", updateCursor);
  canvas.addEventListener("click", selectAt);
  document.addEventListener("keydown", handleShortcut);
}

function handleShortcut(event) {
  if (event.ctrlKey || event.altKey || event.metaKey) return;
  if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement || event.target instanceof HTMLSelectElement) return;
  const actions = {
    p: () => setMode("province"), s: () => setMode("state"),
    "1": () => setZoom(1), "2": () => setZoom(2), "3": () => setZoom(4), "4": () => setZoom(8),
    "5": fitView, "=": () => setZoom(state.scale * 1.25), "+": () => setZoom(state.scale * 1.25),
    "-": () => setZoom(state.scale / 1.25), x: clearSelection,
  };
  const action = actions[event.key.toLowerCase()];
  if (!action) return;
  event.preventDefault();
  action();
}

function setMode(mode) {
  if (state.riverPathRecording) cancelRiverPathRecording();
  state.mode = mode;
  if (mode === "province") state.selectedStates = [];
  if (mode === "state" && state.selectedState && !state.selectedStates.length) {
    state.selectedStates = [state.selectedState];
  }
  updateModeUi();
  loadCurrentEditValues();
  drawSelection();
  scheduleAutosave();
}

function updateModeUi() {
  const isState = state.mode === "state";
  $("provinceMode").classList.toggle("active", !isState);
  $("stateMode").classList.toggle("active", isState);
  $("countryOverlay").classList.toggle("active", state.countryOverlayVisible);
  $("selectedMode").textContent = isState ? "주" : "프로빈스";
  $("modeHelp").textContent = isState
    ? "입력한 조건을 선택한 주의 모든 프로빈스에 일괄 적용합니다."
    : "프로빈스 조건과 예외를 편집합니다.";
  $("applyConstraint").textContent = isState ? "주 전체 적용" : "조건 적용";
  $("clearConstraint").textContent = isState ? "주 전체 삭제" : "조건 삭제";
  $("anchorFields").disabled = isState;
  $("overrideSection").querySelectorAll("input, select, button, details").forEach((element) => {
    element.disabled = isState;
  });
  $("overrideSection").classList.toggle("disabledSection", isState);
}

function toggleCountryOverlay() {
  if (!state.countryBordersImage) return setStatus("국가 경계 데이터가 없습니다. country_index를 먼저 생성하세요.");
  state.countryOverlayVisible = !state.countryOverlayVisible;
  $("countryOverlay").classList.toggle("active", state.countryOverlayVisible);
  drawSelection();
  setStatus(state.countryOverlayVisible ? "국가 경계 표시 켜짐" : "국가 경계 표시 꺼짐");
}

function setZoom(value) {
  state.scale = Math.max(0.2, Math.min(8, value));
  const width = Math.round(canvas.width * state.scale);
  const height = Math.round(canvas.height * state.scale);
  for (const item of [canvas, overlay]) {
    item.style.width = `${width}px`;
    item.style.height = `${height}px`;
  }
  setStatus(`프로빈스 ${Object.keys(state.data.provinceIndex.provinces).length.toLocaleString()}개 · 보기 ${state.scale.toFixed(2)}배`);
  scheduleAutosave(AUTOSAVE_DEBOUNCE_MS);
}

function fitView() {
  if (!canvas.width || !canvas.height) return;
  setZoom(Math.min(wrap.clientWidth / canvas.width, (wrap.clientHeight - 4) / canvas.height));
}

function eventToCanvasPoint(event) {
  const rect = canvas.getBoundingClientRect();
  return {
    x: Math.floor((event.clientX - rect.left) * canvas.width / rect.width),
    y: Math.floor((event.clientY - rect.top) * canvas.height / rect.height),
  };
}

function updateCursor(event) {
  const { x, y } = eventToCanvasPoint(event);
  $("cursorStatus").textContent = `x: ${x}, y: ${y}`;
}

function selectAt(event) {
  const { x, y } = eventToCanvasPoint(event);
  if (x < 0 || y < 0 || x >= canvas.width || y >= canvas.height) return;
  const pixel = pickCtx.getImageData(x, y, 1, 1).data;
  const color = rgbToKey(pixel[0], pixel[1], pixel[2]);
  if (!state.data.provinceIndex.provinces[color]) return clearSelection();
  if (state.riverPathRecording) return appendRiverPathPoint(color);
  state.selectedColor = color;
  state.selectedState = state.data.stateIndex.province_to_state[color] || null;
  if (state.mode === "state") {
    if (event.ctrlKey || event.metaKey) {
      if (state.selectedState) {
        const index = state.selectedStates.indexOf(state.selectedState);
        if (index >= 0) state.selectedStates.splice(index, 1);
        else state.selectedStates.push(state.selectedState);
      }
    } else {
      state.selectedStates = state.selectedState ? [state.selectedState] : [];
    }
    if (!state.selectedStates.length) {
      state.selectedColor = null;
      state.selectedState = null;
    } else if (!state.selectedStates.includes(state.selectedState)) {
      state.selectedState = state.selectedStates[state.selectedStates.length - 1];
      state.selectedColor = state.data.stateIndex.states[state.selectedState]?.provinces?.[0] || null;
    }
  } else {
    state.selectedStates = [];
  }
  updateSelectionPanel();
  loadCurrentEditValues();
  drawSelection();
  scheduleAutosave(AUTOSAVE_DEBOUNCE_MS);
}

function rgbToKey(r, g, b) {
  return `x${r.toString(16).padStart(2, "0").toUpperCase()}${g.toString(16).padStart(2, "0").toUpperCase()}${b.toString(16).padStart(2, "0").toUpperCase()}`;
}

function keyToRgb(color) {
  return [parseInt(color.slice(1, 3), 16), parseInt(color.slice(3, 5), 16), parseInt(color.slice(5, 7), 16)];
}

function clearSelection() {
  if (state.riverPathRecording) cancelRiverPathRecording();
  state.selectedColor = null;
  state.selectedState = null;
  state.selectedStates = [];
  updateSelectionPanel();
  clearForm();
  drawSelection();
  scheduleAutosave(AUTOSAVE_DEBOUNCE_MS);
}

function runProvinceSearch() {
  const input = $("provinceSearch").value.trim();
  if (!input) return setStatus("검색어를 입력하세요.");
  const result = resolveSearchTarget(input);
  if (!result) return setStatus(`검색 결과가 없습니다: ${input}`);
  selectSearchTarget(result);
}

function resolveSearchTarget(input) {
  const normalized = input.trim();
  const upper = normalized.toUpperCase();
  const provinceColor = upper.startsWith("X") ? `x${upper.slice(1)}` : `x${upper}`;
  if (/^x[0-9A-F]{6}$/.test(provinceColor) && validProvince(provinceColor)) {
    return { type: "province", color: provinceColor };
  }

  const states = state.data.stateIndex.states || {};
  const exactState = states[upper] ? upper : null;
  const partialState = exactState || Object.keys(states).find((key) => key.includes(upper));
  if (partialState && states[partialState]?.provinces?.length) {
    return { type: "state", stateId: partialState, color: states[partialState].provinces[0] };
  }

  const countryIndex = state.data.countryIndex;
  if (countryIndex?.countries) {
    const exactTag = countryIndex.countries[upper] ? upper : null;
    const partialTag = exactTag || Object.keys(countryIndex.countries).find((tag) => tag.includes(upper));
    const provinces = partialTag ? countryIndex.countries[partialTag]?.provinces : null;
    const color = Array.isArray(provinces) ? provinces.find(validProvince) : null;
    if (color) return { type: "country", tag: partialTag, color };
  }

  return null;
}

function selectSearchTarget(result) {
  state.selectedColor = result.color;
  state.selectedState = state.data.stateIndex.province_to_state[result.color] || null;
  if (result.type === "state") {
    setMode("state");
    state.selectedState = result.stateId;
    state.selectedStates = [result.stateId];
  } else {
    setMode("province");
    state.selectedStates = [];
  }
  centerOnProvince(result.color);
  updateSelectionPanel();
  loadCurrentEditValues();
  drawSelection();
  const label = result.type === "country" ? `${result.tag} / ${result.color}` : result.type === "state" ? `${result.stateId} / ${result.color}` : result.color;
  setStatus(`검색 이동: ${label}`);
  scheduleAutosave(AUTOSAVE_DEBOUNCE_MS);
}

function centerOnProvince(color) {
  const province = state.data.provinceIndex.provinces[color];
  if (!province?.bbox) return;
  if (state.scale < 1) setZoom(1);
  const [minX, minY, maxX, maxY] = province.bbox;
  const centerX = (minX + maxX + 1) / 2;
  const centerY = (minY + maxY + 1) / 2;
  wrap.scrollLeft = Math.max(0, centerX * state.scale - wrap.clientWidth / 2);
  wrap.scrollTop = Math.max(0, centerY * state.scale - wrap.clientHeight / 2);
}

function updateSelectionPanel() {
  const province = state.selectedColor ? state.data.provinceIndex.provinces[state.selectedColor] : null;
  const stateIds = selectedStateIds();
  const countryTag = selectedCountryTag();
  $("selectedColor").textContent = state.selectedColor || "-";
  $("selectedState").textContent = stateIds.length > 1
    ? `${stateIds[0]} 외 ${stateIds.length - 1}개`
    : (state.selectedState || "-");
  $("selectedCountry").textContent = countryTag || "-";
  if (state.mode === "state" && stateIds.length > 1) {
    const provinces = selectedStateProvinceColors(stateIds);
    const area = provinces.reduce((sum, color) => sum + (state.data.provinceIndex.provinces[color]?.area_pixels || 0), 0);
    $("selectedArea").textContent = `${area.toLocaleString()} (${provinces.length.toLocaleString()}개 프로빈스)`;
  } else {
    $("selectedArea").textContent = province ? province.area_pixels.toLocaleString() : "-";
  }
}

function selectedCountryTag() {
  if (!state.selectedColor) return null;
  return state.data.countryIndex?.province_to_country?.[state.selectedColor] || null;
}

function toggleRiverPathRecording() {
  if (state.riverPathRecording) return finishRiverPathRecording();
  if (state.mode !== "province" || !state.selectedColor) {
    return setStatus("강 경로를 시작할 프로빈스를 먼저 선택하세요.");
  }
  if (isSeaProvince(state.selectedColor)) return setStatus("강 경로는 육지 프로빈스에서 시작해야 합니다.");
  const saved = state.constraints.provinces[state.selectedColor]?.river_path;
  state.riverPathRecording = true;
  state.riverPathOwner = state.selectedColor;
  state.riverPathDraft = Array.isArray(saved) && saved.length ? [...saved] : [state.selectedColor];
  updateRiverPathUi();
  drawSelection();
  setStatus("강 경로 기록 중 · 하류 방향으로 인접 프로빈스를 클릭하세요.");
}

function finishRiverPathRecording() {
  if (!state.riverPathRecording) return;
  if (state.riverPathDraft.length < 2) {
    return setStatus("강 경로에는 시작점과 하류 지점이 하나 이상 필요합니다.");
  }
  const owner = state.riverPathOwner;
  const previous = state.constraints.provinces[owner] || {};
  const next = { ...previous, river_path: [...state.riverPathDraft] };
  state.constraints.provinces[owner] = next;
  recordEdits(owner, changedFields(previous, next), false);
  state.riverPathRecording = false;
  state.riverPathOwner = null;
  state.riverPathDraft = [];
  redrawBaseMap();
  drawSelection();
  updateRiverPathUi();
  updateTrackingUi();
  updateValidation();
  markDirty();
  setStatus(`강 경로 저장 완료 · ${next.river_path.length.toLocaleString()}개 프로빈스`);
}

function cancelRiverPathRecording() {
  state.riverPathRecording = false;
  state.riverPathOwner = null;
  state.riverPathDraft = [];
  updateRiverPathUi();
  drawSelection();
}

function appendRiverPathPoint(color) {
  const path = state.riverPathDraft;
  const previous = path[path.length - 1];
  if (color === previous) return;
  if (isSeaProvince(previous)) {
    return setStatus("바다 프로빈스는 강 경로의 마지막 지점으로만 사용할 수 있습니다.");
  }
  if (path.includes(color)) return setStatus("같은 프로빈스를 경로에 두 번 넣을 수 없습니다.");
  if (!areAdjacentProvinces(previous, color)) {
    return setStatus("강 경로는 서로 맞닿은 프로빈스만 차례대로 연결할 수 있습니다.");
  }
  path.push(color);
  updateRiverPathUi();
  drawSelection();
  setStatus(`강 경로 기록 중 · ${path.length.toLocaleString()}개 프로빈스`);
}

function undoRiverPathPoint() {
  if (!state.riverPathRecording || state.riverPathDraft.length <= 1) return;
  state.riverPathDraft.pop();
  updateRiverPathUi();
  drawSelection();
  setStatus(`마지막 지점 취소 · ${state.riverPathDraft.length.toLocaleString()}개 프로빈스`);
}

function clearRiverPath() {
  const owner = state.riverPathRecording ? state.riverPathOwner : state.selectedColor;
  if (!owner) return;
  const previous = state.constraints.provinces[owner] || {};
  if (state.riverPathRecording) cancelRiverPathRecording();
  if (!Object.prototype.hasOwnProperty.call(previous, "river_path")) {
    updateRiverPathUi();
    return setStatus("삭제할 강 경로가 없습니다.");
  }
  const next = { ...previous };
  delete next.river_path;
  if (Object.keys(next).length) state.constraints.provinces[owner] = next;
  else delete state.constraints.provinces[owner];
  recordEdits(owner, ["river_path"], false);
  redrawBaseMap();
  drawSelection();
  updateRiverPathUi();
  updateTrackingUi();
  updateValidation();
  markDirty();
  setStatus("강 경로 삭제 완료");
}

function currentRiverPath() {
  if (state.riverPathRecording) return state.riverPathDraft;
  if (state.mode !== "province" || !state.selectedColor) return [];
  const path = state.constraints.provinces[state.selectedColor]?.river_path;
  return Array.isArray(path) ? path : [];
}

function isSeaProvince(color) {
  const stateId = color ? state.data.stateIndex.province_to_state[color] : null;
  return typeof stateId === "string" && /(?:^|_)SEA(?:_|$)/i.test(stateId);
}

function updateRiverPathUi() {
  const editor = document.querySelector(".riverPathEditor");
  if (!editor) return;
  const path = currentRiverPath();
  const available = state.mode === "province" && Boolean(state.selectedColor);
  editor.classList.toggle("recording", state.riverPathRecording);
  $("riverPathStatus").textContent = path.length ? `${path.length.toLocaleString()}개 프로빈스` : "미설정";
  $("toggleRiverPath").textContent = state.riverPathRecording ? "경로 기록 완료" : "경로 기록 시작";
  $("toggleRiverPath").disabled = !available;
  $("undoRiverPath").disabled = !state.riverPathRecording || path.length <= 1;
  $("clearRiverPath").disabled = !state.riverPathRecording && path.length === 0;
  $("applyConstraint").disabled = state.riverPathRecording;
  $("clearConstraint").disabled = state.riverPathRecording;
}

function areAdjacentProvinces(colorA, colorB) {
  const province = state.data.provinceIndex.provinces[colorA];
  if (!province) return false;
  const [rawX, rawY, rawWidth, rawHeight] = provincePreviewRect(province);
  const sx = Math.max(0, rawX - 1);
  const sy = Math.max(0, rawY - 1);
  const ex = Math.min(pickCanvas.width, rawX + rawWidth + 1);
  const ey = Math.min(pickCanvas.height, rawY + rawHeight + 1);
  const width = ex - sx;
  const height = ey - sy;
  const data = pickCtx.getImageData(sx, sy, width, height).data;
  const rgbA = keyToRgb(colorA);
  const rgbB = keyToRgb(colorB);
  const matches = (x, y, rgb) => {
    if (x < 0 || y < 0 || x >= width || y >= height) return false;
    const i = (y * width + x) * 4;
    return data[i] === rgb[0] && data[i + 1] === rgb[1] && data[i + 2] === rgb[2];
  };
  for (let y = 0; y < height; y += 1) {
    for (let x = 0; x < width; x += 1) {
      if (!matches(x, y, rgbA)) continue;
      if (matches(x - 1, y, rgbB) || matches(x + 1, y, rgbB)
        || matches(x, y - 1, rgbB) || matches(x, y + 1, rgbB)) return true;
    }
  }
  return false;
}

function selectedStateIds() {
  if (state.mode !== "state") return [];
  if (state.selectedStates.length) return [...state.selectedStates];
  return state.selectedState ? [state.selectedState] : [];
}

function selectedStateProvinceColors(stateIds = selectedStateIds()) {
  const colors = [];
  const seen = new Set();
  for (const stateId of stateIds) {
    const item = state.data.stateIndex.states[stateId];
    if (!item?.provinces?.length) continue;
    for (const color of item.provinces) {
      if (seen.has(color)) continue;
      seen.add(color);
      colors.push(color);
    }
  }
  return colors;
}

function activeKey() { return state.mode === "state" ? selectedStateIds()[0] : state.selectedColor; }

function loadCurrentEditValues() {
  clearForm();
  const key = activeKey();
  const source = state.mode === "state"
    ? commonProvinceConstraintForStates(selectedStateIds())
    : (key ? state.constraints.provinces[key] || {} : {});
  $("elevationHint").value = source.elevation_hint ?? "";
  $("mountainEnabled").checked = Object.prototype.hasOwnProperty.call(source, "mountain_strength");
  $("mountainStrength").value = source.mountain_strength ?? 0;
  $("moistureBonus").value = source.moisture_bonus ?? "";
  $("temperatureDelta").value = source.temperature_delta ?? "";
  $("rainfallDelta").value = source.rainfall_delta ?? "";
  $("fantasyZone").value = source.fantasy_zone ?? "";
  $("riverSeed").checked = Boolean(source.river_seed);
  $("riverMajor").checked = Boolean(source.river_major);
  $("lakeSeed").checked = Boolean(source.lake_seed);
  $("wetlandSeed").checked = Boolean(source.wetland_seed);
  updateRiverPathUi();

  if (state.mode === "province" && state.selectedColor) {
    const override = state.constraints.overrides[state.selectedColor] || {};
    $("locked").checked = Boolean(override.locked);
    $("forceTerrain").value = override.force_terrain ?? "";
    $("forceBiome").value = override.force_biome ?? "";
    $("climateLock").checked = Boolean(override.climate_lock);
    $("forceTemp").value = override.force_temp ?? "";
    $("forceMoisture").value = override.force_moisture ?? "";
    $("forceRainfall").value = override.force_rainfall ?? "";
    $("excludeFromSim").checked = Boolean(override.exclude_from_sim);
  }
  updateMountainControl();
  updateOverrideControls();
  updateValidation();
}

function commonProvinceConstraintForState(stateId) {
  return commonProvinceConstraintForStates(stateId ? [stateId] : []);
}

function commonProvinceConstraintForStates(stateIds) {
  const provinces = selectedStateProvinceColors(stateIds);
  if (!provinces.length) return {};
  const result = {};
  const first = state.constraints.provinces[provinces[0]] || {};
  for (const field of STATE_BATCH_FIELDS) {
    if (!Object.prototype.hasOwnProperty.call(first, field)) continue;
    const value = JSON.stringify(first[field]);
    if (provinces.every((color) => {
      const item = state.constraints.provinces[color] || {};
      return Object.prototype.hasOwnProperty.call(item, field) && JSON.stringify(item[field]) === value;
    })) result[field] = first[field];
  }
  return result;
}

function clearForm() {
  ["elevationHint", "fantasyZone", "forceTerrain", "forceBiome"].forEach((id) => $(id).value = "");
  ["moistureBonus", "temperatureDelta", "rainfallDelta", "forceTemp", "forceMoisture", "forceRainfall"].forEach((id) => $(id).value = "");
  ["mountainEnabled", "riverSeed", "riverMajor", "lakeSeed", "wetlandSeed", "locked", "climateLock", "excludeFromSim"].forEach((id) => $(id).checked = false);
  $("mountainStrength").value = 0;
  updateMountainControl();
  updateOverrideControls();
  updateRiverPathUi();
}

function updateMountainControl() {
  $("mountainStrength").disabled = !$("mountainEnabled").checked;
  updateMountainLabel();
}

function updateMountainLabel() {
  $("mountainValue").textContent = $("mountainEnabled").checked ? Number($("mountainStrength").value).toFixed(2) : "미설정";
}

function updateOverrideControls() {
  const isState = state.mode === "state";
  document.querySelectorAll(".lockedFields input, .lockedFields select").forEach((element) => {
    element.disabled = isState || !$("locked").checked;
  });
  document.querySelectorAll(".climateFields input").forEach((element) => {
    element.disabled = isState || !$("climateLock").checked;
  });
  $("excludeFromSim").disabled = isState;
}

function confirmExclude() {
  if (!$("excludeFromSim").checked) return updateValidation();
  const confirmed = window.confirm("이 프로빈스를 기후 시뮬레이션에서 제외합니다. 주변 계산이 왜곡될 수 있습니다. 계속할까요?");
  if (!confirmed) $("excludeFromSim").checked = false;
  updateValidation();
}

function formConstraint() {
  const item = {};
  putString(item, "elevation_hint", $("elevationHint").value);
  if ($("mountainEnabled").checked) item.mountain_strength = Number($("mountainStrength").value);
  putNumber(item, "moisture_bonus", $("moistureBonus").value);
  putNumber(item, "temperature_delta", $("temperatureDelta").value);
  putNumber(item, "rainfall_delta", $("rainfallDelta").value);
  putString(item, "fantasy_zone", $("fantasyZone").value.trim());
  if (state.mode === "province") {
    if ($("riverSeed").checked) item.river_seed = true;
    if ($("riverMajor").checked) item.river_major = true;
    if ($("lakeSeed").checked) item.lake_seed = true;
    if ($("wetlandSeed").checked) item.wetland_seed = true;
    const savedPath = state.selectedColor ? state.constraints.provinces[state.selectedColor]?.river_path : null;
    if (Array.isArray(savedPath) && savedPath.length) item.river_path = [...savedPath];
  }
  return item;
}

function formOverride() {
  const item = {};
  if ($("locked").checked) item.locked = true;
  putString(item, "force_terrain", $("forceTerrain").value);
  putString(item, "force_biome", $("forceBiome").value.trim());
  if ($("climateLock").checked) item.climate_lock = true;
  putNumber(item, "force_temp", $("forceTemp").value);
  putNumber(item, "force_moisture", $("forceMoisture").value);
  putNumber(item, "force_rainfall", $("forceRainfall").value);
  if ($("excludeFromSim").checked) item.exclude_from_sim = true;
  return item;
}

function putNumber(target, key, value) { if (value !== "") target[key] = Number(value); }
function putString(target, key, value) { if (value) target[key] = value; }

function applyConstraint() {
  const key = activeKey();
  if (!key) return setStatus("먼저 지도에서 대상을 선택하세요.");
  const next = formConstraint();
  if (state.mode === "state") {
    const stateIds = selectedStateIds();
    const provinces = selectedStateProvinceColors(stateIds);
    if (!provinces.length) return setStatus("먼저 주를 선택하세요.");
    if (!Object.keys(next).length) return setStatus("일괄 적용할 조건을 하나 이상 입력하세요.");
    let changedCount = 0;
    for (const color of provinces) {
      const previous = state.constraints.provinces[color] || {};
      const merged = { ...previous, ...next };
      const changed = changedFields(previous, merged);
      if (!changed.length) continue;
      state.constraints.provinces[color] = merged;
      recordEdits(color, changed, false);
      changedCount += 1;
    }
    for (const stateId of stateIds) delete state.constraints.states[stateId];
    setStatus(`${stateIds.length.toLocaleString()}개 주 · ${changedCount.toLocaleString()}개 프로빈스에 조건 일괄 적용`);
  } else {
    const previous = state.constraints.provinces[key] || {};
    const changed = changedFields(previous, next);
    if (Object.keys(next).length) state.constraints.provinces[key] = next;
    else delete state.constraints.provinces[key];
    recordEdits(key, changed, false);
    setStatus("프로빈스 조건 적용 완료");
  }
  redrawBaseMap();
  drawSelection();
  updateTrackingUi();
  updateValidation();
  markDirty();
}

function clearConstraint() {
  const key = activeKey();
  if (!key) return;
  if (state.mode === "state") {
    const stateIds = selectedStateIds();
    const provinces = selectedStateProvinceColors(stateIds);
    if (!provinces.length) return;
    let changedCount = 0;
    for (const color of provinces) {
      const previous = state.constraints.provinces[color] || {};
      const next = { ...previous };
      for (const field of STATE_BATCH_FIELDS) delete next[field];
      const changed = changedFields(previous, next);
      if (!changed.length) continue;
      if (Object.keys(next).length) state.constraints.provinces[color] = next;
      else delete state.constraints.provinces[color];
      recordEdits(color, changed, false);
      changedCount += 1;
    }
    for (const stateId of stateIds) delete state.constraints.states[stateId];
    setStatus(`${stateIds.length.toLocaleString()}개 주 · ${changedCount.toLocaleString()}개 프로빈스에서 조건 삭제`);
  } else {
    const previous = state.constraints.provinces[key] || {};
    delete state.constraints.provinces[key];
    recordEdits(key, Object.keys(previous), false);
    setStatus("프로빈스 조건 삭제 완료");
  }
  loadCurrentEditValues();
  redrawBaseMap();
  drawSelection();
  updateTrackingUi();
  markDirty();
}

function applyOverride() {
  if (state.mode === "state") return;
  if (!state.selectedColor) return setStatus("먼저 프로빈스를 선택하세요.");
  const validation = validateOverride(formOverride());
  if (validation.errors.length) {
    showValidation(validation);
    return setStatus("예외 설정 오류를 해결하세요.");
  }
  const next = formOverride();
  const previous = state.constraints.overrides[state.selectedColor] || {};
  const changed = changedFields(previous, next);
  if (Object.keys(next).length) state.constraints.overrides[state.selectedColor] = next;
  else delete state.constraints.overrides[state.selectedColor];
  recordEdits(state.selectedColor, changed, false);
  redrawBaseMap();
  drawSelection();
  updateTrackingUi();
  updateValidation();
  markDirty();
  setStatus("프로빈스 예외 적용 완료");
}

function clearOverride() {
  if (state.mode === "state" || !state.selectedColor) return;
  const previous = state.constraints.overrides[state.selectedColor] || {};
  delete state.constraints.overrides[state.selectedColor];
  recordEdits(state.selectedColor, Object.keys(previous), false);
  loadCurrentEditValues();
  redrawBaseMap();
  drawSelection();
  updateTrackingUi();
  markDirty();
}

function changedFields(previous, next) {
  const fields = new Set([...Object.keys(previous), ...Object.keys(next)]);
  return [...fields].filter((field) => JSON.stringify(previous[field]) !== JSON.stringify(next[field]));
}

function recordEdits(key, fields, isState) {
  const target = isState ? state.editedStateFields : state.editedFields;
  if (!fields.length) return;
  if (!target[key]) target[key] = [];
  for (const field of fields) if (!target[key].includes(field)) target[key].push(field);
  target[key].sort();
}

function validateOverride(item) {
  const errors = [];
  const warnings = [];
  if (item.force_terrain && !VALID_FORCE_TERRAINS.has(item.force_terrain)) {
    errors.push(`지원하지 않는 강제 지형입니다: ${item.force_terrain}`);
  }
  if (item.climate_lock && item.exclude_from_sim) errors.push("기후값 강제와 시뮬레이션 제외는 동시에 사용할 수 없습니다.");
  if (item.locked && !item.force_terrain && !item.force_biome) warnings.push("최종 라벨 강제가 켜져 있지만 강제할 지형 또는 바이옴이 없습니다.");
  if (!item.locked && (item.force_terrain || item.force_biome)) warnings.push("최종 라벨 강제가 꺼져 있으면 파이프라인은 그 값을 강제 결과로 쓰지 않습니다.");
  if (!item.climate_lock && [item.force_temp, item.force_moisture, item.force_rainfall].some((v) => v !== undefined)) {
    warnings.push("기후값 강제 꺼져 있으면 지정한 기온·수분·강수 값은 실제 계산에 반영되지 않습니다.");
  }
  if (item.exclude_from_sim) warnings.push("시뮬레이션 제외는 주변 프로빈스의 기후 계산을 왜곡할 수 있습니다.");
  return { errors, warnings };
}

function validateCurrentForm() {
  const result = state.mode === "province" ? validateOverride(formOverride()) : { errors: [], warnings: [] };
  if (state.mode === "province" && $("lakeSeed").checked && $("riverSeed").checked) result.warnings.push("호수·종착점과 강 시작점이 같이 지정되어 있습니다. 이 경우 호수·종착점이 우선됩니다.");
  if (state.mode === "province" && $("riverMajor").checked && !$("riverSeed").checked && currentRiverPath().length === 0) {
    result.warnings.push("주요 하천은 강 시작점 또는 강 경로가 있을 때만 유효합니다.");
  }
  return result;
}

function updateValidation() { showValidation(validateCurrentForm()); }

function showValidation(result) {
  const container = $("validationList");
  container.innerHTML = "";
  const messages = [
    ...result.errors.map((text) => ({ text, error: true })),
    ...result.warnings.map((text) => ({ text, error: false })),
  ];
  container.classList.toggle("empty", messages.length === 0);
  if (!messages.length) return container.textContent = "현재 경고가 없습니다.";
  for (const message of messages) {
    const div = document.createElement("div");
    div.className = `message${message.error ? " error" : ""}`;
    div.textContent = message.text;
    container.appendChild(div);
  }
}

function updateTrackingUi() {
  const provinceCount = Object.keys(state.editedFields).length;
  const stateCount = Object.keys(state.editedStateFields).length;
  $("editedProvinceCount").textContent = provinceCount.toLocaleString();
  $("editedStateCount").textContent = stateCount.toLocaleString();
  const dirty = provinceCount + stateCount > 0;
  $("dirtyBadge").textContent = dirty ? "변경 있음" : "변경 없음";
  $("dirtyBadge").classList.toggle("dirty", dirty);
  $("dirtyBadge").classList.toggle("muted", !dirty);
}

function clearOverlay() { octx.clearRect(0, 0, overlay.width, overlay.height); }

function drawSelection() {
  clearOverlay();
  drawCountryOverlay();
  if (state.mode === "state") {
    const stateIds = selectedStateIds();
    if (!stateIds.length) return;
    for (const stateId of stateIds) {
      const item = state.data.stateIndex.states[stateId];
      if (!item?.provinces?.length) continue;
      for (const color of item.provinces) drawProvinceMask(color, [255, 184, 48, 88]);
    }
    if (state.selectedColor) drawProvinceMask(state.selectedColor, [255, 230, 110, 136]);
    return;
  }
  if (!state.selectedColor) return;
  drawProvinceMask(state.selectedColor, [38, 190, 230, 168]);
  drawRiverPathOverlay(currentRiverPath());
}

function drawCountryOverlay() {
  if (!state.countryOverlayVisible || !state.countryBordersImage) return;
  octx.drawImage(state.countryBordersImage, 0, 0);
}

function drawRiverPathOverlay(path) {
  if (!Array.isArray(path) || path.length === 0) return;
  for (const color of path) drawProvinceMask(color, [39, 174, 230, 92]);
  const points = path
    .map((color) => provincePreviewCenter(color))
    .filter(Boolean);
  if (!points.length) return;
  octx.save();
  octx.lineCap = "round";
  octx.lineJoin = "round";
  octx.lineWidth = 3;
  octx.strokeStyle = "rgba(52, 199, 255, 0.95)";
  octx.beginPath();
  points.forEach(([x, y], index) => index ? octx.lineTo(x, y) : octx.moveTo(x, y));
  octx.stroke();
  octx.font = "bold 10px Segoe UI, sans-serif";
  octx.textAlign = "center";
  octx.textBaseline = "middle";
  points.forEach(([x, y], index) => {
    octx.beginPath();
    octx.fillStyle = index === 0 ? "#57d17d" : (index === points.length - 1 ? "#ffb34d" : "#28aede");
    octx.arc(x, y, 6, 0, Math.PI * 2);
    octx.fill();
    octx.fillStyle = "#101418";
    octx.fillText(String(index + 1), x, y + 0.5);
  });
  octx.restore();
}

function provincePreviewCenter(color) {
  const province = state.data.provinceIndex.provinces[color];
  if (!province) return null;
  const [x, y, width, height] = provincePreviewRect(province);
  return [x + width / 2, y + height / 2];
}

function redrawBaseMap() {
  if (!state.image) return;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.drawImage(state.image, 0, 0);
  for (const [stateId, item] of Object.entries(state.constraints.states)) {
    const currentState = state.data.stateIndex.states[stateId];
    if (!currentState) continue;
    for (const color of currentState.provinces) paintProvinceColor(color, colorForConstraint(item));
  }
  for (const [color, item] of Object.entries(state.constraints.provinces)) paintProvinceColor(color, colorForConstraint(item));
  for (const item of Object.values(state.constraints.provinces)) {
    if (!Array.isArray(item.river_path)) continue;
    for (const color of item.river_path) paintProvinceColor(color, [74, 158, 205]);
  }
  for (const [color, item] of Object.entries(state.constraints.overrides)) {
    const fill = colorForOverride(item);
    if (fill) paintProvinceColor(color, fill);
  }
}

function colorForConstraint(item) {
  if (item.fantasy_zone) return [174, 112, 210];
  if (item.river_major) return [49, 125, 184];
  if (item.river_seed || item.river_path) return [74, 158, 205];
  if (item.elevation_hint === "mountain" || Number(item.mountain_strength || 0) >= .8) return [150, 142, 130];
  if (item.elevation_hint === "highland" || Number(item.mountain_strength || 0) > 0) return [177, 151, 105];
  if (item.wetland_seed || item.lake_seed || Number(item.moisture_bonus || 0) > 0) return [104, 178, 168];
  if (Number(item.temperature_delta || 0) < 0) return [105, 159, 212];
  if (Number(item.temperature_delta || 0) > 0) return [220, 153, 91];
  if (Number(item.rainfall_delta || 0) < 0) return [211, 190, 106];
  if (Number(item.rainfall_delta || 0) > 0) return [104, 167, 105];
  return [214, 222, 230];
}

function colorForOverride(item) {
  if (item.exclude_from_sim) return [82, 64, 72];
  if (item.climate_lock) return [82, 178, 210];
  if (item.locked && item.force_terrain) return colorForForcedTerrain(item.force_terrain);
  if (item.locked && item.force_biome) return [196, 137, 218];
  return null;
}

function colorForForcedTerrain(terrain) {
  const colors = {
    plains: [198, 208, 126],
    forest: [89, 144, 82],
    hills: [173, 147, 102],
    mountain: [137, 132, 122],
    desert: [218, 194, 112],
    wetland: [103, 170, 155],
    jungle: [60, 136, 77],
    tundra: [177, 198, 202],
    savanna: [201, 178, 98],
    snow: [232, 240, 248],
  };
  return colors[terrain] || [196, 137, 218];
}

function paintProvinceColor(color, fill) {
  const province = state.data.provinceIndex.provinces[color];
  if (!province) return;
  const [sx, sy, width, height] = provincePreviewRect(province);
  const pickData = pickCtx.getImageData(sx, sy, width, height).data;
  const base = ctx.getImageData(sx, sy, width, height);
  const out = base.data;
  const [r, g, b] = keyToRgb(color);
  for (let i = 0; i < pickData.length; i += 4) {
    if (pickData[i] !== r || pickData[i + 1] !== g || pickData[i + 2] !== b) continue;
    if (isBoundaryPixel(out[i], out[i + 1], out[i + 2])) continue;
    out[i] = fill[0]; out[i + 1] = fill[1]; out[i + 2] = fill[2]; out[i + 3] = 255;
  }
  ctx.putImageData(base, sx, sy);
}

function drawProvinceMask(color, rgba) {
  const province = state.data.provinceIndex.provinces[color];
  if (!province) return;
  const [sx, sy, width, height] = provincePreviewRect(province);
  const pickData = pickCtx.getImageData(sx, sy, width, height).data;
  const mask = octx.getImageData(sx, sy, width, height);
  const out = mask.data;
  const [r, g, b] = keyToRgb(color);
  for (let i = 0; i < pickData.length; i += 4) {
    if (pickData[i] !== r || pickData[i + 1] !== g || pickData[i + 2] !== b) continue;
    out[i] = rgba[0]; out[i + 1] = rgba[1]; out[i + 2] = rgba[2]; out[i + 3] = rgba[3];
  }
  octx.putImageData(mask, sx, sy);
}

function provincePreviewRect(province) {
  const [x1, y1, x2, y2] = province.bbox;
  const scale = state.previewScale;
  return [
    Math.floor(x1 * scale), Math.floor(y1 * scale),
    Math.max(1, Math.ceil((x2 - x1 + 1) * scale)),
    Math.max(1, Math.ceil((y2 - y1 + 1) * scale)),
  ];
}

function isBoundaryPixel(r, g, b) {
  return (r === 24 && g === 24 && b === 24) || (r === 214 && g === 44 && b === 52);
}

function buildProjectState() {
  return {
    schema_version: PROJECT_STATE_SCHEMA_VERSION,
    saved_at: new Date().toISOString(),
    editor: $("editorId").value.trim(),
    base_revision: state.baseRevision,
    map: {
      province_index_version: state.data?.provinceIndex?.version ?? 1,
      state_index_version: state.data?.stateIndex?.version ?? 1,
      source: "../map_data/provinces.png",
      preview_scale: state.previewScale,
    },
    ui: {
      mode: state.mode,
      selected_color: state.selectedColor,
      selected_state: state.selectedState,
      selected_states: state.selectedStates,
      country_overlay: state.countryOverlayVisible,
      zoom: state.scale,
    },
    constraints: { states: state.constraints.states, provinces: state.constraints.provinces },
    overrides: state.constraints.overrides,
    tracking: { edited_fields: state.editedFields, edited_state_fields: state.editedStateFields },
  };
}

function markDirty() {
  updateTrackingUi();
  scheduleAutosave();
}

function autosaveKey() {
  const revision = state.baseRevision || "unknown";
  const prefix = revision.includes(":") ? revision.split(":")[1].slice(0, 8) : revision.slice(0, 8);
  return `${AUTOSAVE_KEY_PREFIX}.${prefix || "unknown"}`;
}

function setAutosaveStatus(text, isError = false) {
  const target = $("autosaveStatus");
  if (!target) return;
  target.textContent = text;
  target.classList.toggle("statusError", isError);
}

function scheduleAutosave(delay = AUTOSAVE_DEBOUNCE_MS) {
  if (state.suppressAutosave || !state.baseRevision) return;
  setAutosaveStatus("저장 필요");
  clearTimeout(state.autosaveTimer);
  state.autosaveTimer = setTimeout(saveAutosave, delay);
}

function startAutosaveLoop() {
  clearInterval(state.autosaveInterval);
  state.autosaveInterval = setInterval(() => {
    if (!state.baseRevision) return;
    saveAutosave();
  }, AUTOSAVE_INTERVAL_MS);
}

function saveAutosave() {
  if (state.suppressAutosave || !state.baseRevision) return;
  try {
    localStorage.setItem(autosaveKey(), JSON.stringify(buildProjectState()));
    const time = new Date().toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    setAutosaveStatus(`자동 저장됨 ${time}`);
  } catch (error) {
    console.error(error);
    setAutosaveStatus("자동 저장 실패 — 작업 저장 JSON으로 백업하세요", true);
  }
}

function clearAutosave() {
  try {
    localStorage.removeItem(autosaveKey());
    setAutosaveStatus("자동 저장본 삭제됨");
    setStatus("자동 저장본 삭제 완료");
  } catch (error) {
    console.error(error);
    setAutosaveStatus("자동 저장본 삭제 실패", true);
  }
}

function offerAutosaveRestore() {
  const raw = localStorage.getItem(autosaveKey());
  if (!raw) return setAutosaveStatus("자동 저장 대기");
  let savedAt = "";
  try {
    const project = JSON.parse(raw);
    savedAt = project.saved_at ? `\n저장 시각: ${new Date(project.saved_at).toLocaleString("ko-KR")}` : "";
  } catch {
    localStorage.removeItem(autosaveKey());
    return setAutosaveStatus("자동 저장 대기");
  }
  const restore = window.confirm(`브라우저에 이전 작업 자동 저장본이 있습니다.${savedAt}\n복원할까요?\n\n확인: 복원\n취소: 새로 시작`);
  if (restore) {
    try {
      restoreProjectState(JSON.parse(raw), { fromAutosave: true, allowRevisionMismatch: true });
      setStatus("자동 저장본 복원 완료");
      setAutosaveStatus("자동 저장본 복원됨");
    } catch (error) {
      console.error(error);
      setAutosaveStatus(`자동 저장본 복원 실패: ${error.message}`, true);
    }
  } else {
    localStorage.removeItem(autosaveKey());
    setAutosaveStatus("자동 저장 대기");
  }
}

async function handleProjectFile(event) {
  const file = event.target.files?.[0];
  event.target.value = "";
  if (!file) return;
  try {
    const project = JSON.parse(await file.text());
    restoreProjectState(project, { fromAutosave: false, allowRevisionMismatch: false });
    setStatus("작업 파일 불러오기 완료");
    scheduleAutosave();
  } catch (error) {
    console.error(error);
    setStatus(`작업 파일 불러오기 실패: ${error.message}`);
  }
}

function restoreProjectState(project, options = {}) {
  validateProjectState(project);
  const incomingRevision = project.base_revision || project.baseRevision || null;
  if (incomingRevision && incomingRevision !== state.baseRevision && !options.allowRevisionMismatch) {
    const proceed = window.confirm(
      "기준 revision이 현재 지도와 다릅니다. 계속 불러오면 나중에 병합 충돌이 생길 수 있습니다.\n\n계속 불러올까요?"
    );
    if (!proceed) throw new Error("사용자가 불러오기를 취소했습니다.");
  }

  state.suppressAutosave = true;
  state.riverPathRecording = false;
  state.riverPathOwner = null;
  state.riverPathDraft = [];
  const warnings = [];
  const constraints = project.constraints || {};
  state.constraints = {
    states: sanitizeStateConstraints(constraints.states || {}, warnings),
    provinces: sanitizeProvinceMap(constraints.provinces || {}, warnings, "조건"),
    overrides: sanitizeProvinceMap(project.overrides || constraints.overrides || {}, warnings, "예외"),
  };

  const tracking = project.tracking || {};
  state.editedFields = sanitizeTracking(tracking.edited_fields || project.edited_fields || {}, warnings);
  state.editedStateFields = sanitizeStateTracking(tracking.edited_state_fields || project.edited_state_fields || {}, warnings);

  const ui = project.ui || {};
  state.mode = ui.mode === "state" ? "state" : "province";
  state.selectedColor = validProvince(ui.selected_color) ? ui.selected_color : null;
  state.selectedState = validState(ui.selected_state) ? ui.selected_state : null;
  state.countryOverlayVisible = Boolean(ui.country_overlay);
  state.selectedStates = Array.isArray(ui.selected_states)
    ? ui.selected_states.filter((stateId) => validState(stateId))
    : [];
  if (state.selectedColor) state.selectedState = state.data.stateIndex.province_to_state[state.selectedColor] || state.selectedState;
  if (state.mode !== "state") state.selectedStates = [];
  if (state.mode === "state" && state.selectedState && !state.selectedStates.includes(state.selectedState)) {
    state.selectedStates.push(state.selectedState);
  }
  if (state.mode === "state" && !state.selectedState && state.selectedStates.length) {
    state.selectedState = state.selectedStates[0];
  }
  if (state.mode === "state" && state.selectedState && !state.selectedColor) {
    state.selectedColor = state.data.stateIndex.states[state.selectedState]?.provinces?.[0] || null;
  }
  $("editorId").value = project.editor || $("editorId").value;

  updateModeUi();
  updateSelectionPanel();
  redrawBaseMap();
  loadCurrentEditValues();
  drawSelection();
  updateTrackingUi();
  updateValidation();
  setZoom(Number(ui.zoom) || state.scale || 1);
  state.suppressAutosave = false;

  if (warnings.length) setStatus(`작업 복원 완료 · 무시된 항목 ${warnings.length}개`);
  else if (!options.fromAutosave) setStatus("작업 복원 완료");
}

function validateProjectState(project) {
  if (!project || typeof project !== "object") throw new Error("작업 파일 형식이 올바르지 않습니다.");
  if (project.schema_version === PROJECT_STATE_SCHEMA_VERSION) return;
  if (project.version === 2) return; // 이전 임시 저장 형식 호환
  throw new Error("지원하지 않는 작업 파일 버전입니다.");
}

function sanitizeStateConstraints(items, warnings) {
  const result = {};
  for (const [stateId, item] of Object.entries(items || {})) {
    if (!validState(stateId)) {
      warnings.push(`${stateId}: 현재 지도에 없는 state`);
      continue;
    }
    result[stateId] = cleanObject(item);
  }
  return result;
}

function sanitizeProvinceMap(items, warnings, label) {
  const result = {};
  for (const [color, item] of Object.entries(items || {})) {
    if (!validProvince(color)) {
      warnings.push(`${color}: 현재 지도에 없는 ${label}`);
      continue;
    }
    const cleaned = cleanObject(item);
    if (Object.keys(cleaned).length) result[color] = cleaned;
  }
  return result;
}

function sanitizeTracking(items, warnings) {
  const result = {};
  for (const [color, fields] of Object.entries(items || {})) {
    if (!validProvince(color)) {
      warnings.push(`${color}: 현재 지도에 없는 편집 기록`);
      continue;
    }
    result[color] = [...new Set(Array.isArray(fields) ? fields : [])].sort();
  }
  return result;
}

function sanitizeStateTracking(items, warnings) {
  const result = {};
  for (const [stateId, fields] of Object.entries(items || {})) {
    if (!validState(stateId)) {
      warnings.push(`${stateId}: 현재 지도에 없는 state 편집 기록`);
      continue;
    }
    result[stateId] = [...new Set(Array.isArray(fields) ? fields : [])].sort();
  }
  return result;
}

function cleanObject(item) {
  if (!item || typeof item !== "object" || Array.isArray(item)) return {};
  return Object.fromEntries(Object.entries(item).filter(([, value]) => value !== undefined && value !== null));
}

function validProvince(color) {
  return Boolean(color && state.data?.provinceIndex?.provinces?.[color]);
}

function validState(stateId) {
  return Boolean(stateId && state.data?.stateIndex?.states?.[stateId]);
}

function buildStateYaml() { return objectToYaml("state_constraints", state.constraints.states, "state_constraints.v0.2"); }
function buildProvinceYaml() { return objectToYaml("province_constraints", state.constraints.provinces, "province_constraints.v0.2"); }
function buildOverrideYaml() { return objectToYaml("province_overrides", state.constraints.overrides, "province_overrides.v0.2"); }

function objectToYaml(rootKey, items, schemaVersion) {
  const lines = [`schema_version: ${quoteYaml(schemaVersion)}`, `${rootKey}:`];
  const keys = Object.keys(items).sort();
  if (!keys.length) return `${lines[0]}\n${rootKey}: {}\n`;
  for (const key of keys) {
    lines.push(`  ${key}:`);
    for (const field of Object.keys(items[key]).sort()) {
      const value = items[key][field];
      if (Array.isArray(value)) {
        if (!value.length) lines.push(`    ${field}: []`);
        else {
          lines.push(`    ${field}:`);
          for (const item of value) lines.push(`      - ${quoteYaml(item)}`);
        }
      } else {
        lines.push(`    ${field}: ${yamlScalar(value)}`);
      }
    }
  }
  return `${lines.join("\n")}\n`;
}

function yamlScalar(value) {
  if (typeof value === "boolean" || typeof value === "number") return String(value);
  return quoteYaml(value);
}

function quoteYaml(value) { return JSON.stringify(String(value)); }

function emptySnapshot() {
  return {
    snapshot_schema_version: SNAPSHOT_SCHEMA_VERSION,
    province_constraints: {},
    province_overrides: {},
    state_constraints: {},
  };
}

function currentSnapshot() {
  return {
    snapshot_schema_version: SNAPSHOT_SCHEMA_VERSION,
    province_constraints: structuredClone(state.constraints.provinces),
    province_overrides: structuredClone(state.constraints.overrides),
    state_constraints: structuredClone(state.constraints.states),
  };
}

function recursiveCanonicalize(obj, parentKey = null) {
  if (Array.isArray(obj)) {
    const items = obj.map((item) => recursiveCanonicalize(item, null));
    return SET_ARRAY_FIELDS.has(parentKey) ? [...items].sort() : items;
  }
  if (obj !== null && typeof obj === "object") {
    return Object.fromEntries(Object.keys(obj)
      .filter((key) => obj[key] !== null)
      .sort()
      .map((key) => [key, recursiveCanonicalize(obj[key], key)]));
  }
  return obj;
}

async function hashSnapshot(snapshot) {
  const canonical = JSON.stringify(recursiveCanonicalize(snapshot));
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical));
  return `sha256:${[...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("")}`;
}

function shortRevision(revision) { return revision ? `${revision.slice(0, 15)}…${revision.slice(-8)}` : "-"; }

function createManifest(editor) {
  return {
    schema_version: MANIFEST_SCHEMA_VERSION,
    export_id: crypto.randomUUID(),
    base_revision: state.baseRevision,
    editor,
    exported_at: new Date().toISOString(),
    edited_provinces: Object.keys(state.editedFields).sort(),
    edited_states: Object.keys(state.editedStateFields).sort(),
    edited_fields: recursiveCanonicalize(state.editedFields),
    edited_state_fields: recursiveCanonicalize(state.editedStateFields),
  };
}

async function beginExport() {
  const editor = $("editorId").value.trim();
  const button = $("exportBundle");
  if (!editor) {
    $("editorId").focus();
    window.alert("Export 전에 편집자 ID를 입력하세요.");
    return setStatus("Export 전에 편집자 ID를 입력하세요.");
  }
  if (typeof JSZip === "undefined") {
    window.alert("ZIP 생성 라이브러리를 불러오지 못했습니다. 페이지를 새로고침해 주세요.");
    return setStatus("JSZip을 불러오지 못했습니다.");
  }
  try {
    button.disabled = true;
    button.textContent = "Export 생성 중...";
    setStatus("Export ZIP 생성 준비 중");
    await nextFrame();
    const result = validateAll();
    if (result.errors.length) {
      showValidation(result);
      return setStatus("오류를 해결한 뒤 Export하세요.");
    }
    if (result.warnings.length) {
      const proceed = await confirmWarnings(result.warnings);
      if (!proceed) return setStatus("Export 취소됨");
    }
    setStatus("Export ZIP 생성 중...");
    await nextFrame();
    await exportBundle(editor);
  } catch (error) {
    console.error(error);
    window.alert(`Export ZIP 생성 실패: ${error.message}`);
    setStatus(`Export ZIP 생성 실패: ${error.message}`);
  } finally {
    button.disabled = false;
    button.textContent = "Export ZIP";
  }
}

function validateAll() {
  const errors = [];
  const warnings = [];
  for (const [color, item] of Object.entries(state.constraints.overrides)) {
    const result = validateOverride(item);
    errors.push(...result.errors.map((message) => `${color}: ${message}`));
    warnings.push(...result.warnings.map((message) => `${color}: ${message}`));
  }
  for (const [color, item] of Object.entries(state.constraints.provinces)) {
    if (item.lake_seed && item.river_seed) warnings.push(`${color}: 호수·종착점과 강 시작점이 같이 지정되어 있습니다. 이 경우 호수·종착점이 우선됩니다.`);
    if (item.river_major && !item.river_seed && !item.river_path) warnings.push(`${color}: 주요 하천은 강 시작점 또는 강 경로가 있을 때만 유효합니다.`);
    if (item.river_path !== undefined) {
      if (!Array.isArray(item.river_path) || item.river_path.length < 2) {
        errors.push(`${color}: 강 경로에는 프로빈스가 2개 이상 필요합니다.`);
        continue;
      }
      if (item.river_path[0] !== color) errors.push(`${color}: 강 경로의 첫 프로빈스는 경로 소유 프로빈스와 같아야 합니다.`);
      if (new Set(item.river_path).size !== item.river_path.length) errors.push(`${color}: 강 경로에 중복 프로빈스가 있습니다.`);
      for (const pathColor of item.river_path) {
        if (!validProvince(pathColor)) errors.push(`${color}: 강 경로에 현재 지도에 없는 프로빈스가 있습니다: ${pathColor}`);
      }
      for (let index = 1; index < item.river_path.length; index += 1) {
        const upstream = item.river_path[index - 1];
        const downstream = item.river_path[index];
        if (validProvince(upstream) && validProvince(downstream) && !areAdjacentProvinces(upstream, downstream)) {
          errors.push(`${color}: 서로 맞닿지 않은 강 경로입니다: ${upstream} → ${downstream}`);
        }
        if (index < item.river_path.length - 1 && isSeaProvince(downstream)) {
          errors.push(`${color}: 바다 프로빈스는 강 경로의 마지막 지점으로만 사용할 수 있습니다.`);
        }
      }
    }
  }
  return { errors, warnings };
}

function confirmWarnings(warnings) {
  const dialog = $("warningDialog");
  const body = $("warningDialogBody");
  body.innerHTML = "";
  for (const warning of warnings) {
    const div = document.createElement("div");
    div.className = "message";
    div.textContent = warning;
    body.appendChild(div);
  }
  dialog.showModal();
  return new Promise((resolve) => dialog.addEventListener("close", () => resolve(dialog.returnValue === "confirm"), { once: true }));
}

async function exportBundle(editor) {
  const zip = new JSZip();
  const manifest = createManifest(editor);
  zip.file("export_manifest.json", JSON.stringify(manifest, null, 2));
  zip.file("state_constraints.yaml", buildStateYaml());
  zip.file("province_constraints.yaml", buildProvinceYaml());
  zip.file("province_overrides.yaml", buildOverrideYaml());
  const blob = await zip.generateAsync({ type: "blob", compression: "STORE" });
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "_").slice(0, 15);
  downloadBlob(`export_${sanitizeFilename(editor)}_${stamp}.zip`, blob);
  setStatus("Export ZIP 생성 완료");
}

function nextFrame() {
  return new Promise((resolve) => requestAnimationFrame(() => resolve()));
}

function sanitizeFilename(value) { return value.replace(/[<>:"/\\|?*\x00-\x1F]/g, "_").trim() || "editor"; }

function downloadProject() {
  const editor = sanitizeFilename($("editorId").value.trim() || "editor");
  const stamp = new Date().toISOString().replace(/[-:]/g, "").replace("T", "_").slice(0, 15);
  saveAutosave();
  downloadText(`project_state_${editor}_${stamp}.json`, JSON.stringify(buildProjectState(), null, 2), "application/json");
  setStatus("작업 저장 JSON 다운로드 완료");
}

function downloadText(filename, text, type = "text/plain") {
  downloadBlob(filename, new Blob([text], { type: `${type};charset=utf-8` }));
}

function downloadBlob(filename, blob) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

init();
