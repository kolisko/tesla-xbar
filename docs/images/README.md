# Visual previews

These illustrations show the plugin's appearance using fictional data and a neutral background. They are not screenshots of a personal desktop. Native fonts, emoji and transparency vary with macOS and xBar.

| Files | Preview |
| --- | --- |
| [`menu-bar.svg`](menu-bar.svg), [`menu-bar.png`](menu-bar.png) | Green range label with a charging symbol. |
| [`menu.svg`](menu.svg), [`menu.png`](menu.png) | Expanded menu with battery readings, charging controls and settings. |
| [`states.svg`](states.svg), [`states.png`](states.png) | Charging, connected and low-range states, plus gray text without status icons for asleep and offline readings. |

[`scripts/render_previews.py`](../../scripts/render_previews.py) generates the SVG sources. The PNG versions are rendered from those SVGs for reliable display in the [main README](../../README.md#see-it-in-action). If changing an illustration, update both formats and check the rendered result. Keep PNGs free of personal information and embedded metadata; the public-file scan checks tracked PNGs for text and EXIF metadata.
