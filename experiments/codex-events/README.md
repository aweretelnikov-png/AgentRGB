# Опыты Codex, фаза 03

Результат и ограничения: [RESULTS.md](RESULTS.md). Проверенная среда: Windows, Codex 0.155.0-alpha.9.2, Python 3.14.4, Node 24.15.0.

Все команды ниже выполняются из корня репозитория. Постоянная конфигурация не меняется. `_local/` содержит только локальные рабочие материалы и игнорируется Git. Не добавляйте туда дампы входных событий, auth или transcripts. `evidence/` содержит только проверенные технические поля.

## Что подтверждает фаза

- Hooks дают стабильные идентификаторы сеанса и хода, но `Stop` не означает окончание хода, а `PermissionRequest` не доказывает универсальное `waiting`.
- Отдельный App Server подтвердил lifecycle, approvals и наблюдение второго клиента только для собственного тестового сервера.
- Опыт 03O не нашёл поддерживаемого пассивного подключения к обычному Codex Desktop; `codex-ipc` не открывался и не исследовался как протокол.

Поэтому эти материалы не являются готовым адаптером Codex для AgentRGB. Они описывают воспроизводимые границы исследования; Codex отложен вне первого MVP.

## Проверки без модели

```powershell
python -m unittest discover -s experiments/codex-events -p test_recorder.py -v
codex app-server generate-json-schema --experimental --out experiments/codex-events/_local/schema
```

## Модельные опыты

Не перезаписывайте существующие журналы: каждому запуску нужен новый путь. Опыты используют текущую авторизацию самого Codex и расходуют обычный лимит модели.

```powershell
python experiments/codex-events/app_server_probe.py inspect --output experiments/codex-events/_local/inspect-new.jsonl
python experiments/codex-events/cli_probe.py normal --output experiments/codex-events/_local/hooks-normal-new.jsonl
python experiments/codex-events/cli_probe.py tools --output experiments/codex-events/_local/hooks-tools-new.jsonl
python experiments/codex-events/app_server_probe.py normal --output experiments/codex-events/_local/app-normal-new.jsonl
python experiments/codex-events/app_server_probe.py interrupt --output experiments/codex-events/_local/app-interrupt-new.jsonl
python experiments/codex-events/app_server_probe.py tools --output experiments/codex-events/_local/app-tools-new.jsonl
```

Перед CLI-пробами убедитесь через inspect, что нет других hooks: CLI использует одноразовый флаг доверия проверенному регистратору. Если другие hooks появились, не запускайте этот путь без их проверки. `permission_mode` фиксируется как получен; он не заменяет проверку sandbox.

Продолжение Stop — отдельный изменяющий опыт с согласованием по [STOP-PLAN.md](STOP-PLAN.md):

```powershell
python experiments/codex-events/cli_probe.py stop --output experiments/codex-events/_local/hooks-stop-new.jsonl
```

Два клиента общего сервера:

```powershell
python experiments/codex-events/two_clients_probe.py
```

Скрипт создаёт собственный обычный тестовый thread, выполняет первый ход, затем подключает наблюдателя с `excludeTurns=true`. После второго хода thread архивируется. Этот опыт не подключается к desktop-сеансам пользователя. WebSocket используется только как интерфейс Codex для теста, а не как выбранный транспорт AgentRGB.

## Ручной approval App Server

```powershell
python experiments/codex-events/app_server_probe.py approval --output experiments/codex-events/_local/approval-new.jsonl --decision-file experiments/codex-events/_local/approval-new.choice
```

Файл решения должен отсутствовать до показа запроса. После появления `pending_approval` человек выбирает действие для фиксированного безопасного сценария вывода 42. Запишите в файл решения ровно `accept`, `decline` или `interrupt`. Не создавайте файл заранее. Не разрешайте произвольный запрос, если изменён сценарий: регистратор специально не сохраняет команду и не доказывает её безвредность сам по себе.

Через 300 с без ответа клиент отменяет только собственный тестовый ход. Это техническая уборка, не модель определения waiting по таймеру. Исход отмены определяется по событию сервера.

## Native CLI UI

[`manual_probe.ps1`](manual_probe.ps1) запускается в пользовательском интерактивном терминале. Он подключает только пассивные hooks к новому CLI. Stdout CLI не перенаправлять в файл. Скрипт не читает экран и не подтверждает запросы вместо человека.

1. Дождаться реального запроса на вывод 42; отдельно зафиксировать человеком, что запрос виден и выполнение ждёт.
2. Разрешить запрос, дождаться окончания. Повторить безопасный запрос и отказать.
3. Для ручного Interrupt попросить только выполнить `Start-Sleep -Seconds 60`, затем нажать Escape во время активного хода. Не использовать таймер как доказательство состояния: проверить полученные hooks.
4. Отправить ещё один короткий запрос без инструментов, чтобы сравнить новый turn id того же session.
5. Завершить CLI штатно. Историю сеанса и сообщения не открывать для анализа.

`hook_recorder.py` не пишет тексты; `app_server_probe.py` фильтрует входной поток; `cli_probe.py` для автоматических опытов отбрасывает stdout/stderr целиком. Тестовый регистратор не реализует модель состояний AgentRGB и не управляет RGB.

## 03O: топология обычного Desktop

`desktop_topology.ps1` собирает только read-only метаданные процессов Windows, безопасную проекцию аргументов Codex, TCP listeners и семейства имён pipes. Нужен доступ к CIM и таблице TCP; из ограниченного sandbox он может быть запрещён. Скрипт не подключается к endpoint и не читает историю, environment, auth или конфигурацию.

```powershell
./experiments/codex-events/desktop_topology.ps1 -OutputFile experiments/codex-events/_local/desktop-topology-new.json
```

Итог текущей проверки — вариант C; подробности и десять ответов находятся в разделе «03O — Desktop observer» отчёта. Наличие `codex-ipc` не разрешает автоматически использовать его как App Server endpoint. Observer для текущего Desktop не создавался.
