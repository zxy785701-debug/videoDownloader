"""Opt-in real, billable acceptance using the user's local DeepSeek configuration.

Never loads/prints keys. Calls localhost learning endpoints. Requests are idempotent.
"""

import hashlib
import json
import sys
import time
from pathlib import Path

import httpx


QUESTIONS = [
    ("视频开头准备去哪个城市？", "supported", ["LA", "洛杉矶"]),
    ("薛仑娥为什么说看不清？", "supported", ["隐形"]),
    ("裴真率说巡演期间会一直穿哪件外套？", "supported", ["薄荷"]),
    ("裴真率来到健身房之前在哪里开演唱会？", "supported", ["纽约"]),
    ("视频最后成员们分别收到了哪些礼物？", "supported", ["花生酱", "饼干"]),
    ("其中裴真率收到的礼物是什么，谁挑选的？", "supported", ["花生酱", "朴珍"]),
    ("这段视频拍摄相机的具体型号和参数是什么？", "insufficient", []),
    ("视频最后一帧左上角的像素 RGB 值是多少？", "insufficient", []),
]


def wait_job(client, job_id, deadline):
    while time.monotonic() < deadline:
        # Latest jobs includes one job per kind; this probe submits sequential chat.
        for record in client.get("/api/v1/analyses").json()["items"]:
            detail = client.get("/api/v1/analyses/" + record["id"]).json()
            job = next((j for j in detail["jobs"] if j["id"] == job_id), None)
            if job and job["status"] not in {"queued", "processing"}:
                return job
        time.sleep(1)
    return {"status": "timeout", "error_code": "PROBE_WAIT_TIMEOUT"}


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    folder = Path(__file__).resolve().parents[2] / ".local" / "learning-real-probes"
    sources = json.loads((folder / "api-results.json").read_text(encoding="utf-8"))
    report = {"simulation": False, "summaries": [], "questions": []}
    with httpx.Client(base_url="http://127.0.0.1:8181", timeout=20, trust_env=False) as client:
        config = client.get("/api/v1/ai/config").json()
        if not config.get("configured"):
            raise SystemExit("Local AI key is not configured")
        report["model"] = config["model"]
        pending = []
        for record in sources:
            if record["status"] != "ready":
                continue
            began = time.monotonic()
            response = client.post(f"/api/v1/analyses/{record['id']}/summary", json={})
            response.raise_for_status()
            pending.append((record, response.json(), began))
        for record, task, began in pending:
            job = wait_job(client, task["job_id"], time.monotonic() + 910) if task["job_id"] else {"status": "ready"}
            result = client.get(f"/api/v1/analyses/{record['id']}/summary").json()
            report["summaries"].append({"platform": record["platform"], "id": record["id"], "status": job["status"],
                                        "error_code": job.get("error_code"), "elapsed_seconds": round(time.monotonic() - began, 2),
                                        "result": result})
        youtube = next(r for r in sources if r["platform"] == "YouTube" and r["status"] == "ready")
        cues = json.loads((folder / "youtube-transcript.json").read_text(encoding="utf-8"))["cues"]
        allowed = {c["id"] for c in cues}
        for question, evidence, terms in QUESTIONS:
            began = time.monotonic()
            request_id = "real-acceptance-" + hashlib.sha256(question.encode()).hexdigest()[:24]
            response = client.post(f"/api/v1/analyses/{youtube['id']}/chat", json={"question": question, "request_id": request_id})
            response.raise_for_status()
            task = response.json()
            job = {"status": "ready"} if task.get("cached") else wait_job(client, task["job_id"], time.monotonic() + 190)
            messages = client.get(f"/api/v1/analyses/{youtube['id']}/messages").json()["items"]
            message = next(m for m in messages if m["id"] == task["message_id"])
            answer = message.get("answer")
            passed = bool(answer and message["status"] == "ready" and answer["evidence"] == evidence
                          and set(answer["cue_ids"]) <= allowed
                          and (not terms or any(term.lower() in answer["answer"].lower() for term in terms)))
            report["questions"].append({"question": question, "expected_evidence": evidence, "passed": passed,
                                        "elapsed_seconds": round(time.monotonic() - began, 2), "message": message})
            (folder / "ai-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
            print(json.dumps({"question_number": len(report["questions"]), "status": job["status"], "passed": passed,
                              "evidence": answer["evidence"] if answer else None}, ensure_ascii=False), flush=True)
        report["usage"] = {r["platform"]: client.get("/api/v1/analyses/" + r["id"]).json()["usage"] for r in sources if r["status"] == "ready"}
    (folder / "ai-results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"model": report["model"], "summaries": [{"platform": r["platform"], "status": r["status"], "seconds": r["elapsed_seconds"]} for r in report["summaries"]],
                      "questions_passed": sum(q["passed"] for q in report["questions"]), "questions_total": len(report["questions"]), "usage": report["usage"]}), flush=True)


if __name__ == "__main__":
    main()
