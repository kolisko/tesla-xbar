"""Pure settings form markup."""
import html
from ..domain.settings import SETTINGS, CONNECTION_FIELDS

def settings_fields_html(config):
    fields = []
    for name in CONNECTION_FIELDS + ("display_mode",):
        field = SETTINGS[name]
        value = str(config.get(name, field.default))
        fields.append(f'<label for="{name}">{field.label}</label>')
        if field.choices:
            options = "".join(f'<option value="{key}"' + (' selected' if key == value else '')
                              + f'>{label}</option>' for key, label in field.choices)
            fields.append(f'<select id="{name}" name="{name}">{options}</select>')
        else:
            fields.append(f'<input id="{name}" name="{name}" required maxlength="{field.max_length}" '
                          + f'value="{html.escape(value, quote=True)}">')
    fields.append('<label for="client_secret">Client Secret (leave blank to keep saved)</label>'
                  '<input id="client_secret" name="client_secret" type="password" maxlength="2048">')
    return "".join(fields)
