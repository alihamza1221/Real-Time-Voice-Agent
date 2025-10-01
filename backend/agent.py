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

from livekit.plugins.turn_detector.multilingual import MultilingualModel
from promts import SESSION_INSTRUCTIONS, ASSISTANT_INSTRUCTIONS
from constants import agent_name
from livekit.agents import AgentTask, function_tool
from dataclasses import Field, dataclass, field
from typing import Optional, Annotated
import pydantic
load_dotenv()


@dataclass
class ProductData:
    product: Optional[list[str]] = None

RunContext_T = RunContext[ProductData]

class CollectConsent(AgentTask[bool]):
    def __init__(self, metadata: str):
        self.current_instructions = """Asking for voice consent If want voice mode or not. 
            - Avoid Background noise un recognized words.
            - The {LANGUAGE} for conversation is provided in DATA below.
            - ONLY use LANGUAGE provided in DATA below.
            - Make sure to get a clear answer for consent yes/no. 
        # PRODUCT DATA : """ + metadata

        super().__init__(
            instructions=self.current_instructions,
            llm=openai.realtime.RealtimeModel(voice="coral", temperature=0.6)
        )

    async def on_enter(self) -> None:
        print("2: Collecting consent...")
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
    def __init__(self, prompt: str, current_session_instructions: str, metadata: str) -> None:
        super().__init__(instructions=prompt,
                         llm=openai.realtime.RealtimeModel(voice="coral",
                                                           temperature=0.6))
        self.current_session_instructions = current_session_instructions
        self.metadata = metadata
        
    async def on_enter(self) -> None:
        # user_data: ProductData = self.session.userdata
        # chat_ctx = self.chat_ctx.copy()
        print("1: Will call collect consent now...")

        if await CollectConsent(self.metadata):
            await self.session.generate_reply(instructions=self.current_session_instructions)
            print("session instructions:", self.current_session_instructions)

            print("3: Consent granted.")
        else:
            print("3: Consent denied. Ending session.")
            await self.session.generate_reply(instructions="Inform the user that you are unable to proceed and will end the call.")
            job_ctx = get_job_context()

            try:
                print("last : Deleting room:", job_ctx.room.name)
                await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
            except Exception as e:
                print("Error deleting room:", e)
    # async def on_user_turn_completed(self, chat_ctx, new_message):
    #     if new_message.text_content:
    #         print(f"User Transcript: {new_message.text_content}")
   
    @function_tool
    async def update_product_configuration(
        self,
        items_configured: Annotated[list[str], pydantic.Field(description="The updated configuration of the given product aligned with provided json data of product")],
        context: RunContext_T,
    ) -> str:
        """Called when the user or agent create or update the product configuration. Will be called each time the update happens in product configuration"""
        userdata = context.userdata
        userdata.product = items_configured

        try:
            payload = {
                "type": "config:update",
                "items_configured": items_configured,
            }
            
            # publish as reliable data with a topic to make filtering easy
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
        """Called when the user confirms the product configuration."""
        userdata = context.userdata
        if not userdata.product:
            return "No product configuration found. Please configure your product first."
        print(userdata.product)
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
    


async def entrypoint(ctx: JobContext):
    metadata = ctx.job.metadata
    if metadata is None or metadata.strip() == "":
        metadata = """{
            "name": "Wood Table",
            "parts": {
              "table_top": ["15m", "14m", "100m"],
              "legs": ["10m", "100m"],
              "space_around": ["10m", "80m"]
            },
            "LANGUAGE": "German"
        }"""

    print("Received Job Metadata:", metadata)
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)
    await ctx.wait_for_participant()

    productData = ProductData()
    session = AgentSession[ProductData](
        userdata=productData,
        vad=ctx.proc.userdata["vad"],
        allow_interruptions=True,
        #stt=deepgram.STT(
        #    smart_format=True
        #),
        #turn_detection=MultilingualModel(),
        #turn_detection="vad",
        #tts=openai.TTS(voice="coral", speed=1.2),
        
    )
    prompt = ASSISTANT_INSTRUCTIONS + metadata
    
    print("Final Prompt:", prompt)
    current_session_instructions = SESSION_INSTRUCTIONS + metadata
    
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