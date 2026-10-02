# Подготовка Python 0.1.0rc1: 2 октября 2026

База — `6ddfc23 chore: prepare 0.1.0 release`. Python version в
`pyproject.toml` изменена на `0.1.0rc1`; Pi остаётся `0.1.0-dev.0`.
Runtime-код, зависимости и npm package не изменены.

## TestPyPI

Read-only GET `https://test.pypi.org/pypi/agentrgb/json` вернул HTTP 404.
Имя отсутствовало на момент проверки; это не резервирует namespace.
PowerShell/curl не смогли установить TLS в runner; GET выполнен через
Python urllib с обычной проверкой сертификата.

Публикация пока не выполнялась: требуется явное разрешение пользователя и ручной
ввод TestPyPI API token через prompt Twine. Credentials не читались и не сохранялись.
Ожидаемые адреса после upload:
[проект](https://test.pypi.org/project/agentrgb/),
[версия](https://test.pypi.org/project/agentrgb/0.1.0rc1/).
Наличие этих страниц до публикации не подтверждено.

## Проверки и сборка

- Python 3.14.4: полный suite, 167/167, OK.
- Node: полный suite, 35/35, без failures/skips.
- `git diff --check`: без ошибок.
- Существующий неблокирующий `ResourceWarning` при cleanup `HTTPError 400`.
- Launcher `py` отсутствует в PATH; использован доступный Python 3.14.4.
- `build 1.6.1`, `twine 7.0.0` установлены во временный tools venv вне checkout.
- Перед build удалены только старые файлы из проверенного ignored `dist/`.
- Изолированный build использовал setuptools 84.0.0; wheel собран из нового sdist.
- `twine check`: PASSED для обоих файлов.

| Файл | SHA-256 |
|---|---|
| `agentrgb-0.1.0rc1-py3-none-any.whl` | `69e794b595e8784959f4df94d3778d12c82bcfb2b1597823125f7438fce82434` |
| `agentrgb-0.1.0rc1.tar.gz` | `6f48219d505784ff6eb758632fbdcef9ea4a95f1355d8e177e9957d76901987f` |

Wheel содержит 16 файлов, sdist — 21. Metadata обоих archives:
`Name: agentrgb`, `Version: 0.1.0rc1`, runtime dependencies отсутствуют.
Entry point `agentrgb = agentrgb.cli:main` присутствует; LICENSE побайтово
совпадает с исходным, README в metadata совпадает с текущим README после
нормализации переводов строк. Все production `.py` совпадают с checkout.

Проверены имена и содержимое всех файлов: experiments, tests, `.env`, кэши,
runtime logs и абсолютные пользовательские пути отсутствуют; распространённые
форматы токенов и private keys не найдены. Такой поиск не гарантирует обнаружение
произвольного секрета. Исторические dev versions остались только в документации
прошлой подготовки, поисковой команде и mock-строках CLI tests; production
источник версии один — `pyproject.toml`.

## Чистый локальный smoke

Новый venv вне checkout; установлен точный RC wheel через
`pip install --no-index --no-deps`. Pip сообщил `Successfully installed
agentrgb-0.1.0rc1`. Импорт идёт из `venv/Lib/site-packages/agentrgb`;
`direct_url.json` содержит archive hash этого wheel и не содержит editable flag.
CLI запускается вне checkout, без `PYTHONPATH`.

- `agentrgb --help`: exit 0.
- До start: `status` — `not running`, exit 1.
- `doctor`: Python 3.14.4, AgentRGB 0.1.0rc1, production imports OK,
  порт свободен; `AULA F75: not found`, ожидаемый exit 1.
- Default `agentrgb start`, без output override: fake Core на свободном
  временном порту `50063`.
- `/health`: HTTP 200, `{"status":"ok","service":"agentrgb"}`.
- `status`: `running`, exit 0.
- Настоящий Windows `CTRL_C_EVENT`: штатный exit 0 без forced termination.
- Exclusive bind после выхода подтвердил освобождение порта.

Временный console bootstrap сбросил унаследованное игнорирование Ctrl+C и
запустил неизменённый установленный CLI в отдельной скрытой Windows console.
Smoke проверяет default fake output; стандартный порт 8765 этим прогоном не проверен.
F75 output не запускался; identity диагностика не нашла устройства.

## Git и оставшиеся шаги

В RC commit входят только `pyproject.toml`, `README.md`, `docs/RELEASING.md`
и этот отчёт. Пользовательские файлы не менялись и не staging:

| Файл | SHA-256 |
|---|---|
| `experiments/README.md` | `80d71c148a344d287c4a461c6a522c0d85d4d610f2f18bcb42594d11aafafffb` |
| `experiments/manual_scenarios.py` | `ff468faf3545e5294ab27951121d6aa2e12551f706139cd1a4b78121a20b5bd4` |

`dist/` не входит в staging. Push, tag, production upload, npm publish и
GitHub Release не выполнялись.

После разрешённого ручного TestPyPI upload требуется новый venv и установка
строго из TestPyPI `agentrgb==0.1.0rc1` с `--no-deps`, вне checkout, без local wheel,
editable install и `PYTHONPATH`. Пока сетевая установка и TestPyPI smoke
**не выполнены**. Дополнить этот отчёт фактически скачанной версией и результатами
CLI, default fake Core, Ctrl+C и освобождения порта. После успешного smoke остановиться.
Занятую версию не перезаписывать: исправления требуют следующего согласованного RC.
