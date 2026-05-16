"""OpenTelemetry tracing setup.

Wired into FastAPI in `main.py`. Head-based sampling at the configured ratio.
No-op exporter when ``OTEL_EXPORTER_OTLP_ENDPOINT`` is unset (tests, local).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI

from backend.v2.shared.config import get_settings

log = logging.getLogger(__name__)


def configure_tracing(app: FastAPI) -> None:
    settings = get_settings()
    try:
        from opentelemetry import trace
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
    except ImportError:
        log.info("OpenTelemetry SDK not installed; tracing disabled.")
        return

    resource = Resource.create({"service.name": "academy-manager-v2", "env": settings.env})
    provider = TracerProvider(
        resource=resource,
        sampler=TraceIdRatioBased(settings.otel_sampling_ratio),
    )

    if settings.otel_exporter_otlp_endpoint:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                OTLPSpanExporter,
            )

            exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint)
            provider.add_span_processor(BatchSpanProcessor(exporter))
        except ImportError:
            log.info("OTLP exporter not installed; tracing will use a no-op exporter.")

    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
