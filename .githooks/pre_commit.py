import subprocess,sys
files=subprocess.check_output(['git','diff','--cached','--name-only'],text=True).splitlines()
files=[f.strip().replace('\\\\','/') for f in files if f.strip()]
if not files: sys.exit(0)
code_changed=any(f=='main.py' or f=='requirements.txt' or f.startswith(('bot/','comfy/','utils/','workflows/','config/','storage/')) for f in files)
if code_changed and 'docs/CHANGELOG_INTERNAL.md' not in files:
    sys.stderr.write('BLOCK: обнови docs/CHANGELOG_INTERNAL.md (менял код)\\n'); sys.exit(1)
non_docs=[f for f in files if not f.startswith('docs/')]; root_ok={'README.md','LICENSE','.gitignore','.gitattributes'}
if non_docs and all(f in root_ok for f in non_docs):
    sys.stderr.write('BLOCK: коммит только README/LICENSE/мета-файлы запрещён\\n'); sys.exit(1)
sys.exit(0)

