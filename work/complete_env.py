from pathlib import Path
import sys
sys.path.insert(0, str(Path.cwd()))
from pydantic_core import PydanticUndefined
from backend.app.config import Settings

fields = Settings.model_fields
for filename in ('.env', '.env.example'):
    path = Path(filename)
    original = path.read_text(encoding='utf-8')
    present = {line.split('=', 1)[0].strip() for line in original.splitlines()
               if '=' in line and not line.lstrip().startswith('#')}
    missing = [field for field in fields if field.upper() not in present]
    additions = []
    if filename == '.env.example':
        values = {'app_name': 'Zecto', 'metrics_bearer_token': ''}
    else:
        values = {'app_name': 'Zecto'}
    for field_name in missing:
        field = fields[field_name]
        if field_name in values:
            value = values[field_name]
        elif field.default is PydanticUndefined or field.default is None:
            value = ''
        elif isinstance(field.default, bool):
            value = str(field.default).lower()
        else:
            value = str(field.default)
        additions.append(f'{field_name.upper()}={value}')
    if additions:
        updated = original.rstrip() + '\n\n# Zecto settings not previously present in this local configuration\n' + '\n'.join(additions) + '\n'
        path.write_text(updated, encoding='utf-8')
        print(f'{filename}: added {len(additions)} missing application settings')
    else:
        print(f'{filename}: all application settings already present')
