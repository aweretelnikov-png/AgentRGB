# D1: read-only проверка Windows HID descriptor после `WinError 87`

23 сентября 2026 года. [Обезличенная выгрузка](results/direct-d1-descriptor.json)
получена через `HidD_GetPreparsedData`, `HidP_GetCaps`,
`HidP_GetValueCaps` и `HidP_GetButtonCaps` по всем доступным top-level
collections `258A:010C`. Коллекции открывались с `access=0` только для
метаданных; чтения клавиш, `GetFeature`, `SetFeature` и других HID writes не
было. Полный Windows device path не сохранялся — только SHA-256 от его
нормализованного UTF-16LE представления. Preparsed data — разобранные Windows
capabilities, не байтовый dump исходного USB report descriptor.

| MI/COL | UsagePage/Usage | Input | Output | Feature | Value caps | Button caps | Feature IDs | Path SHA-256 |
|---|---|---:|---:|---:|---:|---:|---|---|
| 00/— | 0001/0006 | 9 | 2 | 0 | 0 | 0 | — | `8d6f24b6cf3ad77cf7ed8181070c95a106f2f51a947d929e64f00136bf04cba1` |
| 01/01 | 0001/0080 | 2 | 0 | 0 | 0 | 0 | — | `a5e530e87b02c3d3a23dfcabb011273a3ff7b46b3745bd902ae0c8a448f631b5` |
| 01/02 | 000C/0001 | 3 | 0 | 0 | 0 | 0 | — | `fd0ec9470382b1fa545f077830b4d185bef6cf57db20c529f5b7401da480f810` |
| 01/03 | FF00/0001 | 4 | 0 | 0 | 0 | 0 | — | `4ec36f370c6eddfbbd1f09043be93b4e604fa0804e9a0e11df7e200d9ae8e3ef` |
| 01/04 | 0001/0006 | 16 | 0 | 0 | 0 | 0 | — | `eb70165dad4a2bc5931cded83729ef4e5180880e47c7b2ebf1b4446bfc3839e6` |
| 01/05 | FF00/0001 | 0 | 0 | 6 | 1 | 0 | `05` | `a8b93709e094582b4b967f23630147b0d38307b3029a13df37c2934738673508` |
| 01/06 | FF00/0001 | 8 | 0 | 520 | 1 | 0 | `06` | `e2df81c42314e9761029010050cd24479f01a4fa6f85d75a0b9638026528fb66` |
| 01/07 | 0001/0002 | 8 | 0 | 0 | 0 | 0 | — | `6b81413ff0f55e4615f3b2f7125e17bdb99de7fe45aa2d0a0d1a0ba1036f87aa` |

Числа длины — байты, включая report ID. Для используемой `MI_01/COL06`
`FeatureReportByteLength=520`, value caps = 1, button caps = 0, feature IDs
только `06`. Следовательно, `0x06` direct frame объявлен именно там.
`0x39` и `0x3C` **не объявлены ни в одной** из восьми Windows collections;
иной collection и длины для них descriptor не предоставляет. Попытка D1
отправить `0x39` на `COL06` через `HidD_SetFeature` ожидаемо встретила отказ
`WinError 87`. Descriptor объясняет отказ гораздо лучше гипотезы о неверной
длине 520 на `COL06`; он сам по себе не доказывает внутренний путь Windows
ошибки и не позволяет утверждать, что другая физическая ревизия поддерживает
те же reports.

## Сопоставление с pinned F75 WebHID-кодом

Версия источника — `cloudglides/aula-f75-linux-drivers` commit
[`879f155336d1a0fa002a4a72b2e0332fb4b274cd`](https://github.com/cloudglides/aula-f75-linux-drivers/tree/879f155336d1a0fa002a4a72b2e0332fb4b274cd).
В [`useKeyboard.ts`](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/hooks/useKeyboard.ts)
picker фильтрует wired `258A:010C` по vendor usage pages `FF00..FF04` либо
только по VID/PID, затем перечисляет `device.collections` и предупреждает,
если среди feature reports нет `06`. Конкретный COL номер исходник не
фиксирует; журнал его реальной Linux/F75 enumeration в pinned коде не задан.
Реальные collections его экземпляра из исходного текста не восстановить.

В [`direct-mode.ts`](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/lib/direct-mode.ts)
`isDirectModeCapable()` проверяет только `06`. Три enable-вызова
`sendFeatureReport(39/3C/39, 519-byte body)` направлены в выбранный
`HIDDevice`, но **каждая ошибка ловится и игнорируется** с комментарием,
что некоторые версии прошивки не нуждаются в enable. Отдельного выбора
collection для `39/3C` в этом коде нет. `sendDirectFrame()` отправляет
`sendFeatureReport(06, frame)` после этой best-effort последовательности.
Таким образом, заявленная в [PROTOCOL.md](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/docs/PROTOCOL.md)
live-проверка потока `0x08` не является свидетельством успешного приёма
трёх enable reports; source допускает работающий `0x08` при их отказе.
WebHID `sendFeatureReport(reportId, body)` не обходит report IDs,
объявленные HID descriptor для доступного `HIDDevice`.

## Решение и следующий шаг

Для нашей Windows F75 результат соответствует варианту **C**: Direct Mode
enable из F75-specific Linux/WebHID исследования не представлен доступными
feature report IDs. Не отправлять `39/3C` через `HidD_SetFeature` повторно и
не подбирать другую длину или collection. D1 остаётся неподтверждённым;
production backend не менялся.

Минимальный следующий шаг без hardware writes — read-only WebHID enumeration
`device.collections` на этой же Windows клавиатуре с фиксацией только
usage page/usage, report IDs и длин без отправки feature reports. Это
проверит, видит ли WebHID те же `05/06` и отсутствие `39/3C`. После такого
сопоставления отдельно решать, обоснован ли новый строго ограниченный тест
одного `0x06` direct frame без enable; сейчас он не разрешён и не запускался.

Тесты: 112 Python (`PYTHONPATH=src`) и 10 Node прошли. Изменяющих HID-команд
AgentRGB в этом исследовании — **0**. Коммита нет.
