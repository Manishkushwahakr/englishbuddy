from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from jose import jwt, JWTError
from app.config import SECRET_KEY
from app.auth.security import ALGORITHM

router = APIRouter(
    tags=["WebSocket"]
)


class ConnectionManager:

    def __init__(self):
        self.rooms = {}

    async def connect(
        self,
        websocket: WebSocket,
        conversation_id: str,
        user_id: str
    ):
        await websocket.accept()

        if conversation_id not in self.rooms:
            self.rooms[conversation_id] = []

        self.rooms[conversation_id].append({
            "websocket": websocket,
            "user_id": user_id
        })

    def disconnect(
        self,
        websocket: WebSocket,
        conversation_id: str
    ):
        if conversation_id not in self.rooms:
            return

        self.rooms[conversation_id] = [
            connection
            for connection in self.rooms[conversation_id]
            if connection["websocket"] != websocket
        ]

        if not self.rooms[conversation_id]:
            del self.rooms[conversation_id]

    async def send_to_room(
        self,
        conversation_id: str,
        message: dict,
        sender: WebSocket
    ):
        if conversation_id not in self.rooms:
            return

        for connection in self.rooms[conversation_id]:

            if connection["websocket"] != sender:

                await connection["websocket"].send_json(
                    message
                )


manager = ConnectionManager()


@router.websocket("/ws/conversation/{conversation_id}")
async def conversation_websocket(
    websocket: WebSocket,
    conversation_id: str
):

    # Get token from URL
    token = websocket.query_params.get("token")

    if not token:
        await websocket.close(code=1008)
        return

    # Verify JWT
    try:

        payload = jwt.decode(
            token,
            SECRET_KEY,
            algorithms=[ALGORITHM]
        )

        user_id = payload.get("sub")

        if not user_id:
            await websocket.close(code=1008)
            return

    except JWTError:

        await websocket.close(code=1008)
        return

    # Connect user to room
    await manager.connect(
        websocket,
        conversation_id,
        user_id
    )

    # Tell client who connected
    await websocket.send_json({
        "type": "connected",
        "conversation_id": conversation_id,
        "user_id": user_id,
        "message": "Joined conversation room"
    })

    try:

        while True:

            message = await websocket.receive_json()

            message["sender_id"] = user_id

            message_type = message.get("type")

            if message_type in ["offer", "answer", "ice_candidate"]:

                await manager.send_to_room(
                    conversation_id,
                    message,
                    websocket
                )

            else:

                await manager.send_to_room(
                    conversation_id,
                    message,
                    websocket
                )

    except WebSocketDisconnect:

        manager.disconnect(
            websocket,
            conversation_id
        )

        # Notify remaining users
        if conversation_id in manager.rooms:

            for connection in manager.rooms[conversation_id]:

                await connection["websocket"].send_json({
                    "type": "user_disconnected",
                    "user_id": user_id,
                    "message": "The other user has disconnected"
                })

        print(
            f"User {user_id} disconnected from "
            f"conversation {conversation_id}"
        )