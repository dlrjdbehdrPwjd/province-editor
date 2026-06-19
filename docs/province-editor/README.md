# Province Editor GitHub Pages Bundle

This directory is the static GitHub Pages deployment bundle for the province editor.

Source files are copied from:

- `Codex_프로그래머/프로빈스_프로젝트/web/`
- `Codex_프로그래머/프로빈스_프로젝트/data/`

The deployed layout preserves the editor runtime paths:

```text
province-editor/
  web/
  data/
```

The editor loads data through `../data/...` from `web/editor.js`, so keep `web` and `data` as siblings.
