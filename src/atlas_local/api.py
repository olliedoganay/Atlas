from __future__ import annotations

import argparse
import asyncio
import json
import os
import queue
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import uvicorn

from .api_service import AtlasBackendService
from .runtime import configure_console
from .run_contract import TERMINAL_EVENT_TYPES


class PromptRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    user_id: str = Field(..., min_length=1)
    thread_id: str = Field(..., min_length=1)
    chat_model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    thread_title: str | None = None
    cross_chat_memory: bool = True
    auto_compact_long_chats: bool = True
    images: list[dict[str, str]] = Field(default_factory=list)


class UserRequest(BaseModel):
    user_id: str = Field(..., min_length=1)


class MemoryCreateRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    text: str = Field(..., min_length=1)


class ThreadTitleRequest(BaseModel):
    user_id: str = Field(..., min_length=1)
    title: str = Field(..., min_length=1)


class ResetThreadRequest(BaseModel):
    thread_id: str
    user_id: str | None = None


class ResetAllRequest(BaseModel):
    confirmation: str


def create_api_app(service: AtlasBackendService | None = None) -> FastAPI:
    managed_service = service
    required_token = os.environ.get("ATLAS_INSTANCE_TOKEN", "").strip()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        nonlocal managed_service
        if managed_service is None:
            managed_service = AtlasBackendService.create()
        app.state.service = managed_service
        try:
            yield
        finally:
            if service is None and managed_service is not None:
                managed_service.close()

    app = FastAPI(title="Atlas API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    if managed_service is not None:
        app.state.service = managed_service

    @app.middleware("http")
    async def require_instance_token(request: Request, call_next):
        if request.method.upper() == "OPTIONS":
            return await call_next(request)
        if required_token:
            provided = (
                request.headers.get("x-atlas-instance-token", "").strip()
                or request.query_params.get("token", "").strip()
            )
            if provided != required_token:
                return JSONResponse(status_code=401, content={"detail": "Atlas backend identity check failed."})
        return await call_next(request)

    def backend() -> AtlasBackendService:
        return app.state.service

    @app.get("/health")
    def health() -> dict[str, Any]:
        return backend().health()

    @app.get("/status")
    def status() -> dict[str, Any]:
        return backend().status()

    @app.get("/models")
    def models() -> dict[str, Any]:
        return backend().list_models()

    @app.get("/users")
    def users() -> list[dict[str, Any]]:
        return backend().list_users()

    @app.get("/memories")
    def memories(user_id: str = Query(..., min_length=1), limit: int = Query(default=50, ge=1, le=200)) -> list[dict[str, Any]]:
        return backend().list_memories(user_id=user_id, limit=limit)

    @app.post("/memories")
    def create_memory(request: MemoryCreateRequest) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().add_memory(user_id=request.user_id, text=request.text))

    @app.delete("/memories/{memory_id}")
    def delete_memory(memory_id: str, user_id: str = Query(..., min_length=1)) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().delete_memory(user_id=user_id, memory_id=memory_id))

    @app.post("/users")
    def create_user(request: UserRequest) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().create_user(user_id=request.user_id))

    @app.delete("/users/{user_id}")
    def delete_user(user_id: str, confirmation_user_id: str = Query(..., min_length=1)) -> dict[str, Any]:
        return _handle_runtime(
            lambda: backend().reset_user(user_id=user_id, confirmation_user_id=confirmation_user_id)
        )

    @app.get("/threads")
    def threads(user_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
        return backend().list_threads(user_id=user_id)

    @app.patch("/threads/{thread_id}/title")
    def rename_thread(thread_id: str, request: ThreadTitleRequest) -> dict[str, Any]:
        return _handle_runtime(
            lambda: backend().rename_thread(user_id=request.user_id, thread_id=thread_id, title=request.title)
        )

    @app.post("/threads/{thread_id}/duplicate")
    def duplicate_thread(thread_id: str, request: UserRequest) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().duplicate_thread(user_id=request.user_id, thread_id=thread_id))

    @app.post("/threads/{thread_id}/compact")
    def compact_thread(thread_id: str, request: UserRequest) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().start_manual_compact(user_id=request.user_id, thread_id=thread_id))

    @app.get("/threads/{thread_id}/history")
    def thread_history(thread_id: str, user_id: str | None = Query(default=None)) -> list[dict[str, Any]]:
        return _handle_runtime(lambda: backend().get_thread_history(user_id=user_id, thread_id=thread_id))

    @app.get("/runs/{run_id}")
    def run_details(run_id: str) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().get_run(run_id))

    @app.post("/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().cancel_run(run_id))

    @app.post("/chat")
    def chat(request: PromptRequest) -> dict[str, Any]:
        return _handle_runtime(
            lambda: backend().start_chat(
                prompt=request.prompt,
                user_id=request.user_id,
                thread_id=request.thread_id,
                chat_model=request.chat_model,
                temperature=request.temperature,
                thread_title=request.thread_title,
                cross_chat_memory=request.cross_chat_memory,
                auto_compact_long_chats=request.auto_compact_long_chats,
                images=request.images,
            )
        )

    @app.get("/chat/stream/{run_id}")
    async def chat_stream(run_id: str) -> StreamingResponse:
        return _streaming_response(backend(), run_id)

    @app.get("/compact/stream/{run_id}")
    async def compact_stream(run_id: str) -> StreamingResponse:
        return _streaming_response(backend(), run_id)

    @app.post("/admin/reset/thread")
    def reset_thread(request: ResetThreadRequest) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().reset_thread(thread_id=request.thread_id, user_id=request.user_id))

    @app.post("/admin/reset/all")
    def reset_all(request: ResetAllRequest) -> dict[str, Any]:
        return _handle_runtime(lambda: backend().reset_all(confirmation=request.confirmation))

    return app


def _streaming_response(service: AtlasBackendService, run_id: str) -> StreamingResponse:
    try:
        artifact = service.get_run(run_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    async def generator():
        emitted = 0
        for event in artifact.get("events", []):
            emitted += 1
            yield _format_sse(event)

        if artifact.get("status") in {"completed", "failed"}:
            return

        subscriber = service.subscribe(run_id)
        try:
            while True:
                try:
                    event = await asyncio.to_thread(subscriber.get, True, 5.0)
                    emitted += 1
                    yield _format_sse(event)
                    if event.get("type") in TERMINAL_EVENT_TYPES:
                        break
                except queue.Empty:
                    refreshed = service.get_run(run_id)
                    for event in refreshed.get("events", [])[emitted:]:
                        emitted += 1
                        yield _format_sse(event)
                        if event.get("type") in TERMINAL_EVENT_TYPES:
                            return
        finally:
            service.unsubscribe(run_id, subscriber)

    return StreamingResponse(generator(), media_type="text/event-stream")


def _format_sse(event: dict[str, Any]) -> str:
    return f"event: {event.get('type', 'message')}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _handle_runtime(callback):
    try:
        return callback()
    except RuntimeError as exc:
        message = str(exc)
        status = 409 if "already running another task" in message.lower() else 400
        raise HTTPException(status_code=status, detail=message) from exc


def main(argv: list[str] | None = None) -> int:
    configure_console()
    parser = argparse.ArgumentParser(description="Run the Atlas local backend API.")
    parser.add_argument("--host", default=os.environ.get("ATLAS_API_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("ATLAS_API_PORT", "8765")))
    args = parser.parse_args(argv)
    uvicorn.run("atlas_local.api:app", host=args.host, port=args.port, factory=False)
    return 0


app = create_api_app()


if __name__ == "__main__":
    raise SystemExit(main())
