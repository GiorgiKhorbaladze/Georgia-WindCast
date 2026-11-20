# Premium system map verification

Captured in Chromium against the local Streamlit app with real readings from the existing GSE balance archive. The capture run used a 1440 × 960 desktop viewport and a 390 × 844 touch-enabled viewport. Desktop uses native browser fullscreen. The mobile-sized test forces native fullscreen to be unavailable and verifies the full-viewport fallback. This is mobile emulation, with no claim of real-device coverage.

| Language | Desktop | Desktop native fullscreen | Mobile | Mobile immersive fallback |
| --- | --- | --- | --- | --- |
| English | [Normal](en-desktop.png) | [Fullscreen](en-desktop-expanded.png) | [Normal](en-mobile.png) | [Immersive](en-mobile-expanded.png) |
| Georgian | [Normal](ka-desktop.png) | [Fullscreen](ka-desktop-expanded.png) | [Normal](ka-mobile.png) | [Immersive](ka-mobile-expanded.png) |

[Desktop exchange panels](exchange-panels-desktop.png) · [Mobile exchange panels](exchange-panels-mobile.png) · [Source and licensing notes](../../sources/system-snapshot.md)

Run the browser check with the app running and Playwright available to Node. The script tests English and Georgian, zoom and reset, site activation, playback, native and fallback entry/exit, retained map state and horizontal overflow. It checks that the map uses fewer than 50 SVG nodes and logs time to render from navigation. Set `SCREENSHOT_DIR` to capture screenshots. Set `BROWSER_ENGINE` to `firefox` or `webkit` to use an installed Playwright engine, or set `BROWSER_EXECUTABLE` to override its executable.

```sh
node streamlit_cloud/tests/browser_system_map.cjs
```
