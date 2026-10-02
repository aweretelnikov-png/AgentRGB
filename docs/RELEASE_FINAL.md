# Финальная подготовка 0.1.0: 2 октября 2026

Python и Pi metadata переведены на `0.1.0`; финальные артефакты подготовлены,
но не опубликованы. Runtime production-код и зависимости не менялись.
Manifest-тест допускает release SemVer вместо обязательного prerelease-дефиса.
README описывает публичный сценарий и явно предупреждает, что final release
ещё недоступен. Исторические RC evidence сохранены.

## Предыдущие проверки и namespace

- Python TestPyPI RC: [RELEASE_RC1.md](RELEASE_RC1.md).
- npm registry RC: [RELEASE_PI_RC1.md](RELEASE_PI_RC1.md).
- Evidence commit: `9ac52c5 docs: record npm 0.1.0-rc.1 validation`;
  staging включал только README.md, RELEASE_CHECKLIST.md, RELEASE_PI_RC1.md,
  RELEASING.md; cached diff check пройден.
- Перед final preparation GET `https://pypi.org/pypi/agentrgb/json` вернул HTTP 404.
  Это не резервирует имя; перед production upload повторить read-only lookup.
- npm namespace принадлежит ранее опубликованному RC. Read-only проверка tags:
  `next=0.1.0-rc.1`, `latest=0.1.0-rc.1`. Удаление latest ранее дало E400;
  повтор не выполнялся. При будущей финальной публикации latest должен перейти
  на `0.1.0`; результат нужно подтвердить после publish. Сейчас tags не менялись.

## Тесты и артефакты

Python 3.14.4: полный unittest suite, **167/167 OK**.
Node 24.15.0: полный suite, **35/35 PASS**, failures/skips отсутствуют.
`git diff --check` пройден. Python tests используют тестовые outputs, без hardware.

Команда `py` в test PATH отсутствует; использован проверенный Python 3.14.4
и существующий временный build-tools venv, без новых project dependencies.
Предыдущий dist сохранён вне checkout, финальная сборка начата с пустого dist.
`python -m build` собрал sdist и wheel именно из sdist; isolated setuptools 84.0.0.
`python -m twine check dist/*`: оба файла PASSED.
npm 11.12.1: `npm pack --dry-run` и `npm pack` пройдены с временным cache.

| Артефакт | SHA-256 |
|---|---|
| `agentrgb-0.1.0-py3-none-any.whl` | `34d45aeead2a86aca96110ba36390b4765e06b6f6b113bc87b161e8108cda14b` |
| `agentrgb-0.1.0.tar.gz` | `44045b4544a80ce66f3cb73b3b742dc60ce5bc1b355f2f69e34ee349eb84bda4` |
| `agentrgb-pi-0.1.0.tgz` | `9421ae6437eb9f15406874a038c27cf2e6fb3ff00e0231358219d7a7b07da8cd` |

Wheel: 16 файлов; sdist: 21 файл. Metadata: `agentrgb`, version `0.1.0`,
Python `>=3.14`, MIT, runtime dependencies отсутствуют, console entry point
`agentrgb = agentrgb.cli:main`. README и MIT LICENSE совпадают с checkout;
весь Python production source внутри обоих архивов совпадает с исходниками.
Sdist содержит только package source, build metadata, README и LICENSE.

npm tarball содержит ровно:

```text
package/LICENSE
package/README.md
package/agentrgb.ts
package/core.ts
package/package.json
```

Все пять файлов совпадают с исходниками; MIT LICENSE совпадает с корневым.
Manifest: `agentrgb-pi`, `0.1.0`, extension `./agentrgb.ts`, peer API предоставляет Pi.
Experiments, тесты, runtime logs, кэши, credentials, локальные settings и
машинно-зависимые абсолютные пути в артефакты не включены.

## Чистая установка final wheel: PASS

Создан новый venv вне checkout; установлен именно final wheel с `--no-deps
--no-index`, без editable install и `PYTHONPATH`. Installed metadata: `0.1.0`,
import из `Lib/site-packages`; direct_url подтверждает wheel и его SHA-256.
Команды выполнялись вне checkout:

- `agentrgb --help`: exit 0.
- `agentrgb status` до Core: not running, exit 1.
- `doctor`: версия и production imports подтверждены; тестовый backend
  блокировал аппаратное перечисление, F75 not found, ожидаемый exit 1.
  Реальный identity read не выполнялся.
- `agentrgb start` без output argument: default fake, `/health` HTTP 200,
  `status` running, exit 0.
- Настоящий Windows Ctrl+C console event: Core exit 0, exclusive bind
  подтвердил освобождение порта `54733`.

Первый запуск через терминальный PTY не обработал переданные Ctrl+C bytes;
эта тестовая сессия завершена console break. Проверка штатного Ctrl+C повторена
проверенным RC способом в отдельной скрытой Windows-консоли, успешно.
Это различие тестового способа подачи сигнала; production source не менялся.

## Чистая установка final Pi tarball: PASS

Финальный `.tgz` установлен в новый временный npm prefix через `npm install
--legacy-peer-deps --ignore-scripts --no-audit --no-fund <exact-final-tgz>`.
Lockfile подтверждает локальный final tarball и version `0.1.0`; все installed
files совпадают с артефактом. Через `pi install <installed-package>` пакет
зарегистрирован в отдельном `PI_CODING_AGENT_DIR`. Directory source из checkout
не использовался; пользовательская конфигурация Pi не менялась.

Обычный интерактивный **Pi 1.0.0** из cwd вне checkout, без `-e`, RPC или print mode,
показал autoload `agentrgb.ts`. Отключены sessions/tools/skills/themes/templates/
context files; offline mode исключал startup downloads. Warning missing fd
не помешал сценарию без tools. Test proxy задан только в test process environment.

Python сторона использовала именно новый venv с final wheel `0.1.0`.
Проверенный временный launcher в PATH сверил production autostart arguments,
заменил `aula-f75` на `fake` и заблокировал `WindowsHid`/`AulaF75Output`.
Test Core subclass записывала только lifecycle metadata. Installed files
и production source не менялись. Это проверка package/lifecycle с безопасной
подменой output; неизменённый аппаратный autostart не проверялся.
Локальный детерминированный SSE provider возвращал тестовый ответ и отбрасывал
request body без записи; внешний модельный provider не проверялся.

Подтверждено:

1. Autoload → ровно один owned fake Core; `/health` HTTP 200.
2. `run_started` и `run_ended`: оба `applied`, итог `completed`.
3. `/quit`: Pi exit 0; Core записал `core_closed` и `exited`, PID исчез.
4. Exclusive bind подтвердил свободный порт `60032`.

Provider остановлен. Hardware writes и аппаратный smoke не выполнялись.
Пользовательские experiment files сохранены, SHA-256 не изменились.

## Граница этапа

Локальные gates final artifact green; внешние шаги pending в
[RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md). Production PyPI upload, npm publish,
dist-tag mutations, push, git tag и GitHub Release не выполнялись.
Артефакты ignored и исключены из staging; после final preparation commit остановиться.
