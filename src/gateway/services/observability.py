class SpanCollector:
    def __init__(self, tenant_id: str | None = None):
        self._spans: list[dict] = []
        self.tenant_id = tenant_id

    def record(self, name: str, attributes: dict, duration_ms: int | None = None) -> dict:
        span = {"service": "gateway", "name": name,
                "attributes": attributes, "duration_ms": duration_ms}
        self._spans.append(span)
        return span

    def record_external(self, span: dict) -> None:
        self._spans.append(span)

    def spans(self) -> list[dict]:
        return list(self._spans)
