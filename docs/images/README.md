# Visual previews

These illustrations show the plugin's appearance using fictional data and a neutral background. They are not screenshots of a personal desktop. Native fonts, emoji and transparency vary with macOS and xBar.

| Files | Preview |
| --- | --- |
| [`menu-bar.svg`](menu-bar.svg), [`menu-bar.png`](menu-bar.png) | Monochrome charging bolt before the green range label. |
| [`menu.svg`](menu.svg), [`menu.png`](menu.png) | Expanded menu with battery readings, charging controls and settings. |
| [`states.svg`](states.svg), [`states.png`](states.png) | Eight examples: charging, connected, low range, and asleep/offline with either a last known connected cable (green) or unplugged cable (normal range color). Offline/asleep readings have a small trailing dot and no active status icons. |
| [`status-icons.svg`](status-icons.svg), [`status-icons.png`](status-icons.png) | Matching charging, Camp Mode, Pet Mode, climate fan and open padlock icons, plus a combined menu-bar example. |
| [`clima.svg`](clima.svg), [`clima.png`](clima.png) | Clima controls for modes, temperature and shutdown. |
| [`locks-trunks.svg`](locks-trunks.svg), [`locks-trunks.png`](locks-trunks.png) | Combined lock/unlock and front/rear trunk controls with illustrative state readings. |

[`scripts/render_status_icons.cjs`](../../scripts/render_status_icons.cjs) generates
the status-icons preview together with the runtime PNG assets. Its optional
development dependencies are described in the [scripts guide](../../scripts/README.md).

[`scripts/render_previews.py`](../../scripts/render_previews.py) generates the SVG sources. The PNG versions are rendered from those SVGs for reliable display in the [main README](../../README.md#see-it-in-action). If changing an illustration, update both formats and check the rendered result. Keep PNGs free of personal information and embedded metadata; the public-file scan checks tracked PNGs for text and EXIF metadata.

`sentry-location.svg` / `.png` illustrate the Sentry and Location submenus. `location-map-example.png` is a real MapMap rendering of the public Times Square landmark (40.758, -73.9855), with POIs disabled and a locally drawn blue dot. It is a documentation example, not a user location or personal screenshot. Preserve its provider attribution. The menu illustration uses an example timestamp and the public landmark name.
