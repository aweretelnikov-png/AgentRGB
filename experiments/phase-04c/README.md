# Phase 04C: сквозная проверка

**Физический 04C пройден одним запуском; [результат](RESULTS.md).** Этот каталог содержит ограниченный стенд,
read-only identity и журнал для одной реальной цепочки Pi → extension → HTTP →
Core → `AulaF75Output` → F75. Production lifecycle, протокол, Core, Direct
frame, heartbeat и identity gate не изменены. `confirm-on-start.ts` существует
только в эксперименте.

## Сценарий

Pi 0.86.1 получает короткий настоящий запрос: `Reply OK without using tools`.
После `agent_start` экспериментальное расширение выдерживает 2 секунды, затем
вызывает настоящий блокирующий `ctx.ui.confirm`. В физическом TUI пользователь
видит вопрос, оставляет его без ответа минимум на 5 секунд и подтверждает
продолжение. После ответа Pi завершает запрос и пользователь вводит `/quit`.
Никаких искусственных HTTP lifecycle events или файловых операций нет.

Ожидаемый порядок:

```text
Pi       agent_start → ui_prompt_start → ui_prompt_end → agent_end(stop) → agent_settled
Adapter  run_started → run_waiting → run_resumed → run_ended(completed)
Core     working → waiting → working → completed (2 с) → idle
F75      blue → yellow → blue → green → исходная статичная разноцветная подсветка
```

`completed` допускается только для последнего assistant `stopReason=stop` и
следующего `agent_settled`. UI prompt вне активного запуска не создаёт waiting.
Эти правила оставлены в существующем адаптере. HTTP остаётся best-effort:
потеря события возможна, retry/ACK/очередь не добавлены.

## Preflight перед физическим запуском

1. Порт `127.0.0.1:8765` свободен; стенд проверяет это до запуска Core.
2. Полные Python и Node suites проходят.
3. `pi --version` показывает установленную версию; smoke ниже доказывает
   загрузку production и экспериментального расширений.
4. `node ./experiments/phase-04c/run.mjs fake` проходит с реальным Pi и
   `FakeOutput` до read-only работы с F75. Для Pi нужен уже известный локальный
   proxy только в окружении запускаемого тестового процесса; файлы и постоянные
   настройки его не содержат.
5. `PYTHONPATH=src python ./experiments/phase-04c/identity.py` выполняет ровно
   один read request `0x82`: USB `258A:010C`, `MI_01/COL06`, usage
   `FF00/0001`, feature length 520, report ID `06`, model `03`, PSD `00CD`.
   Проверки RGB/config baseline нет. Запрос `0x82` технически передаётся через
   `HidD_SetFeature`, но не меняет подсветку: 0 Direct frames и 0 изменяющих
   команд.
6. Пользователь визуально подтверждает исходную **статичную разноцветную**
   подсветку. Перед выполненным запуском было получено отдельное разрешение
   на один физический 04C.

Текущий preflight 24 сентября 2026 года: Python **139/139**, Node **17/17**,
Pi **0.86.1**, порт свободен, fake smoke **passed** с `agent_end(stop)` и
`completed`, identity **read_only_identified** со всеми значениями выше.
Один промежуточный повтор полного Python suite получил известный для раннего
HTTP 413 ответа Windows `WinError 10053` в транспортном тесте; следующий полный
прогон прошёл 139/139 без изменений кода.
Пользователь подтвердил видимую исходную статичную разноцветную подсветку.
Smoke:
[`summary.json`](results/fake-2026-09-24T05-17-00-497Z/summary.json) и
[`journal.jsonl`](results/fake-2026-09-24T05-17-00-497Z/journal.jsonl).

## Ограниченный физический runner

Из корня репозитория в интерактивном PowerShell:

```powershell
node ./experiments/phase-04c/run.mjs aula-f75
```

Runner явно выбирает `aula-f75`; обычный `python -m agentrgb.server` по-прежнему
выбирает `fake`. Он запускает production `EventServer`, `Core` и
`AulaF75Output` с экспериментальной обёрткой HID, допускающей только один
read request `0x82` и валидные Direct frames `0x06/0x08`. Физический лимит:
**150 секунд от старта стенда и максимум 3000 попыток Direct frame**. При
обычном интервале 50 мс это даёт время увидеть все четыре цвета и ответить
на вопрос. Исчерпание лимита останавливает worker; общий deadline завершает
Core и закрывает listener. После `/quit` runner штатно завершает Core.

Runner запускает Pi в TUI с `--no-session`, отключённой автозагрузкой ресурсов,
`--no-tools` и тремя явными `-e`: production
`integrations/pi/agentrgb.ts`, очищенный регистратор
`experiments/pi-events/pi-event-recorder.ts`, экспериментальный
`confirm-on-start.ts`. Никакие другие инструменты модели не разрешены.

Для справки production-команды отдельных компонентов:

```powershell
$env:PYTHONPATH = Join-Path $PWD 'src'
python -m agentrgb.server --output aula-f75
pi -e ./integrations/pi/agentrgb.ts
```

Они не содержат лимита стенда; физический 04C выполняется только командой
runner выше. Перед первым Direct frame ошибки старта Pi/Core и identity gate
оставляют 0 Direct frames. При ошибке HID, потере/неожиданном порядке событий
стенд прекращает Core; worker останавливается, handle закрывается, кадры
прекращаются. Команд `0x04`, `0x0A`, `0x39`, `0x3C`, disable и restore нет.
Автоматический возврат профиля после остановки кадров ранее подтверждён на
этой F75, но для нового запуска требует визуального наблюдения. Зависший
системный HID-вызов нельзя принудительно завершить из Python без остановки
процесса; это ограничение hard timeout.

## Журнал и оценка

`results/<run>/journal.jsonl` объединяет техническую Pi-трассу с Core/HID
трассой по UTC timestamp. В нём есть Pi event names, `source_instance_id`,
`run_id`, `event_id`, normalized event, aggregate/visible state, desired RGB,
heartbeat start/stop, количество и время первого/последнего кадра, worker stop,
handle close и Core shutdown. Отдельный `summary.json` фиксирует
машинный вердикт. Записи не содержат prompt/response text, thinking, аргументы
или содержимое инструментов, пользовательские имена файлов или секреты.
Pi recorder вызывается после adapter, поэтому порядок его timestamp и времени
обработки Core не измеряет задержку транспорта.

Физический успех требует `summary.status=passed`, отсутствия ошибок,
подтверждения пользователем цветов и самостоятельного возврата исходного
профиля. Код не считает цвет или возврат профиля подтверждённым только по
записям HID.
