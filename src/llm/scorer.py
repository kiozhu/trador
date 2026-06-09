"""LLM scorer — score execution quality + smart position sizing"""
import requests
from ..utils.logger import log


class LLMScorer:
    def __init__(self, api_key: str, base_url: str = "https://api.minimax.io/anthropic",
                 model: str = "MiniMax-M3"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model

    def position_size(self, balance: float, signal: dict, regime: str) -> float:
        """Calculate position size % using LLM analysis.
        Returns % of balance to risk (1.0 to max_position_pct).
        """
        prompt = f"""Kamu adalah POSITION SIZER untuk futures trading.

Context:
- Balance: ${balance:,.2f}
- Signal: {signal.get('symbol')} {signal.get('side')} @ ${signal.get('entry_price'):.4f}
- Score: {signal.get('score', 0)}/100
- Regime: {regime}
- Scanners: {', '.join(signal.get('scanner_signals', []))}

Rules:
- Max risk: 20% of balance per trade
- Safe: 5-10% | Medium: 10-15% | Aggressive: 15-20%
- Higher score = larger size
- Bearish regime = smaller size (reduce exposure)
- Whale/Liquidation signals = +3-5% size

Return ONLY a number (1-20) representing % of balance to use.
Example: 12.5
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
                    "max_tokens": 10,
                    "messages": [{"role": "user", "content": prompt}],
                },
                timeout=20,
            )
            if response.status_code == 200:
                text = response.json()["choices"][0]["message"]["content"].strip()
                # Extract number
                import re
                nums = re.findall(r"\d+\.?\d*", text)
                if nums:
                    pct = float(nums[0])
                    # Clamp between 1 and 20
                    return max(1.0, min(20.0, pct))
        except Exception as e:
            log.debug("LLM position sizing error: %s", e)
        # Fallback: rule-based
        score = signal.get("score", 50)
        base_pct = min(20, max(5, score / 5))  # score 50→10%, score 100→20%
        if regime == "bearish":
            base_pct *= 0.7
        return round(base_pct, 1)

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