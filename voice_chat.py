# coding: utf-8
import oci
import pyttsx3
import speech_recognition as sr
import sys
import json
import os

# Config
COMPARTMENT_ID = "ocid1.compartment.oc1..aaaaaaaapqopu4porqrlm6pcfxhxxpycbmijz34ih2kg3rtfdeptiotmmizq"
CONFIG_PROFILE  = "DEFAULT"
MODEL_ID        = "ocid1.generativeaimodel.oc1.phx.amaaaaaask7dceyaaxukx6phswip5qkz4oeti6gg3mm4vbahum7bfjwzy3da"
ENDPOINT        = "https://inference.generativeai.us-phoenix-1.oci.oraclecloud.com"
CUSTOM_PERSONAS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "custom_personas.json")

PERSONAS = {
    "1": {
        "name": "Alex (Skeptical CTO)",
        "description": "A skeptical CTO at a mid-sized fintech company. Concerned about cloud costs, vendor lock-in, and security.",
        "voice_id": 0
    },
    "2": {
        "name": "Maria (Eager but Uninformed VP)",
        "description": "A VP of Engineering at a retail company. Enthusiastic but lacks deep technical knowledge.",
        "voice_id": 1
    },
    "3": {
        "name": "James (Procurement-focused Buyer)",
        "description": "A procurement manager evaluating OCI against Azure and GCP purely on cost and SLA terms.",
        "voice_id": 0
    },
    "4": {
        "name": "Sara (Unhappy Existing Customer)",
        "description": "An existing OCI customer frustrated with a recent outage. Starts conversations irritably.",
        "voice_id": 1
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

# Custom Personas
def load_custom_personas():
    """Load custom personas from the JSON file."""
    if not os.path.exists(CUSTOM_PERSONAS_FILE):
        return []
    try:
        with open(CUSTOM_PERSONAS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return []

def save_custom_personas(personas: list):
    """Save custom personas to the JSON file."""
    with open(CUSTOM_PERSONAS_FILE, "w", encoding="utf-8") as f:
        json.dump(personas, f, indent=2, ensure_ascii=False)

def get_all_personas_for_terminal():
    """Return built-in + custom personas as a numbered dict for terminal use."""
    combined = dict(PERSONAS)
    custom = load_custom_personas()
    for i, p in enumerate(custom, start=len(PERSONAS) + 1):
        combined[str(i)] = {
            "name": f"{p['name']} ({p['label']})",
            "description": p["desc"],
            "voice_id": 1 if float(p.get("pitch", 1.0)) > 1.05 else 0,
        }
    return combined

# Voice Engine Setup
def speak(text, voice_index=0):
    engine = pyttsx3.init()
    voices = engine.getProperty('voices')
    if len(voices) > voice_index:
        engine.setProperty('voice', voices[voice_index].id)
    engine.setProperty('rate', 180)
    engine.say(text)
    engine.runAndWait()

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

# OCI Logic
def build_client():
    config = oci.config.from_file('~/.oci/config', CONFIG_PROFILE)
    return oci.generative_ai_inference.GenerativeAiInferenceClient(
        config=config,
        service_endpoint=ENDPOINT,
        timeout=(10, 240),
    )

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
    # Filter out system prompts
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

# Main Loop
def main():
    print("\nOCI CUSTOMER VOICE PRACTICE TOOL")
    all_personas = get_all_personas_for_terminal()
    for k, v in all_personas.items():
        label = "  [CUSTOM]" if int(k) > len(PERSONAS) else ""
        print(f"[{k}] {v['name']}{label}")

    choice = input(f"\nSelect Persona (1-{len(all_personas)}): ")
    persona = all_personas.get(choice, all_personas["1"])
    client = build_client()
    
    system_primer = SYSTEM_PROMPT_TEMPLATE.format(persona_description=persona["description"])
    history = [{"role": "USER", "text": system_primer}, {"role": "ASSISTANT", "text": "Ready."}]

    while True:
        user_text = listen()
        if not user_text: continue
        print(f"You: {user_text}")
        
        if user_text.lower() in ["exit", "quit", "stop"]:
            if len(history) > 2:
                print(get_coaching_feedback(client, history, persona["name"]))
            break
            
        history.append({"role": "USER", "text": user_text})
        response_text = chat(client, history)
        history.append({"role": "ASSISTANT", "text": response_text})
        print(f"\n{persona['name'].split()[0]}: {response_text}")
        speak(response_text, voice_index=persona["voice_id"])

# Web Mode
def run_web():
    from flask import Flask, request, jsonify
    from flask_cors import CORS
    import os

    app = Flask(__name__)
    CORS(app)
    client = build_client()

    @app.route("/")
    def index():
        html_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "oci-voice-trainer.html")
        with open(html_path) as f: return f.read()

    @app.route("/personas", methods=["GET"])
    def get_personas():
        """Return all custom personas so the web UI can sync on load."""
        return jsonify({"personas": load_custom_personas()})

    @app.route("/personas", methods=["POST"])
    def add_persona():
        """Add a new custom persona (syncs the localStorage-created one to disk)."""
        data = request.get_json()
        if not data or not data.get("name") or not data.get("desc"):
            return jsonify({"error": "name and desc are required"}), 400
        personas = load_custom_personas()
        # Avoid duplicates by id
        existing_ids = {p["id"] for p in personas}
        if data.get("id") not in existing_ids:
            personas.append(data)
            save_custom_personas(personas)
        return jsonify({"ok": True, "personas": personas})

    @app.route("/personas/<persona_id>", methods=["DELETE"])
    def delete_persona(persona_id):
        """Remove a custom persona by id."""
        personas = [p for p in load_custom_personas() if p["id"] != persona_id]
        save_custom_personas(personas)
        return jsonify({"ok": True, "personas": personas})

    @app.route("/chat", methods=["POST"])
    def endpoint():
        data = request.get_json()
        return jsonify({"reply": chat(client, data["history"])})

    @app.route("/feedback", methods=["POST"])
    def feedback():
        data = request.get_json()
        fb = get_coaching_feedback(client, data["history"], data["persona_name"])
        return jsonify({"feedback": fb})

    app.run(host="0.0.0.0", port=5001, debug=False)

if __name__ == "__main__":
    if "--web" in sys.argv: run_web()
    else: main()