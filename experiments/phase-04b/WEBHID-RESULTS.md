# F75: read-only Chromium WebHID collections на Windows

Позднейший отдельно разрешённый [D2](D2-RESULTS.md) физически подтвердил
`0x06/0x08` без `39/3C`. Предложение D2 ниже сохранено как исторический
план, а не разрешение на повтор.

23 сентября 2026 года пользователь вручную выбрал AULA F75 в системном
WebHID permission dialog Chrome `153.0.8010.53` на том же Windows-компьютере. Минимальная
[страница](webhid-diagnostic/index.html) вызвала только
`navigator.hid.requestDevice({filters:[{vendorId:0x258A,productId:0x010C}]})`
и рекурсивно прочитала `device.collections`. `device.open()` не вызывался;
`sendFeatureReport`, `receiveFeatureReport`, `sendReport` и другие HID report
API отсутствуют. Обезличенный [JSON](results/webhid-metadata-20260923T145846737059Z.json)
сохранён через временный loopback-сервер, который после получения остановлен.
Серийный номер, Windows device path и другие идентификаторы не сохранялись.
`productName="Gaming Keyboard"` записан как запрошенная metadata, но не
используется как доказательство identity. Исходное визуальное состояние:
`исходная статичная разноцветная подсветка`.

## Полное дерево, возвращённое Chrome

`vendorId=0x258A`, `productId=0x010C`; Chrome вернул четыре top-level
collections. У каждой `children=[]`; рекурсивный обход выполнен.

```text
HIDDevice 258A:010C, productName="Gaming Keyboard"
├─ collection 0: usagePage=000C usage=0001
│  inputReports=[02], outputReports=[], featureReports=[], children=[]
├─ collection 1: usagePage=FF00 usage=0001
│  inputReports=[03], outputReports=[], featureReports=[], children=[]
├─ collection 2: usagePage=FF00 usage=0001
│  inputReports=[], outputReports=[], featureReports=[05], children=[]
└─ collection 3: usagePage=FF00 usage=0001
   inputReports=[06], outputReports=[], featureReports=[06], children=[]
```

Chrome показал не все восемь Windows top-level collections: в выбранном
`HIDDevice` нет MI_00 keyboard и части MI_01 collections с другими usages.
По совпадению usages и feature IDs четыре показанные записи совместимы с
Windows `MI_01/COL02`, `COL03`, `COL05`, `COL06`; WebHID metadata не содержит
Windows MI/COL или path, поэтому это сопоставление, а не побайтная identity
каждой collection. Windows inventory: [D1 descriptor](D1-DESCRIPTOR-RESULTS.md).

| Feature report ID | Windows HIDP | Chromium WebHID |
|---|---|---|
| `05` | `MI_01/COL05`, feature length 6 | есть, top-level collection 2 (`FF00/0001`) |
| `06` | `MI_01/COL06`, feature length 520 | есть, top-level collection 3 (`FF00/0001`) |
| `39` | отсутствует во всех 8 | отсутствует во всём рекурсивном дереве |
| `3C` | отсутствует во всех 8 | отсутствует во всём рекурсивном дереве |

Таким образом, для этой F75 Chromium WebHID на Windows не предоставляет
`0x39/0x3C` как feature reports. Результат **A** подтверждён без HID writes.

## Upstream F75 и текущий Chromium

Зафиксированный F75 источник:
[`cloudglides/aula-f75-linux-drivers` commit `879f155336d1a0fa002a4a72b2e0332fb4b274cd`](https://github.com/cloudglides/aula-f75-linux-drivers/tree/879f155336d1a0fa002a4a72b2e0332fb4b274cd).
В его [`direct-mode.ts`](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/lib/direct-mode.ts)
каждый вызов `sendFeatureReport(39/3C/39, body)` обёрнут в `try/catch`,
который подавляет исключение. После этого код без проверки успеха enable
продолжает к `sendDirectFrame()`, вызывающему `sendFeatureReport(06, frame)`;
`isDirectModeCapable()` ищет только report `06`. Поэтому подтверждается
**механизм подавления enable errors в исходном коде**, но не факт, что в его
конкретных live-сеансах ошибки действительно были. Обоснованная гипотеза:
опубликованная Windows/WebHID работа Direct Mode могла фактически
использовать только `0x06/0x08`, а enable sequence на Windows могла быть
no-op с подавленными ошибками. На нашей клавиатуре это ещё не проверено.

Текущий на дату проверки Chromium `main` зафиксирован commit
[`a1845e1214f085bcc5bc29c3bef9fa841868736b`](https://chromium.googlesource.com/chromium/src/+/a1845e1214f085bcc5bc29c3bef9fa841868736b).
Это анализ актуального исходника, а не побайтная аттестация установленного
Chrome binary; наблюдённые collections согласуются с ним.
Его Windows [HID service](https://chromium.googlesource.com/chromium/src/+/a1845e1214f085bcc5bc29c3bef9fa841868736b/services/device/hid/hid_service_win.cc)
создаёт `input_reports`, `output_reports`, `feature_reports` для каждой
top-level collection из `HidP_Input/Output/Feature` report items Windows
preparsed data. [`hid_preparsed_data.cc`](https://chromium.googlesource.com/chromium/src/+/a1845e1214f085bcc5bc29c3bef9fa841868736b/services/device/hid/hid_preparsed_data.cc)
получает её через `HidD_GetPreparsedData`, проверяет `HidP_GetCaps` и затем
извлекает report IDs из элементов **непосредственно в opaque preparsed
buffer**. Этот текущий код *не вызывает* `HidP_GetValueCaps` для построения
WebHID feature IDs. Это уточнение к первоначальному предположению задания:
источник данных тот же Windows preparsed descriptor, но метод разбора другой.
Ни этот код, ни наблюдённый WebHID результат не указывают на обход
ограничений descriptor.

Windows [`HidConnectionWin`](https://chromium.googlesource.com/chromium/src/+/a1845e1214f085bcc5bc29c3bef9fa841868736b/services/device/hid/hid_connection_win.cc)
для `PlatformSendFeatureReport` берёт `report_id` из первого байта буфера,
вызывает `GetHandleForReportId(report_id)` и лишь при найденном handle
исполняет `DeviceIoControl(IOCTL_HID_SET_FEATURE)`. Метод выбора handle
ищет ID в `file_handles_` и возвращает null, если его нет. Это подтверждает
выбор Windows handle по report ID; WebHID не даёт основания считать
`39/3C` доступными при их отсутствии в коллекциях.

## Отдельное предложение D2 — только проект, без запуска

Цель D2: проверить `0x06` / command `0x08` без enable sequence, чтобы
отделить Direct frame от отсутствующих `39/3C`. Перед первой записью — один
fresh read-only identity/baseline `0x82/0x84/0x8A` со строгим прежним gate
и сравнением полных raw; любое расхождение означает 0 writes. При успехе
заранее ограниченный burst **40 одинаковых синих `0x06/0x08` frames** с
интервалом 50 мс: максимум 40 изменяющих записей, `39/3C/04/0A=0`, без
retry, disable и persistent restore. Пользователь наблюдает синий во время
burst; после последнего frame никакие writes не выполняются, проверяется
самостоятельный возврат `исходная статичная разноцветная подсветка`, затем
только read-only `0x82/0x84/0x8A` для сравнения с baseline. При ошибке
кадра или отсутствии видимого синего burst прекращается; при отсутствии
самостоятельного возврата остановка без программного восстановления.
Физический D2 требует отдельного разрешения и здесь не выполнялся.

Проверки: fake/offline тесты страницы и loopback collector; 114 Python и
12 Node regression tests прошли. Число изменяющих HID-команд AgentRGB в этом
исследовании — **0**. Production adapter не менялся; D1 остаётся
заблокированным; H3/H4, Pi и 04C не запускались. Коммита нет.
