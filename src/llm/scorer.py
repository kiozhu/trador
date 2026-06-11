"""LLM scorer — score execution quality + smart position sizing"""
import requests
from ..utils.logger import log

# Supported LLM providers and their endpoints
LLM_PROVIDERS = {
    "minimax": {
        "base_url": "https://api.minimax.io/v1",
        "model": "MiniMax-Text-01",
        "auth_header": "Bearer",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "auth_header": "Bearer",
    },
    "xiaomi": {
        "base_url": "https://platform.xiaomimimo.com/v1",
        "model": "MiMo-32K",
        "auth_header": "Bearer",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "auth_header": "Bearer",
    },
}


class LLMScorer:
    def __init__(self, api_key: str, provider: str = "minimax", model: str = ""):
        self.api_key = api_key
        self.provider = provider.lower()
        cfg = LLM_PROVIDERS.get(self.provider, LLM_PROVIDERS["minimax"])
        self.base_url = cfg["base_url"]
        self.model = model or cfg["model"]
        self.auth_header = cfg["auth_header"]

    def _post(self, messages: list, max_tokens: int = 100) -> dict | None:
        """Make a chat completion request. Returns JSON or None on failure."""
        try:
            headers = {
                "Authorization": f"{self.auth_header} {self.api_key}",
                "Content-Type": "application/json",
            }
            # Xiaomi MiMo uses different auth header
            if self.provider == "xiaomi":
                headers["X-Api-Key"] = self.api_key
                headers.pop("Authorization", None)

            response = requests.post(
                f"{self.base_url}/chat/completions",
                headers=headers,
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": messages,
                },
                timeout=30,
            )
            if response.status_code == 200:
                return response.json()
            else:
                log.error("LLM %s request failed: %s — %s",
                          self.provider, response.status_code, response.text[:200])
        except Exception as e:
            log.error("LLM %s request error: %s", self.provider, e)
        return None

    def test(self) -> dict:
        """Test LLM connection. Returns {'ok': bool, 'message': str}."""
        result = self._post(
            [{"role": "user", "content": "Hi, respond with 'OK' only."}],
            max_tokens=10,
        )
        if result:
            try:
                text = result["choices"][0]["message"]["content"].strip().lower()
                if "ok" in text:
                    return {"ok": True, "message": f"✅ {self.provider.upper()} connected — model: {self.model}"}
                return {"ok": False, "message": f"❌ Unexpected response: {text}"}
            except Exception as e:
                return {"ok": False, "message": f"❌ Parse error: {e}"}
        return {"ok": False, "message": f"❌ {self.provider.upper()} unreachable — check API key"}

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
        messages = [{"role": "user", "content": prompt}]
        result = self._post(messages, max_tokens=10)
        if result:
            try:
                text = result["choices"][0]["message"]["content"].strip()
                import re
                nums = re.findall(r"\d+\.?\d*", text)
                if nums:
                    pct = float(nums[0])
                    return max(1.0, min(20.0, pct))
            except Exception as e:
                log.debug("LLM position sizing parse error: %s", e)
        # Fallback: rule-based
        score = signal.get("score", 50)
        base_pct = min(20, max(5, score / 5))
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
        messages = [{"role": "user", "content": prompt}]
        result = self._post(messages, max_tokens=100)
        if result:
            try:
                text = result["choices"][0]["message"]["content"]
                return self._parse_response(text)
            except Exception as e:
                log.error("LLM scoring parse error: %s", e)
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