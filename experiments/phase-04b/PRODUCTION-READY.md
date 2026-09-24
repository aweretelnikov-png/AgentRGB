# 04B: production adapter подготовлен к отдельному H2

23 сентября 2026 года. Подтверждённый C1B переход перенесён в существующий
`AulaF75Output`. [Diff относительно прежнего RGB-only adapter](PRODUCTION-ADAPTER.diff).
Только fake HID использовался для проверки production-переходов; физический
production H2, H3 и H4 не запускались.

`acquire` проверяет `258A:010C`, `MI_01/COL06`, usage `FF00/0001`, feature 520,
report ID `06`, model `03`, PSD `00CD`. Он читает свежие `0x84`/`0x8A`, сохраняет
полный snapshot в памяти и не меняет unsupported baseline. Для проверенного
config `[66]=09`, `[67]=37`, `[17]=00`, `[18]=01` он пишет один `0x04`, меняя
только `[67] 37→30`, и проверяет 128-byte payload через `0x84`.

`render` пишет `0x0A` только при изменившемся RGB. Для диагностики оставлен
один `0x8A` read-back после каждого color write. `release` возвращает исходный
RGB, если он отличается, затем полный config snapshot; проверяет читаемые
`0x84`/`0x8A`, очищает snapshot и закрывает handle. Ошибки после config и
color ведут к одной best-effort цепочке восстановления без retry.

| Ожидаемый production H2 | Изменяющая команда | Цвет |
|---|---|---|
| acquire | `0x04` | `[67] 37→30` |
| working | `0x0A` | `0000FF` |
| waiting | `0x0A` | `FFFF00` |
| working | `0x0A` | `0000FF` |
| completed | `0x0A` | `00FF00` |
| release | `0x0A` | исходный `FF0000` при сохранённом baseline |
| release | `0x04` | полный исходный config |

При исходном RGB `FF0000` верхний бюджет H2 — **7 изменяющих команд**.
Дублирующие состояния и повторный release не добавляют write. Никакого
heartbeat write и `0x04` при переходах между состояниями нет.

Проверки: **92 Python-теста** и **10 Node-тестов** прошли. Fake-HID тесты
покрывают fresh snapshot, каждый RGB, дедупликацию, точный config report,
unsupported baseline, ошибки read-back и SetFeature, обе цепочки restore,
idempotent release, Core shutdown и сохранение работы Core при отказе output.
Default CLI остаётся `fake`; реальный выход включается только явным
`--output aula-f75`. Pi adapter, нормализованный протокол и Core не менялись.

После тестов выполнен [свежий read-only осмотр](results/inspect-20260923T105159470653Z/summary.json):
`258A:010C`, `MI_01/COL06`, usage `FF00/0001`, feature 520, report ID `06`,
model `03`, PSD `00CD`, config `[66..67]=09 37`, RGB `FF 00 00`.
Полные raw `0x82`/`0x84`/`0x8A` совпали с прежним восстановленным baseline.
Осмотр сделал **0 изменяющих команд**, handle закрыт. Перед будущим H2
нужен ещё один fresh gate непосредственно перед первой записью.

Старый `run.py` теперь выполняет только read-only `inspect`: его прежние H1–H4
и D1 относились к RGB-only adapter и прежним лимитам. Сценарии H2/H3/H4
не перенесены автоматически. Ресурс потенциальных внутренних flash-записей
неизвестен; длительный частый workload не проверен. Коммита нет.

После отдельного разрешения production H2 был проведён: четыре состояния
подтверждены визуально и read-back, но исходная подсветка после release
осталась выключенной при побайтно восстановленных `0x84`/`0x8A`.
[Результаты и остановка](PRODUCTION-H2-RESULTS.md).
