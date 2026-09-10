"""Create documentation mockups with fictional data, without reading a Tesla profile."""
from pathlib import Path
from html import escape

OUT = Path(__file__).resolve().parents[1] / "docs/images"
OUT.mkdir(parents=True, exist_ok=True)
FONT = "Helvetica,Arial,sans-serif"


def text(x, y, value, size=24, fill="#e5e9ed", weight=400):
    return f'<text x="{x}" y="{y}" fill="{fill}" font-family="{FONT}" font-size="{size}" font-weight="{weight}">{escape(value)}</text>'


def bolt(x, y, scale=1):
    return f'<path transform="translate({x},{y}) scale({scale})" d="M18 0 1 23h12L7 40 30 15H17L24 0Z" fill="#ffd24a"/>'



def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img">'
            '<title>Tesla xBar interface preview with fictional data</title>'
            '<defs><linearGradient id="blue" x2="1" y2="1"><stop stop-color="#126e98"/><stop offset="1" stop-color="#173a58"/></linearGradient>'
            '<linearGradient id="panel" x2="0" y2="1"><stop stop-color="#103d53"/><stop offset="0.55" stop-color="#24343f"/><stop offset="1" stop-color="#303337"/></linearGradient></defs>' + body + '</svg>')


bar = '<rect width="320" height="66" rx="14" fill="url(#blue)"/>'
bar += '<rect x="8" y="8" width="237" height="50" rx="22" fill="#ffffff" fill-opacity="0.06"/>'
bar += text(24, 44, '360 km', 30, '#32cd66') + bolt(163, 14, 0.9)
(OUT / 'menu-bar.svg').write_text(svg(320, 66, bar))

body = '<rect width="600" height="1030" rx="22" fill="url(#blue)"/>'
body += '<rect x="4" y="4" width="592" height="1022" rx="18" fill="url(#panel)" stroke="#8fa3af" stroke-opacity="0.5"/>'
body += text(27, 47, 'Tesla', 27, '#dce4eb', 600)
rows = ['Battery: 73 %', 'Tesla range: 360 km', 'Charge limit: 80 %', 'Cable: connected',
        'Charging', 'Power: 11 kW', 'Time to charge limit: 0 h 30 min', 'Battery reading from 12 Jul 09:41']
for i, row in enumerate(rows):
    body += text(27, 96 + i * 45, row, 24, '#aebdc8')

def divider(y):
    return f'<path d="M27 {y}H573" stroke="#95a7b1" stroke-opacity="0.3"/>'

body += divider(440)
for y, label, sub in [(486, 'Charging and port', True), (553, 'Refresh now', False),
                      (600, 'Wake vehicle and refresh', False), (647, 'Connect Tesla account…', False),
                      (694, 'Settings…', False), (741, 'Menu bar display', True)]:
    body += text(27, y, label, 25)
    if sub:
        body += f'<path d="m562 {y-17} 7 7-7 7" fill="none" stroke="#e5e9ed" stroke-width="2.5"/>'
body += divider(511) + divider(774)
body += text(27, 817, 'Refresh interval managed by xBar', 23, '#aebdc8')
body += text(27, 864, 'Tesla Developer', 25)
body += text(27, 911, 'Manage Tesla permissions', 25)
body += divider(944) + text(27, 989, 'xbar', 25)
body += '<path d="m562 972 7 7-7 7" fill="none" stroke="#e5e9ed" stroke-width="2.5"/>'
(OUT / 'menu.svg').write_text(svg(600, 1030, body))

body = '<rect width="1326" height="380" rx="20" fill="#111c29"/>'
examples = [('Charging', '360 km', '#32cd66', 'bolt'), ('Connected · paused', '360 km', '#32cd66', ''),
            ('Unplugged · below 350 km', '320 km', '#f5a623', ''), ('Unplugged · below 300 km', '280 km', '#ef4444', ''),
            ('Asleep · last connected', '360 km', '#32cd66', ''), ('Offline · last connected', '360 km', '#32cd66', ''),
            ('Asleep · last unplugged', '360 km', '#a0a6ad', ''), ('Offline · last unplugged', '360 km', '#a0a6ad', '')]
for i, (label, value, color, icon) in enumerate(examples):
    x, y = 20+(i%4)*326, 20+(i//4)*178
    body += f'<rect x="{x}" y="{y}" width="308" height="158" rx="14" fill="#1b2c3e"/>'
    body += text(x+20, y+40, label, 18, '#b4c6d7')
    body += text(x+20, y+109, value, 34, color)
    if icon=='bolt':body+=bolt(x+164,y+76,0.9)
(OUT / 'states.svg').write_text(svg(1326, 380, body))
print('Created three SVG previews using fictional data only.')
