# Подготовка Pi package 0.1.0-rc.1: 2 октября 2026

Python TestPyPI evidence зафиксирован отдельным commit
`8bd5a65 docs: record TestPyPI 0.1.0rc1 validation`.
Python сохраняет `0.1.0rc1`; production source и Python metadata не изменены.
В Pi package изменена только version `0.1.0-dev.0` → `0.1.0-rc.1`
и README/release documentation. Runtime-код и зависимости не менялись.

## Namespace и границы публикации

Read-only GET `https://registry.npmjs.org/agentrgb-pi` вернул HTTP 404.
Имя отсутствовало на момент проверки; это не резервирует namespace.
Перед publish повторить lookup. Если пакет уже существует и принадлежность
владельцу не подтверждена, остановиться и не переименовывать автоматически.

Публикация **пока не выполнялась**. Требуется отдельное разрешение пользователя
для точного проверенного tarball с dist-tag `next`. `latest` не устанавливать.
Владелец выполняет интерактивный npm login/publish с 2FA. Credentials не сохранять
в repo или документации. Актуальные требования:
[официальная npm документация](https://docs.npmjs.com/requiring-2fa-for-package-publishing-and-settings-modification/).

## Проверки и tarball

- Python 3.14.4: полный suite, 167/167, OK.
- Node 24.15.0: полный suite, 35/35, failures/skips отсутствуют.
- `git diff --check`: без ошибок.
- npm 11.12.1: `npm pack --dry-run` и `npm pack` пройдены.
- Обычный npm cache недоступен sandbox; использован временный process-scoped cache.
- Артефакт: `integrations/pi/agentrgb-pi-0.1.0-rc.1.tgz`, ignored Git.
- Для ручной публикации владельцу добавлено только право чтения этого tarball;
  содержимое и hashes не изменены.

SHA-256:

```text
9bd2b2fb168fffae1d47e55d1688d9515dd15063ed802b539f4c15f83d2d5423
```

npm integrity (SHA-512):

```text
sha512-ZYRe7xDai6S5TV6/yAbiJpSyvCvhHt6gWtN1wZx/vtIyZW5XONExZduG0mlz5paUiaEZAjnddeVtX3BtrquS7w==
```

Точный состав:

```text
package/LICENSE
package/README.md
package/agentrgb.ts
package/core.ts
package/package.json
```

Все пять файлов побайтово совпадают с исходниками; LICENSE совпадает с корневой
MIT LICENSE. Manifest содержит version `0.1.0-rc.1` и extension `./agentrgb.ts`.
Имена и содержимое проверены: experiments, runtime logs, абсолютные пользовательские
пути и распространённые форматы секретов не обнаружены.

## Local tarball smoke

Созданы новые временные npm install, Pi configuration и cwd вне checkout.
Именно собранный tarball установлен командой `npm install --prefix <temp-install>
--legacy-peer-deps --ignore-scripts --no-audit --no-fund <exact-tgz>`.
Peer API предоставляет существующий Pi; его повторная установка не нужна.
`package-lock.json` подтвердил version `0.1.0-rc.1` и integrity проверенного tarball.

Через `pi install <temp-install>/node_modules/agentrgb-pi` пакет зарегистрирован
в отдельном `PI_CODING_AGENT_DIR`; `pi list` подтвердил установленный package.
Все пять installed files совпали с содержимым артефакта. Source checkout как
extension source не использовался; пользовательская Pi configuration не менялась.
Proxy и npm cache заданы только в тестовых process environments; локальные адреса
proxy и пользовательские настройки не включены в repo.

Python сторона использовала ранее проверенный clean TestPyPI venv:
installed `agentrgb 0.1.0rc1`, импорт из `Lib/site-packages`, `direct_url.json`
отсутствует, `PYTHONPATH` удалён из test process environment.

Запущен обычный интерактивный Pi 0.87.1, без `-e`, RPC и print mode.
Отключены sessions, tools, skills, themes, prompt templates и context files.
Offline mode запрещал startup downloads; warning об отсутствующем `fd`
не помешал сценарию без tools. TUI показал autoload `agentrgb.ts`.

Production autostart явно выбирает `aula-f75`. Для owned-Core smoke временный
launcher в PATH проверил исходные аргументы и заменил только output на `fake`.
`WindowsHid` и `AulaF75Output` заблокированы. Установленный production CLI/Core
использовал тестовую subclass для записи только lifecycle metadata; содержимое
модельных запросов/ответов не попадало в Core или evidence.
Артефакт, installed package files и checkout runtime-код не изменялись.
Это подтверждает package installation и lifecycle с тестовой подменой output,
а не обычный аппаратный autostart.

Локальный детерминированный HTTP/SSE provider вернул фиксированный тестовый ответ;
request body отбрасывался без записи. Внешний модельный provider не проверялся.

Подтверждено:

1. Autoload запустил ровно один собственный fake Core на свободном порту `57685`.
2. `/health` — HTTP 200, `status=ok`, `service=agentrgb`; installed CLI `status` — running/exit 0.
3. Получены ровно `run_started` и `run_ended`, оба `applied`; исход — `completed`.
4. `/quit` завершил Pi с exit 0; Core записал `core_closed` и штатный `exited`.
5. Core PID исчез; exclusive bind подтвердил освобождение порта.
6. Hardware writes не выполнялись; forced Core termination не понадобился.

Тестовый provider после smoke остановлен. Python version и npm runtime dependencies
сохранены. Пользовательские `experiments/README.md` и `experiments/manual_scenarios.py`
не менялись и не staging; их SHA-256 совпадают с предыдущим evidence.

## После разрешения на публикацию

Из каталога проверенного tarball выполнить только:

```powershell
npm publish ./agentrgb-pi-0.1.0-rc.1.tgz --tag next --access public --registry=https://registry.npmjs.org/
```

Повторить read-only namespace lookup непосредственно перед upload.
После upload проверить npm version, `dist-tags.next`, integrity и отсутствие
непреднамеренного `latest`. В совершенно новой Pi test configuration выполнить
`pi install npm:agentrgb-pi@next`; подтвердить реально установленную `0.1.0-rc.1`
из registry, без local tarball и source checkout. Повторить ordinary Pi autoload,
TestPyPI Python RC, owned fake Core, lifecycle, `/quit` и освобождение порта.

Registry install и registry integration smoke пока **не выполнены**.
После успешного smoke остановиться. Python production upload, npm `0.1.0`,
`latest`, push, git tag, GitHub Release и другие интеграции не выполнять.
Опубликованную RC version не перезаписывать; исправления требуют `0.1.0-rc.2`.
