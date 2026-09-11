# Status icons

Editable SVG artwork and prebuilt Retina PNG template images for charging, Camp
Mode, Pet Mode, running climate, an unlocked vehicle, and Sentry Mode. The 47 PNG strips cover every
valid combination (Camp and Pet Mode are mutually exclusive).

xBar places all icons, including the charging bolt, in the same monochrome strip
before the range or percentage. macOS chooses
the template tint for the current appearance. Each icon is 16 points tall;
the PNG carries 144 DPI density for its 32-pixel Retina representation.

The installer copies the PNGs into the private profile's `icons/` directory.
Python reads the matching strip directly; there is no rendering process or
additional dependency when the plugin runs. SVG sources are original project
artwork under the repository license. Regenerate them with
[`scripts/render_status_icons.cjs`](../../scripts/render_status_icons.cjs).
