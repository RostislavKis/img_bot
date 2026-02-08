# CHANGELOG_INTERNAL (img_bot)

Журнал ВСЕХ внутренних изменений проекта. Все записи на русском.

**Правило:** каждый коммит с изменением кода ОБЯЗАН содержать запись здесь.

---

## 2026-02-08 — T-002: Copilot-safe git защита репозитория

**Цель:** гарантировать что в GitHub никогда не попадёт "пустой" репозиторий только с README/LICENSE.

**Тикет:** T-002

**Добавлено:**

- `.githooks/pre-commit` — Python pre-commit hook
  - Блокирует коммиты с ТОЛЬКО README/LICENSE/мета-файлами
  - Запрещает .md файлы вне папки `docs/`
  - Требует обновления `docs/CHANGELOG_INTERNAL.md` при изменении кода
  - Работает на Windows/macOS/Linux

- `.github/workflows/repo-sanity.yml` — GitHub Actions для CI
  - Проверяет наличие всех директорий: `bot/`, `comfy/`, `utils/`, `workflows/`, `docs/`, `config/`
  - Проверяет наличие `docs/CHANGELOG_INTERNAL.md`
  - Проверяет что репо не "пустой" (есть код в `bot/` или `main.py`)
  - Запускается при push/PR на master/main

- `.gitignore` — обновлен
  - Добавлен игнор `.vs/` (Visual Studio)
  - Добавлены типовые Python-файлы: `__pycache__/`, `*.pyc`, `*.egg-info/`

- `docs/CHANGELOG_INTERNAL.md` — этот файл
  - Журнал всех внутренних изменений

**Как использовать:**

1. Перед коммитом убедись что в staging есть ВСЕ файлы:
   ```sh
   git status
   git add -A
   ```

2. Если ты меняешь код (не только документацию):
   - Обновил файлы в `bot/`, `comfy/`, `utils/`, `workflows/`, `config/`, или `main.py`?
   - ➜ ОБЯЗАТЕЛЬНО добавь запись в этот файл (`docs/CHANGELOG_INTERNAL.md`)

3. Pre-commit hook сам проверит всё. Если что-то не так — коммит заблокируется с русским сообщением об ошибке.

**Причина:**

На GitHub раньше была ситуация когда залезло только README+LICENSE и репо остался "пустым". Теперь это физически невозможно:
- Локально: hook запретит такой коммит
- На GitHub: Actions проверит структуру и fail-нет если чего-то нет
