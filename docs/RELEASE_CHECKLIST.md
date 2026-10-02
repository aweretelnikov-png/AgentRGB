# Release checklist: 0.1.0

Проверки относятся к конкретным артефактам. После изменения исходников или metadata
нужно пересобрать затронутый артефакт и повторить его проверки. План публикации —
[RELEASING.md](RELEASING.md). Этот этап не включает commit, push, tag или публикацию.

Результаты и границы проверок: [RELEASE_PREP.md](RELEASE_PREP.md). Локальный smoke использовал Pi 0.87.1, fake output и локальный тестовый provider; внешний Core на `8765` не останавливался.

TestPyPI: Python `0.1.0rc1` опубликован и проверен в новом venv из реестра;
metadata, SHA-256, CLI, default fake Core, Ctrl+C и освобождение порта подтверждены
в [RELEASE_RC1.md](RELEASE_RC1.md). Чеклист ниже сохраняет локальные gates
первоначальной подготовки; production publication остаётся отдельным этапом.

Pi npm RC `0.1.0-rc.1` опубликован с `--tag next`; registry install и ordinary Pi
→ owned fake Core → lifecycle → `/quit` → свободный порт проверены:
[RELEASE_PI_RC1.md](RELEASE_PI_RC1.md). Registry также назначил `latest` на RC;
удаление тега отклонено с E400, повтор не выполнялся. Отсутствие `latest`
не подтверждено; финальный npm release не опубликован.

## Code

- [x] Полный Python suite пройден.
- [x] Полный Node suite пройден.
- [x] `git diff --check` без ошибок.
- [x] Пользовательские `experiments/README.md` и `experiments/manual_scenarios.py` не изменены и не включены в release staging.

## Python artifact

- [x] Metadata проверены; лицензия MIT присутствует в артефактах.
- [x] Wheel собран.
- [x] Sdist собран; из него собирается wheel.
- [x] `twine check` пройден для обоих файлов.
- [x] Состав wheel/sdist проверен; console entry point `agentrgb` присутствует.
- [x] Wheel установлен в новый venv без editable install.
- [x] Из каталога вне checkout проверены `--help`, `status`, `doctor` (только identity read).
- [x] `agentrgb start` с default `fake`: `/health`, `status`, Ctrl+C и освобождение порта.
- [x] `dist/` игнорируется Git.

## Pi artifact

- [x] Metadata и точный список `npm pack --dry-run` проверены.
- [x] Tarball содержит только `package.json`, `agentrgb.ts`, `core.ts`, `README.md`, `LICENSE`.
- [x] `.tgz` установлен в отдельное окружение Pi; extension загружен из артефакта.
- [x] Pi autoload проверен без `-e` и без файлов исходного package в пути загрузки.
- [x] `.tgz` не включён в Git.

## Integration

- [x] Pi → установленный fake Core: `run_started` и `run_ended` получены.
- [x] Принадлежащий Pi Core завершается на `/quit`; тестовый порт `18767` освобождается (замена `8765` согласована пользователем).
- [x] Внешний Core остаётся работать после `/quit`.
- [x] Интерактивный Pi из каталога вне checkout: tarball autoload → autostart установленного wheel → lifecycle → `/quit`; fake выбран временным тестовым launcher.

Текущий Pi autostart явно выбирает `--output aula-f75`. Без аппаратного запуска
принадлежащий Pi fake Core можно проверить только тестовой подменой команды запуска.
Это ограничение проведённого smoke: неизменённый аппаратный autostart не проверен. Для
проверки внешнего Core достаточно заранее запустить `agentrgb start` с `fake`.

## Hardware

- [x] Для RC используется существующее доказательство [Phase 04C](../experiments/phase-04c/RESULTS.md): Pi → F75, цвета и возврат пользовательского профиля.
- [ ] Перед public release выполнен один короткий final F75 smoke с отдельного разрешения пользователя.

Phase 04 целиком не повторяется. Аппаратный вывод автоматически не запускается.

## Privacy

- [x] В артефактах нет содержимого запросов и ответов модели.
- [x] Нет секретов, credentials, `.env` или локальных settings.
- [x] Нет HID paths и абсолютных пользовательских путей.
- [x] Нет runtime logs, `experiments/results`, кэшей, `.diff` и временных файлов.

## Publication — только отдельный будущий этап

- [x] Имя `agentrgb` проверено на PyPI (HTTP 404, 25 сентября 2026); повторить непосредственно перед публикацией.
- [x] Имя `agentrgb-pi` проверено в npm (HTTP 404, 25 сентября 2026); повторить непосредственно перед публикацией.
- [ ] Согласован финальный version bump, новые артефакты `0.1.0` повторно проверены.
- [ ] PyPI publish.
- [ ] npm publish.
- [ ] Clean public install из PyPI/npm, без checkout.
- [ ] Final F75 smoke с отдельного разрешения.
- [ ] Git tag.
- [ ] GitHub release.

Отсутствие пакета в реестре не резервирует имя и не гарантирует разрешение на его
регистрацию. Если имя занято, остановиться и согласовать другое имя.
