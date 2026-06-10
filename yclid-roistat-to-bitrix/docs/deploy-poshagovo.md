# Развёртывание сервиса Bitrix24 → Roistat → Metrika Client ID

Пошаговая инструкция для человека, который разворачивает сервис на сервере.
Рассчитана на того, кто умеет заходить по SSH, но не обязан знать systemd и nginx.

## Что это и как работает (в двух словах)

Это маленький сервис. Битрикс24 при создании сделки «дёргает» его по ссылке,
он находит Metrika Client ID и записывает в поле сделки `UF_CRM_DEAL_AMO_WHRFJKVPRXAQRYKJ`.

Схема после установки:

```
Битрикс24 ──HTTPS──► https://ВАШ-ДОМЕН/bitrix/deal-created
                          │
                       nginx (смотрит в интернет)
                          │
                          ▼
                 127.0.0.1:8080  ← наш Python-сервис (работает внутри сервера)
```

Что нужно сделать: положить файлы, заполнить настройки, сделать сервис «вечным»
(systemd), открыть наружу по HTTPS (nginx), отдать финальную ссылку.

---

## Шаг 0. Что понадобится

- Доступ к серверу по SSH с правами `sudo`.
- Домен (или поддомен), направленный A-записью на IP этого сервера. Без домена HTTPS не сделать.
- Архив `bitrix-roistat-transfer.zip` (передаётся отдельно — внутри есть `.env` с реальными
  ключами, его нельзя выкладывать никуда).

---

## Шаг 1. Положить файлы на сервер

Создаём папку и распаковываем туда архив:

```bash
sudo mkdir -p /opt/bitrix-roistat
```

Скопируйте `bitrix-roistat-transfer.zip` на сервер и распакуйте в `/opt/bitrix-roistat`,
чтобы внутри лежали `server.py`, `check_config.py`, `.env`, `.env.example`, `README.md`, `DEPLOY.md`.

Проверка — файлы на месте:

```bash
ls /opt/bitrix-roistat
```

✅ Должны увидеть список этих файлов.

---

## Шаг 2. Проверить, что есть Python 3

```bash
python3 --version
```

✅ Должно вывести что-то вроде `Python 3.10.x`. Если «команда не найдена» — поставьте
Python 3: `sudo apt update && sudo apt install -y python3`.

---

## Шаг 3. Заполнить настройки (`.env`)

В архиве уже есть `.env` с реальными ключами — менять там ничего **не нужно**, кроме случая,
если значения переедут. Просто откройте и проверьте, что заполнены:

```bash
sudo nano /opt/bitrix-roistat/.env
```

Должны быть заданы:

- `WEBHOOK_SECRET=...` — секретное слово, оно попадёт в финальную ссылку. **Запомните его** — понадобится в шаге 7.
- `BITRIX_WEBHOOK_URL=...` — ссылка входящего вебхука Битрикс24.
- `BITRIX_METRIKA_FIELD=...` — поле сделки (`UF_CRM_DEAL_AMO_WHRFJKVPRXAQRYKJ`).
- `ROISTAT_PROJECT_ID=...` и `ROISTAT_API_KEY=...` — доступ к Roistat.
- `HOST=127.0.0.1` и `PORT=8080` — **не трогать.**

Сохранить в nano: `Ctrl+O`, `Enter`, выйти `Ctrl+X`.

> `HOST=127.0.0.1` — правильно и так и должно быть. Это значит «сервис слушает только внутри
> сервера», наружу его откроет nginx.

---

## Шаг 4. Проверить конфиг

```bash
cd /opt/bitrix-roistat
python3 check_config.py
```

✅ Ожидаемый результат:

```
Bitrix profile: ok
Bitrix deal field: ok
Roistat API: ok
Config looks ready.
```

❌ Если что-то `error` — значит неверный ключ/URL в `.env`. Исправьте в `.env` и запустите
проверку снова. **Дальше идти можно только когда всё `ok`.**

---

## Шаг 5. Сделать сервис «вечным» (systemd)

Сейчас сервис можно запустить руками, но он умрёт при закрытии терминала. Чтобы он работал
всегда и сам перезапускался, оформляем его как системную службу.

Создаём файл службы:

```bash
sudo nano /etc/systemd/system/bitrix-roistat.service
```

Вставляем содержимое **как есть**:

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

Сохранить (`Ctrl+O`, `Enter`, `Ctrl+X`).

> Этот файл — инструкция серверу: «запускай `server.py` всегда, при падении перезапускай,
> включай при загрузке». Он лежит в системной папке `/etc/`, а не в папке проекта — поэтому
> его создают здесь, на сервере, вручную.

Выдаём права и запускаем:

```bash
# права на папку — пользователю, под которым работает служба
sudo chown -R www-data:www-data /opt/bitrix-roistat

# .env с ключами читает только владелец
sudo chmod 600 /opt/bitrix-roistat/.env

# подхватить новую службу
sudo systemctl daemon-reload

# включить автозапуск при перезагрузке сервера
sudo systemctl enable bitrix-roistat

# запустить сейчас
sudo systemctl start bitrix-roistat

# посмотреть статус
sudo systemctl status bitrix-roistat
```

✅ В статусе должно быть зелёное **`active (running)`**. Выйти из просмотра статуса — `q`.

❌ Если `failed` — смотрите причину: `sudo journalctl -u bitrix-roistat -n 50`.

---

## Шаг 6. Проверить сервис локально

```bash
curl http://127.0.0.1:8080/health
```

✅ Ожидаемый ответ:

```json
{"status": "ok"}
```

Это значит сервис работает. Снаружи он пока недоступен — открываем в следующем шаге.

---

## Шаг 7. Открыть наружу по HTTPS (nginx + сертификат)

Ставим nginx и certbot:

```bash
sudo apt update
sudo apt install -y nginx certbot python3-certbot-nginx
```

Создаём конфиг сайта (замените `ВАШ-ДОМЕН` на ваш реальный домен в двух местах):

```bash
sudo nano /etc/nginx/sites-available/bitrix-roistat
```

Вставляем:

```nginx
server {
    listen 80;
    server_name ВАШ-ДОМЕН;

    location / {
        proxy_pass http://127.0.0.1:8080;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

Сохранить. Включаем сайт и перезапускаем nginx:

```bash
sudo ln -s /etc/nginx/sites-available/bitrix-roistat /etc/nginx/sites-enabled/
sudo nginx -t          # проверка конфига — должно быть "syntax is ok" / "test is successful"
sudo systemctl reload nginx
```

Выдаём HTTPS-сертификат (certbot сам всё пропишет):

```bash
sudo certbot --nginx -d ВАШ-ДОМЕН
```

На вопросы ответьте e-mail и согласие; на предложение редиректа на HTTPS выберите «да» (redirect).

✅ Проверка снаружи — с любого компьютера откройте в браузере:

```
https://ВАШ-ДОМЕН/health
```

Должны увидеть `{"status": "ok"}` и замочек HTTPS.

---

## Шаг 8. Отдать финальную ссылку

Соберите ссылку из вашего домена и `WEBHOOK_SECRET` из `.env` (шаг 3):

```
https://ВАШ-ДОМЕН/bitrix/deal-created?secret=ЗНАЧЕНИЕ_WEBHOOK_SECRET
```

Эту ссылку нужно вставить в исходящий вебхук Битрикс24 вместо ngrok.

---

## Шаг 9. Боевая проверка

1. Откройте просмотр логов сервиса:

   ```bash
   sudo journalctl -u bitrix-roistat -f
   ```

2. Создаётся тестовая сделка в Битрикс24.
3. В логах должна появиться строка про обработку — `status updated` (поле заполнено)
   или `skipped` (нечего записывать — это тоже нормально).
4. Откройте эту сделку в Битрикс24 и проверьте, что поле `UF_CRM_DEAL_AMO_WHRFJKVPRXAQRYKJ` заполнилось.

Остановить просмотр логов — `Ctrl+C`.

---

## Шпаргалка по управлению сервисом

```bash
sudo systemctl status  bitrix-roistat   # как себя чувствует
sudo systemctl restart bitrix-roistat   # перезапустить (например, после правки .env)
sudo systemctl stop    bitrix-roistat   # остановить
sudo journalctl -u bitrix-roistat -f    # живые логи
```

## Важно

- `.env` содержит **реальные ключи** Bitrix24 и Roistat — не выкладывать в общий доступ,
  передавать только защищённым каналом.
- Названия полей в `.env` без необходимости не менять.
- После любой правки `.env` — перезапустить службу: `sudo systemctl restart bitrix-roistat`.
