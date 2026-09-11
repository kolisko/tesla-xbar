# Status icons

Editable SVG artwork and prebuilt Retina PNG template images for charging, Camp
Mode, Pet Mode, running climate, an unlocked vehicle, Sentry Mode, an open front
trunk and an open rear trunk. The 191 PNG strips cover every
valid combination (Camp and Pet Mode are mutually exclusive).

The trunk icons use the front (`ft`) and rear (`rt`) closure readings independently
of the vehicle's lock state. Both may appear together. They require a current
online reading, like the other vehicle-state icons; unavailable or stale readings
remain text in **Locks and trunks** instead. Open includes an unlatched/ajar lid.
Their shapes follow the Tesla app's front/rear body-section symbols: a single
wheel with a raised hood or rear lid, adapted to the existing 16-point line style.
The unlocked padlock also follows the Tesla app reference, with its open shackle
offset to the left of the solid rounded lock body.

xBar places all icons, including the charging bolt, in the same monochrome strip
before the range or percentage. macOS chooses
the template tint for the current appearance. Each icon is 16 points tall;
the PNG carries 144 DPI density for its 32-pixel Retina representation.

The installer copies the PNGs into the private profile's `icons/` directory.
Python reads the matching strip directly; there is no rendering process or
additional dependency when the plugin runs. SVG sources are editable project
artwork; the unlock and trunk symbols are redrawn from the Tesla app reference, not extracted
from a personal screenshot. Regenerate them with
[`scripts/render_status_icons.cjs`](../../scripts/render_status_icons.cjs).
