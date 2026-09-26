# Локальная подготовка релиза: 25 сентября 2026

База: `9f513f2` (Phase 05B). Версии сохранены: Python `0.1.0.dev0`, npm
`0.1.0-dev.0`. Ничего не опубликовано, не зарегистрировано, не закоммичено,
не отправлено в remote и не помечено тегом. Новых функций нет.

## Metadata и имена

Read-only GET к [PyPI JSON](https://pypi.org/pypi/agentrgb/json) и
[npm registry](https://registry.npmjs.org/agentrgb-pi) вернул HTTP 404 для обоих
имён. Опубликованные пакеты не найдены; это не резервирует имена и не гарантирует,
что реестр разрешит регистрацию. Повторить перед публикацией.

- Python: `agentrgb`, README Markdown, Python `>=3.14`, console script
  `agentrgb = agentrgb.cli:main`, runtime dependencies отсутствуют.
- Pi: `agentrgb-pi`, keywords `pi-package`/`agentrgb`, extension `./agentrgb.ts`,
  peer `@earendil-works/pi-coding-agent: *` (Pi предоставляет API), runtime
  dependencies отсутствуют. Peer `*` не обещает поддержку всех версий Pi.
- По решению владельца добавлена MIT в оба manifest и оба артефакта.
  Минимальный build backend повышен до `setuptools>=77` для SPDX license metadata;
  runtime dependency не добавлена. Копии LICENSE должны оставаться одинаковыми.
- Repository/homepage URL не выдуманы: `git remote -v` пустой. `.github` отсутствует;
  CI/CD не добавлялся.

## Артефакты

Python 3.14.4, Node 24.15.0, npm 11.12.1, установленный Pi 0.87.1.
Команды `py` в тестовом PATH нет; использованы Python 3.14.4 и его новые venv.
`build 1.6.1` и `twine 7.0.0` установлены только во временный build-tools venv,
изолированный build использовал setuptools 84.0.0.

| Файл | Результат | SHA-256 |
|---|---|---|
| `dist/agentrgb-0.1.0.dev0-py3-none-any.whl` | Собран из sdist, twine PASSED | `2a2738c381cea5aa61a84005e3297a7379f1d6ec1e17ed11c0c9815cee28b813` |
| `dist/agentrgb-0.1.0.dev0.tar.gz` | Собран, twine PASSED | `7bd69668be75a7a31dcc979e0083b0c60599b852ffddb374f527baa5d3a5a10b` |
| `integrations/pi/agentrgb-pi-0.1.0-dev.0.tgz` | npm pack, установка проверена | `d4764b915d363386443c4da27cc401c466ba6ea30b4e747eb2221e728499a0d8` |

Wheel содержит 16 файлов:

```text
agentrgb/__init__.py
agentrgb/cli.py
agentrgb/fake.py
agentrgb/protocol.py
agentrgb/server.py
agentrgb/state.py
agentrgb/outputs/__init__.py
agentrgb/outputs/aula_f75.py
agentrgb/outputs/aula_f75_diagnostics.py
agentrgb/outputs/windows_hid.py
agentrgb-0.1.0.dev0.dist-info/licenses/LICENSE
agentrgb-0.1.0.dev0.dist-info/METADATA
agentrgb-0.1.0.dev0.dist-info/WHEEL
agentrgb-0.1.0.dev0.dist-info/entry_points.txt
agentrgb-0.1.0.dev0.dist-info/top_level.txt
agentrgb-0.1.0.dev0.dist-info/RECORD
```

Sdist содержит 21 файл: те же 10 production-модулей, README, LICENSE,
`pyproject.toml`, `MANIFEST.in`, сгенерированные `setup.cfg`, `PKG-INFO` и egg-info.
Production-код совпадает с исходниками. `MANIFEST.in` исключает tests/experiments;
package discovery ограничен `agentrgb`, package data отключены.

Точный список `npm pack --dry-run` и tarball:

```text
LICENSE
README.md
agentrgb.ts
core.ts
package.json
```

Во всех архивах проверены имена и содержимое файлов. Не обнаружены tests,
experiments/results, runtime logs, `.env`, settings, node_modules, кэши, `.diff`,
временные файлы, содержимое диалогов, HID instance paths, абсолютные пути
пользователя или распространённые форматы секретов. LICENSE побайтово одинаков
во всех артефактах. `dist/`, build/egg-info и Pi `.tgz` игнорируются Git.

## Чистая установка

Wheel установлен через `pip install --no-index --no-deps <wheel>` в новый venv
вне checkout, без editable install. Проверены metadata `direct_url.json` и импорт
из `Lib/site-packages/agentrgb`. Во время запусков `PYTHONPATH` отсутствовал,
cwd находился во временном каталоге вне репозитория.

`agentrgb --help` — exit 0. Начальный `status` — running, exit 0: на `8765` уже
работал внешний Core. `doctor` — exit 0, production imports и F75 identity ready;
выполнен только разрешённый identity read, без RGB-кадров.

Tarball установлен через `npm install --prefix <temp-install> --legacy-peer-deps
--ignore-scripts --no-audit --no-fund <tgz>`. Затем `pi install <temp-install>/node_modules/agentrgb-pi`
зарегистрировал установленную копию в отдельном `PI_CODING_AGENT_DIR`.
`pi list` показал её; source checkout в Pi settings не использовался.
Пользовательские Pi settings и credentials не менялись.

Default `agentrgb start` отдельно проверен на `18766`: fake Core поднялся,
`/health` вернул HTTP 200, `status` — running/exit 0. Настоящий Windows
`CTRL_C_EVENT` завершил неизменённый CLI с exit 0, exclusive bind подтвердил
освобождение порта. Тестовый console bootstrap сбросил унаследованное от runner
игнорирование Ctrl+C до запуска CLI; первые попытки без этого требовали cleanup
собственных fake-процессов. Это особенность тестового окружения,
[описанная Microsoft](https://learn.microsoft.com/en-us/windows/console/setconsolectrlhandler).
Процессы успешного Ctrl+C прогона завершились сами; все временные серверы очищены.

## Pi → Core

По решению пользователя занятой порт `8765` оставлен нетронутым; owned-Core smoke
выполнен на `18767`. Это ограничение проверки стандартного порта.

Pi запущен в обычном интерактивном режиме, без `-e` и без RPC, вне checkout.
Параметры отключали сохранение сеанса, tools, skills, themes, prompt templates
и context files. TUI показал загрузку `agentrgb.ts` из установленного package.
Для одного безопасного запуска использован локальный тестовый HTTP/SSE provider
с фиксированным ответом; внешний LLM provider этим прогоном не проверен.
Тестовый API отбрасывал body без записи, credentials не использовались.

Так как production autostart жёстко задаёт `--output aula-f75`, временный launcher
в PATH проверял исходные аргументы, заменял output на `fake` и запускал CLI из
clean wheel venv. Импорты HID были заблокированы. Нормализация событий, Core,
handshake владения и shutdown выполнялись установленным кодом без изменения
исходников или содержимого артефактов. Launcher и журнал только с lifecycle
metadata находились вне checkout; пути и содержимое диалогов в Core не попадали.

Подтверждено:

1. До запуска Pi на `18767` не было Core; extension автоматически создал один child.
2. `/health` вернул `status=ok, service=agentrgb`; installed CLI `status` показал running.
3. Получены ровно `run_started` и `run_ended`, оба `applied`; исход окончания — `completed`.
4. `/quit` завершил Pi с exit 0; Core выполнил `close` и штатно вышел без forced termination.
5. Повторный bind к `18767` успешен.

Отдельный прогон с заранее запущенным fake Core на `18765` использовал обычный
installed CLI без подмены. Pi передал lifecycle, завершился через `/quit`,
а прежний PID Core сохранился и `/health` продолжил отвечать.

Это подтверждает цепочку артефактов и lifecycle с безопасной тестовой подменой
output. Не проверены неизменённый аппаратный autostart этой сборки и внешний
модельный provider. Новых RGB-команд не отправляли; существующий
[04C hardware evidence](../experiments/phase-04c/RESULTS.md) сохранён для RC.

## Перед публикацией

README перестроен вокруг пользовательского сценария; публичная установка
помечена planned, требования и ограничения перечислены явно.
[RELEASING.md](RELEASING.md) содержит TestPyPI plan с `0.1.0rc1`, version inventory
и ручной npm/PyPI flow. [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) отделяет
выполненные локальные gates от будущих действий. Final bump, публикация, короткий
F75 smoke, tag и GitHub release остаются отдельным этапом.

## Финальные проверки и пользовательские файлы

- Полный Python suite: 167 тестов, OK, exit 0 (13,130 с).
- Полный Node suite: 35/35, без failures/skips, exit 0 (2,909 с).
- Оба suite использовали clean wheel Python, без `PYTHONPATH`; hardware не запускался.
- Python сообщил неблокирующий `ResourceWarning` при cleanup `HTTPError 400`.
- `git diff --check` — без ошибок.

SHA-256 пользовательских файлов до и после совпал:

| Файл | SHA-256 |
|---|---|
| `experiments/README.md` | `80d71c148a344d287c4a461c6a522c0d85d4d610f2f18bcb42594d11aafafffb` |
| `experiments/manual_scenarios.py` | `ff468faf3545e5294ab27951121d6aa2e12551f706139cd1a4b78121a20b5bd4` |

Оба файла остались в исходном пользовательском состоянии: modified/untracked.
Release staging пустой. Артефакты и временные журналы в него не включены.
