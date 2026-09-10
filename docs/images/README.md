# Visual previews

These illustrations show the plugin's appearance using fictional data and a neutral background. They are not screenshots of a personal desktop. Native fonts, emoji and transparency vary with macOS and xBar.

| Files | Preview |
| --- | --- |
| [`menu-bar.svg`](menu-bar.svg), [`menu-bar.png`](menu-bar.png) | Green range label with a charging symbol. |
| [`menu.svg`](menu.svg), [`menu.png`](menu.png) | Expanded menu with battery readings, charging controls and settings. |
| [`states.svg`](states.svg), [`states.png`](states.png) | Eight examples: charging, connected, low range, and asleep/offline with either a last known connected cable (green) or unplugged cable (gray). Unavailable readings have no status icon. |
| [`status-icons.svg`](status-icons.svg), [`status-icons.png`](status-icons.png) | Camp Mode, Pet Mode, climate fan and open padlock icons, plus a combined menu-bar example. |

[`scripts/render_status_icons.cjs`](../../scripts/render_status_icons.cjs) generates
the status-icons preview together with the runtime PNG assets. Its optional
development dependencies are described in the [scripts guide](../../scripts/README.md).

[`scripts/render_previews.py`](../../scripts/render_previews.py) generates the SVG sources. The PNG versions are rendered from those SVGs for reliable display in the [main README](../../README.md#see-it-in-action). If changing an illustration, update both formats and check the rendered result. Keep PNGs free of personal information and embedded metadata; the public-file scan checks tracked PNGs for text and EXIF metadata.
