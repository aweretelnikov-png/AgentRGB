# Release checklist: 0.1.0

Все локальные gates относятся к финальным артефактам `0.1.0`, подготовленным
2 октября 2026: [RELEASE_FINAL.md](RELEASE_FINAL.md). Final release не опубликован.
После изменения packaged source или metadata пересобрать затронутые артефакты
и повторить проверки. Процедура: [RELEASING.md](RELEASING.md).
Исторические [Python RC](RELEASE_RC1.md) и [npm RC](RELEASE_PI_RC1.md) сохранены.

## Локальная подготовка — PASS

- [x] Production PyPI name read-only lookup: HTTP 404, 2 октября 2026.
- [x] Python и npm metadata: `0.1.0`; runtime-код и зависимости сохранены.
- [x] Python full suite: 167/167; Node full suite: 35/35.
- [x] `git diff --check` без ошибок.
- [x] README содержит публичный сценарий и явное предупреждение, что final release не опубликован.
- [x] Wheel и sdist собраны с нуля; wheel собран из sdist.
- [x] `twine check`, metadata, console entry point, MIT LICENSE и точный состав проверены.
- [x] SHA-256 обоих Python artifacts вычислен.
- [x] Final wheel установлен в новом venv вне checkout, без editable/PYTHONPATH.
- [x] CLI help/status/doctor проверены; doctor использовал hardware-blocked backend.
- [x] Default fake Core: health/running → настоящий Ctrl+C → exit 0 → свободный порт.
- [x] `npm pack --dry-run` и `npm pack`; ровно пять ожидаемых файлов; SHA-256 вычислен.
- [x] Final npm tarball установлен во временный prefix, installed files/version подтверждены.
- [x] Ordinary Pi 1.0.0 → autoload → installed final Python → owned fake Core → lifecycle → `/quit` → Core stopped → свободный порт.
- [x] HID заблокирован test launcher; внешний model provider и hardware не запускались.
- [x] Артефакты не содержат experiments, секретов, локальных settings, logs или абсолютных пользовательских путей.
- [x] `dist/` и `.tgz` ignored и исключены из release staging.
- [x] Пользовательские `experiments/README.md` и `experiments/manual_scenarios.py` сохранены и исключены из staging.
- [x] Существующее hardware evidence [Phase 04C](../experiments/phase-04c/RESULTS.md) сохранено; final hardware smoke отдельно.

Тестовая подмена `aula-f75` на `fake` подтверждает package installation и lifecycle,
но не неизменённый аппаратный autostart. Реальный identity read в doctor не проверялся.
Проверка внешнего Core сохранена в [предыдущем evidence](RELEASE_PREP.md).

npm `latest` сейчас указывает на `0.1.0-rc.1`, как и `next`; удаление latest
вернуло E400 и не повторялось. При финальном publish latest должен перейти на
`0.1.0`; это следует проверить после публикации. На этом этапе tags не менялись.
PyPI HTTP 404 не резервирует имя; перед upload повторить read-only lookup.

## Внешние шаги — pending

- [ ] PyPI production publish `0.1.0`.
- [ ] npm publish `0.1.0` и подтверждение `latest → 0.1.0`.
- [ ] Production registry clean install Python/npm, без checkout.
- [ ] Final F75 smoke с отдельным разрешением.
- [ ] Git tag.
- [ ] GitHub Release.

После final preparation commit остановиться: без публикации, dist-tag changes,
push, tag, GitHub Release и аппаратного запуска.
