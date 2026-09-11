"""Create documentation mockups with fictional data, without reading a Tesla profile."""
from pathlib import Path
from html import escape
import base64

OUT = Path(__file__).resolve().parents[1] / "docs/images"
OUT.mkdir(parents=True, exist_ok=True)
FONT = "Helvetica,Arial,sans-serif"


def text(x, y, value, size=24, fill="#e5e9ed", weight=400):
    return f'<text x="{x}" y="{y}" fill="{fill}" font-family="{FONT}" font-size="{size}" font-weight="{weight}">{escape(value)}</text>'


def bolt(x, y, scale=1):
    artwork = (OUT.parents[1] / 'src/icons/charging.svg').read_text()
    drawing = artwork.split('>', 1)[1].rsplit('</svg>', 1)[0].replace('#000', '#e5e9ed')
    return f'<g transform="translate({x},{y}) scale({scale})">{drawing}</g>'



def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
            '<title>Tesla xBar interface preview with fictional data</title>'
            '<defs><linearGradient id="blue" x2="1" y2="1"><stop stop-color="#126e98"/><stop offset="1" stop-color="#173a58"/></linearGradient>'
            '<linearGradient id="panel" x2="0" y2="1"><stop stop-color="#103d53"/><stop offset="0.55" stop-color="#24343f"/><stop offset="1" stop-color="#303337"/></linearGradient></defs>' + body + '</svg>')


bar = '<rect width="320" height="66" rx="14" fill="url(#blue)"/>'
bar += '<rect x="8" y="8" width="237" height="50" rx="22" fill="#ffffff" fill-opacity="0.06"/>'
bar += bolt(24, 18, 1.7) + text(67, 44, '360 km', 30, '#32cd66')
(OUT / 'menu-bar.svg').write_text(svg(320, 66, bar))

body = '<rect width="600" height="1183" rx="22" fill="url(#blue)"/>'
body += '<rect x="4" y="4" width="592" height="1175" rx="18" fill="url(#panel)" stroke="#8fa3af" stroke-opacity="0.5"/>'
body += text(27, 47, 'Tesla', 27, '#dce4eb', 600)
rows = ['Battery: 73 %', 'Tesla range: 360 km', 'Charge limit: 80 %', 'Cable: connected',
        'Charging', 'Power: 11 kW', 'Time to charge limit: 0 h 30 min', 'Battery reading from 12 Jul 09:41']
for i, row in enumerate(rows):
    body += text(27, 96 + i * 45, row, 24, '#aebdc8')

def divider(y):
    return f'<path d="M27 {y}H573" stroke="#95a7b1" stroke-opacity="0.3"/>'

body += divider(440)
for y, label, sub in [(486, 'Charging and port', True), (537, 'Clima', True), (588, 'Sentry', True), (639, 'Location', True), (706, 'Refresh now', False),
                      (753, 'Wake vehicle and refresh', False), (800, 'Connect Tesla account…', False),
                      (847, 'Settings…', False), (894, 'Menu bar display', True)]:
    body += text(27, y, label, 25)
    if sub:
        body += f'<path d="m562 {y-17} 7 7-7 7" fill="none" stroke="#e5e9ed" stroke-width="2.5"/>'
body += divider(664) + divider(927)
body += text(27, 970, 'Refresh interval managed by xBar', 23, '#aebdc8')
body += text(27, 1017, 'Tesla Developer', 25)
body += text(27, 1064, 'Manage Tesla permissions', 25)
body += divider(1097) + text(27, 1142, 'xbar', 25)
body += '<path d="m562 1125 7 7-7 7" fill="none" stroke="#e5e9ed" stroke-width="2.5"/>'
(OUT / 'menu.svg').write_text(svg(600, 1183, body))

body = '<rect width="1326" height="380" rx="20" fill="#111c29"/>'
examples = [('Charging', '360 km', '#32cd66', 'bolt'), ('Connected · paused', '360 km', '#32cd66', ''),
            ('Unplugged · below 350 km', '320 km', '#f5a623', ''), ('Unplugged · below 300 km', '280 km', '#ef4444', ''),
            ('Asleep · last connected', '360 km ·', '#32cd66', ''), ('Offline · last connected', '360 km ·', '#32cd66', ''),
            ('Asleep · last unplugged', '360 km ·', '#e5e9ed', ''), ('Offline · last unplugged', '360 km ·', '#e5e9ed', '')]
for i, (label, value, color, icon) in enumerate(examples):
    x, y = 20+(i%4)*326, 20+(i//4)*178
    body += f'<rect x="{x}" y="{y}" width="308" height="158" rx="14" fill="#1b2c3e"/>'
    body += text(x+20, y+40, label, 18, '#b4c6d7')
    body += text(x+(65 if icon == 'bolt' else 20), y+109, value, 34, color)
    if icon == 'bolt':
        body += bolt(x+20, y+82, 1.8)
(OUT / 'states.svg').write_text(svg(1326, 380, body))
body = '<rect width="600" height="702" rx="18" fill="#202932"/>'
body += text(28, 42, 'Clima', 25, weight=600)
for y, label in [(88, 'Climate mode: Camp Mode'), (124, 'Climate: on'), (160, 'Target temperature: 22 °C'),
                 (196, 'Inside temperature: 20.5 °C'), (232, 'Outside temperature: 19 °C')]:
    body += text(28, y, label, 22, '#a0a6ad')
body += divider(255)
for y, label in [(300, 'Turn climate on'), (347, 'Keep Climate On'), (394, '✓ Camp Mode'),
                 (441, 'Pet Mode'), (488, 'Set temperature (°C)')]:
    body += text(28, y, label, 24)
body += '<path d="m562 471 7 7-7 7" fill="none" stroke="#e5e9ed" stroke-width="2.5"/>'
body += divider(520)
body += text(28, 563, 'Turn modes off', 24)
body += text(28, 610, 'Turn climate and modes off', 24)
body += text(28, 667, 'Illustrative data · Temperature sets both front zones', 17, '#a0a6ad')
(OUT / 'clima.svg').write_text(svg(600, 702, body))
body = '<rect width="1080" height="900" rx="20" fill="#111c29"/>'
body += '<rect x="16" y="16" width="430" height="868" rx="16" fill="#202932"/>'
body += '<rect x="464" y="16" width="600" height="868" rx="16" fill="#202932"/>'
body += text(40, 62, 'Sentry', 26, weight=600)
body += text(40, 112, 'Sentry: on', 22, '#a0a6ad')
body += text(40, 174, '✓ Turn Sentry on', 24)
body += text(40, 225, 'Turn Sentry off', 24)
body += text(488, 62, 'Location', 26, weight=600)
map_png = base64.b64encode((OUT / 'location-map-example.png').read_bytes()).decode()
body += f'<image x="488" y="86" width="552" height="368" href="data:image/png;base64,{map_png}"/>'
for y, label in [(495, 'Address'), (533, 'Times Square'), (568, 'New York, NY'),
                 (610, 'Location reading from 12 Jul 09:41')]:
    body += text(488, y, label, 22, '#a0a6ad')
body += text(488, 671, 'Open in Apple Maps', 24)
body += text(488, 722, 'Hide map preview', 24)
body += text(488, 773, 'Connect Tesla account…', 24)
body += text(488, 824, 'Disable Location', 24)
body += text(40, 797, 'Public landmark example', 18, '#a0a6ad')
body += text(40, 833, 'No personal location data', 18, '#a0a6ad')
(OUT / 'sentry-location.svg').write_text(svg(1080, 900, body))
print('Created five SVG previews using fictional data only.')
