# Premium system map verification

Captured in Chromium against the local Streamlit app with real readings from the existing GSE balance archive. The capture run used a 1440 × 960 desktop viewport and a 390 × 844 touch-enabled viewport. Desktop uses native browser fullscreen. The mobile-sized test forces native fullscreen to be unavailable and verifies the full-viewport fallback. This is mobile emulation, with no claim of real-device coverage.

| Language | Desktop | Desktop native fullscreen | Mobile | Mobile immersive fallback |
| --- | --- | --- | --- | --- |
| English | [Normal](en-desktop.png) | [Fullscreen](en-desktop-expanded.png) | [Normal](en-mobile.png) | [Immersive](en-mobile-expanded.png) |
| Georgian | [Normal](ka-desktop.png) | [Fullscreen](ka-desktop-expanded.png) | [Normal](ka-mobile.png) | [Immersive](ka-mobile-expanded.png) |

[English desktop balance](exchange-panels-desktop.png) · [English mobile balance](exchange-panels-mobile.png) · [Georgian desktop balance](ka-exchange-panels-desktop.png) · [Georgian mobile balance](ka-exchange-panels-mobile.png)

[Pinned archive reconciliation and original XML evidence](reconciliation.md) · [Source and licensing notes](../../sources/system-snapshot.md)

In the 20 November 2026 QA run, the displayed 17:12 Tbilisi readings matched the balance archive. The separate wind archive carried the same source period, value and payload SHA-256. Both archives showed retrieval at 17:15:34 Tbilisi. The national equation left a **+16.968126 MW** residual, displayed as **+16.97 MW**. The comparison uses stored data and does not establish why the source totals differ.

Run the browser check with the app running and Playwright available to Node. The script tests English and Georgian, zoom, drag pan and reset, site activation, recorded timestamps and playback, button and Escape exits in native and fallback modes, retained map state, height-only resizing, 390 px fallback rotation, reduced-motion preferences, stale/missing display and horizontal overflow. It checks that the map uses fewer than 50 SVG nodes and logs time to render from navigation. Set `SCREENSHOT_DIR` to capture screenshots. Set `BROWSER_ENGINE` to `firefox` or `webkit` to use an installed Playwright engine, or set `BROWSER_EXECUTABLE` to override its executable.

```sh
node streamlit_cloud/tests/browser_system_map.cjs
```
