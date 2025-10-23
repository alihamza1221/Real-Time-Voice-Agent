import asyncio
import json
from dotenv import load_dotenv
from importlib_metadata import metadata
from livekit.agents import (
    AgentSession,
    Agent,
    AutoSubscribe,
    RoomInputOptions,
    JobContext,
    JobProcess,
    cli,
    WorkerOptions, RunContext
)
from livekit.agents import get_job_context
from livekit import api 
from livekit.plugins import (
    openai,
    silero,
    noise_cancellation,
)

from promts import SESSION_INSTRUCTIONS, ASSISTANT_INSTRUCTIONS
from constants import agent_name
from livekit.agents import AgentTask, function_tool
from dataclasses import Field, dataclass, field
from typing import Optional, Annotated
import pydantic
load_dotenv()



class ConfiguredPart(pydantic.BaseModel):
    uniqueId: str
    name: str
    value: Optional[str] = None
    title: Optional[str] = None

@dataclass
class ProductData:
    product: Optional[dict] = field(default_factory=lambda: {
        "name": None,
        "parts": [],
        "selected_options": [],
        "language": None
    })
    



RunContext_T = RunContext[ProductData]

class CollectConsent(AgentTask[bool]):
    def __init__(self, metadata: any):
        self.current_instructions = """Asking for voice consent If want voice mode or not. 
            - Avoid Background noise un recognized words.
            - The {LANGUAGE} for conversation is provided in DATA below.
            - ONLY use LANGUAGE provided in DATA below.
            - Make sure to get a clear answer for consent yes/no. 
        # PRODUCT DATA : """ + json.dumps(metadata)

        super().__init__(
            instructions=self.current_instructions,
            llm=openai.realtime.RealtimeModel(voice="coral",
                                                           temperature=0.6)
        )

    async def on_enter(self) -> None:
        print("STEP 2: _________Collecting consent_________")
        await self.session.generate_reply(instructions=self.current_instructions)

    @function_tool
    async def consent_given(self) -> None:
        """Use this when the user gives consent to assist with voice mode. If user wants the voice mode"""
        self.complete(True)

    @function_tool
    async def consent_denied(self) -> None:
        """Use this when the user denies consent to assist with voice mode or say no to continue."""
        self.complete(False)


class ProductConfigurationAssistant(Agent): 
    def __init__(self, prompt: str, current_session_instructions: str, metadata: any) -> None:
        super().__init__(instructions=prompt,
                         llm=openai.realtime.RealtimeModel(voice="coral",
                                                           temperature=0.6))
        self.current_session_instructions = current_session_instructions
        self.metadata = metadata
        
    async def on_enter(self) -> None:
        if not self.session._room_io or not self.session._room_io._room:
            print("Room IO or Room is not available.")
        else:
            self.session._room_io._room.on("data_received", self._on_data_received)

        print("STEP 1: _________Will call collect consent now_________")

        if await CollectConsent(self.metadata):
            await self.session.generate_reply(user_input=self.current_session_instructions, instructions="You can now proceed with product configuration as the user has given consent.", tool_choice=self.update_product_configuration,)

            print("STEP 3: _________Consent granted_________")
        else:
            print("STEP 3: _________Consent denied. Ending session.")
            await self.session.generate_reply(instructions="Inform the user that you are unable to proceed and will end the call.")
            job_ctx = get_job_context()

            try:
                print("LAST : _________Deleting room:", job_ctx.room.name)
                await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
            except Exception as e:
                print("Error deleting room:", e)
    
    def _on_data_received(self, data):
        # Convert to string and parse JSON if applicable
        print("_________Data received callback triggered.")
        asyncio.create_task(self.process_incoming_data(data))

    async def process_incoming_data(self, data):
        try:
            payload = data.data if hasattr(data, "data") else data

            message_str = ""
            if isinstance(payload, (bytes, bytearray)):
                message_str = payload.decode("utf-8")
            elif isinstance(payload, str):
                message_str = payload
            else:
                message_str = str(payload)

            message = """
            
            - Important! From Now on, respond with updated configuration only. 
            - If part is already configured continue configuration what's left in updated config. 
            - If some options are removed just ignore and focus in remaining options.
            ____________________________

            UPDATED CONFIGURATION DATA:
            ____________________________
            
            """ + message_str
            
            print("_______UPDATED CONFIG DATA_____\n", message)
            chat_ctx = self.chat_ctx.copy()
            chat_ctx.add_message(role="system", content=message)
            
            await self.update_chat_ctx(chat_ctx)
            
            updated_instructions = ASSISTANT_INSTRUCTIONS + message_str
            await self.update_instructions(updated_instructions)
            await self.session.generate_reply(user_input=message_str, instructions=updated_instructions, tool_choice=self.update_product_configuration)
        except Exception as e:
            print("Failed to decode/process incoming data:", e)
            return

        print(f"Data received on topic {data.topic}:'{data}'")


    @function_tool
    async def update_product_configuration(
        self,
        items_configured: Annotated[ConfiguredPart, pydantic.Field(description="The specific part being configured. Must include uniqueId, name, and the selected value.")],
        context: RunContext_T,
    ) -> str:
        """Will be called each time the update happens in any part of product configuration. Called on each part configuration."""
        userdata = context.userdata
        if not userdata.product.get("selected_options"):
            userdata.product["selected_options"] = []

        userdata.product["selected_options"].append(items_configured.model_dump())

        try:
            payload = {
                "type": "config:update",
                "items_configured": items_configured.model_dump(),
            }
            
            await context.session._room_io._room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True,
                topic="config",
            )
        except Exception:
            pass
            
        return f"The product configuration is updated to {items_configured}"
    

    @function_tool()
    async def confirm_configuration(self, context: RunContext_T) -> str | tuple[Agent, str]:
        """Called when the user confirms the product configuration. or end the configuration."""
        userdata = context.userdata
      
        print("_______Found Config: " , userdata.product)
        try:
            payload = {
                "type": "config:complete",
                "items_configured": userdata.product,
            }
            
            await context.session._room_io._room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True,
                topic="config",
            )
        except Exception:
            pass
        return f"Thank you for confirming your product configuration: {userdata.product}. We will proceed with the next steps."
    @function_tool()
    async def close_voice_mode(self, context: RunContext_T) -> str | tuple[Agent, str]:
        """Called when the user wants to close the voice mode at any point or say close or stop."""
        userdata = context.userdata
        
        #print(userdata.product)
        try:
            payload = {
                "type": "config:close_voice_mode",
                "items_configured": userdata.product,
            }
            
            await context.session._room_io._room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                reliable=True,
                topic="config",
            )
            
            job_ctx = get_job_context()

            try:
                print("LAST : _________Deleting room:", job_ctx.room.name)
                await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
            except Exception as e:
                print("Error deleting room:", e)
        except Exception:
            print("Error in close_voice_mode No room to delete")
            pass
        return f"Thank you will end the call now."
    


async def entrypoint(ctx: JobContext):
    metadata = ctx.job.metadata
   
    metadata = json.loads(metadata)

    #print("Received Job Metadata:", metadata)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.wait_for_participant()

    
    productData = ProductData()
    session = AgentSession[ProductData](
        userdata=productData,
        vad=ctx.proc.userdata["vad"],
        allow_interruptions=True,
        preemptive_generation=True,

        #stt=deepgram.STT(
        #    smart_format=True
        #),
        #turn_detection=MultilingualModel(),
        #turn_detection="vad",
        #tts=openai.TTS(voice="coral", speed=1.2),
        
    )
    prompt = ASSISTANT_INSTRUCTIONS + json.dumps(metadata, indent = 2 )
    
    current_session_instructions = SESSION_INSTRUCTIONS + json.dumps(metadata, indent=2)
    await session.start(
        room=ctx.room,
        agent=ProductConfigurationAssistant(prompt, current_session_instructions, metadata=metadata),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
            video_enabled=False,
            pre_connect_audio=True,
            close_on_disconnect=True,
        ),
        # room_output_options=RoomInputOptions(
            
        # ),
    )
    

def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, initialize_process_timeout=500, agent_name=agent_name))
    
    
    
