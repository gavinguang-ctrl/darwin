from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def generate(self, prompt: str, system: str = "") -> str: ...


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o"):
        from config import OPENAI_PROXY_URL
        from openai import OpenAI
        import httpx
        self._is_proxy = bool(OPENAI_PROXY_URL)
        if OPENAI_PROXY_URL:
            http_client = httpx.Client(timeout=300, proxy=None)
            self.client = OpenAI(api_key=api_key, base_url=f"{OPENAI_PROXY_URL}/v1",
                                 http_client=http_client)
        else:
            self.client = OpenAI(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, system: str = "") -> str:
        import time
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        for attempt in range(3):
            try:
                if self._is_proxy:
                    chunks = []
                    stream = self.client.chat.completions.create(
                        model=self.model, messages=messages, stream=True)
                    for chunk in stream:
                        if chunk.choices and chunk.choices[0].delta.content:
                            chunks.append(chunk.choices[0].delta.content)
                    return "".join(chunks)
                else:
                    resp = self.client.chat.completions.create(model=self.model, messages=messages)
                    return resp.choices[0].message.content
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(3 + attempt * 3)


class AnthropicProvider(LLMProvider):
    _PROXY_MODEL_MAP = {
        "claude-sonnet-4-20250514": "claude-sonnet-4-6",
        "claude-opus-4-20250514": "claude-opus-4-6",
        "claude-opus-4-7": "claude-opus-4-7",
    }

    def __init__(self, api_key: str, model: str = "claude-opus-4-7"):
        from config import ANTHROPIC_PROXY_URL
        import httpx, anthropic
        self._is_proxy = bool(ANTHROPIC_PROXY_URL)
        if self._is_proxy:
            http_client = httpx.Client(timeout=300, proxy=None)
            self.client = anthropic.Anthropic(
                api_key=api_key,
                base_url=ANTHROPIC_PROXY_URL,
                http_client=http_client,
            )
        else:
            self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def generate(self, prompt: str, system: str = "") -> str:
        import time
        model = self._PROXY_MODEL_MAP.get(self.model, self.model) if self._is_proxy else self.model
        kwargs = {
            "model": model,
            "max_tokens": 16384,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system
        for attempt in range(3):
            try:
                if self._is_proxy:
                    chunks = []
                    with self.client.messages.stream(**kwargs) as stream:
                        for text in stream.text_stream:
                            chunks.append(text)
                    return "".join(chunks)
                else:
                    resp = self.client.messages.create(**kwargs)
                    return resp.content[0].text
            except Exception:
                if attempt == 2:
                    raise
                time.sleep(3 + attempt * 3)


class GoogleProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash", use_proxy: bool = True):
        from config import GOOGLE_PROXY_KEY, GOOGLE_PROXY_URL
        self._api_key = api_key
        self._proxy_key = GOOGLE_PROXY_KEY
        self._proxy_url = GOOGLE_PROXY_URL
        self.model = model
        self._use_proxy = use_proxy

    _PROXY_MODEL_MAP = {
        "gemini-3-flash-preview": "gemini-3-flash",
        "gemini-3.1-pro-preview": "gemini-3.1-pro-high",
    }

    def _try_proxy(self, prompt: str) -> str | None:
        if not self._proxy_key or not self._proxy_url:
            return None
        proxy_model = self._PROXY_MODEL_MAP.get(self.model, self.model)
        import time, httpx
        from openai import OpenAI
        for attempt in range(5):
            try:
                http_client = httpx.Client(timeout=300, proxy=None)
                client = OpenAI(api_key=self._proxy_key, base_url=f"{self._proxy_url}/v1",
                                http_client=http_client)
                chunks = []
                stream = client.chat.completions.create(
                    model=proxy_model, messages=[{"role": "user", "content": prompt}],
                    max_tokens=16384, stream=True,
                )
                for chunk in stream:
                    if chunk.choices and chunk.choices[0].delta.content:
                        chunks.append(chunk.choices[0].delta.content)
                text = "".join(chunks)
                if text:
                    return text
            except Exception:
                if attempt < 4:
                    time.sleep(3 + attempt * 3)
        return None

    def _try_direct(self, prompt: str) -> str:
        import os, time
        os.environ.setdefault("HTTP_PROXY", "http://127.0.0.1:7890")
        os.environ.setdefault("HTTPS_PROXY", "http://127.0.0.1:7890")
        from google import genai
        from google.genai.types import GenerateContentConfig, SafetySetting, HarmCategory
        safety = [
            SafetySetting(category=c, threshold="OFF")
            for c in [
                HarmCategory.HARM_CATEGORY_HARASSMENT,
                HarmCategory.HARM_CATEGORY_HATE_SPEECH,
                HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT,
                HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT,
                HarmCategory.HARM_CATEGORY_CIVIC_INTEGRITY,
            ]
        ]
        client = genai.Client(api_key=self._api_key)
        for attempt in range(5):
            try:
                if attempt > 0:
                    client = genai.Client(api_key=self._api_key)
                resp = client.models.generate_content(
                    model=self.model, contents=prompt,
                    config=GenerateContentConfig(safety_settings=safety),
                )
            except Exception as e:
                if attempt == 4:
                    raise
                time.sleep(3 + attempt * 3)
                continue
            if resp.text is not None:
                return resp.text
            if resp.prompt_feedback and resp.prompt_feedback.block_reason:
                raise ValueError(f"Google内容过滤拦截: {resp.prompt_feedback.block_reason}")
            time.sleep(1 + attempt)
        raise ValueError("Google API 重试均返回空")

    def generate(self, prompt: str, system: str = "") -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        if self._use_proxy:
            result = self._try_proxy(full_prompt)
            if result:
                return result
        return self._try_direct(full_prompt)


_GOOGLE_MODELS = ["gemini-3-flash-preview", "gemini-3.1-pro-preview", "gemini-2.5-flash", "gemini-2.5-pro"]

PROVIDERS = {
    "openai": {"class": OpenAIProvider, "models": ["gpt-5.5", "gpt-5.4", "gpt-5.4-mini", "gpt-4o", "gpt-4o-mini"]},
    "anthropic": {"class": AnthropicProvider, "models": ["claude-opus-4-7", "claude-sonnet-4-20250514", "claude-opus-4-20250514", "claude-haiku-4-5-20251001"]},
    "google（代理）": {"class": GoogleProvider, "models": _GOOGLE_MODELS, "extra": {"use_proxy": True}},
    "google（官方）": {"class": GoogleProvider, "models": _GOOGLE_MODELS, "extra": {"use_proxy": False}},
}


def get_provider(provider_name: str, api_key: str, model: str = "") -> LLMProvider:
    info = PROVIDERS[provider_name]
    cls = info["class"]
    kwargs = {"api_key": api_key}
    if model:
        kwargs["model"] = model
    kwargs.update(info.get("extra", {}))
    return cls(**kwargs)
