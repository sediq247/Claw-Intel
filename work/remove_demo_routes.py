from pathlib import Path
p=Path('backend/app/main.py')
raw=p.read_bytes()
try: s=raw.decode('utf-8'); enc='utf-8'
except UnicodeDecodeError: s=raw.decode('cp1252'); enc='cp1252'
start=s.index('class QuoteInput(BaseModel):')
end=s.index('class A2AResearchInput(BaseModel):', start)
s=s[:start]+s[end:]
start=s.index('# Controlled, clearly simulated fixtures.')
end=s.index('@app.websocket("/ws/{department}")', start)
s=s[:start]+s[end:]
s=s.replace('    if method == "POST" and len(parts) == 4 and parts[:2] == ["api", "scenarios"] and parts[3] == "run":\n        return 5, "/api/scenarios/{scenario_id}/run"\n','')
s=s.replace('        "title": row.title, "status": row.status, "scenario_id": row.scenario_id,\n','        "title": row.title, "status": row.status,\n')
s=s.replace('DemoQuote, DemoWallet, ', '').replace(', Position,', ',').replace(', Trade,', ',')
p.write_bytes(s.encode(enc))
