from mcp_server_recall_fixed import EXAM_PASSAGES


TESTS = [
    {
        "question": "What is the backup call sign for Meridian Trench Research Station?",
        "expected": ["Umbral Two"],
        "keywords": ["Umbral Two", "backup"]
    },
    {
        "question": "How often is Meridian resupplied?",
        "expected": ["19 days"],
        "keywords": ["Resupply", "19 days"]
    },
    {
        "question": "When did the Russet signal relay fault occur?",
        "expected": ["5 Jan", "5 January"],
        "keywords": ["Russet", "5 Jan"]
    },
    {
        "question": "What is the first-month driving limit at Ashgrove?",
        "expected": ["40min", "40 min", "40 minutes"],
        "keywords": ["first-month", "40min"]
    },
    {
        "question": "What dose was used in the Velmara pilot?",
        "expected": ["180mg", "180 mg"],
        "keywords": ["pilot", "180mg"]
    },
    {
        "question": "Which proposed Velmara dose was never used?",
        "expected": ["210mg", "210 mg"],
        "keywords": ["210mg", "never used"]
    },
    {
        "question": "What is the console texture-memory ceiling in Hollowlight Engine?",
        "expected": ["512MB", "512 MB"],
        "keywords": ["console", "512MB"]
    },
    {
        "question": "What is Hollowlight's emergency build tag?",
        "expected": ["Driftglass Two"],
        "keywords": ["emergency", "Driftglass Two"]
    },
    {
        "question": "At what moisture level is Thornmere grain downgraded?",
        "expected": ["18%"],
        "keywords": ["Grain", "18%"]
    },
    {
        "question": "What is Thornmere Two used for?",
        "expected": [
            "internal grading disputes",
            "grading disputes"
        ],
        "keywords": ["Thornmere Two", "grading disputes"]
    }
]


def find_relevant_passage(keywords):
    for passage in EXAM_PASSAGES:
        lower = passage.lower()

        if all(keyword.lower() in lower for keyword in keywords):
            return passage

    return None


passed = 0

for i, test in enumerate(TESTS, start=1):

    print("=" * 80)
    print(f"TEST {i}")
    print("QUESTION:")
    print(test["question"])
    print()

    passage = find_relevant_passage(test["keywords"])

    if passage is None:
        print("FAIL: No matching passage found.")
        continue

    print("MATCHING PASSAGE:")
    print(passage)
    print()

    found_answer = any(
        answer.lower() in passage.lower()
        for answer in test["expected"]
    )

    if found_answer:
        print("PASS")
        print("Expected answer:", test["expected"][0])
        passed += 1
    else:
        print("FAIL: Passage found, but expected answer is missing.")
        print("Expected:", test["expected"])

print()
print("=" * 80)
print(f"RESULT: {passed}/{len(TESTS)} tests passed")