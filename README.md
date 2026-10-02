# AgentRGB

AgentRGB показывает состояние Pi coding agent через подсветку клавиатуры. Core работает локально и получает только события жизненного цикла, без содержимого запросов, ответов и инструментов.

Подготовка первой публичной версии `0.1.0` ещё идёт. Текущие RC версии: Python `0.1.0rc1`, Pi package `0.1.0-rc.1`. Python RC опубликован только в [TestPyPI](https://test.pypi.org/project/agentrgb/0.1.0rc1/); Pi RC опубликован в npm с `next`, registry smoke пройден ([evidence](docs/RELEASE_PI_RC1.md)). Registry также назначил `latest` на RC; удаление отклонено с E400. Production PyPI и финальный npm `0.1.0` не опубликованы.

## Требования

- Windows — текущая подтверждённая ОС.
- Python **3.14+**; локальные проверки выполнены на Python 3.14.4.
- Установленный [Pi coding agent](https://pi.dev) и доступная команда `pi`.
- Для физической индикации проверена **проводная AULA F75 `258A:010C`**, vendor HID-интерфейс `MI_01/COL06`. Другие ОС, клавиатуры и ревизии не подтверждены.
- Команда `agentrgb` должна быть в PATH процесса Pi.

## Планируемая публичная установка

**Planned: эти команды предназначены для будущего релиза. Финальная версия AgentRGB пока не опубликована в PyPI и npm; npm RC устанавливается явно через `pi install npm:agentrgb-pi@next`.**

```powershell
py -3.14 -m pip install agentrgb
pi install npm:agentrgb-pi
pi
```

Pi автоматически загружает пакет. Он подключается к существующему Core или запускает `agentrgb start --output aula-f75`. При `/quit` пакет завершает только Core, который запустил сам. Ошибка AgentRGB отключает индикацию, но не останавливает Pi.

Автозапуск Pi рассчитан на проверенную AULA F75 и может управлять её подсветкой. Для работы без клавиатуры сначала запустите в отдельном терминале `agentrgb start`: по умолчанию это безопасный `fake`. Pi подключится к такому Core и оставит его работающим при выходе.

## Состояния

| Состояние | Индикация |
|---|---|
| `working` | Синий (`blue`) |
| `waiting` | Жёлтый (`yellow`) |
| `completed` | Короткий зелёный сигнал (`green`) |
| `idle` | Пользовательская подсветка |

`waiting` поддерживается только при блокирующем Pi UI prompt внутри активного запуска. Обычный вопрос в ответе модели не создаёт `waiting`. `completed` означает штатное окончание выполнения, а не подтверждённый успех задачи.

F75 использует volatile Direct Mode `0x06/0x08` с heartbeat. При обычной работе AgentRGB не переписывает пользовательский lighting profile. После прекращения кадров проверенное устройство самостоятельно возвращает профиль; возврат после любого аварийного завершения не гарантируется.

## Ручной запуск и диагностика

```powershell
agentrgb --help
agentrgb start                 # fake, без RGB-устройства
# Только для осознанного аппаратного запуска:
agentrgb start --output aula-f75
```

Core работает в текущем терминале. `Ctrl+C` завершает его и освобождает порт. Для диагностики в другом терминале:

```powershell
agentrgb doctor
agentrgb status
```

`status` обращается только к HTTP Core: `running` даёт код `0`, `not running` или `unavailable` — `1`. Это доступность Core, а не состояние агента или исправность RGB-выхода.

`doctor` проверяет Python, версию AgentRGB, production imports, Core, порт и identity F75. Identity read использует `SetFeature` с opcode `0x82` и `GetFeature`, без Direct-кадров и изменения RGB/profile. Отсутствующее, неоднозначное или неподходящее устройство, ошибка диагностики либо занятый другим процессом порт дают код `1`. Если всё готово — `0`; незапущенный Core при свободном порте этому не мешает. Ошибка аргументов даёт код `2`.

CLI и Pi используют `AGENTRGB_PORT` (по умолчанию `8765`). При изменении порта задайте одинаковое значение в обоих терминалах; допустимы целые числа от `1` до `65535`.

## Локальная установка для разработки

Из корня репозитория, PowerShell:

```powershell
py -3.14 -m pip install -e .
pi install ./integrations/pi
pi list
```

После этого `pi` загружает пакет без `-e`. Не подключайте установленный extension повторно через `-e ./integrations/pi/agentrgb.ts`. Подробности — в [README пакета](integrations/pi/README.md).

Editable install предназначен для разработки. Release gate использует wheel в новом venv и Pi package из npm tarball, запуск вне checkout: [чеклист](docs/RELEASE_CHECKLIST.md), [сборка и ручная публикация](docs/RELEASING.md). Runtime-зависимостей у Python-пакета нет. Если Python launcher `py` отсутствует, используйте путь к проверенному Python 3.14+.

## Проверки

После development install, без реальной клавиатуры:

```powershell
py -3.14 -m unittest discover -s tests
$env:AGENTRGB_TEST_PYTHON = py -3.14 -c "import sys; print(sys.executable)"
node --test tests/*.test.mjs experiments/pi-events/recorder.test.mjs
git diff --check
```

## Известные ограничения

- Pi transport — best-effort localhost HTTP: события при недоступности Core могут потеряться; retry и подтверждений доставки нет.
- `waiting` поддерживается только через Pi UI prompt. Pi `interrupted` и run-level `error` пока не классифицируются.
- Проверена конкретная проводная AULA F75. Другие устройства и режимы Bluetooth/2,4 ГГц не поддержаны; долговременная надёжность не исследована.
- Требуется Python 3.14+; подтверждённая ОС — Windows.
- При нескольких Pi выход владельца Core отключит индикацию остальных. Supervisor и полноценное управление несколькими клиентами отложены.
- QoderCLI, CodexCLI и WLED не входят в `0.1.0`. OpenRGB остаётся возможным будущим адаптером.

## Документы и подтверждённые проверки

- [VISION](docs/VISION.md), [MVP](docs/MVP.md), [ARCHITECTURE](docs/ARCHITECTURE.md) — цель, границы и устройство проекта.
- [STATES](docs/STATES.md), [INTEGRATIONS](docs/INTEGRATIONS.md) — модель состояний и соответствие событий Pi.
- [04C](experiments/phase-04c/RESULTS.md) — подтверждённый путь Pi → F75 на Windows с Pi 0.86.1.
- [H5–H7](experiments/phase-04b/H7-RESULTS.md) — Direct Mode, штатный shutdown и контролируемый сбой output. Исторические persistent-команды `0x04/0x0A` не используются production lifecycle.
- [AGENTS.md](AGENTS.md) — правила разработки.

## Лицензия

[MIT](LICENSE).
