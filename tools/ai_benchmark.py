"""Isolated, transcript-only AI provider benchmark; never imported by production."""
from __future__ import annotations
import argparse, json, os, re, sys, time, urllib.error, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Allow direct execution from the tools directory without changing the
# production package layout.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import config
from ai.ai import chunk_transcript
from models import Clip, Timestamp
from transcript.transcript import load_transcript

DEFAULT_TRANSCRIPT = Path(config.TRANSCRIPT_FOLDERS["youtube"]) / "aircAruvnKk.txt"
DEFAULT_OUTPUT = ROOT / "tools" / "benchmark_output"
CATEGORIES = {
    "interesting": "surprising, unusual, fascinating, controversial, or highly engaging moments",
    "educational": "useful concepts, explanations, facts, lessons, or insights",
    "funny": "jokes, funny stories, unexpected moments, punchlines, or humorous reactions",
    "scary": "disturbing, frightening, tense, creepy, shocking, or unsettling moments",
}
OPENROUTER_MODELS = (
    "deepseek/deepseek-v4-flash-0731",
    "z-ai/glm-5.2:free",
    "nvidia/nemotron-3-super-120b-a12b:free",
    "qwen/qwen3.8-27b",
)

CLIP_SCHEMA = {
    "type": "object",
    "properties": {
        "clips": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "start": {"type": "string"},
                    "end": {"type": "string"},
                    "title": {"type": "string"},
                    "reason": {"type": "string"},
                    "score": {"type": "number"},
                },
                "required": ["start", "end", "title", "reason", "score"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["clips"],
    "additionalProperties": False,
}

def prompt(category: str, text: str, index: int, total: int) -> str:
    return f'''You are an expert short-form video editor.

Given the following timestamped transcript, identify the strongest contiguous sections that could become compelling short-form clips. This is transcript-only analysis; do not assume access to the video or audio.

Selected category: {category}
Find moments matching this category: {CATEGORIES[category]}.

Rules:
* Do not invent dialogue or change what the speaker said.
* Every clip must correspond to a contiguous section of the provided transcript.
* Start and end timestamps must come from the transcript timing.
* Prefer clips with a strong beginning and satisfying ending.
* Avoid clips that begin or end in the middle of an important sentence unless necessary.
* Return 5–10 candidate clips when supported.
* Score each clip from 1–10.
* This is transcript chunk {index + 1} of {total}; select only moments present in this chunk.
* Do not explain your reasoning or provide chain-of-thought.
* Do not include commentary, analysis, markdown, or any text outside the JSON object.
* Keep titles and reasons concise.
* Return ONLY the required JSON object.

Return this exact JSON shape:
{{"clips":[{{"start":"HH:MM:SS","end":"HH:MM:SS","title":"...","reason":"...","score":9.2}}]}}

Timestamped transcript:
{text}'''

def post(url: str, payload: dict[str, Any], headers: dict[str, str]) -> tuple[dict[str, Any] | None, str, int | None, float]:
    started = time.perf_counter()
    request_headers = {"Content-Type": "application/json"}
    request_headers.update(headers)
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), headers=request_headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode()), "", response.status, time.perf_counter() - started
    except urllib.error.HTTPError as exc:
        return None, exc.read().decode(errors="replace")[:500], exc.code, time.perf_counter() - started
    except Exception as exc:
        return None, str(exc), None, time.perf_counter() - started

def gemini(model: str, text: str):
    key = os.environ.get("GEMINI_API_KEY", "")
    if not key: return None, "credential unavailable", None, 0.0
    return post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}", {"contents":[{"parts":[{"text":text}]}], "generationConfig":{"temperature":0.3,"topP":0.9,"maxOutputTokens":4096}}, {})

def openrouter(model: str, text: str):
    raw_key = os.environ.get("OPENROUTER_API_KEY")
    key = raw_key.strip() if raw_key else ""
    if not key: return None, "credential unavailable", None, 0.0
    return post("https://openrouter.ai/api/v1/chat/completions", {"model":model,"messages":[{"role":"user","content":text}],"temperature":0.3,"max_tokens":4096,"reasoning":{"effort":"none","exclude":True},"response_format":{"type":"json_schema","json_schema":{"name":"clip_candidates","strict":True,"schema":CLIP_SCHEMA}}}, {"Authorization":"Bearer " + key})

def groq(model: str, text: str):
    key = os.environ.get("GROQ_API_KEY", "")
    if not key: return None, "credential unavailable", None, 0.0
    return post("https://api.groq.com/openai/v1/chat/completions", {"model":model,"messages":[{"role":"user","content":text}],"temperature":0.3,"max_tokens":4096}, {"Authorization":f"Bearer {key}"})

def response_text(provider: str, body: dict[str, Any]) -> str | None:
    if not isinstance(body, dict):
        return None
    try:
        if provider == "Gemini":
            return body.get("candidates",[{}])[0].get("content",{}).get("parts",[{}])[0].get("text")
        return body.get("choices",[{}])[0].get("message",{}).get("content")
    except (IndexError, AttributeError, TypeError):
        return None

def usage(provider: str, body: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(body, dict):
        return {"input_tokens":None,"output_tokens":None,"total_tokens":None,"reported_cost":None}
    u = body.get("usageMetadata",{}) if provider == "Gemini" else body.get("usage",{})
    if not isinstance(u, dict):
        u = {}
    return {"input_tokens":u.get("promptTokenCount",u.get("prompt_tokens")),"output_tokens":u.get("candidatesTokenCount",u.get("completion_tokens")),"total_tokens":u.get("totalTokenCount",u.get("total_tokens")),"reported_cost":u.get("cost")}

def parse(raw: str | None):
    m = {"raw_candidates":0,"parsed_candidates":0,"invalid_json":0,"invalid_timestamps":0,"short_clips":0}
    if not isinstance(raw, str) or not raw.strip():
        m["invalid_json"] = 1
        return [], m
    raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw.strip()).strip()
    if not raw:
        m["invalid_json"] = 1
        return [], m
    try: data = json.loads(raw)
    except json.JSONDecodeError: m["invalid_json"] = 1; return [], m
    items = data if isinstance(data,list) else data.get("clips",[]) if isinstance(data,dict) else []
    if not isinstance(items,list): m["invalid_json"] = 1; return [], m
    m["raw_candidates"] = len(items); clips=[]
    for item in items:
        try:
            start, end = Timestamp.from_string(str(item["start"])), Timestamp.from_string(str(item["end"]))
            if end.to_seconds() - start.to_seconds() < 5: m["short_clips"] += 1; continue
            clips.append(Clip(len(clips)+1,start,end,str(item.get("title","Untitled")),str(item.get("reason","")),float(item.get("score",0))).to_dict())
        except (KeyError,ValueError,TypeError,AttributeError): m["invalid_timestamps"] += 1
    m["parsed_candidates"] = len(clips); return clips, m

def deduplicate(clips):
    ordered = sorted(clips, key=lambda c: float(c.get("score",0)), reverse=True); result=[]
    for clip in ordered:
        start = Timestamp.from_string(clip["start"]).to_seconds()
        if any(abs(start-Timestamp.from_string(old["start"]).to_seconds()) < 30 for old in result): continue
        result.append(clip)
    return result[:10], len(clips)-len(result)

def run(provider, model, caller, category, chunks, words):
    result={"provider":provider,"model":model,"category":category,"transcript_word_count":words,"transcript_chunks":len(chunks),"requests":0,"raw_candidates":0,"parsed_candidates":0,"invalid_json":0,"invalid_timestamps":0,"short_clips":0,"duplicate_clips":0,"final_valid_clips":0,"average_score":None,"latency_seconds":0.0,"usage":{"input_tokens":0,"output_tokens":0,"total_tokens":0,"reported_cost":None},"errors":[],"clips":[],"raw_responses":[],"raw_response_bodies":[]}
    all_clips=[]
    for i, text in enumerate(chunks):
        result["requests"] += 1
        try:
            body, error, status, latency = caller(model,prompt(category,text,i,len(chunks)))
        except Exception as exc:
            result["errors"].append({"status":None,"type":"provider_exception","message":str(exc)})
            continue
        result["latency_seconds"] += latency
        if error: result["errors"].append({"status":status,"type":"http" if status else "request","message":error}); continue
        raw=response_text(provider,body or {})
        result["raw_responses"].append(raw)
        result["raw_response_bodies"].append(body or {})
        if not isinstance(raw, str) or not raw.strip():
            result["errors"].append({"status":status,"type":"empty_response","message":"Provider returned no response content"})
        u=usage(provider,body or {})
        for k in ("input_tokens","output_tokens","total_tokens"):
            if u[k] is not None: result["usage"][k] += u[k]
        if u["reported_cost"] is not None: result["usage"]["reported_cost"] = u["reported_cost"]
        clips, metrics=parse(raw)
        for k,v in metrics.items(): result[k] += v
        all_clips.extend(clips)
    final, duplicates=deduplicate(all_clips); result["duplicate_clips"]=duplicates; result["final_valid_clips"]=len(final); result["clips"]=final; result["latency_seconds"]=round(result["latency_seconds"],3)
    if final: result["average_score"]=round(sum(float(c["score"]) for c in final)/len(final),2)
    return result

def report(payload):
    grouped={}
    for item in payload["results"]: grouped.setdefault((item["provider"],item["model"]),{})[item["category"]]=item
    lines=["# ClipperOS AI Benchmark",f"Generated: {payload['generated_at']}",f"Transcript: `{payload['transcript']}` ({payload['word_count']} words, {payload['chunks']} chunks)","","## Provider/model comparison","","| Provider | Model | Interesting | Educational | Funny | Scary | JSON reliability | Timestamp reliability | Latency | Cost |","|---|---|---:|---:|---:|---:|---|---|---:|---:|"]
    for (provider,model), categories in grouped.items():
        values=[]
        for category in CATEGORIES:
            item=categories[category]; values.append(str(item.get("final_valid_clips","skipped")) if item.get("requests",0) else "skipped")
        attempted=[item for item in categories.values() if item.get("requests",0)]
        json_ok="yes" if attempted and all(item.get("invalid_json",0)==0 and not item.get("errors") for item in attempted) else "no/unknown"
        timestamp_ok="yes" if attempted and all(item.get("invalid_timestamps",0)==0 for item in attempted) else "no/unknown"
        latency=round(sum(item.get("latency_seconds",0) for item in attempted)/len(attempted),3) if attempted else "—"
        cost=next((item.get("usage",{}).get("reported_cost") for item in attempted if item.get("usage",{}).get("reported_cost") is not None),"unknown")
        lines.append(f"| {provider} | `{model}` | " + " | ".join(values) + f" | {json_ok} | {timestamp_ok} | {latency} | {cost} |")
    lines += ["","## Detailed category metrics","","| Provider | Model | Category | Final clips | JSON errors | Latency | Cost |","|---|---|---|---:|---:|---:|---:|"]
    for r in payload["results"]:
        lines.append(f"| {r['provider']} | `{r['model']}` | {r['category']} | {r.get('final_valid_clips','—')} | {r.get('invalid_json','—')} | {r.get('latency_seconds','—')} | {r.get('usage',{}).get('reported_cost','unknown')} |")
    lines += ["","## Returned clips"]
    for r in payload["results"]:
        lines.append(f"### {r['provider']} / `{r['model']}` / {r['category']}")
        if r.get("errors"): lines.append(f"Errors: `{json.dumps(r['errors'],ensure_ascii=False)}`")
        for c in r.get("clips",[]): lines.append(f"- **{c['start']}–{c['end']}** — {c['title']} (score {c['score']}) — {c['reason']}")
        if not r.get("clips"): lines.append("No valid clips returned.")
    return "\n".join(lines)+"\n"

def require_openrouter_key() -> str:
    raw_key = os.environ.get("OPENROUTER_API_KEY")
    key = raw_key.strip() if raw_key else ""
    if not key:
        raise SystemExit(
            "OPENROUTER_API_KEY is not visible to this Python process. "
            "Run the benchmark from a PowerShell session where "
            "$env:OPENROUTER_API_KEY is set."
        )
    print(
        f"OPENROUTER_API_KEY found (prefix: {key[:8]}..., length: {len(key)})",
        flush=True,
    )
    return key


def main():
    require_openrouter_key()
    ap=argparse.ArgumentParser(); ap.add_argument("--transcript",type=Path,default=DEFAULT_TRANSCRIPT); ap.add_argument("--output",type=Path,default=DEFAULT_OUTPUT); args=ap.parse_args()
    path=args.transcript.expanduser().resolve(); t=load_transcript(path.stem,"youtube")
    if t is None: raise SystemExit(f"Could not load cached transcript: {path}")
    chunks=chunk_transcript(t); payload={"generated_at":datetime.now(timezone.utc).isoformat(),"transcript":str(path),"word_count":t.word_count(),"chunks":len(chunks),"results":[]}
    specs=[("OpenRouter",m,openrouter,"OPENROUTER_API_KEY") for m in OPENROUTER_MODELS]
    for provider,model,caller,key in specs:
        for category in CATEGORIES:
            if not os.environ.get(key): payload["results"].append({"provider":provider,"model":model,"category":category,"requests":0,"errors":[{"type":"credential","message":f"{key} is unavailable"}],"clips":[]})
            else: print(f"Running {provider} / {model} / {category}...",flush=True); payload["results"].append(run(provider,model,caller,category,chunks,t.word_count()))
    args.output.mkdir(parents=True,exist_ok=True); (args.output/"benchmark_results.json").write_text(json.dumps(payload,indent=2,ensure_ascii=False),encoding="utf-8"); (args.output/"benchmark_report.md").write_text(report(payload),encoding="utf-8"); print(f"Saved benchmark results to {args.output}")

if __name__ == "__main__": main()
