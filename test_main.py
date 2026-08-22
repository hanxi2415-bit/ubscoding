import unittest

from main import app, calculate_route


def payload():
    return {
        "start_coordinate": [0, 0],
        "end_coordinate": [2, 0],
        "start_time": "2026-06-10T08:30:00Z",
        "nodes": [[0, 0], [1, 0], [2, 0]],
        "edges": [
            {"edge_id": "edge_0", "node1": [0, 0], "node2": [1, 0], "base_duration_sec": 10},
            {"edge_id": "edge_1", "node1": [1, 0], "node2": [2, 0], "base_duration_sec": 10},
            {"edge_id": "edge_2", "node1": [0, 0], "node2": [2, 0], "base_duration_sec": 20},
        ],
        "obstructions": [
            {
                "edge_id": "edge_1", "edge": {"from": [1, 0], "to": [2, 0]},
                "start_time": "2026-06-10T08:30:10Z", "end_time": "2026-06-10T08:30:20Z",
                "speed_factor": 0,
            },
            {
                "edge_id": "edge_2", "edge": {"from": [0, 0], "to": [2, 0]},
                "start_time": "2026-06-10T08:30:00Z", "end_time": "2026-06-10T08:32:00Z",
                "speed_factor": 0.2,
            },
        ],
    }


class RouteTests(unittest.TestCase):
    def test_fastest_route_accounts_for_closure(self):
        self.assertEqual(calculate_route(payload()), {
            "total_duration_sec": 30,
            "arrival_time": "2026-06-10T08:30:30Z",
            "path": ["edge_0", "edge_1"],
        })

    def test_obstructions_are_directional(self):
        data = payload()
        data["start_coordinate"], data["end_coordinate"] = data["end_coordinate"], data["start_coordinate"]
        data["edges"] = data["edges"][:2]
        data["obstructions"] = data["obstructions"][:1]
        result = calculate_route(data)
        self.assertEqual(result["total_duration_sec"], 20)
        self.assertEqual(result["path"], ["edge_1", "edge_0"])

    def test_endpoint_and_same_start_end(self):
        data = payload()
        data["end_coordinate"] = [0, 0]
        response = app.test_client().post("/kan-cheong-delivery-driver", json=data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["total_duration_sec"], 0)
        self.assertEqual(response.get_json()["path"], [])

    def test_unreachable_destination(self):
        data = payload()
        data["edges"] = data["edges"][:1]
        data["obstructions"] = []
        self.assertIsNone(calculate_route(data)["arrival_time"])


if __name__ == "__main__":
    unittest.main()
