import json
from dotenv import load_dotenv
from livekit.agents import (
    AgentSession,
    Agent,
    AutoSubscribe,
    llm,
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
    deepgram
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
    def __init__(self):
        super().__init__(
            instructions="Asking for voice assistant consent If want to chat on voice mode or not make sure to get a clear yes or no answer.",
            llm=openai.realtime.RealtimeModel(voice="coral", temperature=0.6)
        )

    async def on_enter(self) -> None:
        print("Collecting consent...")
        await self.session.generate_reply(instructions="First Ask for voice assistant consent and get a clear yes or no answer. Make sure selection is clear")

    @function_tool
    async def consent_given(self) -> None:
        """Use this when the user gives consent to assist in product configuration. If user wants do configuration"""
        self.complete(True)

    @function_tool
    async def consent_denied(self) -> None:
        """Use this when the user denies consent to assist in product configuration or say no to continue."""
        self.complete(False)


class ProductConfigurationAssistant(Agent):
    def __init__(self, ASSISTANT_INSTRUCTIONS: str) -> None:
        super().__init__(instructions=ASSISTANT_INSTRUCTIONS,
                         llm=openai.realtime.RealtimeModel(voice="coral",
                                                           temperature=0.6))

    async def on_enter(self) -> None:
        # user_data: ProductData = self.session.userdata
        # chat_ctx = self.chat_ctx.copy()

        if await CollectConsent():
            await self.session.generate_reply(instructions=SESSION_INSTRUCTIONS)
        else:
            await self.session.generate_reply(instructions="Inform the user that you are unable to proceed and will end the call.")
            job_ctx = get_job_context()

            try:
                print("Deleting room:", job_ctx.room.name)
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
    print("Job Metadata:", metadata)
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
        #tts=openai.TTS(voice="coral", speed=1.2),
    )
    prompt = ASSISTANT_INSTRUCTIONS + metadata
    await session.start(
        
        room=ctx.room,
        agent=ProductConfigurationAssistant(prompt),
        room_input_options=RoomInputOptions(
            noise_cancellation=noise_cancellation.BVC(),
            video_enabled=False,
            pre_connect_audio=True,
            close_on_disconnect=False,
        ),
        # room_output_options=RoomInputOptions(
            
        # ),
    )
    


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, initialize_process_timeout=200, agent_name=agent_name))