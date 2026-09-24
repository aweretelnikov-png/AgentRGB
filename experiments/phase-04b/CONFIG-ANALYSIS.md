# Офлайн-анализ config после H2

## Итог ручной проверки M1–M3

**Опыт завершён, baseline восстановлен.** Изменяющих HID-команд AgentRGB: **0**.
После восьмого Fn+Tab полные 520-байтные ответы `0x84` и `0x8A` побайтно
совпали с baseline. Пользователь подтвердил исходную визуальную подсветку.
Это доказательство возврата наблюдаемых блоков и внешнего вида, не всего
неизвестного аппаратного профиля. Factory reset не использовался.

[Baseline](results/manual-20260922T110723866453Z/baseline/summary.json),
[все raw diffs и SHA-256](results/manual-20260922T110723866453Z/experiment-summary.json),
[финальный снимок](results/manual-20260922T110723866453Z/M3-8/summary.json).
В каталогах каждого этапа сохранены полные `.bin` и `.hex` ответы, config
payload отдельно, диагностические raw до валидации, API-результат и время.
Все 23 ответа сверены с SHA-256 и hex-представлением офлайн.

Свежая идентификация: `258A:010C`, `MI_01/COL06`, usage `FF00/0001`, feature
520, report `06`, model `03`, PSD `00CD`. Baseline primary RGB `FF0000`.
Исходные конкурирующие толкования были зафиксированы до ручных действий:

| Толкование | Effect | Custom | Brightness | Верхний nibble / speed по коду | Flags |
|---|---:|---:|---:|---:|---:|
| От начала report | 1 | 0 | 9 | 3 | 7 |
| От начала payload | 1 | 0 | 8 | 3 | 7 |

### Побайтные результаты

В таблице «было → стало» сравнивает последовательные снимки. Полные diff
от baseline и от предыдущего чтения находятся в JSON выше. Индексы десятичные.

| Действие пользователя | Изменённый report byte | Payload offset | Было | Стало | Интерпретация |
|---|---:|---:|---|---|---|
| M1: Fn+↓, один раз | 66 | 58 | `09` | `08` | Brightness; пользователь увидел уменьшение |
| Restore M1: Fn+↑ | 66 | 58 | `08` | `09` | Полный config вернулся к baseline |
| M2: Fn+← | — | — | — | — | Ни одного изменения config |
| Restore M2: Fn+→ | — | — | — | — | Ни одного изменения; полный baseline |
| M3-1: Fn+Tab | 67 | 59 | `37` | `30` | Одноцветный красный, верхний nibble сохранён |
| M3-2: Fn+Tab | 67 | 59 | `30` | `31` | По наблюдению пользователя не горит |
| M3-3: Fn+Tab | 67 | 59 | `31` | `32` | Не горит; при Fn одна клавиша светилась белым |
| M3-4: Fn+Tab | 67 | 59 | `32` | `33` | Не горит |
| M3-5: Fn+Tab | 67 | 59 | `33` | `34` | Не горит |
| M3-6: Fn+Tab | 67 | 59 | `34` | `35` | Не горит |
| M3-7: Fn+Tab | 67 | 59 | `35` | `36` | Не горит |
| M3-8: Fn+Tab | 67 | 59 | `36` | `37` | Исходная подсветка восстановилась |

После каждого Fn+Tab весь color response оставался равен baseline:
primary `[29..31]=FF 00 00`, изменений других bytes тоже нет. В config
на всех восьми шагах менялся только report[67]. Effect/custom/brightness
не менялись. Гипотеза пользователя о реактивном режиме на M3-3 не подтверждена:
белое свечение на Fn само по себе не устанавливает семантику режима.

### Ответы на вопросы о реальной F75

1. **ModelConfig.cs прав в системе координат проверенных полей:** brightness
   report[66] и color flags report[67]. Остальные offsets и все эффекты этим
   опытом не проверены; само назначение effect/custom bytes не меняли.
2. **PROTOCOL.md неверно называет эти offsets payload offsets.** Для
   проверенной пары надо вычесть 8: payload[58], payload[59]. Позиции
   payload[66]/[67] в M1/M3 не менялись.
3. Brightness при текущем effect=1 находится в report[66], payload[58].
   Исходное значение — **9**, а не 8.
4. Байтом выбора цвета является report[67], payload[59]. Формат
   `(speed << 4) | flags` поддержан источниками, но **назначение верхнего
   nibble как скорости M2 не подтвердил**: Fn+←/→ ничего не изменили.
5. Штатный Fn+Tab меняет младший nibble `7→0`, остальные config bytes
   сохраняет. В этом состоянии пользователь видит один красный цвет.
6. Фактически произошло **`37→30`**, не `37→00`. Для MVP следуем наблюдению
   конкретной F75, а не обнулению всего байта в LightingService.
7. Primary RGB и весь `0x8A` при всех Fn+Tab не менялись. Flags 0 согласуется
   с использованием исходного красного RGB; произвольный синий при flags 0
   в этом read-only опыте не проверялся.
8. Минимальное наблюдённое изменение config — младший nibble report[67].
   Не нужны наблюдаемые изменения effect, custom mode, brightness или
   верхнего nibble. Это вывод для данного исходного состояния, не всех режимов.
9. **Да, можно предложить report, повторяющий наблюдённое изменение firmware.**
   Само применение через `0x04` и аппаратный restore остаются непроверенными.

### Точное предложение будущего change/restore — без формирования buffers

Новые `0x04` `.bin`/`.hex` не создавались; `config_offline.prepare` не запускался.
Ни один старый кандидат не отправлялся. Ниже только спецификация для отдельного
будущего разрешённого опыта. Источник — новый fresh snapshot непосредственно
перед будущей записью, сверенный с предпосылками текущего опыта.

Пусть `S` — полный валидный свежий config response, с исходными
report[17]=00, [18]=01, [66]=09, [67]=37 и RGB FF0000.

```text
Restore config, 520 bytes:
  [0:8]     = 06 04 00 00 01 00 80 00
  [8:136]   = S[8:136]                 # все 128 исходных bytes
  [136:520] = 00 × 384

Change config:
  те же 520 bytes, только [67] = 30
  diff от Restore: report[67] / payload[59]: 37 → 30
```

Terminator report[134:136]=5A A5 копируется из snapshot, checksum и wired
save отсутствуют в исследованном builder. Исходная brightness=9 сохраняется;
значение 8 означало бы дополнительное изменение и не входит в предложение.
Restore не реконструируется из отдельных полей. Оба buffers в будущей
реализации должны иметь независимое хранение. Нынешний baseline имеет тот же
config SHA-256, что и предыдущий офлайн snapshot, но не заменяет fresh snapshot
перед будущей записью.

Максимум будущего минимального полного цикла: **4 изменяющие команды**:
config single-color `0x04`, blue `0x0A`, original config `0x04`, original color
`0x0A`. В том числе **2 config writes с потенциальным сохранением во flash**.
Никаких повторных writes. Промежуточные read-back и визуальные подтверждения
обязательны; при раннем сбое дальнейшие изменения прекращаются, только
предусмотренные однократные restore-попытки в пределах того же лимита.
Порядок config → color соответствует upstream Apply, но независимая гарантия
restore-порядка на нашем устройстве этим ручным опытом не установлена.

### Счётчики и ограничения

- Read-request SetFeature: **23**, GetFeature: **23**. Это три baseline,
  четыре M1/M2 и шестнадцать M3. Каждый прошёл валидацию без retry.
- Изменяющие команды AgentRGB: **0**; вручную выполнено 8 Fn+Tab.
- Все handles закрыты после снимков. Core/listener не запускался.
- Стенд не содержит state-write transport path; каждый этап допускает только
  заданную последовательность read-opcodes. Между этапами ожидается ручное
  подтверждение пользователя; снимки не перезаписываются.
- Production и Pi/Node не менялись. H2/H3/H4 и 04C не запускались. Коммита нет.
- Повторно прошли все 73 Python-теста: [лог](results/manual-20260922T110723866453Z/offline-tests.log).
  Отдельная офлайн-проверка с mock WindowsHid.SetFeature подтвердила запрет
  state opcodes, чтений вне заданного этапа и повторного запроса сверх лимита.
- Результат снимает спор `37→30` против `37→00` для переключения этого профиля.
  M2 не дал физического доказательства скорости, а HID `0x04` не проверялся.

## Исторический офлайн-анализ до ручного опыта

Ниже сохранены прежние выводы и кандидаты. Прежняя неопределённость brightness
и flags уточнена результатами M1/M3 выше; разрешения на отправку нет.

22 сентября 2026 года. **К следующей записи не готово.** Выполнен только один
свежий read-only snapshot: `0x82 → 0x84 → 0x8A`. Изменяющих команд: **0**.
H2/H3/H4 не запускались, 04C не начата. Production, Pi/Node не менялись.

## Свежие данные

[Сводка](results/config-20260922T105023189900Z/summary.json),
[полный config, 520 байт](results/config-20260922T105023189900Z/config-response.bin),
[payload, 128 байт](results/config-20260922T105023189900Z/config-payload.bin),
[офлайн-разбор и SHA-256](results/config-20260922T105023189900Z/offline-analysis.json).
Raw каждого GET сохранён до валидации, вместе с API-результатом, временем,
sequence, header, SHA-256 и отправленным read-request.

Подтверждены `258A:010C`, `MI_01/COL06`, usage `FF00/0001`, feature 520,
report ID `06`, model `03`, PSD `00CD`. Primary RGB: `FF 00 00`.
Три read-request SetFeature и три GetFeature; handle закрыт. Core/listener
не запускался. Никаких write/restore не требовалось.

## Главное расхождение: система координат

Aula-Manager проверен по текущему main, commit
`b98c0afad7ae57bbd4f073230c1ee1cb87006318` (MIT, Copyright 2026 Roman).
Ссылки ниже закреплены на этот commit. Исходники сохранены в `research/upstream`
только как исследовательские материалы с LICENSE; сторонний код в адаптер
не переносился и приложение Aula-Manager не запускалось.

[PROTOCOL.md](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/docs/PROTOCOL.md)
называет offsets 17/18/64 смещениями payload. Однако
[ModelConfig.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/src/Aula.Core/Models/ModelConfig.cs),
[KeyboardConfig.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/src/Aula.Core/Models/KeyboardConfig.cs)
и [тесты](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/tests/Aula.Core.Tests/KeyboardConfigTests.cs)
применяют эти offsets непосредственно к ответу с 8-байтным header.
Следовательно, прибавлять 8 при воспроизведении этой реализации нельзя.

| Поле | По коду Aula-Manager: report offset / значение | По буквальной формулировке документа: payload offset / значение |
|---|---|---|
| effect | 18 / `01` | 18 (= report 26) / `01` |
| custom mode | 17 / `00` | 17 (= report 25) / `00` |
| brightness effect 1 | 66 / `09` = 9 | 66 (= report 74) / `08` = 8 |
| speed/flags effect 1 | 67 / `37` | 67 (= report 75) / `37` |
| speed | 3 | 3 |
| flags | 7 | 7 |

Таким образом, ожидаемые `payload[66]=08`, `payload[67]=37` действительно
прочитаны, но их принадлежность **effect 1** не подтверждена кодом Aula-Manager.
По его индексации это пара effect 5. Совпадение effect/custom в двух системах
координат случайно не позволяет выбрать систему по одному snapshot.
По реализации текущие поля: **effect=1, custom=0, brightness=9, speed=3, flags=7**.
Это вывод по коду, а не независимое физическое доказательство значения offsets.

Дополнительная [публикация cloudglides](https://github.com/cloudglides/aula-f75-linux-drivers/blob/main/docs/PROTOCOL.md)
тоже не устраняет расхождение: описывает effect в payload[10], но таблицу
параметров от payload[64]. Её утверждения о color/per-key отличаются от
Aula-Manager; эти правила не перенесены в AgentRGB.

## Colorful и фактическое поведение Apply

[LightingService.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/src/Aula.Core/Services/LightingService.cs)
использует nibble `07` для colorful и `00` для single color. Это согласуется
с полевым протоколом. `KeyboardConfig.EffectParams` также распознаёт colorful
через младшие четыре бита. Поэтому flags=7 — правдоподобное объяснение того,
что изменение primary RGB не дало видимого синего. Причинность на нашем
устройстве пока не доказана; стабильность HID во всех условиях также не доказана.

Точный wired Apply для effect 1 и заданного single RGB:

1. Читает config.
2. Задаёт report[17]=0 (не per-key), report[18]=1.
3. Записывает заданную brightness в report[66], если она указана.
4. Effect 1 имеет `HasSpeed=false` в
   [EffectLibrary.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/src/Aula.Core/Models/EffectLibrary.cs).
   Параметр Speed игнорируется. При заданном RGB весь report[67] становится
   `00`, а не `30`. Даже RawFlags будет перезаписан последующей static-color веткой.
5. Отправляет config `0x04`, затем color `0x0A`. Других управляющих полей,
   wired apply/save-команд в этом пути нет.

[LightingServiceTests.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/tests/Aula.Core.Tests/LightingServiceTests.cs)
проверяет custom/effect/параметры, colorful, игнорирование speed у static и
порядок config → color. Static-color тест проверяет порядок и RGB, но **не**
assert report[67]=00; этот вывод получен из кода. Upstream C#-тесты прочитаны,
не запускались; это не аппаратное подтверждение.

Если буквально передать brightness=8, speed=3, effect=1 и цвет, реализация
изменит report[66] `09→08` и report[67] `37→00`; custom/effect останутся прежними.
Это не сохранение исходной brightness по её собственной индексации и не
сохранение nibble скорости. Поэтому такой report не выбран для будущей записи.

## Wired 0x04: формат установлен по коду и тестам

[F75Report.CreateConfigWrite](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/src/Aula.Core/Protocol/F75Report.cs)
и [F75ReportTests.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/tests/Aula.Core.Tests/F75ReportTests.cs):

- Полная длина — 520 байт, включая report ID.
- Полный header: `06 04 00 00 01 00 80 00`.
- Report[8:136] — все 128 байт исходного config payload.
- Report[134:136] = `5A A5`, это последние два байта payload; они копируются.
- Report[136:520] — нули. Checksum не вычисляется.
- [SinowealthProtocol.cs](https://github.com/free-soldier28/Aula-Manager/blob/b98c0afad7ae57bbd4f073230c1ee1cb87006318/src/Aula.Core/Protocol/SinowealthProtocol.cs)
  отправляет ровно один SetFeature; отдельного apply/save нет.

В нашем подтверждённом read-request header[2]=01, в upstream read builder=00.
Существующий read-path не изменялся. Для **write** используется установленный
upstream header, а не простая замена opcode в snapshot. Правила `0x13`, его
write/apply flags, checksum и save к wired не применяются.

## Офлайн-буферы и точный diff

Все кандидаты имеют статус `BLOCKED_NOT_FOR_HARDWARE`. Наличие файлов не означает
разрешение отправки. `config_offline.py` вообще не импортирует HID и не содержит
транспорта. Неизвестные 128 payload bytes сохраняются за исключением явно
указанного поля; исходный snapshot и restore не alias с кандидатами.

База сравнения — original config **write report**, то есть restore, а не
read-response с другим header.

| Файл | Единственный изменённый байт относительно restore | Ограничение |
|---|---|---|
| [candidate-upstream-static.bin](results/config-20260922T105023189900Z/candidate-upstream-static.bin) | report[67] = payload[59]: `37→00`, speed/flags | Повторяет static Apply при сохранении brightness=9; не сохраняет speed nibble |
| [candidate-preserve-speed.bin](results/config-20260922T105023189900Z/candidate-preserve-speed.bin) | report[67] = payload[59]: `37→30`, только flags nibble | Сохраняет speed=3, но не повторяет static-color ветку Apply |

Report[17]=00, report[18]=01, report[66]=09 в обоих сохранены. Никакого изменения
report[75] или выбора literal-payload варианта наугад нет. Требуемый единый
report с доказанным сохранением brightness=8/speed=3 **не утверждён**.

## Точный restore и его источник

[Restore, все 520 байт в hex](results/config-20260922T105023189900Z/restore-config.hex),
[тот же binary](results/config-20260922T105023189900Z/restore-config.bin).
Источник — полный свежий `config-response.bin` этого опыта, не набор
реконструированных параметров. Payload restore полностью равен snapshot[8:136].

SHA-256 source: `5a90dd25a6dd82b2d639193ba2e03d9e3d98ae909dad32531ae0a1924cd413e0`.
SHA-256 restore: `2eac39f69d7ab2b062a4bab1d1efc1c96956176205ae2464ce13bb0160284eb9`.
Изменения от полного read-response: report[1] `84→04`, report[2] `01→00`;
остальные байты для этого свежего snapshot совпадают, включая нулевой хвост.
Побайтное построение restore доказано офлайн; аппаратное восстановление через
`0x04` на нашей клавиатуре в этой фазе не проверено.

## Будущий цикл и flash

Код Apply и его тест подтверждают порядок **config → color** для применения.
Отдельной процедуры восстановления произвольного полного snapshot upstream
не предоставляет. Следовательно, вариант A соответствует порядку Apply,
но гарантия правильности restore из любого промежуточного состояния отсутствует.
Вариант B источниками не подтверждён. Не выдаём порядок применения за
доказанный универсальный порядок восстановления.

После устранения неоднозначности план минимального успешного опыта:
fresh snapshot → config change → один `0x84` read-back → blue → один `0x8A`
read-back → визуальное подтверждение → original config → original color →
один `0x84` и один `0x8A` read-back → визуальное восстановление → close.
Остановка при первом отклонении, без retries; максимум одна попытка каждого
restore. Если изменён только config, не планируется лишняя color-запись.

В полном цикле максимум **4 изменяющие команды**: две `0x04` (change/restore)
и две `0x0A` (blue/restore). Config writes по полевым данным сразу сохраняются
во flash, поэтому две config-команды — две потенциальные flash-записи.
Внутреннее число операций flash неизвестно; отсутствие flash-эффекта `0x0A`
не гарантируется. Read requests учитываются отдельно: семь в успешном цикле
(три snapshot, два промежуточных, два завершающих), они не color/config writes.
Стресс-тест, перебор, анимации не планируются.

## Офлайн-проверки и решение

Все **73 Python-теста** прошли: прежние 58 и 15 новых. Проверены обе системы
координат; effect, brightness, speed, flags; `37→(3,7)`; различия кандидатов;
сохранение неизвестных байтов; полное восстановление payload; отсутствие alias;
header/длина/terminator; независимость `0x0A`; подготовка при SetFeature,
подменённом на немедленную ошибку. Полный prepare не вызывает SetFeature.

Формат контейнера и restore сформированы. Однако расхождение координат таблицы,
brightness 8/9 и требование сохранить speed при upstream `37→00` не позволяют
утвердить минимальный change report. Гипотеза colorful поддержана источниками,
но критерий готовности к физическому опыту **не выполнен**. Разрешение на запись
не запрашивается. Нужны дополнительные документальные/исходные доказательства
этих полей, а не аппаратный перебор. Коммит не выполнялся.
