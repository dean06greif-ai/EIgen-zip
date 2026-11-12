"""Majors-Testlauf: Autopilot je Coin (4h, 720 Tage) inkl. Makro-Stufe, ohne DB.
Aufruf: python scripts/majors_macro_run.py BTCUSDT[,ETHUSDT,...] [minuten]  -> /tmp/majors/<coin>.json"""
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
for k, v in (("ADMIN_PASSWORD", "x"), ("ADMIN_USER", "Admin"), ("JWT_SECRET", "x")):
    os.environ.setdefault(k, v)


async def main(symbol: str, minutes: float):
    from services import regime_lab as lab, regime_autopilot
    body = {"symbols": symbol.split(","), "timeframe": "4h", "days": 720, "max_minutes": minutes,
            "seed": 626, "macro_stage": True, "warm_start": False}
    jid = lab.create_job("autopilot", body)
    await regime_autopilot.run_autopilot(jid, body, None)
    job = lab.JOBS[jid]
    out = Path("/tmp/majors")
    out.mkdir(exist_ok=True)
    (out / f"{symbol.replace(',', '_')}.json").write_text(json.dumps(
        {"status": job.get("status"), "error": job.get("error"), "result": job.get("result")},
        default=str))
    print(symbol, job.get("status"), job.get("error"))


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], float(sys.argv[2]) if len(sys.argv) > 2 else 10))
