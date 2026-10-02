# Ручная подготовка и публикация 0.1.0

Python `0.1.0rc1` опубликован только в TestPyPI; установка из реестра и fake Core
smoke проверены: [результаты RC](RELEASE_RC1.md). Pi RC `0.1.0-rc.1` опубликован в npm с `next`, registry smoke пройден:
[Pi RC evidence](RELEASE_PI_RC1.md). `latest` также указывает на RC; удаление
отклонено с E400. Production PyPI и финальный npm `0.1.0` не опубликованы. [Чеклист](RELEASE_CHECKLIST.md) сохраняет результаты локальной подготовки.
Текущие версии: `0.1.0rc1` (Python) и `0.1.0-rc.1` (Pi). Финальная `0.1.0`
предназначена для настоящего релиза. Лицензия — MIT. Команды upload, login, publish,
tag и GitHub release ниже относятся к будущему этапу с отдельным решением пользователя.

## Локальные артефакты

В корне репозитория, с Python 3.14+:

```powershell
py -3.14 -m pip install build twine
py -3.14 -m build
py -3.14 -m twine check dist/*
```

`build` и `twine` — локальные dev tools, а не runtime dependencies AgentRGB.
Проверить состав wheel/sdist, установить именно wheel в новый временный venv и
запускать CLI вне checkout, без `PYTHONPATH`. Не использовать `pip install -e .`.
Из `integrations/pi` выполнить `npm pack --dry-run`, проверить список и затем
`npm pack`. Проверять Pi из полученного `.tgz`, с Python CLI из чистого venv в PATH.
`dist/` и `.tgz` не включать в Git.

В чистом окружении проверить `agentrgb --help`, `agentrgb status`, `agentrgb doctor`,
затем default `agentrgb start` (`fake`), `/health`, Ctrl+C и освобождение порта.
До запуска Core `status` должен сообщать `not running` с кодом 1; это ожидаемо.
`doctor` не меняет RGB, но отсутствие подходящего F75 может дать код 1.

Pi autostart в текущей версии использует `--output aula-f75`. При отсутствии
разрешения на аппаратный вывод owned-Core smoke требует тестовой подмены команды
на `fake`; факт подмены необходимо указать в отчёте. Он проверяет установку и
lifecycle, но не является полным обычным запуском неизменённого продукта.
Наличие внешнего fake Core позволяет отдельно проверить autoload и правило
«Pi не завершает чужой Core» без подмены.

## TestPyPI: необязательный публикационный тест

Тест не выполняется автоматически. Использовать только `0.1.0rc1`; при повторной
публикации уже занятой версии — следующий согласованный RC. TestPyPI — отдельный
реестр и отдельная учётная запись. Порядок upload/install сверён с
[руководством PyPA](https://packaging.python.org/en/latest/guides/using-testpypi/).

RC готовится в рабочем checkout: единственный источник Python version —
`pyproject.toml`. Python bump не менял Pi; его отдельный RC описан ниже. Проверки RC и SHA-256
фиксируются в [RELEASE_RC1.md](RELEASE_RC1.md).

После полного Python/Node suite и `git diff --check` очистить только проверенный
ignored `dist/`, собрать новые wheel/sdist и проверить их:

```powershell
py -3.14 -m build
py -3.14 -m twine check dist/*
$rcWheel = Join-Path (Get-Location) 'dist/agentrgb-0.1.0rc1-py3-none-any.whl'
$rcSdist = Join-Path (Get-Location) 'dist/agentrgb-0.1.0rc1.tar.gz'
```

Проверить metadata, entry point, LICENSE, README и состав обоих архивов.
Установить wheel в новый временный venv вне checkout, повторить CLI и default fake
Core smoke с Ctrl+C и освобождением порта. После проверок допустим отдельный
commit `chore: prepare 0.1.0rc1`, без push/tag.

Только после явного разрешения пользователя выполнить ручную публикацию:

```powershell
py -3.14 -m twine upload --repository testpypi $rcWheel $rcSdist
```

Credentials вводит владелец вручную через штатный prompt Twine. Не передавать
токен в командной строке, коде, журнале или переписке; не сохранять credentials
в репозитории. Не создавать для этого `.pypirc` или `.env`.

После публикации RC создать ещё один venv вне checkout и установить точную версию:

```powershell
$rcVenv = Join-Path $env:TEMP ("agentrgb-testpypi-" + [guid]::NewGuid().ToString())
py -3.14 -m venv $rcVenv
& "$rcVenv\Scripts\python.exe" -m pip install --no-deps --only-binary=:all: --index-url https://test.pypi.org/simple/ agentrgb==0.1.0rc1
```

Runtime dependencies отсутствуют, поэтому дополнительный индекс не нужен.
Повторить CLI smoke из каталога вне checkout. Этот тест не публикует финальную
версию и не заменяет будущую установку из настоящего PyPI.

## npm RC: `0.1.0-rc.1`, dist-tag `next`

Python сохраняет `0.1.0rc1`. Результаты Pi RC подготовки фиксируются в
[RELEASE_PI_RC1.md](RELEASE_PI_RC1.md). Read-only проверить `agentrgb-pi`
в публичном npm registry непосредственно перед upload; если имя занято чужим
пакетом, остановиться. Отсутствие имени не гарантирует доступность регистрации.

После полного Python/Node suite и `git diff --check` из `integrations/pi`
выполнить `npm pack --dry-run`, затем `npm pack`. Ожидаются только LICENSE,
README.md, agentrgb.ts, core.ts, package.json. Проверить version и SHA-256 `.tgz`.
Установить именно tarball во временную конфигурацию Pi вне checkout, проверить
обычный Pi autoload, Core ownership, lifecycle и `/quit` с fake test launcher,
блокирующим HID. Это безопасная подмена output, а не hardware smoke.

После проверки подготовить commit `chore: prepare Pi package 0.1.0-rc.1`,
без tarball, пользовательских experiments, push и tag. Публикация требует
отдельного разрешения. Владелец использует интерактивный npm login/publish с 2FA;
credentials не сохранять в repo или документации. Требования сверять с
[официальной npm документацией](https://docs.npmjs.com/requiring-2fa-for-package-publishing-and-settings-modification/).
Только после разрешения, из каталога проверенного tarball:

```powershell
npm publish ./agentrgb-pi-0.1.0-rc.1.tgz --tag next --access public --registry=https://registry.npmjs.org/
```

Не выполнять publish без `--tag next`. После upload проверить npm metadata,
version, dist-tag и integrity. В совершенно новой Pi test environment выполнить:

```powershell
pi install npm:agentrgb-pi@next
pi list
pi
```

Подтвердить установленную `0.1.0-rc.1`, extension source из registry installation,
Python `0.1.0rc1` из TestPyPI environment, ordinary Pi autoload, owned fake Core,
lifecycle и `/quit` с освобождением порта. Сохранить факт test launcher и отсутствие
HID writes. Source checkout и local tarball для registry smoke не использовать.
После успешного smoke остановиться; production PyPI, npm `0.1.0`, tag `latest`,
git tag и GitHub Release не выполнять. Версию не перезаписывать; исправления
требуют следующего согласованного RC `0.1.0-rc.2`.

## Финальные версии

После clean artifact tests и отдельного решения о релизе:

| Место | Перед финальной сборкой |
|---|---|
| `pyproject.toml`, `project.version` | `0.1.0rc1` → `0.1.0` |
| `integrations/pi/package.json`, `version` | `0.1.0-rc.1` → `0.1.0` |
| README и инструкции с текущей версией | Обновить на `0.1.0` и убрать пометку planned только после публикации |
| `tests/test_cli.py` | Проверить mock версии; это тестовая строка, а не источник версии пакета |
| `tests/pi-core.test.mjs`, manifest test | Сейчас требует дефис в версии (`/-/`); при final bump заменить проверкой, допускающей release SemVer, и обновить название теста |

Production CLI получает версию из metadata установленного distribution; отдельной
production-константы версии нет. Перед bump повторить поиск:

```powershell
git grep -n -e '0.1.0.dev0' -e '0.1.0-dev.0'
```

Исторические результаты опытов не переписывать. Пересобрать финальные артефакты в
новый пустой каталог, проверить версии внутри архивов и повторить весь checklist.
Подменять финальными файлами проверенные dev/RC-артефакты нельзя.

## Ручная публикация PyPI и npm

Перед публикацией повторить read-only lookup имён. Если имя занято другим
пакетом, остановиться; переименование согласовать отдельно. Публичный URL проекта
для metadata добавлять только после выбора и проверки реального репозитория.

Для PyPI после отдельного решения загрузить только проверенные финальные wheel и
sdist по явным путям через `twine upload --repository-url https://upload.pypi.org/legacy/`.
Не использовать общий `dist/*`, где могут оказаться dev или RC файлы.

Для npm оператор вручную входит через браузер, проверяет учётную запись и
публикует точный проверенный tarball. Команды сверены с
[npm login](https://docs.npmjs.com/cli/v11/commands/npm-login/),
[npm publish](https://docs.npmjs.com/cli/v11/commands/npm-publish/) и
[требованиями 2FA](https://docs.npmjs.com/requiring-2fa-for-package-publishing-and-settings-modification/).

```powershell
npm login --auth-type=web --registry=https://registry.npmjs.org/
npm whoami --registry=https://registry.npmjs.org/
npm publish ./agentrgb-pi-0.1.0.tgz --dry-run --registry=https://registry.npmjs.org/
# После проверки и отдельного решения о публикации:
npm publish ./agentrgb-pi-0.1.0.tgz --access public --registry=https://registry.npmjs.org/
```

Пройти штатную 2FA-проверку. Вход и настройки аккаунта автоматически не менять;
токены не запрашивать и в проекте не хранить. `npm login` управляет локальной
сессией npm вне репозитория; выполнять его должен владелец аккаунта.

После обеих публикаций проверить чистую установку из реестров и обычный запуск Pi.
Короткий final smoke F75 выполняется отдельно, только с разрешения; для подготовки
RC достаточно существующего [04C evidence](../experiments/phase-04c/RESULTS.md).
Git tag и GitHub release — последние ручные действия после проверки результата
и отдельного решения пользователя. Первый релиз не требует нового CI/CD;
Trusted Publishing можно рассмотреть после `0.1.0`.
