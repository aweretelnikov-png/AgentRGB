# Direct Mode `0x08`: офлайн-исследование и последующая проверка descriptor

23 сентября 2026 года. Это исследование не меняет production `AulaF75Output` и
не отправляет изменяющих HID-команд. Исходная переливающаяся подсветка вернулась после
POWER; [DARK-before и POWER-after](POWER-RESULTS.md) побайтно равны по всем
трём полным `0x82/0x84/0x8A`, хотя до отключения свет был выключен, а после
включения работал. Это сильное свидетельство скрытого runtime-состояния, но
конкретный механизм пока неизвестен.

**Позднейший результат:** отдельно разрешённый [физический D1](D1-RESULTS.md)
остановился на первом `0x39` (`WinError 87`, 0 успешных writes). Последующая
[read-only проверка Windows descriptor](D1-DESCRIPTOR-RESULTS.md) нашла
feature IDs `05` на `COL05` и `06` на `COL06`, но не `39/3C` ни в одной
collection. План D1 ниже сохранён как исходный исторический план, не как
разрешение на повтор.

Ещё позже [физический D2](D2-RESULTS.md) подтвердил работающий volatile
`0x06/0x08` без `39/3C` и самостоятельный возврат исходной статичной
разноцветной подсветки после прекращения 40 кадров. Production adapter пока
не менялся.

## Источники и граница применимости

Исследованы зафиксированные версии:

- [OpenRGB `SinowealthKeyboard10cController.cpp`](https://github.com/CalcProgrammer1/OpenRGB/blob/6838d9d9c06b07b9590b14178bcec2cb31b9396f/Controllers/SinowealthController/SinowealthKeyboard10cController/SinowealthKeyboard10cController.cpp), [RGB controller](https://github.com/CalcProgrammer1/OpenRGB/blob/6838d9d9c06b07b9590b14178bcec2cb31b9396f/Controllers/SinowealthController/SinowealthKeyboard10cController/RGBController_SinowealthKeyboard10c.cpp), [detector](https://github.com/CalcProgrammer1/OpenRGB/blob/6838d9d9c06b07b9590b14178bcec2cb31b9396f/Controllers/SinowealthController/SinowealthControllerDetect.cpp) и [таблица моделей](https://github.com/CalcProgrammer1/OpenRGB/blob/6838d9d9c06b07b9590b14178bcec2cb31b9396f/Controllers/SinowealthController/SinowealthKeyboard10cController/SinowealthKeyboard10cDevices.cpp).
- [MR OpenRGB !3062](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3062): автор явно назвал поддержку F75 ещё **не испытанной на F75** в описании MR. Код есть в текущем master, но само описание MR не доказывает аппаратный результат на F75. [Поздний MR !3412](https://gitlab.com/CalcProgrammer1/OpenRGB/-/merge_requests/3412) подтверждает direct-color на реальной F99; у разных F99 менялся байт model ID.
- Независимый [aula-rgb-controller README](https://github.com/veysiemrah/aula-rgb-controller/tree/c9d447f9e48f6fcc157bc47bbfbbc92fd7eeb77e) и [protocol_notes.md](https://github.com/veysiemrah/aula-rgb-controller/blob/c9d447f9e48f6fcc157bc47bbfbbc92fd7eeb77e/tools/protocol_notes.md): испытана F87 TK, F75 обозначена как возможная, но не проверенная. [Реализация](https://github.com/veysiemrah/aula-rgb-controller/blob/c9d447f9e48f6fcc157bc47bbfbbc92fd7eeb77e/lib/src/protocol.c) использует отдельный enable и при disable читает и **записывает config**. Её указание «~1 секунды» не является замером на нашей F75.
- **Актуальный на 23 сентября 2026 commit F75-проекта — `879f155336d1a0fa002a4a72b2e0332fb4b274cd`** (проверен по GitHub API перед работой). Его [протокольный отчёт](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/docs/PROTOCOL.md) прямо помечает wired Direct Mode как проверенный в live-сеансах на F75. [Фактический `direct-mode.ts`](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/lib/direct-mode.ts) совпадает с описанием по IDs, телам, кадру и порядку; [wired `f75.ts`](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/lib/f75.ts) использует ту же семантику полного 520-byte буфера и `frame.slice(1)` для WebHID, но direct-команд сам не формирует. Источник не доказывает совпадения его F75 с нашим `model=03, PSD=00CD, MI_01/COL06`; в комментарии `direct-mode.ts` сохранилось название F87.

После D1 уточнён уровень доказательств: pinned `direct-mode.ts` подавляет
ошибки каждого `39/3C/39` enable report как non-fatal. Поэтому live-метка
для потока `0x08` в `PROTOCOL.md` не подтверждает успешный приём enable
reports. Подробнее — [результат descriptor](D1-DESCRIPTOR-RESULTS.md).

## Wired frame `0x08`

OpenRGB и F75-проект совпадают в формате кадра. Номера ниже относятся к полному
буферу HID `SET_FEATURE` (не к 519-байтному WebHID body):

| Диапазон | Значение | Основание |
|---|---|---|
| `[0]` | `06`, report ID | оба исходника; feature report, не interrupt output |
| `[1]` | `08`, direct RGB command | оба исходника |
| `[2..3]` | `00 00` | нулевая инициализация буфера в OpenRGB |
| `[4]` | `01`, zone | оба исходника |
| `[5]` | `00` | нулевая инициализация |
| `[6]` | `7A` = 122 | оба исходника и F75-проект |
| `[7]` | `01` | оба исходника |
| `[8..373]` | 122 тройки `R G B` по LED index `0..121` | оба исходника; **interleaved**, не planar |
| `[374..519]` | `00` | нулевой хвост в OpenRGB; прямой кадр не содержит видимого trailer/checksum |

Размер — 520 байт; USB HID feature `SET_REPORT` имеет report type `03`, report
ID `06` (`wValue=0306`). На Windows HID API отправляется весь буфер, включая
`[0]=06`; WebHID передаёт 519 байт body без report ID. Команда `0x08` не
содержит `5A A5` в `[0x202..0x203]`: этот trailer относится к другому,
сохраняемому `0x0A` profile. Отсутствие trailer/checksum следует из двух
реализаций, но нами физически не проверялось.

### F75-specific enable/disable и фактические длины

В pinned `direct-mode.ts` функция `sendSmallFeatureReport` для **каждого**
шага создаёт `ArrayBuffer(REPORT_SIZE - 1)` = **519-byte body**, записывает
указанный префикс в начало, оставляет остальные байты нулевыми и вызывает
`sendFeatureReport(reportId, body)`. Поэтому представление с явным report ID
занимает **520 байт** и для `0x39`, и для `0x3C`. Документ называет эти отчёты
«small» по длине содержательного префикса, а не по длине передаваемого body;
расхождения с кодом нет. `f75.ts` для обычных wired-команд также передаёт
519-byte body, полученное от 520-byte frame через `slice(1)`.

| Шаг | Report ID `[0]` | Начало body `[1..]` | Остальная часть body | SHA-256 полного 520-byte представления |
|---|---|---|---|---|
| enable 1 | `39` | `20 06 00 01 00` (5 байт) | 514 нулей | `79d8c18b7b9d83afaf7558debd34577ddaba6c7dc7837dbefe0fd92133a4b0cc` |
| enable 2 | `3C` | `20 01 00` (3 байта) | 516 нулей | `b79cc74d5fab179b04e487141c833eff1b50467dce23c9524b4cc5aff88be4fc` |
| enable 3 | `39` | `20 06 01 01 00` (5 байт) | 514 нулей | `7af3eb79e6e5996865b4078f8a7be888f7a0ea814ff99741593dbb729116119c` |
| direct blue | `06` | `08 00 00 01 00 7A 01`, затем 122 × `00 00 FF` | `[374..519]` — 146 нулей | `5446889ac334b8ad6722428f2fb583cc1a178709808679101e23c674a8cd5b54` |
| disable, **не D1** | `3C` | `20 00 00` (3 байта) | 516 нулей | `7c3174d0c5da7ac5020325ca32203a5a27f90a5fc3f050a7205a3fed3f788336` |

У direct blue в полном frame `[8..373]` — RGB triples; в WebHID body без
ID это `[7..372]`. Специальные байты `[6]=7A`, `[7]=01` — direct count и
параметр direct frame, а не адрес/длина обычного `0x84` из `f75.ts`.

**122 против 126.** `0x7A=122` — объявленный count **direct `0x08`**;
`126` — длина каждого цветового канала **planar `0x06`** в отдельной таблице
per-key, в том числе в ранее сохранённом [F75Report.cs](research/upstream/src/Aula.Core/Protocol/F75Report.cs).
Это разные команды и структуры, а не два равноправных значения count для
`0x08`. Таблица OpenRGB для F75 индексирует физические клавиши до `89`, для
F99 — дальше; многие позиции буфера зарезервированы/не назначены клавишам.
Побайтовая карта клавиш нашей ревизии F75 не проверена. Для **одноцветного**
кандидата прототип заполняет все 122 заявленные позиции одним RGB, так что
перестановка индексов не влияет на цвет клавиш, а хвост `[374..519]` остаётся
нулевым. Это не доказывает поведение side lights.

## Detection, enter, update, stop

OpenRGB регистрирует `258A:010C` на interface 1, usage page `FF00`, usage 1;
detector выполняет `0x82`, берёт `response[13]` и допускает только известный
model-map (`CD` → F75, `A4` → F99 и т. д.). Наш `PSD=00CD` согласуется с
map-key `CD`; `model=03` находится в **другом** байте `[8]`, поэтому OpenRGB
его не использует как тот же идентификатор. В текущем detector есть
независимый вопрос качества кода: 7-байтный `command` передаётся как 520
байт; MR !3412 предлагает исправление. Это не основание ослабить identity
gate AgentRGB.

У OpenRGB перед первым кадром нет отдельного config/enter write: конструктор
выбирает `MODE_DIRECT`, `DeviceUpdateLEDs` отправляет ровно один `0x08`
`hid_send_feature_report`, а поток при простое повторяет update примерно
каждые 1–1,5 секунды (проверка `>1s`, цикл сна 500 ms). `DeviceUpdateMode`
пустой; деструктор останавливает поток и закрывает HID. В самом OpenRGB нет
`0x04`, `0x0A`, explicit disable или restore в этом пути. Это описание кода,
не измеренный timeout F75. Keepalive OpenRGB доказывает ожидание отката без
кадров, но не точный срок.

F87 TK проект, напротив, перед кадром посылает report IDs `39 → 3C → 39`
(`3C` — enable), а disable выполняет `0x84` read **и `0x04` config write**.
F75-проект также вызывает `39 → 3C → 39`, после прекращения кадров его
[UI-код](https://github.com/cloudglides/aula-f75-linux-drivers/blob/879f155336d1a0fa002a4a72b2e0332fb4b274cd/web/src/components/AnimationsPanel.tsx)
посылает **blank `0x08` frame, затем `3C` disable**. Он сообщает, что непрерывные ~20 fps удерживают direct, а
одиночный кадр и даже интервалы 400 ms приводят к возврату firmware effect.
Точное время возврата **без disable** на нашей F75 не установлено. `39/3C`
имеют отдельные HID report IDs; их нельзя тихо включать в счёт `0x08`.

Таким образом, кандидат lifecycle для AgentRGB — `open → enable 39/3C/39 →
0x08 heartbeat → stop frames → close → hardware timeout`. Рабочий короткий
интервал **50 ms** берётся из F75-кода (~20 fps); бесконечный worker для D1
не нужен. F75-источник сообщает о firmware fallback при прекращении кадров,
но его UI при штатном stop делает ещё blank+disable, поэтому **возврат без
disable на нашем экземпляре остаётся целью D1**, а не готовой гарантией.
Полная volatile-семантика и отсутствие внутренних flash-записей от
`0x08/39/3C` на нашей F75 источниками не доказаны.

## Офлайн-прототип и условный D1

[direct_mode_proto.py](direct_mode_proto.py) строит новые immutable 520-byte
буферы для всех пяти типов отчётов из таблицы без импортов HID, обнаружения
или пути отправки. Для blue:

```text
[00..07] 06 08 00 00 01 00 7A 01
[08..373] (00 00 FF) × 122
[374..519] 00 × 146
```

SHA-256 этого полного blue-кандидата: `5446889ac334b8ad6722428f2fb583cc1a178709808679101e23c674a8cd5b54`.

[Тесты](../../tests/test_direct_mode_proto.py) проверяют три enable-отчёта,
каждый body и нулевой padding, direct header/count/все 122 RGB-позиции,
отдельный disable, свежесть кадров, отсутствие `0x04/0x0A` и отсутствие
отправки при построении; единственный тестовый приёмник — FakeHid.
Это подтверждает соответствие **публичному формату**, не совместимость с
нашим устройством.

Условный будущий D1: один fresh read-only identity/baseline `0x82/84/8A` с
прежним строгим gate → enable `39/3C/39` → **ровно 40** direct blue frames
`06/08` с интервалом **50 ms** (20 fps, около 2 секунд видимого blue) →
прекратить frames → **без blank/disable/restore** ждать firmware timeout →
визуально проверить исходный переливающийся профиль → read-only
`0x82/84/8A`, сравнить полные raw с baseline. Предупредить наблюдателя до
начала фиксированного burst: ввод пользователя не продлевает N и не запускает
новые frames. После последнего frame никаких изменяющих команд нет.
Pinned WebHID-код ждёт 5 ms после каждого enable; ограниченный план D1
сохраняет этот интервал.

[Отдельный D1 runner](direct_d1_runner.py) подготовлен **без CLI и без
автозапуска**. Он принимает только явно переданный backend, сверяет fresh
`0x82/0x84/0x8A` с полным POWER baseline до первой изменяющей команды,
сохраняет raw до валидации, затем итерирует заранее построенные 43 отчёта.
После финального кадра runner закрывает handle: он не отправляет disable,
restore или retry. До физического запуска runner испытали с FakeHid. При
разрешённом запуске он остановился уже на первом enable; до финального кадра
и последующего read-only снимка дело не дошло.

Заранее фиксированный write budget D1 — **3 enable + 40 direct = 43**
`SET_FEATURE`. `disable=0`, `0x04=0`, `0x0A=0`; повторов и бесконечного
таймера нет. Если любой enable report даёт ошибку, следующие experimental
reports не отправлять, закрыть handle. Если blue не появился, прекратить
frames и ждать отката без новых команд. Если после stop профиль не вернулся,
не отправлять disable автоматически; остановиться. Ранее подтверждённый
физический power cycle остаётся внешним ручным восстановлением.

Успех D1 требует одновременно: визуально синюю клавиатуру во время burst,
неизменные persistent `0x84/0x8A`, самостоятельный возврат исходной
переливающейся подсветки без disable и без power cycle, и полное совпадение
`0x84/0x8A` с baseline после возврата. Промежуточное чтение во время синего
пока не предусмотрено: отсутствие persistent-изменений оценивается по
финальному сравнению полных raw с baseline. Этот критерий не проверен из-за
остановки на первом enable.

### Fresh read-only baseline перед запросом разрешения

[Снимок 2026-09-23 12:18:51 UTC](results/direct-d1-prep-20260923T121851596701Z/summary.json)
получен тремя и только тремя циклами `SET_FEATURE read-request → GET_FEATURE`;
ReadOnlyHid запрещал любые другие reports. `258A:010C`, `MI_01/COL06`,
`FF00/0001`, 520 байт, report ID `06`, model `[8]=03`, PSD `[12..13]=00CD`,
config `[66..67]=09 37`, primary RGB `FF0000`. Handle закрыт. Все полные
520-byte ответы **побайтно совпадают с POWER-after**:

| Ответ | SHA-256 |
|---|---|
| `0x82` | `40d4fc0f4a1091627643a59dfbfd42eab89749b55c6ea15031e04a8703196523` |
| `0x84` | `5a90dd25a6dd82b2d639193ba2e03d9e3d98ae909dad32531ae0a1924cd413e0` |
| `0x8A` | `93f7fa0a46dc0c58f6bb5a117da5bd146a0933a598d48361c8425a0b51f286b5` |

Текущее визуальное состояние при этом отдельном чтении не спрашивалось;
последнее подтверждение исходной переливающейся подсветки — опыт POWER.
Непосредственно перед будущей физической записью runner повторит fresh
identity/baseline и остановится с **0 изменяющих writes** при любом отличии.

## Persistent protocol и OEM apply

[Production H2](PRODUCTION-H2-RESULTS.md): `04 acquire → 0A blue → 0A yellow
→ 0A blue → 0A green → 0A RGB restore → 04 config restore`. Все четыре
цвета подтверждены визуально и read-back; финальные `84/8A` равны baseline,
но визуально стало темно. [POWER](POWER-RESULTS.md) вернул исходный профиль
без записи, при тех же raw. Значит читаемое восстановление недостаточно для
release и persistent backend нельзя считать безопасным для обычного цикла.

В захвате OEM для **F87 TK**, описанном в `aula-rgb-controller`, изменение
цвета сопровождалось `color write → 84 request → GET config → 04 write-back`.
H2 отправлял несколько `0x0A` подряд, без `0x04` после каждого. Отсутствующий
apply/latch правдоподобно мог объяснить DARK, но это **гипотеза**, поскольку
захват не с нашей F75, C1B с одним переходом восстановился, а скрытый state
не читается. Предлагать такой 4-шаговый путь для production нельзя: каждый
`0x04` потенциально пишет persistent область, ресурс неизвестен. Не
добавлять повторные `0x04`, задержки, retry или другие восстановительные
команды без нового доказательства.

F75-specific pinned источник подтверждает 3-step enable, формат кадра и
короткий heartbeat. Однако firmware timeout без explicit disable ещё не
проверен на нашей клавиатуре: именно это должен определить ограниченный D1.
Разрешение на его физический запуск запрашивается отдельно после свежего
read-only baseline и регрессионных проверок. H3/H4, Pi, 04C и изменения
production adapter закрыты. Изменяющих HID-команд в этом этапе — **0**;
коммита нет. Fake-only тесты прототипа и runner — **9**, полный Python suite —
**106**, Node suite — **10**; все прошли.
