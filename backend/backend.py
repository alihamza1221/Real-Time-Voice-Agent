# utils_async.py
import os
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from livekit import api as lk_api
from dotenv import load_dotenv
import aiohttp
import uvicorn
from datetime import timedelta
import asyncio
from livekit import api
from constants import agent_name


load_dotenv()

LIVEKIT_URL = os.environ["LIVEKIT_URL"]              # e.g. wss://your.livekit.cloud
LIVEKIT_API_KEY = os.environ["LIVEKIT_API_KEY"]
LIVEKIT_API_SECRET = os.environ["LIVEKIT_API_SECRET"]
port = int(os.environ.get("PORT", 8090))

def http_url(ws_url: str) -> str:
    if ws_url.startswith("wss://"):
        return "https://" + ws_url[len("wss://"):]
    if ws_url.startswith("ws://"):
        return "http://" + ws_url[len("ws://"):]
    return ws_url

async def ensure_room(room_name: str):
    # Always close the client to avoid "Unclosed client session"
    async with lk_api.LiveKitAPI(
        url=http_url(LIVEKIT_URL),
        api_key=LIVEKIT_API_KEY,
        api_secret=LIVEKIT_API_SECRET,
    ) as client:
        try:
            res = await client.room.list_rooms(lk_api.ListRoomsRequest(names=[room_name]))
            print("-----------rooms", res.rooms)
            if len(res.rooms) == 0:
                raise aiohttp.ClientResponseError(
                    request_info=None,
                    history=None,
                    status=404,
                    message="Room not found",
                    headers=None,
                )
        except aiohttp.ClientResponseError as e:
            # 404 => room does not exist, create it
            if e.status == 404:
                print("Room not found, creating a new one")
                await client.room.create_room(
                    create=lk_api.CreateRoomRequest(
                        name=room_name,
                        empty_timeout=3600,
                        max_participants=5,
                    )
                )
            else:
                raise

class TokenRequest(BaseModel):
    metadata: str

class TokenResponse(BaseModel):
    token: str
    livekitUrl: str
    roomName: str

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.post("/api/join", response_model=TokenResponse)
async def join(req: TokenRequest):
    try:
        #random generated room name
        room_name:str = f"room-{uuid.uuid4()}"
        identity = f"user-{uuid.uuid4()}"
        await ensure_room(room_name)

        at = lk_api.AccessToken(LIVEKIT_API_KEY, LIVEKIT_API_SECRET) \
            .with_identity(identity) \
            .with_grants(lk_api.VideoGrants(
                room_join=True,
                room=room_name,
                can_publish=True,
                can_subscribe=True,
                can_publish_data=True,
            )) \
            .with_ttl(timedelta(seconds=3600))


        token = at.to_jwt()
        await create_explicit_dispatch(room_name, agent_name, req.metadata)
        return TokenResponse(token=token, livekitUrl=LIVEKIT_URL, roomName=room_name)

    except aiohttp.ClientResponseError as e:
        # Surface LiveKit HTTP errors
        raise HTTPException(status_code=e.status, detail=e.message)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/agents")
async def get_agents(room_name: str):
        lkapi = api.LiveKitAPI()
        print(room_name, ": room_name")
        dispatches = await lkapi.agent_dispatch.list_dispatch(room_name=room_name)
        print(f"there are {len(dispatches)} dispatches in {room_name}")
        await lkapi.aclose()

async def create_explicit_dispatch(room_name:str, agent_name: str, metadata: str):
    lkapi = api.LiveKitAPI()
    dispatch = await lkapi.agent_dispatch.create_dispatch(
        api.CreateAgentDispatchRequest(
            agent_name=agent_name, room=room_name, metadata=metadata
        )
    )
    print("created dispatch", dispatch)

    print(room_name, ": room_name")
    dispatches = await lkapi.agent_dispatch.list_dispatch(room_name=room_name)
    print(f"there are {len(dispatches)} dispatches in {room_name}")
    await lkapi.aclose()
if __name__ == "__main__":
    uvicorn.run("backend:app", host="0.0.0.0", port=port, reload=False,access_log=True)
