#!/usr/bin/env python3
import json
import os
import re
import sys
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlparse
from urllib.error import HTTPError
from urllib.request import Request, urlopen


ROOT = os.path.dirname(os.path.abspath(__file__))


def load_env(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for raw_line in file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


load_env(os.path.join(ROOT, ".env"))


def normalized_webhook_url():
    value = os.getenv("BITRIX_WEBHOOK_URL", "").strip()
    return value.rstrip("/") + "/" if value else ""


def camel_to_bitrix_field_code(value):
    raw = value.strip().strip("{}")
    if raw.startswith("UF_"):
        return raw
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", raw).upper()
    return snake


CONFIG = {
    "host": os.getenv("HOST", "127.0.0.1"),
    "port": int(os.getenv("PORT", "8080")),
    "secret": os.getenv("WEBHOOK_SECRET", ""),
    "bitrix_webhook_url": normalized_webhook_url(),
    "bitrix_metrika_field": camel_to_bitrix_field_code(os.getenv("BITRIX_METRIKA_FIELD", "")),
    "bitrix_roistat_visit_field": camel_to_bitrix_field_code(os.getenv("BITRIX_ROISTAT_VISIT_FIELD", "")),
    "megafon_match": os.getenv("MEGAFON_MATCH", "megafon").lower(),
    "roistat_project_id": os.getenv("ROISTAT_PROJECT_ID", ""),
    "roistat_api_key": os.getenv("ROISTAT_API_KEY", ""),
}


class IntegrationError(Exception):
    pass


def log(message):
    print(f"{datetime.now().isoformat(timespec='seconds')} {message}", flush=True)


def http_json(method, url, body=None, headers=None, timeout=30):
    data = None
    request_headers = {"Content-Type": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    request = Request(url, data=data, method=method, headers=request_headers)
    try:
        response = urlopen(request, timeout=timeout)
    except HTTPError as error:
        raw = error.read().decode("utf-8")
        if raw:
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                pass
        raise
    with response:
        raw = response.read().decode("utf-8")
        if not raw:
            return {}
        return json.loads(raw)


def bitrix_call(method, payload):
    if not CONFIG["bitrix_webhook_url"]:
        raise IntegrationError("BITRIX_WEBHOOK_URL is empty")
    url = CONFIG["bitrix_webhook_url"] + method + ".json"
    response = http_json("POST", url, payload)
    if "error" in response:
        description = response.get("error_description") or response["error"]
        raise IntegrationError(f"Bitrix24 {method} failed: {description}")
    return response.get("result")


def roistat_call(path, body=None, query=None, method="POST"):
    if not CONFIG["roistat_project_id"] or not CONFIG["roistat_api_key"]:
        raise IntegrationError("ROISTAT_PROJECT_ID or ROISTAT_API_KEY is empty")
    params = {"project": CONFIG["roistat_project_id"]}
    if query:
        params.update(query)
    url = "https://cloud.roistat.com/api/v1" + path + "?" + urlencode(params)
    headers = {"Api-key": CONFIG["roistat_api_key"]}
    response = http_json(method, url, body if method != "GET" else None, headers=headers)
    if response.get("status") not in (None, "success"):
        raise IntegrationError(f"Roistat {path} failed: {response}")
    return response


def parse_body(handler):
    length = int(handler.headers.get("Content-Length") or 0)
    raw = handler.rfile.read(length).decode("utf-8") if length else ""
    content_type = handler.headers.get("Content-Type", "")
    if not raw:
        return {}
    if "application/json" in content_type:
        return json.loads(raw)
    parsed = parse_qs(raw)
    return flatten_form(parsed)


def flatten_form(parsed):
    result = {}
    for key, values in parsed.items():
        value = values[-1] if values else ""
        parts = re.findall(r"[^\[\]]+", key)
        cursor = result
        for part in parts[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[parts[-1]] = value
    return result


def deep_get(data, path):
    cursor = data
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return None
        cursor = cursor[part]
    return cursor


def find_deal_id(payload):
    candidates = [
        deep_get(payload, ["data", "FIELDS", "ID"]),
        deep_get(payload, ["FIELDS", "ID"]),
        deep_get(payload, ["data", "fields", "ID"]),
        payload.get("deal_id") if isinstance(payload, dict) else None,
        payload.get("DEAL_ID") if isinstance(payload, dict) else None,
        payload.get("ID") if isinstance(payload, dict) else None,
    ]
    for value in candidates:
        if value:
            return str(value)
    raise IntegrationError(f"Cannot find deal id in payload: {payload}")


def normalize_phone(phone):
    digits = re.sub(r"\D+", "", str(phone or ""))
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    return digits


def extract_phone_values(entity):
    phones = []
    raw_phone = entity.get("PHONE")
    if isinstance(raw_phone, list):
        for item in raw_phone:
            if isinstance(item, dict) and item.get("VALUE"):
                phones.append(normalize_phone(item["VALUE"]))
            elif isinstance(item, str):
                phones.append(normalize_phone(item))
    elif isinstance(raw_phone, str):
        phones.append(normalize_phone(raw_phone))
    return [phone for phone in phones if phone]


def get_deal(deal_id):
    return bitrix_call("crm.deal.get", {"id": deal_id})


def get_contact(contact_id):
    return bitrix_call("crm.contact.get", {"id": contact_id}) if contact_id else None


def get_company(company_id):
    return bitrix_call("crm.company.get", {"id": company_id}) if company_id else None


def deal_looks_like_megafon(deal):
    needle = CONFIG["megafon_match"]
    if not needle:
        return True
    haystack = " ".join(
        str(deal.get(key, ""))
        for key in ("SOURCE_ID", "SOURCE_DESCRIPTION", "ORIGINATOR_ID", "ORIGIN_ID", "COMMENTS", "TITLE")
    ).lower()
    return needle in haystack


def find_deal_phones(deal):
    phones = extract_phone_values(deal)
    contact = get_contact(deal.get("CONTACT_ID"))
    if contact:
        phones.extend(extract_phone_values(contact))
    company = get_company(deal.get("COMPANY_ID"))
    if company:
        phones.extend(extract_phone_values(company))
    return list(dict.fromkeys(phone for phone in phones if phone))


def find_nested_value(data, names):
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in names and value not in ("", None):
                return str(value)
        for value in data.values():
            found = find_nested_value(value, names)
            if found:
                return found
    if isinstance(data, list):
        for item in data:
            found = find_nested_value(item, names)
            if found:
                return found
    return None


def get_visit_by_id(visit_id):
    response = roistat_call(
        "/project/site/visit/list",
        body={
            "filters": [["id", "=", str(visit_id)]],
            "limit": 1,
            "offset": 0,
        },
    )
    visits = response.get("visits") or response.get("data") or []
    return visits[0] if visits else None


def get_latest_visit_id_by_phone(phone):
    clients_response = roistat_call(
        "/project/clients",
        body={"filters": [["phone", "=", phone]], "limit": 10, "offset": 0},
    )
    clients = clients_response.get("clients") or []
    visit_events = []
    for client in clients:
        client_id = client.get("id")
        if not client_id:
            continue
        feed = roistat_call(
            "/project/clients/detail/feed",
            query={"client": str(client_id)},
            method="GET",
        ).get("feed", [])
        visit_events.extend(item for item in feed if item.get("type") == "visit" and item.get("visitId"))
    if not visit_events:
        return None
    visit_events.sort(key=lambda item: item.get("creationDate") or "", reverse=True)
    return str(visit_events[0]["visitId"])


def find_metrika_client_id_by_calltracking(phone):
    response = roistat_call(
        "/project/calltracking/call/list",
        body={
            "filters": {"and": [["caller", "=", phone]]},
            "extend": ["visit", "order"],
            "limit": 10,
            "offset": 0,
        },
    )
    calls = response.get("data") or []
    calls.sort(key=lambda item: item.get("date") or "", reverse=True)
    for call in calls:
        value = find_nested_value(
            call,
            {"yandex_client_id", "metrika_client_id", "ym_client_id", "ym_uid", "_ym_uid"},
        )
        if value:
            return value, str(call.get("visit_id") or "")
    return None, None


def get_order_info(order_id):
    response = roistat_call(f"/project/orders/{order_id}/info", method="GET")
    order = response.get("order") or {}
    visits = response.get("visits") or []
    return order, visits


def find_metrika_client_id_in_order(deal_id):
    try:
        order, visits = get_order_info(deal_id)
    except IntegrationError as error:
        if "resource_not_found" in str(error):
            return None, None
        raise
    candidates = []
    if order:
        candidates.append(order)
        if order.get("visit"):
            candidates.append(order["visit"])
    candidates.extend(visits)

    for candidate in candidates:
        value = find_nested_value(
            candidate,
            {"yandex_client_id", "metrika_client_id", "ym_client_id", "ym_uid", "_ym_uid"},
        )
        if value:
            visit_id = candidate.get("id") or candidate.get("visit_id") or order.get("visit_id")
            return value, str(visit_id or "")

    visit_id = order.get("visit_id")
    if visit_id:
        visit = get_visit_by_id(visit_id)
        if visit:
            value = find_nested_value(
                visit,
                {"yandex_client_id", "metrika_client_id", "ym_client_id", "ym_uid", "_ym_uid"},
            )
            if value:
                return value, str(visit_id)

    return None, None


def find_metrika_client_id(deal_id, deal):
    deal_value = find_nested_value(
        deal,
        {"yandex_client_id", "metrika_client_id", "ym_client_id", "ym_uid", "_ym_uid", "uf_crm_dct_ya_cid"},
    )
    if deal_value:
        return deal_value, str(deal.get("UF_CRM_ROISTAT") or "")

    field = CONFIG["bitrix_roistat_visit_field"]
    visit_id = str(deal.get(field) or "").strip() if field else ""

    if not visit_id:
        value, order_visit_id = find_metrika_client_id_in_order(deal_id)
        if value:
            return value, order_visit_id

    if not visit_id:
        for phone in find_deal_phones(deal):
            value, call_visit_id = find_metrika_client_id_by_calltracking(phone)
            if value:
                return value, call_visit_id

    if not visit_id:
        for phone in find_deal_phones(deal):
            visit_id = get_latest_visit_id_by_phone(phone)
            if visit_id:
                break

    if not visit_id:
        raise IntegrationError("Roistat visit was not found by deal field or phone")

    visit = get_visit_by_id(visit_id)
    if not visit:
        raise IntegrationError(f"Roistat visit {visit_id} was not found")

    value = find_nested_value(
        visit,
        {"yandex_client_id", "metrika_client_id", "ym_client_id", "ym_uid", "_ym_uid"},
    )
    if not value:
        raise IntegrationError(f"Metrika Client ID was not found in Roistat visit {visit_id}")
    return value, visit_id


def update_deal_metrika(deal_id, metrika_client_id):
    field = CONFIG["bitrix_metrika_field"]
    if not field:
        raise IntegrationError("BITRIX_METRIKA_FIELD is empty")
    return bitrix_call(
        "crm.deal.update",
        {"id": deal_id, "fields": {field: str(metrika_client_id)}, "params": {"REGISTER_SONET_EVENT": "N"}},
    )


def process_deal_created(payload):
    deal_id = find_deal_id(payload)
    try:
        deal = get_deal(deal_id)
    except IntegrationError as error:
        if "not found" in str(error).lower() or "bad request" in str(error).lower():
            return {"status": "skipped", "deal_id": deal_id, "reason": "deal_not_available"}
        raise
    if not deal:
        raise IntegrationError(f"Deal {deal_id} was not found")

    if not deal_looks_like_megafon(deal):
        log(f"deal {deal_id}: skipped, source does not match MEGAFON_MATCH")
        return {"status": "skipped", "deal_id": deal_id, "reason": "source_mismatch"}

    existing_value = str(deal.get(CONFIG["bitrix_metrika_field"], "")).strip()
    if existing_value:
        return {"status": "skipped", "deal_id": deal_id, "reason": "field_already_filled"}

    metrika_client_id, visit_id = find_metrika_client_id(deal_id, deal)
    update_deal_metrika(deal_id, metrika_client_id)
    return {
        "status": "updated",
        "deal_id": deal_id,
        "roistat_visit_id": visit_id,
        "metrika_client_id": metrika_client_id,
    }


def check_secret(handler):
    query = parse_qs(urlparse(handler.path).query)
    given = query.get("secret", [""])[0]
    expected = CONFIG["secret"]
    if expected and given != expected:
        raise IntegrationError("Invalid secret")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        log(fmt % args)

    def send_json(self, status, payload):
        raw = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            self.send_json(200, {"status": "ok"})
            return
        self.send_json(404, {"error": "not_found"})

    def do_POST(self):
        try:
            check_secret(self)
            path = urlparse(self.path).path
            payload = parse_body(self)

            if path == "/bitrix/deal-created":
                result = process_deal_created(payload)
                self.send_json(200, result)
                return

            if path == "/manual/update":
                deal_id = str(payload.get("deal_id") or payload.get("DEAL_ID") or "")
                metrika_client_id = str(payload.get("metrika_client_id") or "")
                if not deal_id or not metrika_client_id:
                    raise IntegrationError("deal_id and metrika_client_id are required")
                update_deal_metrika(deal_id, metrika_client_id)
                self.send_json(200, {"status": "updated", "deal_id": deal_id})
                return

            self.send_json(404, {"error": "not_found"})
        except Exception as error:
            traceback.print_exc()
            self.send_json(500, {"status": "error", "message": str(error)})


def validate_startup_config():
    missing = []
    for key in ("bitrix_webhook_url", "bitrix_metrika_field", "roistat_project_id", "roistat_api_key"):
        if not CONFIG[key]:
            missing.append(key.upper())
    if missing:
        log("warning: missing config values: " + ", ".join(missing))


def main():
    validate_startup_config()
    server = ThreadingHTTPServer((CONFIG["host"], CONFIG["port"]), Handler)
    log(f"listening on http://{CONFIG['host']}:{CONFIG['port']}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("stopping")
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(str(error), file=sys.stderr)
        sys.exit(1)
