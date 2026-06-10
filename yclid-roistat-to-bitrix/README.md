# Bitrix24 -> Roistat -> Metrika Client ID локальный прототип

Этот прототип принимает событие о созданной сделке из Битрикс24, достает сделку и телефон, ищет в Roistat связанный визит, забирает из него `Metrika Client ID` и записывает значение в пользовательское поле сделки.

Работает локально на макбуке, без стороннего сервера. Для приема вебхука из облачного Битрикс24 нужен публичный туннель до локального порта, например ngrok или Cloudflare Tunnel.

## Что подготовить

1. В Битрикс24 создайте входящий вебхук с правами CRM и скопируйте URL вида:

   `https://your.bitrix24.ru/rest/USER_ID/WEBHOOK_CODE/`

2. В сделках Битрикс24 создайте/найдите пользовательское поле для `Metrika Client ID`, например `UF_CRM_...`.

3. В Roistat возьмите `project id` и `Api-key`.

4. Скопируйте конфиг:

   ```bash
   cp .env.example .env
   ```

5. Заполните `.env`.

## Запуск

```bash
python3 server.py
```

Проверка:

```bash
curl http://127.0.0.1:8080/health
```

## Как подключить к Битрикс24

1. Поднимите туннель на порт `8080`.

   Пример для ngrok:

   ```bash
   ngrok http 8080
   ```

2. В Битрикс24 добавьте исходящий вебхук/робота/событие на создание сделки и укажите URL:

   `https://PUBLIC-TUNNEL-URL/bitrix/deal-created?secret=change-me`

3. Событие должно передавать ID сделки. Скрипт понимает несколько популярных форматов:

   `data[FIELDS][ID]`, `FIELDS.ID`, `ID`, `deal_id`.

## Ручная проверка без Битрикс-события

Можно дернуть обработчик напрямую:

```bash
curl -X POST 'http://127.0.0.1:8080/bitrix/deal-created?secret=change-me' \
  -H 'Content-Type: application/json' \
  -d '{"deal_id": "123"}'
```

Для проверки одной только записи в Битрикс24:

```bash
curl -X POST 'http://127.0.0.1:8080/manual/update?secret=change-me' \
  -H 'Content-Type: application/json' \
  -d '{"deal_id": "123", "metrika_client_id": "1234567890"}'
```

## Важные настройки

`BITRIX_METRIKA_FIELD` обязательно должен быть кодом поля сделки, куда пишем ID.

`BITRIX_ROISTAT_VISIT_FIELD` лучше заполнить, если в Битрикс24 где-то уже есть номер визита Roistat. Тогда поиск будет точнее.

Если номера визита в сделке нет, скрипт берет телефон из сделки/контакта/компании и ищет клиента в Roistat по телефону, затем берет последний визит из ленты клиента.

## Источники API

Использованы официальные методы Битрикс24 `crm.deal.get`, `crm.deal.update`, `crm.contact.get`, `crm.company.get` и методы Roistat `/project/clients`, `/project/clients/detail/feed`, `/project/site/visit/list`.
