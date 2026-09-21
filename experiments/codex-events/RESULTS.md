# Фаза 03: Codex как источник событий

Дата опытов: 2026-09-21. Версия: **codex-cli 0.155.0-alpha.9.2**, Windows.

**Отчёт собран; покрытие подтверждено частично.** Автоматические опыты завершены, ручной CLI-сеанс штатно закрыт. В native CLI подтверждены показ approval, однократное разрешение и ручной Interrupt при отмене следующего approval. Дополнительно получен ручной Interrupt после PreToolUse без approval; факт запуска самого shell-процесса этим hook не доказывается. Отдельный отказ с продолжением хода не проверен. Проверка 03O не обнаружила поддерживаемого endpoint уже работающего Desktop; пассивное подключение осталось неподтверждённым. Здесь нет гарантии полного покрытия обычного пользовательского Codex.

## Главные результаты

- **confirmed:** Stop может прийти дважды для одного `turn_id`, с продолжением между ними. Первый Stop не означает окончание активности.
- **confirmed:** отдельный App Server даёт `turn/started`, `turn/completed: completed` и `turn/completed: interrupted`; обычные последовательные ходы имеют разные стабильные идентификаторы.
- **confirmed:** App Server даёт пару approval request / `serverRequest/resolved`. После реального разрешения пользователя выполнение продолжилось; при отмене pending request очищен после окончания хода.
- **rejected:** утверждение «App Server сообщает только о ходах, запущенных тем же подключённым клиентом». Второй клиент получил события следующего хода первого клиента после `thread/resume` с `excludeTurns=true`.
- **unknown:** доступность такого подключения к обычному уже открытому desktop/CLI пользователя. Общий тестовый сервер не доказывает доступность endpoint обычного приложения.
- **unknown:** независимый терминальный `failed`. Наблюдались промежуточные `error` с `willRetry=true`, после которых ход закончился `completed`.

Значения статусов: `confirmed` — подтверждено указанным опытом либо локальной схемой, с явным указанием основания; `partially confirmed` — проверена лишь часть утверждения; `rejected` — найден контрпример; `unknown` — доказательств нет. Поддержка поля в схеме не равна проверке его поведения.

## 03A. Среда и границы доступа

Первым действием после чтения задания выполнен `git status`: ветка `master`, рабочее дерево чистое. Результаты Pi не изменялись.

| Параметр | Наблюдение |
|---|---|
| Исполняемый файл | `codex.exe` из versioned `OpenAI/Codex/bin/` в локальной установке приложения; это не найденный npm shim |
| Точная версия | `codex-cli 0.155.0-alpha.9.2` |
| SHA-256 бинарного файла | `bc45017e8239dc150258f69309ced9df6bbcdf5b8e4f346decf780ac0999e226` |
| Обычный интерфейс текущей задачи | Codex desktop, подтверждено контекстом приложения. Использование пользователем других интерфейсов не установлено |
| Способ первоначальной установки / версия оболочки desktop | `unknown`; расположение бинарного файла не доказывает конкретный установщик |
| Python / Node | Python 3.14.4; Node v24.15.0, стандартные библиотеки, новых зависимостей нет |
| Пользовательский `config.toml` | Есть; выбран `gpt-6-astra`, указан `sandbox_mode=workspace-write` |
| Пользовательский `hooks.json` / inline hooks | Не обнаружены |
| Проектная `.codex/` | До опытов отсутствовала; не создавалась |
| `config/read` из отдельного App Server | Активны слои `user` и `system`; `approval_policy`, `approvals_reviewer`, `model_provider` возвращены как `null` |
| `hooks/list` для проекта | Пусто; ошибок и предупреждений нет. Других PermissionRequest hooks не найдено |
| Настройки текущей desktop-задачи | Из контекста задачи: `workspace-write`, reviewer `auto_review`. Это отдельные overrides; `null` в `config/read` не означает их отсутствия в desktop |
| Тестовые App Server threads | Явно заданы `read-only`, `on-request`, reviewer `user`; по умолчанию ephemeral |
| CLI exec | `--ephemeral --sandbox read-only`; в hooks наблюдалось `permission_mode=bypassPermissions`. Это наблюдаемый enum, а не доказательство отключения файлового sandbox |

История, transcripts, auth и секреты не открывались исследовательскими скриптами. Сам Codex использовал обычную авторизацию; ключи не копировались. `config/read` и `hooks/list` фильтровались до вывода. Настройки не копировались в репозиторий. Точный механизм восстановления всех desktop-overrides через отдельный сервер не установлен.

Запуск отдельного сервера из Windows sandbox завершался до ответа. Тот же read-only диагностический опыт вне sandbox прошёл. Это ограничение среды запуска исследователя, не ошибка запуска агента и не доказательство `failed`.

## 03B. Источники и установленный интерфейс

Проверены официальные [Hooks](https://learn.chatgpt.com/docs/hooks) и [App Server](https://learn.chatgpt.com/docs/app-server), а также схемы, сгенерированные **установленным бинарным файлом** через `codex app-server generate-json-schema --experimental`. [Сводка схем и контрольные суммы](evidence/schema-summary.json) позволяет привязать проверку к версии. Полный пакет схем находится только в игнорируемом `_local/schema/` и воспроизводится командой из README.

Локальный `HookEventName` включает все запрошенные события: SessionStart, SessionEnd, UserPromptSubmit, PreToolUse, PostToolUse, PermissionRequest, Stop, Interrupt, PreCompact, PostCompact (в API enum — camelCase). Это схема каталога hooks; отдельной локальной схемы stdin command hook не получено.

| Hook | Реально получен | Разрешённые поля, реально наблюдавшиеся |
|---|---|---|
| SessionStart | confirmed, CLI A/B/H | `session_id`, `permission_mode`; `turn_id` отсутствовал |
| SessionEnd | confirmed, CLI A/B/H | `session_id`; `turn_id` и `permission_mode` отсутствовали |
| UserPromptSubmit | confirmed, CLI A/B/H | `session_id`, `turn_id`, `permission_mode` |
| PreToolUse | confirmed, B | Те же идентификаторы и `permission_mode`, тип `Bash` |
| PostToolUse | confirmed, B | Те же идентификаторы и `permission_mode`, тип `Bash` |
| PermissionRequest | confirmed, native CLI F, запрос виден пользователю | `session_id`, `turn_id`, `permission_mode=default`, тип `Bash` |
| Stop | confirmed, A/B/H | `session_id`, `turn_id`, `permission_mode`, boolean `stop_hook_active` |
| Interrupt | confirmed, ручная отмена native CLI approval и после PreToolUse без approval | `session_id`, `turn_id`, `permission_mode=default` |
| PreCompact / PostCompact | unknown, compaction не вызывали | Event enum подтверждён |

По официальному контракту PermissionRequest допускает автоматическое решение другим hook, Stop допускает продолжение, Interrupt относится к активному основному ходу. Реальные эксперименты с auto-allow/deny другим PermissionRequest hook не выполнялись. Универсальное hook-событие окончания ожидания в изученном интерфейсе не найдено.

App Server CLI этой сборки предлагает `daemon`, `proxy`, `--remote` и несколько способов подключения. В локальной схеме нет отдельного `thread/subscribe`; есть `thread/resume` и `thread/unsubscribe`. `ThreadResumeParams.excludeTurns` позволяет не получать turns. `ServerRequestResolvedNotification` содержит только `threadId` и `requestId`, **без `turnId`**. `TurnStatus` содержит `inProgress`, `completed`, `interrupted`, `failed`.

## 03C. Пассивный регистратор

[`hook_recorder.py`](hook_recorder.py) сохраняет только локальные `sequence`, UTC timestamp, `hook_event_name`, `session_id`, `turn_id`, `permission_mode`, `stop_hook_active` для Stop и тип инструмента. Поля выбираются заново из allowlist; неизвестные имена инструмента записываются как `other`. Исходный JSON не сохраняется.

stdout/stderr пусты, завершение — exit 0 даже при ошибке JSON или записи. Нет decision, разрешений, изменения запросов, инструментов и продолжений. Отдельная блокировка Windows защищает sequence от параллельных writers; ожидание ограничено 250 мс. При недоступности записи событие может потеряться. Hook запускается синхронно с timeout 3 с, поэтому небольшая задержка запуска процесса есть; абсолютное отсутствие задержек не обещается. Sequence отражает порядок записи регистратором, а не глобальные часы Codex.

[`stop_once.py`](stop_once.py) — отдельный **непассивный** обработчик только опыта H. Пользователь явно разрешил его после чтения [плана](STOP-PLAN.md). Он не подключён к постоянной конфигурации. Флаг `stop_hook_active` и одноразовый маркер ограничивают его одним продолжением.

Одноразовый CLI-флаг доверия hooks применён только после проверки отсутствия других hooks. Он не отключает sandbox инструментов. Никаких пользовательских trust-записей эксперимент не создаёт намеренно.

## 03D–H. CLI Hooks: сырые последовательности

Полные JSONL содержат исходные значения выбранных технических полей, без содержимого сообщений. Ниже порядок событий сокращён только для чтения; реальные идентификаторы, время и sequence доступны по ссылкам.

### A. Обычное окончание

[`hooks-normal.jsonl`](evidence/hooks-normal.jsonl):

```text
SessionStart
UserPromptSubmit(turn_id=T1)
Stop(turn_id=T1, stop_hook_active=false)
SessionEnd
```

`UserPromptSubmit` получен один раз, идентификатор совпал со Stop. В этом опыте продолжения не было. **partially confirmed:** событие подходит как кандидат начала, но опыт не покрывает блокирующий UserPromptSubmit hook и не доказывает фактический старт после любого submit. Последовательные CLI turns одного session дополнительно проверены в F/G: первый завершён после разрешения, второй прерван.

### B. Инструменты

[`hooks-tools.jsonl`](evidence/hooks-tools.jsonl):

```text
SessionStart
UserPromptSubmit(T1)
PreToolUse(T1, Bash) → PostToolUse(T1, Bash)
PreToolUse(T1, Bash) → PostToolUse(T1, Bash)
Stop(T1, false)
SessionEnd
```

Два инструмента внутри одного turn — **confirmed**. В сценарии запрошены сначала безопасный `exit 7`, затем вывод числа. Регистратор намеренно не сохраняет команды и результаты инструментов, поэтому **фактический exit code первого инструмента по этому журналу не доказан**. Нельзя выдавать заданный модели сценарий за проверенный исход выполнения. Опыт подтверждает порядок hooks и стабильность turn id, но не классификацию ошибки инструмента или запуска.

### F/G. Реальное ожидание и ручной Interrupt

Вызов native CLI подготовлен в [`manual_probe.ps1`](manual_probe.ps1) и открыт в отдельном пользовательском окне. После предупреждения `TERM=dumb` пользователь разрешил запуск TUI и подтвердил видимый запрос одобрения безопасной команды. Снимок до ответа: [`hooks-manual-pending.jsonl`](evidence/hooks-manual-pending.jsonl).

```text
SessionStart(permission_mode=default)
UserPromptSubmit(T1, default)
PreToolUse(T1, Bash)
PermissionRequest(T1, Bash)
[пользователь подтвердил видимый native CLI approval; ответ ещё не дан]
```

**confirmed:** в этом профиле PermissionRequest сопровождает реальный запрос пользователю; идентификатор turn совпадает с UserPromptSubmit и PreToolUse. **unknown:** точный момент hook относительно отрисовки UI и структурированная граница окончания ожидания. Отсутствие событий и прошедшее время не используются как доказательство waiting. Содержимое экрана и сетевой диагностики в артефакты не копируется.

Дополнение после ответа: пользователь выбрал однократное разрешение и подтвердил выполнение команды. Полный снимок первого хода: [`hooks-manual-allow.jsonl`](evidence/hooks-manual-allow.jsonl). После PermissionRequest получены только `PostToolUse(T1, Bash) → Stop(T1, stop_hook_active=false)`, с теми же session/turn id. **confirmed:** путь allow в native CLI. Отдельного hook окончания ожидания в этом опыте не наблюдалось; PostToolUse фиксирует окончание инструмента, поэтому не принимается за точную границу выхода из waiting.

Во втором ходе пользователь выполнил предложенную отмену в approval UI. Снимок [`hooks-manual-approval-interrupt.jsonl`](evidence/hooks-manual-approval-interrupt.jsonl) содержит `UserPromptSubmit(T2) → PreToolUse(T2, Bash) → PermissionRequest(T2, Bash) → Interrupt(T2)`. **confirmed:** ручная отмена дала структурированный Interrupt. Это прерывание всего хода, а не подтверждённый отдельный deny с продолжением. На момент снимка после Interrupt нет PostToolUse или Stop; это не гарантия их отсутствия во всех сценариях. Session id сохранился, T2 отличается от T1, внутри каждого хода id стабилен. Отдельный deny и Escape во время выполняющегося инструмента остаются **unknown**.

Hooks-профиль `waiting` пока **не допускается**: обе достоверные границы не найдены. В частности, даже реально полученный PermissionRequest сам по себе недостаточен при наличии других решающих hooks.

Дополнительный ручной опыт G: [`hooks-manual-tool-interrupt.jsonl`](evidence/hooks-manual-tool-interrupt.jsonl) содержит для третьего turn `UserPromptSubmit(T3) → PreToolUse(T3, Bash) → Interrupt(T3)`. PermissionRequest в этом ходе нет; PostToolUse и Stop на момент снимка отсутствуют. **confirmed:** ручной Interrupt после входа в обработку инструмента, стабильность T3 и сохранение session id. **partially confirmed:** прерывание непосредственно выполняющегося shell-процесса — PreToolUse приходит до выполнения и сам по себе не доказывает, что процесс уже стартовал. Освобождение shell-процесса не проверялось. Текст намерения модели не использован как доказательство запуска.

Пользователь завершил CLI через `/quit`. Итоговый [`hooks-manual-complete.jsonl`](evidence/hooks-manual-complete.jsonl) содержит 14 записей и заканчивается `SessionEnd` с прежним `session_id`, без `turn_id`. **confirmed:** штатное закрытие наблюдаемого сеанса. После обеих отмен до закрытия сеанса не получены Stop или PostToolUse соответствующих прерванных turns. Это результат двух конкретных опытов, не универсальная гарантия. SessionEnd не создаёт completed и не заменяет окончание обычного хода.

### H. Stop с продолжением

[`hooks-stop.jsonl`](evidence/hooks-stop.jsonl):

```text
SessionStart
UserPromptSubmit(turn_id=01a0c2d5-761f-7381-961b-7be8a08ce874)
Stop(тот же turn_id, stop_hook_active=false)
Stop(тот же turn_id, stop_hook_active=true)
SessionEnd
```

Два Stop разделены примерно 4,9 с. Основание продолжения — поведение разрешённого одноразового hook и повторный Stop с изменившимся флагом, **не длительность интервала**. Дополнительного UserPromptSubmit не было. Текст ответа не анализировался.

**rejected:** безусловные `Stop → run_ended` и `Stop → completed`. `stop_hook_active=false` не делает первый Stop окончательным. `true` тоже не доказывает окончательность для произвольного набора других hooks. Повторный Stop нельзя превращать в новый run.

## 03I–K. App Server

### J. Начало, нормальное окончание и отмена

[`app-normal.jsonl`](evidence/app-normal.jsonl) содержит два хода одного thread:

```text
thread/started
turn/started(T1, inProgress)
error(T1, willRetry=true) × 4
turn/completed(T1, completed)
turn/started(T2, inProgress)
turn/completed(T2, completed)
```

T1 и T2 различны; id на начале и окончании каждого хода совпадает. **confirmed:** `turn.id` — source-native кандидат `run_id` в проверенном сценарии. Начало thread не означает начало работы. Хеширование идентификатора не требуется.

[`app-interrupt.jsonl`](evidence/app-interrupt.jsonl): новый turn прерван штатным `turn/interrupt`, получен `turn/completed` с `interrupted`. **confirmed** для API-отмены; это не ручной Escape и не проверка hook Interrupt.

`error(willRetry=true)` не завершил ход. **rejected:** преобразование любого notification `error` в терминальный `error` AgentRGB. Для `failed` есть локальный enum, но естественный независимый терминальный сбой не встретился: **unknown** для поведения. Искусственный опасный сбой не создавался.

Дополнительный безопасный инструментальный опыт [`app-tools.jsonl`](evidence/app-tools.jsonl) дал `item/completed(commandExecution, failed) → item/completed(commandExecution, completed) → turn/completed(completed)` внутри одного turn. **confirmed:** ошибка отдельного инструмента не означает ошибку всего запуска. Это структурированное подтверждение App Server, а не восстановление отсутствующего результата инструмента из CLI hook-журнала.

### K1. Approval с реальным ответом пользователя

[`app-approval-accept.jsonl`](evidence/app-approval-accept.jsonl):

```text
turn/started(T1)
thread/status/changed(active, waitingOnApproval)
item/started(commandExecution, inProgress)
item/commandExecution/requestApproval(threadId, turnId=T1, requestId=0)
[пользователю показан вопрос тестового клиента; пользователь разрешил]
serverRequest/resolved(threadId, requestId=0)
thread/status/changed(active, activeFlags=[])
item/completed(commandExecution, completed)
thread/status/changed(idle)
turn/completed(T1, completed)
```

**confirmed:** server request, состояние ожидания и окончание ожидания после ответа пользователя. Клиент не отвечал автоматически: решение передано только после явного ответа пользователя в этой задаче. UI принадлежит экспериментальному клиенту; это не доказательство показа штатного окна desktop или TUI. Reason, command, ответы модели, содержимое user input в журнал не попали.

### K2. Очистка pending request при отмене

[`app-approval-interrupt.jsonl`](evidence/app-approval-interrupt.jsonl):

```text
turn/started(T1)
thread/status/changed(active, waitingOnApproval)
item/commandExecution/requestApproval(T1, requestId=0)
[нет ответа пользователя; клиент достиг лимита опыта и послал turn/interrupt]
thread/status/changed(idle)
turn/completed(T1, interrupted)
serverRequest/resolved(requestId=0)
```

**confirmed:** resolved может прийти после терминального события. В этой последовательности возврат `waiting → working` был бы ложным. Таймер здесь только ограничивает время жизни теста и инициирует явную API-отмену; семантическое окончание подтверждено `turn/completed`, а не таймером. **unknown:** ручная отмена этого запроса, отказ пользователя и порядок событий в других гонках.

### I. Может ли второй клиент наблюдать чужой ему turn?

На новом изолированном loopback App Server создан тестовый thread. После первого обычного хода второй клиент вызвал `thread/resume` с `excludeTurns=true`, без overrides. Ответ содержал ноль turns. Следующий ход начал первый клиент; оба подключения получили одинаковый turn id и `completed`.

Доказательства: [`two-clients-owner.jsonl`](evidence/two-clients-owner.jsonl), [`two-clients-observer.jsonl`](evidence/two-clients-observer.jsonl).

**confirmed:** наблюдение событий другого клиента возможно внутри доступного общего App Server. **rejected:** категоричное ограничение событиями только собственного клиента.

До первого хода resume возвращал `-32600`; без успешной подписки второй клиент получал общие thread-status notifications, но не turn lifecycle. Проверены отдельные попытки с ephemeral и обычным новым thread. Причину кода ошибки не считаем установленной. В успешном опыте использован обычный тестовый thread, после опыта архивированный. Ни один существовавший до фазы пользовательский thread не читался и не возобновлялся.

Первый опыт Unix endpoint не запустился; WebSocket loopback сработал. Это выбор способа связи **тестового клиента с Codex**, не транспорта AgentRGB. Node 24 использует встроенный WebSocket, внешних библиотек нет.

**unknown:** endpoint и возможность безопасной подписки к уже работающему desktop-сеансу пользователя. Стандартный user control socket не обнаружен в проверенном расположении. Это не доказательство отсутствия другого endpoint. Подключение к отдельному новому серверу не подписывает его на все другие процессы Codex.

Операция resume не имеет установленной нами гарантии чисто пассивного наблюдения: подключённый клиент технически способен управлять ходом, а распределение approvals между несколькими клиентами не проверялось. Тест не доказал безопасное совместное владение запросами подтверждения. Нельзя назначать App Server основным путём MVP только по богатству его схемы.

## 03L. Сравнение

| Возможность | Hooks | App Server |
|---|---|---|
| Обычный пользовательский workflow | partially confirmed: CLI exec и native TUI; desktop не подтверждён | partially confirmed: два клиента общего сервера; attach к обычному desktop unknown |
| Начало активности | partially confirmed: UserPromptSubmit, без блокирующих hooks | confirmed: turn/started |
| Стабильный run/turn id | confirmed в проверенных CLI turns, инструментах и Stop-продолжении | confirmed: два последовательных turn и второй клиент |
| Реальное waiting | partially confirmed: запрос реально показан, но надёжное общее правило по hooks не доказано; профиль не допускается | confirmed для command approval в тестовом клиенте |
| Окончание waiting | unknown; профиль не допускается | confirmed: requestId/resolved с учётом терминального turn |
| Окончание активности | rejected для безусловного Stop; иной универсальной границы не доказано | confirmed: turn/completed |
| completed | rejected для безусловного Stop; универсальный профиль unknown | confirmed |
| interrupted | confirmed для ручной отмены approval и после PreToolUse; остальные сценарии unknown | confirmed: штатный API interrupt |
| error/failed | unknown; не поддерживать | unknown в опыте; enum failed подтверждён схемой |
| Не требует собственного управляющего клиента | partially confirmed для hooks CLI | partially confirmed: второй клиент может наблюдать общий сервер, но нужен доступный endpoint; обычный desktop unknown |

## 03M–N. Предложение модели, без реализации

### Hooks

- `session_id` остаётся идентификатором сеанса, `turn_id` — кандидат на `run_id`.
- `UserPromptSubmit` — кандидат начала только для проверенного профиля без отвергающих submit hooks. Обычный submit не является универсальной гарантией принятого запуска.
- `PermissionRequest` не превращается в waiting.
- `Stop` сохраняется только как наблюдение попытки остановки, без снятия активности и сигнала completed.
- `Interrupt → run_ended + interrupted` подтверждено для ручной отмены approval и после PreToolUse основного хода. Это две наблюдённые отмены, не гарантия для всех сценариев.
- Run-level error не генерируется.

**Ограничение:** такой профиль пока не имеет доказанной общей границы окончания обычной активности. Поэтому нельзя включить только working и оставлять свет до следующего SessionEnd: это создало бы зависшую активность. Полноценный Hooks-адаптер первой версии пока не готов к реализации. Исход `unknown` помогает только при уже доказанном `run_ended`; он не исправляет недостоверную границу.

### App Server

- `threadId`/source instance задают контекст; `turn.id` используется напрямую как `run_id`.
- `turn/started → run_started / working`.
- Для проверенного command approval, направленного пользовательскому клиенту: request связывает `(threadId, requestId)` с `turnId`; открытый запрос — кандидат waiting. Другие разновидности server requests не считаются ожиданием автоматически.
- `serverRequest/resolved` удаляет соответствующий pending request. `working` допустим только при достоверно активном том же turn, без оставшихся блокирующих запросов и без уже принятого окончания. Resolved не означает обязательно ответ пользователя.
- `turn/completed` всегда снимает активность; `completed` и `interrupted` задают подтверждённые исходы.
- `status=failed → error` — предложение по локальной схеме, ещё не подтверждённое живым опытом.
- Промежуточные `error`, в том числе `willRetry=true`, не дают терминального сигнала.

Вложенные запросы, разрешение одного из нескольких ожиданий, разрыв соединения, восстановление подписки, повторные события, смена turn до позднего resolved и другие гонки не проверены. Не переносить наблюдённый порядок двух примеров на все случаи.

## Ответы на 15 итоговых вопросов

| № | Ответ и статус |
|---|---|
| 1 | **partially confirmed:** UserPromptSubmit в CLI-профиле; **confirmed:** turn/started в отдельном App Server. Универсальный пассивный desktop-источник ещё unknown. |
| 2 | **confirmed** для проверенных App Server и CLI Hooks turns, включая новый turn того же session. Нативный id не хешировать. |
| 3 | **partially confirmed:** реальный native CLI approval сопровождался PermissionRequest. Надёжное общее определение waiting через Hooks остаётся **unknown**; не поддерживать. |
| 4 | **unknown:** обе границы Hooks waiting не найдены; не выводить выход из следующего инструмента или таймера. |
| 5 | **confirmed:** Stop — точка, после которой hook может продолжить тот же turn; безусловный run_ended **rejected**. |
| 6 | **confirmed** для ручной отмены approval и после PreToolUse без approval в native CLI. Все способы пользовательского прерывания и отсутствие иных инициаторов не доказаны. |
| 7 | **unknown:** надёжная универсальная граница Hooks не найдена. SessionEnd — конец сеанса, не обычного turn. |
| 8 | Безусловный completed по Stop **rejected**; общий надёжный способ через Hooks **unknown**. |
| 9 | **unknown:** универсальный структурированный терминальный error Hooks не доказан. |
| 10 | **partially confirmed:** второй клиент общего сервера получает чужие turn events; attach к существующему обычному desktop/CLI **unknown**. |
| 11 | **unknown** для привычного приложения. Запуск собственного сервера ради наблюдения меняет workflow; использовать его как обязательное условие MVP пока нельзя. |
| 12 | **confirmed:** реальные turn/started и turn/completed, completed и interrupted. |
| 13 | **confirmed:** command approval, ответ пользователя и resolved; очистка resolved после API-отмены. Для App Server не проверены native UI и deny; отдельный CLI Hooks-опыт не заменяет эту проверку. |
| 14 | **partially confirmed:** Hooks меньше затрагивают CLI workflow, но не закрывают общий жизненный цикл; App Server лучше по событиям, но ещё не доказан как пассивное дополнение обычного desktop. Окончательный выбор отложить до проверки подключения без смены привычного интерфейса. |
| 15 | Hooks: не заявлять waiting, completed и error; interrupted подтверждён для двух ручных отмен, общий lifecycle неполон. App Server в проверенном клиенте: working, approval waiting, окончание, completed, interrupted; failed/error пока только гипотеза, пассивный desktop-профиль не заявлять. |

## Предлагаемые минимальные изменения docs/, не применены

1. `INTEGRATIONS.md`: разделить Hooks и App Server; добавить подтверждённый контрпример Stop, границы waiting и результаты второго клиента. Не писать «App Server не может наблюдать чужие threads».
2. `STATES.md` и `ARCHITECTURE.md`: уточнить возможность source-native `turn.id` и сопоставления pending request с run; не фиксировать реализацию или транспорт.
3. `MVP.md`: зафиксировать неполноту Hooks lifecycle и условность App Server для обычного workflow; не обещать полный профиль Codex по таблице API.

## Проверки и оставшаяся работа

Выполнено: **9 тестов unittest — PASS**, проверка Python `compileall` и синтаксиса Node `--check` — PASS. Тесты проверяют отсутствие приватных полей, валидацию значений, молчаливую обработку ошибок, параллельный sequence, проекцию App Server, TOML аргументы, защиту Stop от цикла, опубликованные JSONL и отмену только собственных тестовых ходов при уборке. Сырые журналы проверены по allowlist перед публикацией. Локальные Markdown-ссылки проверены; машинные пользовательские пути в публикуемых файлах не найдены.

В ручной части проверены реальный native CLI approval, разрешение, отмена approval с Interrupt, Interrupt после PreToolUse без approval и три последовательных turn одного session. Остаются отдельный deny без отмены всего хода и независимое подтверждение запуска/освобождения shell-процесса при отмене. PreToolUse не доказывает фактический запуск процесса. Отдельно остаётся проверить доступный endpoint и безопасную подписку обычного desktop без перехвата approvals и без чтения истории. Необходимость этой работы не заменяется таймерами.

Основные `docs/`, README проекта, конфигурация пользователя, RGB, ядро и транспорт AgentRGB не менялись. Коммит не создавался.

## 03O — Desktop observer

**Результат: вариант C — не подтверждено.** Отдельный App Server доказан как богатый источник событий, но пассивное наблюдение обычного Codex Desktop не подтверждено. В текущей топологии не найден поддерживаемый App Server endpoint для второго клиента. Это результат проверки конкретной запущенной среды, а не утверждение о невозможности attach во всех версиях или конфигурациях.

### Область и доказательства

Проверка выполнена 2026-09-21. Перед ней `git status --short` показывал только уже созданный в этой задаче `experiments/codex-events/`; прежние результаты не перезаписывались. Использованы help установленного Codex, ранее сгенерированные этим же бинарным файлом JSON Schema и стандартные read-only средства Windows.

Воспроизводимый сборщик: [`desktop_topology.ps1`](desktop_topology.ps1). Очищенный снимок: [`desktop-topology.json`](evidence/desktop-topology.json). В нём только дерево процессов, имена разрешённых флагов/их безопасная классификация, TCP listeners и семейства имён pipes. Полные командные строки, пользовательские пути, environment, содержимое файлов и сообщения в снимок не попали. Идентификаторы в именах вспомогательных pipes заменены на `<id>`; их владельцы не установлены.

### Установленный интерфейс подключения

**confirmed по локальному help:**

| Механизм | Назначение и ограничение |
|---|---|
| `codex app-server --listen` | Поддерживает `stdio://`, `unix://`, `unix://PATH`, `ws://IP:PORT`, `off`; значение по умолчанию — `stdio://` |
| `codex app-server proxy --sock` | Проксирует stdio к существующему App Server control socket; аргумент — путь Unix domain socket, не произвольный Windows named pipe |
| `codex app-server daemon` | Имеет команды управления отдельным daemon, включая start/restart/stop/bootstrap и read-only version. Наличие команды не доказывает, что Desktop использует этот daemon |
| `codex --remote` | Подключает TUI к заданному WebSocket/Unix endpoint; не обнаруживает автоматически сервер уже работающего Desktop |
| `codex remote-control` | Управление daemon и pairing. Start/stop/pair не вызывались: они выходят за пассивную проверку |

**confirmed по локальным схемам:** `initialize` требует `clientInfo`; `InitializeCapabilities` содержит opt-out notifications, но не отдельный флаг observer/read-only. В `ClientRequest` нет отдельного `thread/subscribe` или desktop attach. `thread/resume` требует `threadId`, поддерживает `excludeTurns=true`; эта опция исключает turns из ответа, но сама по себе не гарантирует отсутствие влияния на approvals. `thread/unsubscribe` также требует `threadId`. Наличие `thread/attachment/*` относится к артефактам задачи, а не к подключению наблюдателя.

Схемы описывают протокол доступного сервера, но не создают endpoint текущего Desktop. Подтверждение второго клиента из предыдущего опыта остаётся ограниченным нашим отдельным сервером.

### Топология работающего Desktop

Снимок Windows от `2026-09-21T14:58:52Z`:

```text
ChatGPT.exe, PID 15732, product_name=Codex
└─ codex.exe, PID 16692, app-server --analytics-default-enabled
   └─ codex-code-mode-host.exe, PID 18820
```

Есть также процессы интерфейса Electron, браузера и вспомогательных инструментов. Их роли не приравниваются к App Server.

- **confirmed:** PID 16692 — прямой дочерний процесс Desktop. Версия его исполняемого файла: `codex-cli 0.155.0-alpha.9.2`; SHA-256 совпадает с бинарным файлом, использованным в предыдущих опытах: `bc45017e8239dc150258f69309ced9df6bbcdf5b8e4f346decf780ac0999e226`.
- **confirmed:** у backend обнаружен `app-server` и единственный длинный флаг `--analytics-default-enabled`. Не обнаружены `--listen`, `--stdio`, `--remote`, `--sock`, daemon/proxy или флаги WebSocket auth. Полная командная строка не сохранялась.
- **confirmed:** `Get-NetTCPConnection -State Listen` не обнаружил TCP listeners у процессов выбранного дерева Codex. Это снимок во времени, не непрерывный мониторинг.
- **confirmed:** стандартный каталог user control endpoint существует, но стандартный `app-server-control.sock` при read-only проверке вне sandbox отсутствовал. Файлы каталога и их содержимое не использовались. Отдельная попытка перечисления каталога из sandbox получила отказ доступа; этот отказ не использовался как доказательство отсутствия socket.
- **confirmed:** обычное перечисление Windows named pipes показало `codex-ipc` и семейства Codex sandbox/browser-use/computer-use. Перечисление не устанавливает владельца pipe. Локальный help не объявляет эти pipes транспортом App Server, а JSON Schema не описывает их протокол.
- **partially confirmed, вывод из help и аргументов:** запуск backend соответствует стандартному stdio-режиму. Дескрипторы процесса, память и закрытый IPC не исследовались, поэтому отсутствие дополнительных недокументированных каналов не утверждается. Подключение второго клиента к уже занятым stdio не предусмотрено найденным интерфейсом.

Значение `153.0.8010.48` в PE-метаданных процессов оболочки записано лишь как product version исполняемого файла; оно не объявляется версией релиза приложения Codex. Для протокола проверена версия именно дочернего `codex.exe`.

### Почему live-подключение не выполнялось

Не найден endpoint, одновременно связанный с текущим Desktop и предназначенный для App Server protocol. Поэтому observer не создавался, `proxy` не запускался и соединения к `codex-ipc` либо другим pipes не открывались. Новые серверы не запускались. Пользовательский turn специально не запрашивался: без observer он не дал бы нужного доказательства.

Не вызывались `thread/list`, `thread/read`, `thread/turns/list`, `thread/items/list`, `thread/resume` или любые управляющие RPC. История, transcripts, базы данных приложения, auth, cookies, память и environment процессов не читались. Полные command lines использовались только в памяти для выбора разрешённых технических аргументов; неизвестные значения, конфигурационные значения и секреты не выводились.

Approvals не создавались и не перехватывались. Observer не подключался, поэтому нельзя заявить экспериментальную проверку его невмешательства в Desktop. Есть только отсутствие каких-либо observer-действий в этом опыте. Обратная разработка `codex-ipc`, смена запуска Desktop и включение daemon/remote-control не выполнялись.

### Ответы на десять вопросов 03O

| № | Вопрос | Результат |
|---|---|---|
| 1 | Найден поддерживаемый endpoint текущего Desktop? | **unknown / не подтверждено:** такой endpoint не обнаружен; найдены backend-процесс и недоказанные как App Server pipes |
| 2 | Удалось подключиться без истории? | Нет; подключение не предпринималось из-за отсутствия подходящего endpoint. История не читалась |
| 3 | Получен threadId без thread/list? | Нет; новых live notifications нет, thread/list не вызывался |
| 4 | Получен turn/started нового desktop-turn? | **unknown:** live-опыт не выполнялся |
| 5 | Получен turn/completed того же turn? | **unknown:** live-опыт не выполнялся |
| 6 | Повлиял observer на Desktop? | Observer отсутствовал; управляющих вызовов не было. Безопасность подключённого observer остаётся **unknown** |
| 7 | Требовался thread/resume? | **unknown** для Desktop; не вызывался |
| 8 | Сработал excludeTurns=true? | **unknown** для Desktop; поддержка поля и работа на отдельном тестовом сервере не заменяют attach-опыт |
| 9 | App Server можно считать основным Codex source для MVP? | Нет, если условие — обычный Desktop без изменения workflow. Он остаётся кандидатом при отдельно доказанном доступном endpoint и невмешательстве |
| 10 | Что честно оставить вне MVP? | Не заявлять полную индикацию обычного Codex Desktop, его waiting, штатное окончание и completed/error. Hooks Interrupt полезен в проверенном CLI, но не исправляет отсутствие общей границы окончания; постоянный working на одном UserPromptSubmit не включать |

### Итог решения и проверки

Узкий опыт 03O завершён по предусмотренному **варианту C**. Возможности отдельного App Server сохранены как экспериментальный результат, а готовый пассивный источник обычного Desktop не заявляется. Hooks не объявляются полным запасным решением. По результатам фазы обновлены `docs/INTEGRATIONS.md`, `docs/MVP.md`, `docs/ARCHITECTURE.md` и `docs/STATES.md`; адаптер, RGB и транспорт не реализуются.

Проверены: версия и хеш backend, help связанных CLI-интерфейсов и remote-control, локальные схемы, read-only топология Windows и очищенность опубликованного снимка. Итоговые проверки: **9 unittest — PASS**, синтаксис PowerShell — PASS, allowlist и отсутствие пользовательских путей в снимке — PASS, локальные ссылки и контрольные суммы использованных схем — PASS. `README.md` проекта и результаты Pi не изменены. Коммит не создан.
