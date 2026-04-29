#!/usr/bin/env python3
"""PostToolUse hook: scan written files for secrets. Alerts + gitignores on match."""
import sys, json, re
from pathlib import Path

SKIP_EXTENSIONS = {'.pickle', '.pkl', '.pyc', '.png', '.jpg', '.jpeg', '.gif',
                   '.ico', '.woff', '.ttf', '.bin', '.gz', '.zip'}
SKIP_DIRS = {'__pycache__', '.git', 'node_modules'}
THIS_FILE = Path(__file__).resolve()

SECRET_PATTERNS = [
    (r'AIza[0-9A-Za-z\-_]{35}',                                               'Google API key'),
    (r'AKIA[0-9A-Z]{16}',                                                      'AWS access key'),
    (r'sk-[a-zA-Z0-9\-_]{32,}',                                               'API secret key (sk- prefix)'),
    (r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY',                          'private key'),
    (r'(?i)(?:api_key|apikey|auth_token|access_token|password|passwd|secret)'
     r'\s*=\s*["\']?[A-Za-z0-9+/\-_]{20,}["\']?',                            'secret assignment'),
]

PLACEHOLDER_RE = re.compile(r'(?i)(your[_\-]|<[^>]+>|example|placeholder|dummy|changeme|\.\.\.|\*{4,}|YOUR_)')

d = json.load(sys.stdin)
fp = d.get('tool_input', {}).get('file_path', '')
if not fp:
    sys.exit(0)

p = Path(fp).resolve()
if p == THIS_FILE or p.suffix in SKIP_EXTENSIONS:
    sys.exit(0)
if any(part in SKIP_DIRS for part in p.parts):
    sys.exit(0)

try:
    content = p.read_text(errors='replace')
except Exception:
    sys.exit(0)

found = []
for pattern, label in SECRET_PATTERNS:
    for m in re.finditer(pattern, content):
        if not PLACEHOLDER_RE.search(m.group(0)):
            line_num = content[:m.start()].count('\n') + 1
            found.append(f"  line {line_num}: {label}")

if not found:
    sys.exit(0)

# Add to .gitignore
gi_note = ''
try:
    cwd = Path.cwd()
    try:
        rel_str = str(p.relative_to(cwd))
    except ValueError:
        rel_str = str(p)
    gitignore = cwd / '.gitignore'
    existing = gitignore.read_text() if gitignore.exists() else ''
    if rel_str not in existing:
        with open(gitignore, 'a') as f:
            f.write(f'\n# secret-scan auto-added\n{rel_str}\n')
        gi_note = ' — added to .gitignore'
    else:
        gi_note = ' — already in .gitignore'
except Exception:
    gi_note = ' — could not update .gitignore'

msg = (
    f"SECRET SCAN ALERT: possible secrets in {fp}{gi_note}\n" +
    '\n'.join(found) +
    "\n\nDo NOT commit this file. Rotate any exposed credentials immediately if already pushed."
)
print(json.dumps({'systemMessage': msg}))
