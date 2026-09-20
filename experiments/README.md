# Технические эксперименты

Каталог содержит исследовательские прототипы и сохранённые результаты аппаратных проверок. Эти скрипты не являются производственным кодом AgentRGB и не задают универсальную HID-абстракцию.

## Проверенная конфигурация

- Windows 11;
- AULA F75 по USB;
- VID `258A`, PID `010C`;
- vendor HID `MI_01/COL06`, usage page `0xFF00`;
- feature report 520 байт;
- semantic model ID `0x03`;
- PSD `0x00CD`.

`aula-f75-readonly/` содержит прототип обнаружения и чтения model/config/color-profile. `aula-f75-write-restore/` содержит подготовку и результат ограниченного опыта с двумя изменяющими операциями `0x0A`: change и restore.

После change чтение `0x8A` подтвердило RGB в абсолютных байтах `[29..31] = 00 00 FF`. После restore контрольный `GET_FEATURE` не удался, поэтому финальные `0x8A` и `0x84` аппаратно не подтверждены. Системного переподключения не произошло; визуально исходный пользовательский профиль с переливающейся подсветкой восстановлен.

Значение `effect = 1` нельзя считать подтверждённым обозначением `static`: наблюдаемый исходный эффект был переливающимся. Не установлено, неверно ли разобрана часть `0x84` или эффект зависит от дополнительных параметров. Полная семантика профиля остаётся неизвестной.

## Статус аппаратного направления

| Возможность | Статус |
|---|---|
| detect | confirmed |
| identify | confirmed |
| read config | confirmed |
| read color profile | confirmed |
| write color profile | confirmed |
| read-back after change | confirmed |
| visual restore | confirmed |
| full hardware restore | partially confirmed |
| effect semantics | partially confirmed |
| per-key RGB | not tested |
| 2.4 GHz | not tested |
| Bluetooth | not tested |

Визуальное восстановление наблюдаемого пользовательского состояния подтверждено; полное аппаратное восстановление пока подтверждено частично.
