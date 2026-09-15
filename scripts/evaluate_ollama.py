"""실행 중인 Mori SSE API를 순차 평가하고 원본 결과와 지연 시간을 저장한다."""

import argparse
import asyncio
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx


CASES = [
    {"id": "greeting", "question": "안녕! 한 문장으로 자기소개해줘.", "tools": [], "contains": ["Mori", "모리"]},
    {"id": "calculate", "question": "1250000원에서 15% 할인한 가격을 계산해줘.", "tools": ["calculate"], "contains": ["1,062,500", "1062500", "106만 2500", "106만 2,500"]},
    {"id": "datetime", "question": "한국은 지금 몇 월 며칠 무슨 요일이야? 시간도 알려줘.", "tools": ["get_current_datetime"]},
    {"id": "memory", "question": "내 이름과 좋아하는 언어가 뭐였지?", "tools": None,
     "history": [{"role": "user", "content": "내 이름은 민수이고 Python을 좋아해."}, {"role": "assistant", "content": "민수님, Python을 좋아하시는군요."}], "contains_all": ["민수", "Python"]},
    {"id": "conversation_search", "question": "이전 대화를 검색해서 내가 말한 서버 메모리 용량을 찾아줘.", "tools": ["search_conversation"],
     "history": [{"role": "user", "content": "서버 메모리는 3.7 GiB야."}, {"role": "assistant", "content": "서버 메모리 정보를 확인했어요."}], "contains": ["3.7"]},
    {"id": "knowledge", "question": "프로젝트 문서에서 Ollama 실행 방법을 검색하고 해당 문서를 읽어서 명령어와 출처를 알려줘.", "tools": ["search_knowledge", "read_knowledge"], "contains": ["ollama run"]},
    {"id": "disabled", "question": "0.1+0.2는? 짧게 답해줘.", "use_tools": False, "tools": [], "contains": ["0.3"]},
]


async def run_case(client, case):
    start = time.perf_counter()
    row = {"id": case["id"], "question": case["question"], "first_text_seconds": None,
           "tool_events": [], "answer": "", "done": False, "error": None}
    payload = {"messages": case.get("history", []) + [{"role": "user", "content": case["question"]}],
               "use_tools": case.get("use_tools", True), "think": False}
    event = ""
    try:
        async with asyncio.timeout(240):
            async with client.stream("POST", "/api/chat/stream", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if line.startswith("event: "):
                        event = line[7:]
                    elif line.startswith("data: "):
                        data = json.loads(line[6:])
                        if event == "delta":
                            if row["first_text_seconds"] is None:
                                row["first_text_seconds"] = round(time.perf_counter() - start, 3)
                            row["answer"] += data["text"]
                        elif event == "tool":
                            row["tool_events"].append({**data, "elapsed_seconds": round(time.perf_counter() - start, 3)})
                        elif event == "done":
                            row["done"] = True
                            row["answer"] = data["message"]["content"]
                        elif event == "error":
                            row["error"] = data
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"
    row["total_seconds"] = round(time.perf_counter() - start, 3)
    names = [tool["name"] for tool in row["tool_events"]]
    expected = case["tools"]
    row["tool_selection_pass"] = (True if expected is None else
        (names == [] if expected == [] else all(name in names for name in expected)))
    answer = row["answer"].casefold()
    row["answer_check_pass"] = (
        any(word.casefold() in answer for word in case["contains"]) if "contains" in case else
        all(word.casefold() in answer for word in case["contains_all"]) if "contains_all" in case else None)
    row["passed"] = row["done"] and not row["error"] and row["tool_selection_pass"] and row["answer_check_pass"] is not False
    return row


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default="artifacts/ollama-evaluation.json")
    args = parser.parse_args()
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    report = {"started_at": datetime.now(UTC).isoformat(), "url": args.url,
              "method": "Sequential, one sample per case, think=false. First case includes cold-start if unloaded. Keyword checks are not full semantic grading.", "results": []}
    async with httpx.AsyncClient(base_url=args.url, timeout=240) as client:
        health = await client.get("/api/health")
        health.raise_for_status()
        report["health"] = health.json()
        for case in CASES:
            row = await run_case(client, case)
            report["results"].append(row)
            path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps(row, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    asyncio.run(main())
