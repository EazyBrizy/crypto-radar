import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse

from app.services.realtime_gateway import realtime_gateway, sse_encode
from app.services.realtime_events import connection_heartbeat_event, subscription_updated_event

router = APIRouter(prefix="/realtime", tags=["realtime"])


@router.websocket("/ws")
async def realtime_websocket(websocket: WebSocket) -> None:
    await realtime_gateway.connect_websocket(websocket)
    await realtime_gateway.send_websocket(websocket, connection_heartbeat_event())

    try:
        while True:
            message = await websocket.receive_json()
            if message.get("type") == "ping":
                await realtime_gateway.send_websocket(websocket, connection_heartbeat_event())
            if message.get("type") == "subscribe":
                await realtime_gateway.send_websocket(
                    websocket,
                    subscription_updated_event(
                        channels=[
                            channel
                            for channel in message.get("channels", [])
                            if isinstance(channel, str)
                        ]
                    )
                )
    except WebSocketDisconnect:
        realtime_gateway.disconnect_websocket(websocket)


@router.get("/events")
async def realtime_events() -> StreamingResponse:
    queue = realtime_gateway.subscribe_sse()

    async def event_stream():
        try:
            yield sse_encode(connection_heartbeat_event())
            while True:
                try:
                    message = await asyncio.wait_for(queue.get(), timeout=15)
                    yield sse_encode(message)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            realtime_gateway.unsubscribe_sse(queue)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
