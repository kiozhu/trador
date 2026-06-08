"""LLM scorer — score execution quality only, never changes strategy"""
import requests
from ..utils.logger import log


class LLMScorer:
    def __init__(self, api_key: str, base_url: str = "https://api.minimax.io/anthropic",
                 model: str = "MiniMax-M3"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def score(self, trade: dict) -> dict:
        """Score a trade's execution quality. Returns {score, reason, lesson}."""
        prompt = f"""Kamu adalah EXECUTION SCORER. Nilai kualitas eksekusi trade.

Trade:
- Symbol: {trade.get('symbol')}
- Side: {trade.get('side')}
- Entry: ${trade.get('entry_price'):.2f}
- Exit: ${trade.get('exit_price'):.2f}
- Hold: {trade.get('hold_minutes', 0)} menit
- PnL: {trade.get('pnl_pct'):.2f}%
- Strategy: {trade.get('strategy_id')}
- Exit reason: {trade.get('exit_reason')}

Penilaian 1-10 untuk:
1. Entry timing — entry di harga yang bagus?
2. Exit timing — exit di waktu yang tepat?
3. Risk management — SL/TP dihitung benar?
4. Overall execution

Jawaban format:
Score: <nilai 1-10>
Reason: <1-2 kalimat>
Lesson: <lesson jika ada, kosongkan jika tidak>
"""
        try:
            response = requests.post(
                f"{self.base_url}/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=30,
            )
            if response.status_code == 200:
                text = response.json()["choices"][0]["message"]["content"]
                return self._parse_response(text)
            else:
                log.error("LLM scoring failed: %s", response.status_code)
        except Exception as e:
            log.error("LLM scoring error: %s", e)
        return {"score": 5, "reason": "LLM unavailable", "lesson": ""}

    def _parse_response(self, text: str) -> dict:
        result = {"score": 5, "reason": "", "lesson": ""}
        for line in text.split("\n"):
            if line.startswith("Score:"):
                try:
                    result["score"] = int(line.split(":")[1].strip())
                except ValueError:
                    pass
            elif line.startswith("Reason:"):
                result["reason"] = line.split(":")[1].strip()
            elif line.startswith("Lesson:"):
                result["lesson"] = line.split(":")[1].strip()
        return result