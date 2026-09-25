# AgentRGB

AgentRGB — открытая локальная система физической индикации состояния ИИ-агентов через RGB-периферию компьютера.

Общий поток данных:

```text
ИИ-агент → события источника → нормализованные события AgentRGB
         → состояние сеансов и временные сигналы
         → правила индикации → адаптер вывода → RGB-устройство
```

Проект отделяет источники событий от способов вывода. Ядро не должно знать о Codex, Pi, OpenRGB или конкретной клавиатуре. Первый подтверждённый источник — Pi coding agent, первый выход — прямой HID-адаптер AULA F75 по USB. Codex и OpenRGB остаются направлениями дальнейшей работы.

AgentRGB работает локально на Windows, не требует учётной записи или облачного сервиса и не должен передавать наружу содержимое запросов и ответов модели.

## Состояние проекта

Реализованы локальные Python Core, HTTP-приёмник, Pi extension и прямой HID-выход AULA F75. Первый рабочий путь проверен на **Windows + Pi 0.86.1 + wired AULA F75 `258A:010C`** через интерфейс `MI_01/COL06`. Это подтверждение конкретной конфигурации, а не всех F75 и их ревизий. [Физический 04C](experiments/phase-04c/RESULTS.md) подтвердил полный цикл от реального Pi до клавиатуры.

| Состояние | Индикация F75 |
|---|---|
| `working` | Синий |
| `waiting` | Жёлтый |
| `completed` | Короткий зелёный сигнал |
| `idle` | Штатная подсветка пользователя |

AULA F75 работает через volatile Direct Mode `0x06/0x08`: пока AgentRGB управляет цветом, он посылает heartbeat. Он не переписывает пользовательский lighting profile при обычной работе. После прекращения кадров клавиатура самостоятельно возвращает свой профиль, как наблюдалось на проверенном устройстве. По умолчанию Core использует `fake`; аппаратный выход включается только явным `--output aula-f75`.

## Development install

Нужен Python 3.14 или новее; полный suite проверен на Python 3.14.4. Из корня репозитория в PowerShell:

```powershell
python -m pip install -e .
agentrgb --help
```

Текущая версия пакета — `0.1.0.dev0`. Runtime-зависимостей нет; после установки `PYTHONPATH` не требуется.

## Start

Для проводной AULA F75:

```powershell
agentrgb start --output aula-f75
```

Core работает в текущем терминале; `Ctrl+C` штатно завершает его работу. `agentrgb start` без параметров использует `fake`. Прежний запуск `python -m agentrgb.server --output aula-f75` сохранён.

## Check

В другом терминале:

```powershell
agentrgb status
agentrgb doctor
```

`status` проверяет локальный Core через HTTP без обращения к HID: `running` даёт код `0`, `not running` или `unavailable` — код `1`. Это проверка доступности Core, а не состояния агента или RGB-выхода.

`doctor` проверяет Python, версию установленного AgentRGB, импорты production-модулей, Core, порт и identity F75. Identity read использует служебный запрос `SetFeature` с opcode `0x82` и `GetFeature`, без Direct-кадров и изменения RGB/profile. Отсутствующее, неоднозначное или неподходящее устройство, ошибка проверки, отсутствие обязательных компонентов или недоступный/занятый другим процессом порт дают код `1`. Если всё готово, код `0`; незапущенный Core при свободном порте этому не мешает. Ошибки аргументов дают код `2`.

Все команды и Pi extension используют `AGENTRGB_PORT` (по умолчанию `8765`). При изменении порта задайте одинаковое значение в их терминалах. CLI принимает целое число от `1` до `65535`; неверное значение даёт код `2`.

## Pi

Локальная установка из корня репозитория (Python 3.14+, `agentrgb` в PATH процесса Pi):

```powershell
python -m pip install -e .
pi install ./integrations/pi
pi list
pi
```

Пакет загружается без `-e`. При `session_start` он использует существующий Core или запускает `agentrgb start --output aula-f75`; при выходе штатно останавливает только собственный child. Ошибка AgentRGB отключает интеграцию, но не Pi. Ожидание startup ограничено; supervisor и повторная доставка событий не добавлены.

Pi package auto-start в v0.1 рассчитан на проверенную AULA F75 configuration. Для работы без устройства заранее запустите `agentrgb start` (fake): пакет подключится к нему и не остановит при выходе. При нескольких Pi выход владельца Core отключит индикацию остальных; полноценное управление временем жизни для нескольких клиентов отложено.

Одноразовая загрузка без установки: `pi -e ./integrations/pi`. После установки не подключайте extension повторно через `-e ./integrations/pi/agentrgb.ts`. Подробности — [README пакета](integrations/pi/README.md).

Будущий опубликованный flow, **пока недоступный: npm package ещё не опубликован**:

```powershell
python -m pip install agentrgb
pi install npm:agentrgb-pi
pi
```

## Проверки

После development install программные тесты не требуют реальной клавиатуры:

```powershell
python -m unittest discover -s tests
$env:AGENTRGB_TEST_PYTHON = python -c "import sys; print(sys.executable)"
node --test tests/*.test.mjs experiments/pi-events/recorder.test.mjs
git diff --check
```

## Документы

- [`docs/VISION.md`](docs/VISION.md) — проблема, цель и принципы проекта.
- [`docs/MVP.md`](docs/MVP.md) — границы первой версии.
- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — модули, контракты и поток событий.
- [`docs/STATES.md`](docs/STATES.md) — состояния активности, временные сигналы и правила обработки.
- [`docs/INTEGRATIONS.md`](docs/INTEGRATIONS.md) — предварительное соответствие событий Codex и Pi модели AgentRGB.
- [`AGENTS.md`](AGENTS.md) — правила работы над репозиторием.

## Статус интеграций

Отрицательные результаты persistent `0x04/0x0A` сохранены в [исследованиях 04B](experiments/phase-04b/RESULTS.md): команды меняли цвет и читаемые config/color удавалось восстановить, но H2 выявил скрытое состояние DARK. Полное обесточивание вернуло свет без повторной настройки профиля. После этого production перешёл на volatile Direct Mode. [H5–H7](experiments/phase-04b/H7-RESULTS.md) проверили его обычный цикл, shutdown и контролируемый сбой; [04C](experiments/phase-04c/RESULTS.md) подтвердил сквозной путь Pi → F75.

## Известные ограничения

- Pi → Core использует localhost HTTP с best-effort доставкой. При временной недоступности Core событие может потеряться; retry и подтверждения доставки нет.
- Pi adapter поддерживает `working`, `waiting` только для блокирующего `ctx.ui` и `completed` только после final assistant `stopReason=stop` и `agent_settled`. `interrupted` и run-level `error` не поддерживаются; обычный текстовый вопрос модели не является `waiting`.
- Подтверждена конкретная проводная F75. Direct Mode требует heartbeat; долговременная эксплуатационная надёжность пока не исследована. Автоматический возврат профиля после аварийного завершения процесса не гарантируется.

## Лицензия

Лицензия проекта пока не выбрана.
