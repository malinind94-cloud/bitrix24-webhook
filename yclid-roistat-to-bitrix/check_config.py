#!/usr/bin/env python3
import json
import os
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import server


def post_json(url, body=None, headers=None):
    data = json.dumps(body or {}).encode("utf-8")
    request = Request(url, data=data, method="POST", headers=headers or {"Content-Type": "application/json"})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def get_json(url, headers=None):
    request = Request(url, method="GET", headers=headers or {})
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main():
    cfg = server.CONFIG
    errors = []

    bitrix_base = cfg["bitrix_webhook_url"]
    if not bitrix_base:
        errors.append("BITRIX_WEBHOOK_URL is empty")
    else:
        profile = post_json(bitrix_base + "profile.json")
        if profile.get("error"):
            errors.append("Bitrix profile failed: " + str(profile.get("error_description") or profile.get("error")))
        else:
            print("Bitrix profile: ok")

        fields = post_json(bitrix_base + "crm.deal.fields.json")
        field_code = cfg["bitrix_metrika_field"]
        if fields.get("error"):
            errors.append("Bitrix crm.deal.fields failed: " + str(fields.get("error_description") or fields.get("error")))
        elif field_code not in fields.get("result", {}):
            errors.append(f"Bitrix deal field was not found: {field_code}")
            close = [key for key in fields.get("result", {}) if "AMO" in key or "WHRF" in key or "YM" in key]
            if close:
                print("Similar Bitrix fields: " + ", ".join(close[:20]))
        else:
            print(f"Bitrix deal field: ok ({field_code})")

    if not cfg["roistat_project_id"] or not cfg["roistat_api_key"]:
        errors.append("Roistat project id or api key is empty")
    else:
        roistat = get_json(
            "https://cloud.roistat.com/api/v1/user/projects",
            headers={"Api-key": cfg["roistat_api_key"]},
        )
        if roistat.get("status") not in (None, "success"):
            errors.append("Roistat API failed: " + str(roistat))
        else:
            project_ids = {str(project.get("id")) for project in roistat.get("projects", [])}
            if str(cfg["roistat_project_id"]) not in project_ids:
                errors.append(f"Roistat project is not available for this API key: {cfg['roistat_project_id']}")
            else:
                print(f"Roistat API: ok (project {cfg['roistat_project_id']})")

    if errors:
        print("")
        print("Problems:")
        for error in errors:
            print("- " + error)
        return 1

    print("")
    print("Config looks ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
