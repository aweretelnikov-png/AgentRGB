# Phase 05B — Pi package и автозапуск Core

Проверено 25 сентября 2026 года на Windows, Python 3.14.4, Node.js 24.15.0, Pi 0.87.1. Это проверка конкретной среды, а не обещание совместимости со всеми версиями Pi.

## Результаты

- Editable install Python-пакета успешен; `PYTHONPATH` smoke-процессам не задавался.
- `pi install ./integrations/pi` успешно добавил локальный package через штатный CLI Pi; `pi list` показывает его среди пользовательских packages. Settings вручную не редактировались, существующие packages сохранены.
- `npm pack --dry-run --json --ignore-scripts` проверил состав: `package.json`, `README.md`, `agentrgb.ts`, `core.ts`. Публикация и создание npm scope не выполнялись.
- Полный Python suite: 167/167. Полный Node suite: 35/35. `git diff --check` прошёл.
- Unit tests проверили manifest, ENOENT, startup deadline, readiness, ошибки, уведомление один раз, отмену startup, повторный shutdown и fallback termination.
- Process tests запустили настоящие Python Core с fake output. При гонке за один порт ровно один Pi controller получил ownership; shutdown проигравшего сохранил победителя. Победитель штатно завершился по EOF приватного stdin.

## Реальный Pi, без hardware

Smoke runner — `smoke.py`. Он создаёт временный Windows launcher `agentrgb`, доступный только через PATH тестового процесса. Launcher проверяет исходные аргументы `start --output aula-f75`, заменяет output на `fake` и блокирует создание `AulaF75Output` и `WindowsHid`. Производственный package не переключается на fake. Прокси передаётся только процессам теста, постоянные переменные окружения не меняются.

| Режим | Загрузка | Результат | Остановка |
|---|---|---|---|
| `once` | Pi RPC, `--no-extensions -e <package directory>` | `run_started`, `run_ended(completed)`, оба `applied` | Runner закрыл stdin Pi; Pi закрыл stdin своего Core |
| `installed` | Pi RPC, установленный package, без `-e` | Та же последовательность | Тот же штатный путь |
| `tui` | Обычный Pi TUI, установленный package, без `-e` | Безопасный run без инструментов, та же последовательность | `/quit`; Pi закрыл stdin своего Core |

Во всех трёх успешных проверках Pi завершился с кодом 0, Core вызвал `Core.close()`, процесс Core вышел, listener отсутствовал после выхода. Принудительная остановка не применялась; hardware writes — 0. Временные файлы и launcher удалены runner. В журнал попадали только тип нормализованного события, outcome/result и технические отметки lifecycle, без текстов модели и секретов.

Команды повторения из корня репозитория (с process-scoped proxy в тестовой среде):

```powershell
python experiments/phase-05b/smoke.py once
python experiments/phase-05b/smoke.py installed
python experiments/phase-05b/smoke.py tui
```

В `tui` после загрузки отправить безопасный запрос без инструментов, дождаться завершения и ввести `/quit`. Runner ограничивает этот процесс 120 секундами; RPC run — 90 секундами после подготовки. Launcher создаётся через поставляемый с pip `distlib`; это зависимость экспериментального runner, не production package.

## Ограничения и отклонения

- Первый RPC smoke в песочнице не завершился за deadline; runner завершил свой Pi. Успешные реальные проверки выполнены в пользовательском окружении с доступной авторизацией Pi.
- Первый installed RPC smoke, отправивший prompt сразу после запуска, получил только `run_ended(completed)` с `unknown_run`. Точную причину потери старта не устанавливали. Smoke теперь ждёт health перед prompt; после ожидания он прошёл. Production best-effort delivery, deadline 200 мс, отсутствие retry/ACK и существующая нормализация не менялись. Это не доказательство устранения потерь при нагрузке.
- Полноценного multi-client lifecycle нет: Pi-владелец завершает свой Core даже при наличии других клиентов. Другие Pi используют его как external и автоматически не перезапускают.
- Штатный shutdown проверен через закрытие приватного pipe. Fallback termination проверен с fake child; он не обещает graceful cleanup аппаратного output.
- В тестах использован launcher на Python 3.14.4. Для обычного запуска `agentrgb` в PATH Pi должен относиться к установке на Python 3.14+; автоматического поиска Python environments нет.
- В пользовательском PATH на момент отчёта команды `python` и `agentrgb` всё ещё относятся к Python 3.12. Editable install для Python 3.14.4 выполнен, но его `Scripts` не добавлен в постоянный PATH. Перед повседневным использованием нужно выбрать окружение Python 3.14+; постоянные настройки PATH в этой фазе не менялись.
- npm/PyPI опубликованный flow остаётся планом. Package оставлен локально установленным; коммит, push, tag и release не выполнялись.

Источники контрактов: [Pi Packages](https://pi.dev/docs/latest/packages), [Pi Extensions](https://pi.dev/docs/latest/extensions), [Pi RPC shutdown](https://pi.dev/docs/latest/rpc), [Node child_process](https://nodejs.org/api/child_process.html#subprocesskillsignal). Фактический smoke проверял установленный Pi 0.87.1.
