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
                                                           temperature=0.))
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
            
            print("_________Publishing payload:", payload)
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
        """Called when the user confirms the product configuration. or end the configuration."""
        userdata = context.userdata
        if not userdata.product:
            return "No product configuration found. Please configure your product first."
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
        
        print(userdata.product)
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
                print("last : Deleting room:", job_ctx.room.name)
                await job_ctx.api.room.delete_room(api.DeleteRoomRequest(room=job_ctx.room.name))
            except Exception as e:
                print("Error deleting room:", e)
        except Exception:
            print("Error in close_voice_mode No room to delete")
            pass
        return f"Thank you will end the call now."
    


async def entrypoint(ctx: JobContext):
    metadata = ctx.job.metadata
    
    if not metadata or metadata.strip() == "":
        metadata = """
{
name: 'Wood Table',
parts: [
    {"id":0,"uniqueId":"1588942193773","name":"platte_thickness","titel":"Stärke","value":["16 mm","19 mm","25 mm","8 mm"]},{"id":1,"uniqueId":"1614246937544","name":"texture_direction","titel":"Maserungsrichtung ","value":["Vertikal","Horizontal"]},{"id":2,"uniqueId":"1709586217030","name":"sideschoice_of_edges1","titel":"Seitenauswahl der Kanten :","value":["oben","rechts","unten","links"]},{"id":3,"uniqueId":"1709635825282","name":"edge_processing1","titel":"Kantenbearbeitung:","value":["Ohne","Weiß Hochglanz","Schwarz Hochglanz","Ahorn Natur","Alu Geschliffen","Anthrazit","Atollblau","Beige","Beton dunkel","Beton hell","Eiche Salzburg","Eierschale","Esche Taormina Vogue","Grau","Hellgrau","Kernapfel","Kirsche Acco","Limone","Lipstick","Murnau Ahorn","Niagara Eiche hell","Nussbaum","Onyx","Rose","Samerbergbuche","Schiefer","Schwarz","Seablue","Silber","Sonoma Eiche","Taubenblau","Türkis","Walnuss Venedig","Weiss","Wenge Classic","Marmor Weiss","Marmor Dunkel Grau","Marmor Hell Grau","Swiss Elm Kalt","Aloe Green","Dive Blue","Efeu","Eternal Oak","Jaffa Orange","Lamella Cream","Lamella Terra","Marineblau","Olive","Pistazien Grün","Astfichte","Cappuccino","Cashmere","Coco Tweed Creme","Fichte Weiß","Frontweiss","MellowPine White","Stonetex Black"]},{"id":4,"uniqueId":"1709232334992","name":"st_amount_socket","titel":"Steckdosenbohrungen","value":["Keine","Eine","Zwei","Drei","Vier","Fünf"]},{"id":5,"uniqueId":"1709232556743","name":"rows_of_holes_for_shelves","titel":"Lochreihen für Regalbretter","value":["Keine","lange Seite - 2 Reihen für Regalbretter - pro Platte","kurze Seite - 2 Reihen für Regalbretter - pro Platte"]},{"id":6,"uniqueId":"1709232830865","name":"hinges_drill_hole","titel":"Scharniere inkl. Bohrung","value":["Keine","Eckanschlag 2 Bohrungen und 2 Scharniere","Mittelwand 2 Bohrungen und 2 Scharniere","Einliegend 2 Bohrungen und 2 Scharniere","Eckanschlag 3 Bohrungen und 3 Scharniere","Mittelwand 3 Bohrungen und 3 Scharniere","Einliegend 3 Bohrungen und 3 Scharniere","Eckanschlag 4 Bohrungen und 4 Scharniere","Mittelwand 4 Bohrungen und 4 Scharniere","Einliegend 4 Bohrungen und 4 Scharniere","Eckanschlag 5 Bohrungen und 5 Scharniere","Mittelwand 5 Bohrungen und 5 Scharniere","Einliegend 5 Bohrungen und 5 Scharniere"]}],
LANGUAGE: 'German'
})
        """

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
    
    
    
"""

[

{"id":0,"name":"platte_thickness","titel":"Stärke",

"value":["16 mm","19 mm","25 mm","8 mm"]},
"features" []},



{"id":0,"name":"platte_thickness","titel":"Stärke",

"value":["16 mm","19 mm","25 mm","8 mm"]},
"features" []},
[{"id":0,"name":"platte_thickness","titel":"Stärke",

"value":["16 mm","19 mm","25 mm","8 mm"]},
"features" []},
{"id":0,"name":"platte_thickness","titel":"Stärke"},]

"""