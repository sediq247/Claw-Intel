from pathlib import Path
roots = [Path('backend'), Path('frontend'), Path('docs'), Path('tests'), Path('Readme.MD'), Path('.env.example'), Path('Dockerfile'), Path('docker-compose.yml')]
extensions = {'.py','.tsx','.ts','.css','.html','.md','.json','.yml','.yaml','.txt','.example','.ini'}
files = []
for root in roots:
    if root.is_file(): files.append(root)
    elif root.exists(): files.extend(p for p in root.rglob('*') if p.is_file() and p.suffix.lower() in extensions and not any(x in p.parts for x in ('.git','.venv','node_modules','dist','__pycache__')))
changed = 0
for path in set(files):
    try:
        raw = path.read_bytes()
        try: old, encoding = raw.decode('utf-8'), 'utf-8'
        except UnicodeDecodeError: old, encoding = raw.decode('cp1252'), 'cp1252'
    except OSError: continue
    new = old.replace('ClawIntel','Zecto').replace('Clawintel','Zecto').replace('CLAWINTEL','ZECTO')
    new = new.replace('clawintel:open-wallet','zecto:open-wallet').replace('clawintel_http_','zecto_http_')
    new = new.replace('clawintel.test','zecto.test').replace('clawintel-web','zecto-web').replace('clawintel-agent-work-','zecto-agent-work-')
    if new != old: path.write_bytes(new.encode(encoding)); changed += 1
print(f'Rebranded {changed} files')
