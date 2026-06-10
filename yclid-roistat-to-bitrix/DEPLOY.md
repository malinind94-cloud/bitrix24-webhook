# Передача и запуск на сервере

## Что передать сотруднику

Передайте архив `bitrix-roistat-transfer.zip` или эти файлы:

- `server.py`
- `check_config.py`
- `.env.example`
- `README.md`
- `DEPLOY.md`

Файл `.env` содержит реальные ключи и вебхуки. Его можно передавать только по защищенному каналу. Если сомневаетесь, передайте `.env.example`, а реальные значения сообщите отдельно.

## Что должно быть в `.env` на сервере

```env
HOST=127.0.0.1
PORT=8080
WEBHOOK_SECRET=заменить-на-секрет

BITRIX_WEBHOOK_URL=https://ваш-портал.bitrix24.ru/rest/USER/WEBHOOK/
BITRIX_METRIKA_FIELD={UfCrmDealAmoWhrfjkvprxaqrykj}
BITRIX_ROISTAT_VISIT_FIELD=UF_CRM_ROISTAT
MEGAFON_MATCH=

ROISTAT_PROJECT_ID=301529
ROISTAT_API_KEY=заменить-на-api-key
```

## Быстрый запуск на сервере

```bash
mkdir -p /opt/bitrix-roistat
cd /opt/bitrix-roistat
```

Скопировать файлы в эту папку, затем:

```bash
cp .env.example .env
nano .env
python3 check_config.py
python3 server.py
```

Проверка:

```bash
curl http://127.0.0.1:8080/health
```

## Systemd-сервис

Создать файл:

```bash
sudo nano /etc/systemd/system/bitrix-roistat.service
```

Содержимое:

```ini
[Unit]
Description=Bitrix24 Roistat Metrika Client ID webhook
After=network-online.target

[Service]
Type=simple
WorkingDirectory=/opt/bitrix-roistat
ExecStart=/usr/bin/python3 /opt/bitrix-roistat/server.py
Restart=always
RestartSec=5
User=www-data
Group=www-data

[Install]
WantedBy=multi-user.target
```

Права:

```bash
sudo chown -R www-data:www-data /opt/bitrix-roistat
sudo chmod 600 /opt/bitrix-roistat/.env
```

Запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable bitrix-roistat
sudo systemctl start bitrix-roistat
sudo systemctl status bitrix-roistat
```

Логи:

```bash
sudo journalctl -u bitrix-roistat -f
```

## URL для Битрикс24

Если сервер открыт напрямую на порту `8080`:

```text
http://SERVER_IP:8080/bitrix/deal-created?secret=WEBHOOK_SECRET
```

Лучше настроить домен и HTTPS через nginx:

```text
https://ваш-домен.ru/bitrix/deal-created?secret=WEBHOOK_SECRET
```

Именно этот URL нужно указать в исходящем вебхуке Битрикс24 на событие создания сделки.
