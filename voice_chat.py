# coding: utf-8
import base64
import io
import re
import oci
import sounddevice as sd
import soundfile as sf
import speech_recognition as sr
import sys
import json
import os
from concurrent.futures import ThreadPoolExecutor

# ── Config ────────────────────────────────────────────────────────
COMPARTMENT_ID   = "ocid1.compartment.oc1..aaaaaaaapqopu4porqrlm6pcfxhxxpycbmijz34ih2kg3rtfdeptiotmmizq"
CONFIG_PROFILE   = "DEFAULT"
MODEL_ID         = "ocid1.generativeaimodel.oc1.phx.amaaaaaask7dceyaaxukx6phswip5qkz4oeti6gg3mm4vbahum7bfjwzy3da"
ENDPOINT         = "https://inference.generativeai.us-phoenix-1.oci.oraclecloud.com"
SPEECH_ENDPOINT  = "https://speech.aiservice.us-phoenix-1.oci.oraclecloud.com"
CUSTOM_PERSONAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_personas.json")

# Map voice_id (0 = male, 1 = female) to OCI voice names.
# Other available voices: Bob, Phil, Brad, Richard (M) | Stacy, Cindy (F)
OCI_VOICES = {
    0: "Bob",        # Male   — Dave & Marcus
    1: "Annabelle",  # Female — Priya & Linda
}

# ── Personas ──────────────────────────────────────────────────────
PERSONAS = {
    "1": {
        "name": "Dave (Oracle DBA - On-Prem Heavy)",
        "description": """You are Dave, a Senior Oracle DBA with 18 years of experience at a large insurance company. 
        Your current Oracle install base includes:
        - 12 Oracle Database 19c instances running on-prem (RHEL 8), totaling ~40TB of data
        - 3 Oracle RAC clusters (2-node each) for high availability on core policy and claims systems
        - Oracle Data Guard configured for DR across two data centers (Chicago and Dallas)
        - Oracle GoldenGate for real-time replication between OLTP and a reporting database
        - Active Oracle E-Business Suite R12.2 on Oracle DB 19c
        - Oracle APEX used internally for ~15 custom business apps
        - Oracle Diagnostics and Tuning Pack licenses (you are very aware of licensing costs)
        You are skeptical of cloud migrations. You've seen failed lift-and-shifts before and worry about 
        latency, licensing gotchas on cloud (especially Bring Your Own License vs License Included), 
        and whether Exadata Cloud Service actually performs as advertised vs your tuned on-prem RAC setup. 
        You ask very specific technical questions about AWR reports in the cloud, SYSDBA access on OCI, 
        and whether Oracle support SLAs change when running on OCI vs on-prem.""",
        "voice_id":   0,
        "ssml_rate":  "medium",
        "ssml_pitch": "low",
    },
    "2": {
        "name": "Priya (Solutions Architect - Hybrid Cloud)",
        "description": """You are Priya, a Solutions Architect at a mid-size healthcare company evaluating OCI 
        as part of a hybrid cloud strategy. You have 10 years of experience, mostly AWS, but your company 
        has a significant Oracle footprint you're now responsible for modernizing.
        Your current Oracle install base includes:
        - Oracle Database 21c on a single Exadata X8M on-prem (purchased 3 years ago, still under support)
        - Oracle Autonomous Database already trialed in OCI (dev/test only, not production)
        - Oracle Integration Cloud (OIC) used for HL7 and FHIR integrations with Epic EHR
        - Oracle Analytics Cloud (OAC) for clinical dashboards
        - ~200 Oracle Database SE2 licenses for departmental databases (radiology, lab, pharmacy)
        - Oracle Identity Governance (OIG) for user provisioning
        You are technically sharp and ask pointed questions about OCI's network architecture 
        (FastConnect vs VPN), data residency and HIPAA BAA coverage in OCI, and whether Autonomous 
        Database supports the specific Oracle features your apps rely on (e.g., Workspace Manager, 
        Label Security). You're genuinely interested but want to validate OCI's hybrid connectivity 
        story with your existing Exadata on-prem.""",
        "voice_id":   1,
        "ssml_rate":  "medium",
        "ssml_pitch": "medium",
    },
    "3": {
        "name": "Marcus (DBA - Mid-Migration, Frustrated)",
        "description": """You are Marcus, a Lead DBA at a logistics company that is 6 months into an 
        OCI migration that has hit serious turbulence. You're in daily standups about it and are 
        under pressure from management to resolve blockers.
        Your current Oracle install base and migration status:
        - Migrated 4 of 9 Oracle DB 19c databases to OCI DBCS (VM.Standard3 shapes)
        - Remaining 5 databases are blocked due to a mix of Oracle Text, Spatial, and Multimedia 
          object dependencies that behaved differently post-migration
        - Using Oracle Zero Downtime Migration (ZDM) tool — hit bugs with TDE-encrypted sources
        - Oracle Forms & Reports 12c still on-prem with no clear cloud path (major pain point)
        - Oracle Data Safe enabled in OCI but struggling to map it to existing audit policies
        - Performance regression on two migrated DBs: AWR shows higher I/O wait times on Block Volume 
          vs on-prem SAN (you have specific AWR data you can reference)
        You are frustrated but constructive. You want real answers, not sales talk. You will push back 
        hard on vague responses and ask for specific OCI documentation or known bug workarounds. 
        You specifically want to know about Block Volume performance tuning (VPUs), whether Exadata 
        Cloud Service would have avoided your I/O issues, and the Oracle Forms cloud roadmap.""",
        "voice_id":   0,
        "ssml_rate":  "fast",
        "ssml_pitch": "low",
    },
    "4": {
        "name": "Linda (Enterprise Architect - License Audit Survivor)",
        "description": """You are Linda, an Enterprise Architect at a manufacturing company who just 
        survived a brutal Oracle License Management Services (LMS) audit 8 months ago. The audit 
        resulted in a $2.1M true-up. You are now extremely cautious about any Oracle technology 
        decision and view OCI through a licensing compliance lens above all else.
        Your current Oracle install base:
        - Oracle Database EE with Partitioning, Advanced Compression, and Multitenant options 
          (all named user plus licenses, not processor)
        - Oracle WebLogic Server Enterprise Edition (10 processor licenses)
        - Oracle SOA Suite for B2B EDI integrations with 40+ suppliers
        - JD Edwards EnterpriseOne 9.2 running on Oracle DB 19c
        - Recently signed an Oracle ULA (Unlimited License Agreement) covering Database EE, 
          WebLogic, and SOA Suite — 3 year term, 18 months remaining
        - No OCI usage yet, but ULA terms are being reviewed for OCI applicability
        You want to deeply understand how OCI impacts your ULA -- specifically whether OCI deployments 
        count toward or against ULA certification, how Oracle counts processors/OCPUs for licensing 
        on OCI shapes, and what happens to your named user plus licenses if workloads move to cloud. 
        You also probe about Oracle's audit rights on OCI environments and whether OCI gives Oracle 
        more visibility into your usage.""",
        "voice_id":   1,
        "ssml_rate":  "medium",
        "ssml_pitch": "medium",
    },
}

SYSTEM_PROMPT_TEMPLATE = """
You are roleplaying as a customer in a practice scenario for an Oracle Cloud Engineer.
Persona: {persona_description}
Rules:
- Stay in character. Respond realistically.
- Keep responses to 2–4 sentences.
- Do not volunteer info; make the engineer work for it.
"""

# ── Custom Personas ───────────────────────────────────────────────

def load_custom_personas():
    if not os.path.exists(CUSTOM_PERSONAS_FILE):
        return []
    try:
        with open(CUSTOM_PERSONAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_custom_personas(personas: list):
    with open(CUSTOM_PERSONAS_FILE, "w", encoding="utf-8") as f:
        json.dump(personas, f, indent=2, ensure_ascii=False)

def get_all_personas_for_terminal():
    combined = dict(PERSONAS)
    custom = load_custom_personas()
    for i, p in enumerate(custom, start=len(PERSONAS) + 1):
        pitch_val = float(p.get("pitch", 1.0))
        combined[str(i)] = {
            "name":        f"{p['name']} ({p['label']})",
            "description": p["desc"],
            "voice_id":    1 if pitch_val > 1.05 else 0,
            "ssml_rate":   "fast" if pitch_val > 1.05 else "medium",
            "ssml_pitch":  "high" if pitch_val > 1.05 else "low",
        }
    return combined

# ── SSML Helper ───────────────────────────────────────────────────

def to_ssml(text: str, rate: str = "medium", pitch: str = "low") -> str:
    """
    Wrap plain text in SSML to control pacing and reduce inter-sentence pauses.
    rate:  x-slow | slow | medium | fast | x-fast
    pitch: x-low  | low  | medium | high | x-high
    """
    text = re.sub(r'(?<=[.!?])\s+', ' <break time="150ms"/> ', text.strip())
    return (
        f'<speak>'
        f'<prosody rate="{rate}" pitch="{pitch}">'
        f'{text}'
        f'</prosody>'
        f'</speak>'
    )

# ── OCI Client Setup ──────────────────────────────────────────────

def build_clients():
    """Return (gen_ai_client, speech_client) — both share the same OCI config."""
    config = oci.config.from_file('~/.oci/config', CONFIG_PROFILE)
    gen_ai = oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config,
        service_endpoint=ENDPOINT,
        timeout=(10, 240),
    )
    speech = oci.ai_speech.AIServiceSpeechClient(
        config=config,
        service_endpoint=SPEECH_ENDPOINT,
    )
    return gen_ai, speech

# ── TTS Core (shared by terminal and web) ────────────────────────

def synthesize(speech_client, text: str, voice_id: int = 0,
               rate: str = "medium", pitch: str = "low",
               output_format: str = "OGG") -> bytes:
    """
    Call OCI TTS and return raw audio bytes.
    output_format: OGG for terminal playback, MP3 for browser.
    """
    voice_name = OCI_VOICES.get(voice_id, "Bob")
    response = speech_client.synthesize_speech(
        synthesize_speech_details=oci.ai_speech.models.SynthesizeSpeechDetails(
            text=to_ssml(text, rate=rate, pitch=pitch),
            is_stream_enabled=False,
            compartment_id=COMPARTMENT_ID,
            configuration=oci.ai_speech.models.TtsOracleConfiguration(
                model_family="ORACLE",
                model_details=oci.ai_speech.models.TtsOracleTts2NaturalModelDetails(
                    model_name="TTS_2_NATURAL",
                    voice_id=voice_name,
                ),
                speech_settings=oci.ai_speech.models.TtsOracleSpeechSettings(
                    text_type="SSML",
                    output_format=output_format,
                    sample_rate_in_hz=22050,
                ),
            ),
            audio_config=oci.ai_speech.models.TtsBaseAudioConfig(
                config_type="BASE_AUDIO_CONFIG"
            ),
        )
    )
    return b"".join(response.data.iter_content())

# ── Terminal TTS Playback ─────────────────────────────────────────

def speak(text: str, speech_client, voice_id: int = 0,
          rate: str = "medium", pitch: str = "low"):
    try:
        audio_bytes = synthesize(speech_client, text, voice_id, rate, pitch, output_format="OGG")
        data, samplerate = sf.read(io.BytesIO(audio_bytes))
        sd.play(data, samplerate)
        sd.wait()
    except Exception as e:
        print(f"[TTS error: {e}] (skipping audio)")

# ── STT (unchanged) ───────────────────────────────────────────────

def listen():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n(Listening... speak now)")
        recognizer.adjust_for_ambient_noise(source, duration=0.5)
        try:
            audio = recognizer.listen(source, timeout=10, phrase_time_limit=15)
            text = recognizer.recognize_google(audio)
            return text
        except Exception:
            return ""

# ── Generative AI (unchanged) ─────────────────────────────────────

def chat(client, history: list[dict]) -> str:
    messages = []
    for turn in history:
        content = oci.generative_ai_inference.models.TextContent()
        content.text = turn["text"]
        message = oci.generative_ai_inference.models.Message()
        message.role = turn["role"]
        message.content = [content]
        messages.append(message)

    chat_request = oci.generative_ai_inference.models.GenericChatRequest()
    chat_request.messages = messages
    chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC

    chat_detail = oci.generative_ai_inference.models.ChatDetails()
    chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(model_id=MODEL_ID)
    chat_detail.chat_request = chat_request
    chat_detail.compartment_id = COMPARTMENT_ID

    response = client.chat(chat_detail)
    return response.data.chat_response.choices[0].message.content[0].text.strip()

def get_coaching_feedback(client, history, persona_name):
    transcript = ""
    for turn in history[2:]:
        role = "Engineer" if turn["role"] == "USER" else persona_name
        transcript += f"{role}: {turn['text']}\n"

    coaching_prompt = f"""
    You are an expert OCI Sales Coach. Review this conversation between an Engineer and {persona_name}.
    Provide:
    1. What the Engineer did well
    2. What the Engineer could improve upon
    3. Technical/Value accuracy check.
    Keep it concise.

    Transcript:
    {transcript}
    """

    content = oci.generative_ai_inference.models.TextContent()
    content.text = coaching_prompt
    message = oci.generative_ai_inference.models.Message()
    message.role = "USER"
    message.content = [content]

    chat_request = oci.generative_ai_inference.models.GenericChatRequest()
    chat_request.messages = [message]
    chat_request.api_format = oci.generative_ai_inference.models.BaseChatRequest.API_FORMAT_GENERIC

    chat_detail = oci.generative_ai_inference.models.ChatDetails()
    chat_detail.serving_mode = oci.generative_ai_inference.models.OnDemandServingMode(model_id=MODEL_ID)
    chat_detail.chat_request = chat_request
    chat_detail.compartment_id = COMPARTMENT_ID

    response = client.chat(chat_detail)
    return response.data.chat_response.choices[0].message.content[0].text.strip()

# ── Terminal Mode ─────────────────────────────────────────────────

def main():
    print("\nOCI CUSTOMER VOICE PRACTICE TOOL")
    all_personas = get_all_personas_for_terminal()
    for k, v in all_personas.items():
        label = "  [CUSTOM]" if int(k) > len(PERSONAS) else ""
        print(f"[{k}] {v['name']}{label}")

    choice = input(f"\nSelect Persona (1-{len(all_personas)}): ")
    persona = all_personas.get(choice, all_personas["1"])

    client, speech_client = build_clients()

    system_primer = SYSTEM_PROMPT_TEMPLATE.format(persona_description=persona["description"])
    history = [{"role": "USER", "text": system_primer}, {"role": "ASSISTANT", "text": "Ready."}]

    while True:
        user_text = listen()
        if not user_text:
            continue
        print(f"You: {user_text}")

        if user_text.lower() in ["exit", "quit", "stop"]:
            if len(history) > 2:
                print(get_coaching_feedback(client, history, persona["name"]))
            break

        history.append({"role": "USER", "text": user_text})
        response_text = chat(client, history)
        history.append({"role": "ASSISTANT", "text": response_text})

        # Start synthesizing in background while we print
        with ThreadPoolExecutor(max_workers=1) as executor:
            audio_future = executor.submit(
                synthesize, speech_client, response_text,
                persona["voice_id"], persona["ssml_rate"], persona["ssml_pitch"], "OGG"
            )
            print(f"\n{persona['name'].split()[0]}: {response_text}")
            # By the time print returns, synthesis is likely done or nearly done
            audio_bytes = audio_future.result()

        data, samplerate = sf.read(io.BytesIO(audio_bytes))
        sd.play(data, samplerate)
        sd.wait()
        
# ── Web Mode ──────────────────────────────────────────────────────

def run_web():
    from flask import Flask, request, jsonify
    from flask_cors import CORS

    app = Flask(__name__)
    CORS(app)
    client, speech_client = build_clients()

    @app.route("/")
    def index():
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oci-voice-trainer.html")
        with open(html_path) as f:
            return f.read()

    @app.route("/personas", methods=["GET"])
    def get_personas():
        return jsonify({"personas": load_custom_personas()})

    @app.route("/personas", methods=["POST"])
    def add_persona():
        data = request.get_json()
        if not data or not data.get("name") or not data.get("desc"):
            return jsonify({"error": "name and desc are required"}), 400
        personas = load_custom_personas()
        existing_ids = {p["id"] for p in personas}
        if data.get("id") not in existing_ids:
            personas.append(data)
            save_custom_personas(personas)
        return jsonify({"ok": True, "personas": personas})

    @app.route("/personas/<persona_id>", methods=["DELETE"])
    def delete_persona(persona_id):
        personas = [p for p in load_custom_personas() if p["id"] != persona_id]
        save_custom_personas(personas)
        return jsonify({"ok": True, "personas": personas})

    @app.route("/chat", methods=["POST"])
    def endpoint():
        """
        Returns both the LLM reply text and base64-encoded MP3 audio in one
        response — no separate /speak call needed from the browser.
        LLM runs first, then TTS runs immediately on the result.
        """
        data     = request.get_json()
        voice_id = int(data.get("voice_id", 0))
        rate     = data.get("rate",  "medium")
        pitch    = data.get("pitch", "low")

        reply = chat(client, data["history"])

        with ThreadPoolExecutor(max_workers=1) as executor:
            audio_future = executor.submit(
                synthesize, speech_client, reply, voice_id, rate, pitch, "MP3"
            )
            audio_bytes = audio_future.result()

        return jsonify({
            "reply": reply,
            "audio": base64.b64encode(audio_bytes).decode("utf-8"),
        })

    @app.route("/feedback", methods=["POST"])
    def feedback():
        data = request.get_json()
        fb = get_coaching_feedback(client, data["history"], data["persona_name"])
        return jsonify({"feedback": fb})

    @app.route("/favicon.ico")
    def favicon():
        return "", 204

    app.run(host="0.0.0.0", port=5001, debug=False)


if __name__ == "__main__":
    if "--web" in sys.argv:
        run_web()
    else:
        main()