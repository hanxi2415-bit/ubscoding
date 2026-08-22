import base64
import json

## payload = str(input())
payload = "ewoJImFkYXB0SW5wdXQiOiB7CgkJInVzZXIiOiB7CgkJCSJpZCI6ICJVNDIiLAoJCQkiZnVsbE5hbWUiOiAiSmFuZSBEb2UiCgkJfSwKCQkiYWN0aW9uIjogIkNSRUFURSIsCgkJImV0YWRhdGEiOiB7CgkJCSJwcmlvcml0eSI6ICJISUdIIgoJCX0KCX0KfQ=="


def solve(payload: str):
    decoded = base64.b64decode(payload).decode("utf-8")
    data = json.loads(decoded)

    # print(decoded)

    priority_map = {
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3
    }

    priority = priority_map[data["adaptInput"]["metadata"]["priority"]]

    output = {
        "adaptOutput": {
            "id": data["adaptInput"]["user"]["id"],
            "name": data["adaptInput"]["user"]["fullName"],
            "action": data["adaptInput"]["action"].lower(),
            "priority": priority
        }
    }

    #print(output)

    output_json = json.dumps(output, indent=4)

    #print(output_json)
    return output_json
