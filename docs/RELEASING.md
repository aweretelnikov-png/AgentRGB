# Ручная подготовка и публикация 0.1.0

Сейчас выполняется только локальная подготовка по [чеклисту](RELEASE_CHECKLIST.md).
Версии остаются `0.1.0.dev0` (Python) и `0.1.0-dev.0` (Pi). Финальная `0.1.0`
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

Сделать отдельную копию production source из проверенного dev sdist; рабочий
checkout не менять. Из корня репозитория:

```powershell
$rcRoot = Join-Path $env:TEMP ("agentrgb-rc-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Path $rcRoot | Out-Null
py -3.14 -m tarfile -e .\dist\agentrgb-0.1.0.dev0.tar.gz $rcRoot
$rcSource = Join-Path $rcRoot 'agentrgb-0.1.0.dev0'
$rcDist = Join-Path $rcRoot 'dist-rc1'
```

Только в `$rcSource\pyproject.toml` заменить `version = "0.1.0.dev0"` на
`version = "0.1.0rc1"`. Затем проверить metadata и собрать в отдельный каталог:

```powershell
py -3.14 -c "import pathlib,sys,tomllib; p=tomllib.loads((pathlib.Path(sys.argv[1])/'pyproject.toml').read_text(encoding='utf-8'))['project']; assert p['name']=='agentrgb' and p['version']=='0.1.0rc1', p" $rcSource
if ($LASTEXITCODE -ne 0) { throw 'RC metadata mismatch' }
py -3.14 -m build --outdir $rcDist $rcSource
if ($LASTEXITCODE -ne 0) { throw 'RC build failed' }
$rcWheel = Join-Path $rcDist 'agentrgb-0.1.0rc1-py3-none-any.whl'
$rcSdist = Join-Path $rcDist 'agentrgb-0.1.0rc1.tar.gz'
py -3.14 -m twine check $rcWheel $rcSdist
if ($LASTEXITCODE -ne 0) { throw 'RC twine check failed' }
@'
import email, sys, tarfile, zipfile
with zipfile.ZipFile(sys.argv[1]) as archive:
    names = [n for n in archive.namelist() if n.endswith('.dist-info/METADATA')]
    assert len(names) == 1
    wheel = email.message_from_bytes(archive.read(names[0]))
with tarfile.open(sys.argv[2]) as archive:
    stream = archive.extractfile('agentrgb-0.1.0rc1/PKG-INFO')
    assert stream is not None
    sdist = email.message_from_bytes(stream.read())
for metadata in (wheel, sdist):
    assert metadata['Name'] == 'agentrgb'
    assert metadata['Version'] == '0.1.0rc1', metadata['Version']
print('Both artifacts: agentrgb 0.1.0rc1')
'@ | py -3.14 - $rcWheel $rcSdist
if ($LASTEXITCODE -ne 0) { throw 'RC artifact metadata mismatch' }
```

Повторить content audit и clean wheel install для RC. Непосредственно перед
upload снова проверить эти два файла. Только после отдельного решения выполнить
следующую команду с явным TestPyPI URL и точными именами, без wildcard:

```powershell
py -3.14 -m twine upload --repository-url https://test.pypi.org/legacy/ $rcWheel $rcSdist
```

Credentials вводит владелец вручную через штатный prompt Twine. Не передавать
токен в командной строке, коде, журнале или переписке; не сохранять credentials
в репозитории. Не создавать для этого `.pypirc` или `.env`.

После публикации RC создать ещё один venv вне checkout и установить точную версию:

```powershell
$rcVenv = Join-Path $rcRoot 'install-venv'
py -3.14 -m venv $rcVenv
& "$rcVenv\Scripts\python.exe" -m pip install --no-deps --only-binary=:all: --index-url https://test.pypi.org/simple/ agentrgb==0.1.0rc1
```

Runtime dependencies отсутствуют, поэтому дополнительный индекс не нужен.
Повторить CLI smoke из каталога вне checkout. Этот тест не публикует финальную
версию и не заменяет будущую установку из настоящего PyPI.

## Финальные версии

После clean artifact tests и отдельного решения о релизе:

| Место | Перед финальной сборкой |
|---|---|
| `pyproject.toml`, `project.version` | `0.1.0.dev0` → `0.1.0` |
| `integrations/pi/package.json`, `version` | `0.1.0-dev.0` → `0.1.0` |
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
