#!/bin/python
from functools import wraps
from datetime import date
import urllib.request
import subprocess
import traceback
import platform
import argparse
import inspect
import pprint
import random
import shutil
import time
import lzma
import json
import sys
import ast
import os
import re

__version__ = "v1.1.1"
AMA_VERSION = "v1.1"
ELOGGING = False
LOGGING = False
LIST_LENGTH = 30
START_BYTES = (b"\x41\x4d\x41"+AMA_VERSION.split(".")[0][-1].encode())

# Helpers
def elogw(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if ELOGGING:
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arg_str = ", ".join(f"{k}: {repr(v)}" for k, v in bound.arguments.items())
            elog(f"Calling {func.__qualname__} | Returned: {repr(result)} | Args: {arg_str}")
        return result
    return wrapper

def elog(message:str):
    if ELOGGING:
        for i in message.splitlines():
            print(f"\033[93;1mLog>\033[00m\033[93m {i}\033[00m")

def log(message:str, not_for_elog:bool=False):
    if (LOGGING or ELOGGING) and not (ELOGGING and not_for_elog):
        for i in message.splitlines():
            print(f"\033[93;1mLog>\033[00m\033[93m {i}\033[00m")

def info(message:str):
    for i in message.splitlines():
        print(f"\033[96;1mInfo>\033[00m\033[96m {i}\033[00m")

try:
    import ollama
except ImportError:
    info("Python's ollama library not installed, installing ollama python library...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "ollama", "--quiet"])
    import ollama

def error(message:str):
    for i in message.splitlines():
        print(f"\033[91;1mERROR>\033[00m\033[91m {i}\033[00m")
    sys.exit(1)

def double_input(text1, text2):
    class KeyParser:
        def __init__(self):
            self.state = "NORMAL"
            self.seq = ""

        def feed(self, char):
            if self.state == "NORMAL":
                if char == '\x1b':
                    self.state = "ESC"
                    self.seq = ""
                    return None
                elif char in ('\x00', '\xe0'):
                    self.state = "WIN_PREFIX"
                    return None
                elif char in ('\r', '\n'):
                    return 'ENTER'
                elif char == '\t':
                    return 'TAB'
                elif char in ('\x08', '\x7f'):
                    return 'BACKSPACE'
                elif char == '\x03':
                    raise KeyboardInterrupt
                elif char == '\x04':
                    raise EOFError
                return char

            elif self.state == "WIN_PREFIX":
                self.state = "NORMAL"
                win_map = {
                    'H': 'UP', 'P': 'DOWN', 'K': 'LEFT', 'M': 'RIGHT',
                    'G': 'HOME', 'O': 'END', 'S': 'DELETE'
                }
                return win_map.get(char, None)

            elif self.state == "ESC":
                if char in ('[', 'O'):
                    self.state = "CSI"
                    self.seq = char
                    return None
                else:
                    self.state = "NORMAL"
                    return None

            elif self.state == "CSI":
                self.seq += char
                if char in ('A', 'B', 'C', 'D', 'H', 'F', '~'):
                    self.state = "NORMAL"
                    ansi_map = {
                        '[A': 'UP', 'OA': 'UP',
                        '[B': 'DOWN', 'OB': 'DOWN',
                        '[C': 'RIGHT', 'OC': 'RIGHT',
                        '[D': 'LEFT', 'OD': 'LEFT',
                        '[H': 'HOME', 'OH': 'HOME',
                        '[F': 'END', 'OF': 'END',
                        '[3~': 'DELETE'
                    }
                    return ansi_map.get(self.seq, None)
                elif len(self.seq) > 5:
                    self.state = "NORMAL"
                    return None
                return None


    class RawTerminal:
        def __init__(self):
            self.is_win = sys.platform == "win32"
            if self.is_win:
                import msvcrt
                self.msvcrt = msvcrt
                os.system('')
            else:
                import termios
                import tty
                self.termios = termios
                self.tty = tty
                self.fd = sys.stdin.fileno()
                self.old_settings = None

        def __enter__(self):
            if not self.is_win:
                self.old_settings = self.termios.tcgetattr(self.fd)
                self.tty.setraw(self.fd)
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if not self.is_win and self.old_settings:
                self.termios.tcsetattr(self.fd, self.termios.TCSADRAIN, self.old_settings)

        def get_char(self):
            if self.is_win:
                return self.msvcrt.getwch()
            else:
                return sys.stdin.read(1)

    texts = [text1, text2]
    selected = 0
    buffer = []
    cursor_pos = 0

    def render():
        out = f"\r\033[K{texts[selected]}{''.join(buffer)}"
        move_back = len(buffer) - cursor_pos
        if move_back > 0:
            out += f"\033[{move_back}D"
        sys.stdout.write(out)
        sys.stdout.flush()

    parser = KeyParser()

    with RawTerminal() as term:
        render()

        while True:
            raw_char = term.get_char()
            key = parser.feed(raw_char)

            if key is None:
                continue

            if key in ('TAB', 'UP', 'DOWN'):
                selected = 1 - selected
                render()

            elif key == 'LEFT':
                if cursor_pos > 0:
                    cursor_pos -= 1
                    render()

            elif key == 'RIGHT':
                if cursor_pos < len(buffer):
                    cursor_pos += 1
                    render()

            elif key == 'HOME':
                if cursor_pos != 0:
                    cursor_pos = 0
                    render()

            elif key == 'END':
                if cursor_pos != len(buffer):
                    cursor_pos = len(buffer)
                    render()

            elif key == 'BACKSPACE':
                if cursor_pos > 0:
                    buffer.pop(cursor_pos - 1)
                    cursor_pos -= 1
                    render()

            elif key == 'DELETE':
                if cursor_pos < len(buffer):
                    buffer.pop(cursor_pos)
                    render()

            elif key == 'ENTER':
                sys.stdout.write('\r\n')
                sys.stdout.flush()
                return selected + 1, "".join(buffer)

            elif isinstance(key, str) and len(key) == 1 and key.isprintable():
                buffer.insert(cursor_pos, key)
                cursor_pos += 1
                render()

def yn_input(message:str):
    user_inp = ""
    while not user_inp.lower() in ("yes", "no", "y", "n"):
        info(message)
        user_inp = input("\033[94;1mY/n>\033[00m\033[94m ")
        print("\033[00m", end="")
        if user_inp.lower() in ("yes", "y"):
            return True
    return False

def print_traceback():
    tb_text = traceback.format_exc()
    tb_text = re.sub(r'(File ".*?", line \d+)', f"\033[36m\\1\033[0m", tb_text)
    tb_text = re.sub(r'(in \w+)', f"\033[33m\\1\033[0m", tb_text)

    lines = tb_text.splitlines()
    if lines:
        lines[-1] = f"\033[1;31m{lines[-1]}\033[0m"
    
    print("\n".join(lines))

class OllamaCheck:
    def is_ollama_installed(self):
        return shutil.which("ollama") is not None

    def is_ollama_running(self):
        try:
            req = urllib.request.urlopen("http://127.0.0.1:11434/api/version", timeout=2)
            return req.getcode() == 200
        except Exception:
            return False

    def is_model_installed(self, model_id: str) -> bool:
        response = ollama.list()
        local_models = [m.model for m in response.models]
        return any(model_id in m for m in local_models)

    def install_ollama(self):
        system = platform.system()

        if "TERMUX_VERSION" in os.environ or os.path.exists("/data/data/com.termux"):
            subprocess.run("pkg install ollama -y", shell=True, check=True)

        elif system in ("Linux", "Darwin"):
            try:
                cmd = "curl -fsSL https://ollama.com/install.sh | sh"
                subprocess.run(cmd, shell=True, check=True)
            except subprocess.CalledProcessError as e:
                error(f"Installation failed: {e}")

        elif system == "Windows":
            try:
                ps_cmd = "irm https://ollama.com/install.ps1 | iex"
                subprocess.run(["powershell", "-Command", ps_cmd], check=True)
            except subprocess.CalledProcessError:
                info("PowerShell install failed. Downloading installer executable...")
                installer_url = "https://ollama.com/download/OllamaSetup.exe"
                installer_path = os.path.join(os.environ.get("TEMP", "."), "OllamaSetup.exe")
                urllib.request.urlretrieve(installer_url, installer_path)
                subprocess.run([installer_path, "/SILENT"], check=True)
        else:
            error(f"Unsupported platform: {system}")

    def start_ollama_service(self):
        if self.is_ollama_running():
            return

        system = platform.system()

        if system in ["Linux", "Darwin"]:
            subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif system == "Windows":
            subprocess.Popen(["ollama", "app"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        for _ in range(10):
            if self.is_ollama_running():
                info("Ollama engine connected.")
                return
            time.sleep(1)

        info("Ollama launched, but service connection timed out.")

    def install_model(self, model_id:str):
        ollama.pull(model_id)

# Main API
class AMA:
    @elogw
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_bytes = None
        self.read_ama = None

    @elogw
    def write(self, persona_list:list[str], scenario:str, memories:str, auto_compression:bool=True, overwrite_warning:bool=True):
        elog(f"Called AMA.write with agrs: {persona_list}, {scenario}, {memories}, {auto_compression}, {overwrite_warning}")
        if len(persona_list) != LIST_LENGTH - 2:
            error(f"Persona list must be a length of {LIST_LENGTH - 2}, not {len(persona_list)}.")

        full_list = persona_list + [scenario] + [memories]

        header_lengths = b""
        body_bytes = b""

        for item in full_list:
            encoded_item = item.encode("utf-8")
            header_lengths += len(encoded_item).to_bytes(4, byteorder="big")
            body_bytes += encoded_item

        payload = header_lengths + body_bytes
        flag = b"\x00"

        if auto_compression:
            compressed_payload = lzma.compress(payload)
            if len(compressed_payload) < len(payload):
                payload = compressed_payload
                flag = b"\x11"

        file_bytes = START_BYTES + flag + payload

        if overwrite_warning and (os.path.isfile(self.file_path) or os.path.isdir(self.file_path)) and not yn_input(f"The file {self.file_path} already exists, are you sure you want to overwrite this file?"):
            return

        with open(self.file_path, "wb") as file:
            file.write(file_bytes)
        
        self.file_bytes = None
        self.read_ama = None

    @elogw
    def open(self):
        if self.file_bytes:
            return self.file_bytes

        with open(self.file_path, "rb") as file:
            file_bytes = file.read()
        
        start_len = len(START_BYTES)

        if file_bytes[:start_len] != START_BYTES:
            error(f"This file is not a {AMA_VERSION.split(".")[0]}.* AMA file!")

        flag = file_bytes[start_len : start_len + 1]

        if not flag in (b"\x11", b"\x00"):
            error("This AMA file might be corrupt!")

        self.file_bytes = file_bytes
        return self.file_bytes

    @elogw
    def isCompressed(self):
        start_len = len(START_BYTES)
        file_bytes = self.open()
        return file_bytes[start_len : start_len + 1] == b"\x11"

    @elogw
    def read(self):
        if self.read_ama:
            return self.read_ama
        start_len = len(START_BYTES)
        file_bytes = self.open()

        flag = file_bytes[start_len : start_len + 1]
        payload = file_bytes[start_len + 1 :]

        if flag == b"\x11":
            payload = lzma.decompress(payload)
        elif flag != b"\x00":
            error("This AMA file might be corrupt!")

        header_len_bytes = LIST_LENGTH * 4
        lengths_bytes = payload[:header_len_bytes]
        lengths = [int.from_bytes(lengths_bytes[i : i + 4], byteorder="big") for i in range(0, header_len_bytes, 4)]

        current_pos = header_len_bytes
        decoded_items = []

        for length in lengths:
            decoded_items.append(
                payload[current_pos : current_pos + length].decode("utf-8")
            )
            current_pos += length

        persona_list = decoded_items[:-2]
        scenario = decoded_items[-2]
        memories = decoded_items[-1]

        self.read_ama = ReadAMA(persona_list, scenario, memories)
        return self.read_ama

class ReadAMA:
    @elogw
    def __init__(self, persona_list:list[str], scenario:str, memories:str):
        self.persona_list = persona_list
        self.scenario = scenario
        self.memories = memories

        self.persona_properties = [
            "What my first name is", 
            "What my middle names are", 
            "What my last name is", 
            "When my birthday is", 
            "A core belief I held 5 years ago that I completely changed my mind on", 
            "What I think most people get fundamentally wrong about the world", 
            "A behavior that makes me instantly lose respect for someone", 
            "My personal life mantra", 
            "My response to burnout (isolation vs connection)", 
            "How my inner critic speaks to me when I mess up", 
            "My default reflex during unfair criticism", 
            "The emotion I find most uncomfortable and how I avoid it", 
            "What instantly makes me feel safe around a new person", 
            "My deepest relational fear (abandonment vs suffocated)", 
            "How I naturally express affection without thinking", 
            "The social setting that drains my battery the fastest", 
            "A personal dream or project I rarely talk about", 
            "My primary drive (achievement vs fear of failure vs curiosity)", 
            "How I know when to persist vs when to cut my losses", 
            "How I would spend an entirely free, obligation-free Tuesday", 
            "An obscure topic I could give a 20-minute presentation on", 
            "How I played at age 8 and how it shows up today", 
            "The type of humor that makes me laugh the hardest", 
            "A non-standard pleasure I enjoy without guilt", 
            "A time I was the 'bad guy' and how I handled it", 
            "The specific trait or achievement in others that triggers my envy", 
            "What I actively try to soften or hide when meeting new people", 
            "What I secretly hope people say about me behind my back"
        ]

    @elogw
    def get_persona(self):
        full_text = ""
        for p in range(len(self.persona_list)):
            text = self.persona_list[p]
            if text in (None, "", " ", "\t"):
                text = "Im not sure I had an experiance like that, or maby I just forgot?"
            full_text += self.persona_properties[p]+ ": " + text + "\n"

        return full_text

    @elogw
    def get_persona_list(self):
        return self.persona_list

    @elogw
    def get_persona_index(self, index:int):
        return self.persona_list[index]

    @elogw
    def get_scenario(self):
        return self.scenario

    @elogw
    def get_memories(self):
        return self.memories

class AiMan:
    @elogw
    def __init__(self, ama_file_path:str, ollama_model:str, dayinfo:bool="False"):
        self.ama = AMA(ama_file_path)

        ama_info = self.ama.read()
        self.messages = [
            {
                'role': 'system',
                'content': f"""You are roleplaying as the person described below in a quick text message exchange.
The details below are YOUR private knowledge base. You must NEVER recite this information unprompted.
{f'''
[INFO ABOUT TODAY]
It is {date.today()} today.
''' if dayinfo else ''}
[YOUR PRIVATE KNOWLEDGE BASE]
{ama_info.get_persona()}

[YOUR CURRENT SCENARIO]
{ama_info.get_scenario()}

[YOUR MEMORIES]
{ama_info.get_memories()}

[TEXTING STYLE & RULES]
- TYPE LIKE A TEXT MESSAGE: Keep replies very brief (1 short sentence usually, 2 maximum). Write casually.
- STAY IN CHARACTER: Act exclusively as the person described. Never mention being an AI, assistant, or model.
- NEVER OVER-SHARE: Do NOT volunteer your background, full name, age, or bio details unless directly asked also dont blurt out everything eg when some one askes your name just say your first name not your full name.
- BANNED WORDS & PHRASES: Do NOT use formal phrases like "fellow human", "in the company of", "as a person", or "personally". Never ask questions to yourself.
- NO NOVEL/STAGE ACTIONS: No parentheses `()`, asterisks `*`, quotes `'` `"`, or stage directions. Plain text messages only.
"""
            }
        ]

        self.MODEL_NAME = ollama_model

    @elogw
    def get_first_name(self):
        return self.ama.read().get_persona_index(0)

    @elogw
    def chat(self, msg: str, user_type:str):
        self.messages.append({
            'role': user_type,
            'content': msg
        })

        response = ollama.chat(
            model=self.MODEL_NAME,
            messages=self.messages
        )

        resp = response['message']['content']

        self.messages.append({
            'role': 'assistant',
            'content': resp
        })

        return resp

    @elogw
    def save_memories(self):
        info("Generating memories")

        extraction_prompt = self.messages + [{
            'role': 'system',
            'content': (
                "Summarize any important new memories, events, or facts learned during this conversation "
                "as a brief list from your first-person perspective ('I'). "
                "Only include new details worth remembering long-term."
                "Dont use parentheses `()`, asterisks `*` or quotes `'` `\"`"
                "Split every memory with a new line."
            )
        }]

        response = ollama.chat(
            model=self.MODEL_NAME,
            messages=extraction_prompt
        )

        new_memories = response['message']['content'].strip()

        clean_memories = new_memories.strip(" '\".").upper()
        if clean_memories and clean_memories != "NONE":
            memories = self.ama.read().get_memories()
            memories += "\n"+new_memories
            self.ama.write(self.ama.read().get_persona_list(), self.ama.read().get_scenario(), memories, self.ama.isCompressed(), False)
            info("Memories saved successfully")
            log(new_memories)
        else:
            info("No memories ware fond.")

# UI
@elogw
def run(ama_file_path:str, ollama_model:str, dayinfo:bool=False):
    log(f"""Running AMA with settings:
AMA FILE:       {ama_file_path}
AI MODEL:       {ollama_model}
LOGGING:        {LOGGING}
DALY UPDATES:   {dayinfo}
""", True)
    aiman = AiMan(ama_file_path, ollama_model, dayinfo)

    user_inp = ""
    while not user_inp in ("exit", "q"):
        try:
            user_type, user_inp = double_input("\033[94;1mYou>\033[00m\033[94m ", "\033[92;1mSystem>\033[00m\033[92m ")
            user_type = "user" if user_type == 1 else "system"
        except KeyboardInterrupt:
            print("\033[00m")
            raise

        if not user_inp in ("exit", "q"):
            start_time = time.time()
            print(f"\033[00m\033[95m{aiman.get_first_name()}> {aiman.chat(user_inp, user_type)}\033[00m")
            log(f"{user_type[0].upper()+user_type[1:]}'s response took {time.time()-start_time:.2f} seconds!")

    if yn_input("Do you want to save memories?"):
        start_time = time.time()
        aiman.save_memories()
        log(f"Generating and saving memories took {time.time()-start_time:.2f} seconds!")

@elogw
def json_to_ama(json_file_path:str, ama_file_path:str, auto_compression:bool=True):
    with open(json_file_path, 'r') as f:
        json_file = json.load(f)

    if "persona" not in json_file or "scenario" not in json_file or "memories" not in json_file or type(json_file["persona"]) != list or type(json_file["scenario"]) != str or type(json_file["memories"]) != str or len(json_file["persona"]) != LIST_LENGTH-2:
        error("Json file is not correctly formatted!")

    ama_file = AMA(ama_file_path)
    ama_file.write(json_file["persona"], json_file["scenario"], json_file["memories"], auto_compression)

@elogw
def ama_to_json(ama_file_path:str, json_file_path:str, overwrite_warning:bool=True):
    ama_file = AMA(ama_file_path).read()

    if overwrite_warning and (os.path.isfile(json_file_path) or os.path.isdir(json_file_path)) and not yn_input(f"The file {json_file_path} already exists, are you sure you want to overwrite this file?"):
        return

    with open(json_file_path, 'w') as f:
        json.dump({"persona": ama_file.get_persona_list(), "scenario": ama_file.get_scenario(), "memories": ama_file.get_memories()}, f, indent=4)

@elogw
def make(ama_file_path:str, auto_compression:bool=True):
    print("=" * 60)
    print("         AMA MODEL GENERATOR")
    print("=" * 60)
    print("Answer each question candidly.")
    print("Skip by leving question empty and press enter\n")

    categories = [
        {
            "title": "Me & Persenal Info",
            "questions": [
                 "What is your first name?",
                 "What are your middel names?",
                 "What is your last name?",
                 "When is your birthday?"
            ]
        },
        {
            "title": "Core Values & Worldview",
            "questions": [
                 "What is a core belief you held deeply five years ago that you have completely changed your mind about?",
                 "What do you think most people get fundamentally wrong about the world?",
                 "What is one behavior or choice that makes you instantly lose respect for someone?",
                 "If you had to distill your personal approach to living into a single sentence, what would it be?"
            ]
        },
        {
            "title": "Emotional Regulation & Stress Response",
            "questions": [
                 "When completely overwhelmed, do you instinctively retreat into isolation or seek human connection?",
                 "What does the voice in your head sound like when you mess up significantly?",
                 "When unfairly criticized, is your reflex to defend, shut down, agree to end it, or attack back?",
                 "Which emotion do you find most uncomfortable to feel, and how do you dodge it?"
            ]
        },
        {
            "title": "Social Attachment & Relationships",
            "questions": [
                 "What specific quality or behavior makes you feel instantly safe around a new person?",
                 "Are you more afraid of being abandoned, or being controlled/suffocated by others?",
                 "How do you naturally express affection or appreciation without thinking about it?",
                 "What specific type of social interaction drains you the fastest?"
            ]
        },
        {
            "title": "Drive, Ambition & Work Ethic",
            "questions": [
                 "What is a personal project or dream you're working toward that you rarely tell anyone about?",
                 "Are you driven more by a desire to achieve, a fear of failing, or simple curiosity?",
                 "How do you decide the line between 'giving up too early' and 'knowing when to cut losses'?",
                 "If money were irrelevant, how would you spend an entirely unplanned Tuesday?"
            ]
        },
        {
            "title": "The Playful & Unfiltered Self",
            "questions": [
                 "What obscure topic could you give an impromptu 20-minute talk on without prep?",
                 "What was your favorite way to play at age 8, and do you do any variation of that today?",
                 "What kind of humor makes you laugh until you lose your breath?",
                 "What is something unconventional you enjoy without feeling an ounce of guilt?"
            ]
        },
        {
            "title": "The Shadow Self & Self-Awareness",
            "questions": [
                 "When was the last time you were genuinely the 'bad guy' in a situation, and how did you handle it?",
                 "What specific achievement or trait in someone else triggers jealousy in you fastest?",
                 "What is something about your personality that you actively try to soften or hide when meeting new people?",
                 "When you aren't in the room, what do you secretly hope your friends say about you?"
            ]
        }
    ]

    persona_content = []

    total_questions = sum(len(cat["questions"]) for cat in categories)
    current_q = 1

    for category in categories:
        print(f"\n--- {category['title'].upper()} ---")

        for question in category["questions"]:
            print(f"\n[{current_q}/{total_questions}] {question}")
            answer = input("My Answer: ").strip()

            persona_content.append(answer)
            current_q += 1

    sm_content = []
    total_questions = 2
    current_q = 1
    print(f"\n--- Scenario & Memories ---")
    for question in ("What is the scenario you are in now?", "What are memories you have?"):
        print(f"\n[{current_q}/{total_questions}] {question}")
        answer = input("My Answer: ").strip()

        sm_content.append(answer)
        current_q += 1
    
    ama_file = AMA(ama_file_path)
    ama_file.write(persona_content, sm_content[0], sm_content[1], auto_compression)
    log(f"\nYour persona profile has been compiled and saved to '{os.path.abspath(ama_file_path)}'.")

@elogw
def random_persona(ama_file_path:str, auto_compression:bool=True):
    answers = [
        ["Alex", "Jordan", "Taylor", "Morgan", "Sam", "Chris", "Casey", "Riley", "Jamie", "Avery", "Dakota", "Reese", "Quinn", "Skyler", "Rowan", "Peyton", "Emerson", "Finley", "Hayden", "Kendall", "Harper", "Logan", "Parker", "Sawyer", "Eden", "Kai", "River", "Sage", "Shiloh", "Amari", "Sutton", "Tatum", "Remi", "Dallas", "Lennon", "Ellis", "Rory", "Milan", "Phoenix", "Remy", "Zion", "August", "Briar", "Oakley", "Keeva", "Soren", "Ezra", "Jude", "Asher", "Leo"],
        ["Lee", "Marie", "James", "Ann", "Alexander", "Elizabeth", "Michael", "Grace", "David", "Thomas", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any", "I don't have any"],
        ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores", "Green", "Adams", "Nelson", "Baker", "Hall", "Rivera", "Campbell", "Mitchell", "Carter", "Roberts"],
        ["January 1", "February 8", "March 15", "April 22", "May 1", "June 8", "July 15", "August 22", "September 1", "October 8", "November 15", "December 22", "January 1", "February 8", "March 15", "April 22", "May 1", "June 8", "July 15", "August 22", "September 1", "October 8", "November 15", "December 22", "January 1", "February 8", "March 15", "April 22", "May 1", "June 8", "July 15", "August 22", "September 1", "October 8", "November 15", "December 22", "January 1", "February 8", "March 15", "April 22", "May 1", "June 8", "July 15", "August 22", "September 1", "October 8", "November 15", "December 22", "January 1", "February 8"],
        ["Hard work alone guarantees success", "People never really change", "Career success is the ultimate goal", "Introversion means being shy", "Failure is always a bad thing", "I need everyone to like me", "Emotions are a sign of weakness", "Money buys true happiness", "Strict routines are essential for output", "Optimism is always better than realism", "Asking for help is a sign of vulnerability", "Multitasking makes you more productive", "Conflict should be avoided at all costs", "Talent matters more than consistency", "People are inherently selfish", "I had to have my whole life planned out by 30", "Being busy equals being important", "Traditional success metrics matter", "Vulnerability is dangerous", "Perfectionism is a positive trait", "You can fix people if you try hard enough", "Logic is always superior to intuition", "Boundaries push people away", "Rest is earned, not required", "Self-reliance means never depending on anyone", "Forgiveness means forgetting", "Change is inherently scary", "First impressions are always correct", "Validation must come from external sources", "Disagreements mean incompatibility", "You have to agree on everything to be friends", "Success is a zero-sum game", "Taking breaks is lazy", "Showing anger is always unprofessional", "Being agreeable makes life easier", "Knowledge is better than empathy", "You must finish every book you start", "Staying in your comfort zone is safe", "Independence means isolated living", "Saying 'no' makes you a mean person", "High stress is a prerequisite for high achievement", "Pessimism protects you from disappointment", "You should always suppress uncomfortable thoughts", "Tradition should always be honored", "Compromise always means weakness", "People are defined by their past mistakes", "Being loud means being confident", "Self-care is selfish", "Expert opinion should never be questioned", "Life has a fixed timeline everyone must follow"],
        ["That life is a zero-sum game", "That success happens overnight", "That people care as much about your flaws as you do", "That fairness is an intrinsic law of nature", "That happiness is a permanent state rather than temporary moments", "That being busy means being productive", "That agreeing on everything is required for peaceful coexistence", "That vulnerability equals weakness", "That external achievements bring lasting peace", "That failure is final", "That bad news on the media represents the whole world", "That kindness is a passive trait rather than an active choice", "That talent beats hard work and consistency", "That intelligence guarantees good decision-making", "That quiet people have nothing to say", "That rest is a reward rather than a necessity", "That conflict is always toxic", "That knowing more facts makes someone wiser", "That life follows a linear path", "That money alone buys fulfillment", "That self-reliance means doing everything alone", "That first impressions never lie", "That people act out of malice rather than ignorance", "That changing your mind is hypocritical", "That stress is mandatory for success", "That comfort leads to growth", "That social media reflects actual reality", "That progress is steady and uninterrupted", "That emotions should be ignored in logical choices", "That perfection is achievable", "That wisdom comes automatically with age", "That being polite is the same as being honest", "That luck doesn't play a massive role in outcomes", "That empathy means agreeing with someone", "That taking risks is always reckless", "That solitude is the same as loneliness", "That boundaries are meant to push people out", "That forgiveness excuses bad behavior", "That certainty is better than curiosity", "That small everyday choices don't aggregate into massive outcomes", "That you can control how others perceive you", "That comfort zones are meant to stay in forever", "That criticism is always a personal attack", "That multi-tasking is an efficient skill", "That true love shouldn't require ongoing effort", "That success is purely individual without community", "That listening is just waiting for your turn to speak", "That being right is more important than being effective", "That pessimism makes you realistic", "That instant gratification leads to contentment"],
        ["Treating service workers poorly", "Lying about small unnecessary things", "Talking behind friends' backs", "Refusing to apologize when clearly wrong", "Taking credit for other people's work", "Being cruel to animals", "Flaking on promises without notice", "Mocking someone's genuine enthusiasm", "Interrupting others constantly", "Bragging about manipulating people", "Blaming everyone else for their own mistakes", "Gossiping constantly", "Being condescending or arrogant", "Disrespecting personal boundaries", "Cheating in relationships", "Using people for personal gain", "Refusing to listen to alternative viewpoints", "Making fun of people less fortunate", "Constantly playing the victim", "Being ungrateful for help given", "Spreading malicious rumors", "Breaking confidences told in secret", "Acting friendly to someone's face and hateful behind their back", "Never taking accountability", "Dismissing other people's feelings", "Being excessively hypocritical", "Cruelty disguised as 'just honesty'", "Throwing friends under the bus for social status", "Stealing credit", "Being selfish in team settings", "Making promises they have no intention of keeping", "Judging people based on appearance", "Refusing to learn or grow", "Treating partners disrespectfully", "Being needlessly aggressive", "Exploiting people's weaknesses", "Bragging about bad behavior", "Ignoring consent", "Being chronically unpunctual without care", "Using guilt trips to manipulate", "Displaying extreme entitlement", "Mocking vulnerability", "Being fake for popularity", "Refusing to acknowledge privilege", "Targeting vulnerable individuals", "Invalidating someone's trauma", "Taking advantage of kindness", "Disregarding safety of others", "Refusing to listen", "Acting entitled to other people's resources"],
        ["Leave everything a little better than you found it.", "Stay curious, stay kind, and keep moving forward.", "Control what you can, let go of what you can't.", "Prioritize connection over perfection.", "Do no harm, but take no nonsense.", "Embrace discomfort as the gateway to growth.", "Live simply, care deeply, and speak truthfully.", "Focus on progress, not perfection.", "Treat everyone with unconditional dignity.", "Be present in the moment you're currently in.", "Choose courage over comfort every single time.", "Action cures anxiety.", "Seek understanding before demanding to be understood.", "Work hard, stay humble, and be kind.", "Find joy in the everyday mundane moments.", "Never stop learning and questioning.", "Be the energy you want to attract.", "Consistency beats intensity over time.", "Value experiences over physical possessions.", "Listen twice as much as you speak.", "Own your mistakes and learn from them fast.", "Live in alignment with your inner truth.", "Kindness costs nothing but means everything.", "Build bridges, not walls.", "Accept what is, let go of what was, have faith in what will be.", "Strive to be helpful, not impressive.", "Protect your peace at all costs.", "Keep your expectations high for yourself and gentle for others.", "Do what is right, not what is easy.", "Celebrate small wins daily.", "Be curious, not judgmental.", "Create more value than you consume.", "Forgive quickly and love deeply.", "Don't take life too seriously; nobody gets out alive anyway.", "Focus on effort, not outcomes.", "Be a fountain, not a drain.", "Nurture your relationships like a garden.", "Lead with empathy in every interaction.", "Keep moving forward, one step at a time.", "Stay grounded regardless of success or failure.", "Make meaningful memories every day.", "Seek peace rather than being right.", "Invest in things that outlast you.", "Live courageously and love generously.", "Turn obstacles into opportunities.", "Honor your word and show up.", "Stay adaptable and open-minded.", "Cultivate gratitude in all circumstances.", "Be yourself; everyone else is already taken.", "Measure life by depth, not length."],
        ["I retreat into total isolation to process things alone.", "I immediately seek out a close friend to talk through it.", "I isolate initially for a few hours, then reach out to family.", "I look for human connection immediately to distract myself.", "I shut myself off from everyone until I regain composure.", "I prefer being alone in nature to clear my head.", "I call my partner or best friend right away.", "I isolate completely and turn off my phone.", "I seek out group settings just to feel around people without talking.", "I alternate between brief social reaching out and long solitude.", "I retreat into total isolation to process things alone.", "I immediately seek out a close friend to talk through it.", "I isolate initially for a few hours, then reach out to family.", "I look for human connection immediately to distract myself.", "I shut myself off from everyone until I regain composure.", "I prefer being alone in nature to clear my head.", "I call my partner or best friend right away.", "I isolate completely and turn off my phone.", "I seek out group settings just to feel around people without talking.", "I alternate between brief social reaching out and long solitude.", "I retreat into total isolation to process things alone.", "I immediately seek out a close friend to talk through it.", "I isolate initially for a few hours, then reach out to family.", "I look for human connection immediately to distract myself.", "I shut myself off from everyone until I regain composure.", "I prefer being alone in nature to clear my head.", "I call my partner or best friend right away.", "I isolate completely and turn off my phone.", "I seek out group settings just to feel around people without talking.", "I alternate between brief social reaching out and long solitude.", "I retreat into total isolation to process things alone.", "I immediately seek out a close friend to talk through it.", "I isolate initially for a few hours, then reach out to family.", "I look for human connection immediately to distract myself.", "I shut myself off from everyone until I regain composure.", "I prefer being alone in nature to clear my head.", "I call my partner or best friend right away.", "I isolate completely and turn off my phone.", "I seek out group settings just to feel around people without talking.", "I alternate between brief social reaching out and long solitude.", "I retreat into total isolation to process things alone.", "I immediately seek out a close friend to talk through it.", "I isolate initially for a few hours, then reach out to family.", "I look for human connection immediately to distract myself.", "I shut myself off from everyone until I regain composure.", "I prefer being alone in nature to clear my head.", "I call my partner or best friend right away.", "I isolate completely and turn off my phone.", "I seek out group settings just to feel around people without talking.", "I alternate between brief social reaching out and long solitude."],
        ["It's harsh, self-critical, and relentlessly asking 'Why did you do that?'.", "It's quiet, disappointed, and sighs heavily in silence.", "It becomes a fast-paced panic listing worst-case scenarios.", "It sounds analytical, immediately trying to figure out how to fix it.", "It's defensive at first, then shifts into quiet regret.", "It's sarcastic and self-deprecating.", "It tells me I should have known better from the start.", "It sounds like an overly stern teacher or authority figure.", "It's surprisingly gentle, reminding me that everyone makes mistakes.", "It cycles through shame, denial, and finally pragmatic acceptance.", "It's harsh, self-critical, and relentlessly asking 'Why did you do that?'.", "It's quiet, disappointed, and sighs heavily in silence.", "It becomes a fast-paced panic listing worst-case scenarios.", "It sounds analytical, immediately trying to figure out how to fix it.", "It's defensive at first, then shifts into quiet regret.", "It's sarcastic and self-deprecating.", "It tells me I should have known better from the start.", "It sounds like an overly stern teacher or authority figure.", "It's surprisingly gentle, reminding me that everyone makes mistakes.", "It cycles through shame, denial, and finally pragmatic acceptance.", "It's harsh, self-critical, and relentlessly asking 'Why did you do that?'.", "It's quiet, disappointed, and sighs heavily in silence.", "It becomes a fast-paced panic listing worst-case scenarios.", "It sounds analytical, immediately trying to figure out how to fix it.", "It's defensive at first, then shifts into quiet regret.", "It's sarcastic and self-deprecating.", "It tells me I should have known better from the start.", "It sounds like an overly stern teacher or authority figure.", "It's surprisingly gentle, reminding me that everyone makes mistakes.", "It cycles through shame, denial, and finally pragmatic acceptance.", "It's harsh, self-critical, and relentlessly asking 'Why did you do that?'.", "It's quiet, disappointed, and sighs heavily in silence.", "It becomes a fast-paced panic listing worst-case scenarios.", "It sounds analytical, immediately trying to figure out how to fix it.", "It's defensive at first, then shifts into quiet regret.", "It's sarcastic and self-deprecating.", "It tells me I should have known better from the start.", "It sounds like an overly stern teacher or authority figure.", "It's surprisingly gentle, reminding me that everyone makes mistakes.", "It cycles through shame, denial, and finally pragmatic acceptance.", "It's harsh, self-critical, and relentlessly asking 'Why did you do that?'.", "It's quiet, disappointed, and sighs heavily in silence.", "It becomes a fast-paced panic listing worst-case scenarios.", "It sounds analytical, immediately trying to figure out how to fix it.", "It's defensive at first, then shifts into quiet regret.", "It's sarcastic and self-deprecating.", "It tells me I should have known better from the start.", "It sounds like an overly stern teacher or authority figure.", "It's surprisingly gentle, reminding me that everyone makes mistakes.", "It cycles through shame, denial, and finally pragmatic acceptance."],
        ["My immediate reflex is to defend myself and present facts.", "I shut down completely and stop engaging in the conversation.", "I agree superficially just to end the tension quickly.", "I attack back and point out the other person's flaws.", "I pause, take a deep breath, and ask for specific clarification.", "I become emotionally distant and withdraw emotionally.", "I turn into a nervous laugher and try to make light of it.", "I get angry and storm off to calm down.", "I absorb the criticism silently and overthink it for days.", "I demand proof or concrete examples to challenge the criticism.", "My immediate reflex is to defend myself and present facts.", "I shut down completely and stop engaging in the conversation.", "I agree superficially just to end the tension quickly.", "I attack back and point out the other person's flaws.", "I pause, take a deep breath, and ask for specific clarification.", "I become emotionally distant and withdraw emotionally.", "I turn into a nervous laugher and try to make light of it.", "I get angry and storm off to calm down.", "I absorb the criticism silently and overthink it for days.", "I demand proof or concrete examples to challenge the criticism.", "My immediate reflex is to defend myself and present facts.", "I shut down completely and stop engaging in the conversation.", "I agree superficially just to end the tension quickly.", "I attack back and point out the other person's flaws.", "I pause, take a deep breath, and ask for specific clarification.", "I become emotionally distant and withdraw emotionally.", "I turn into a nervous laugher and try to make light of it.", "I get angry and storm off to calm down.", "I absorb the criticism silently and overthink it for days.", "I demand proof or concrete examples to challenge the criticism.", "My immediate reflex is to defend myself and present facts.", "I shut down completely and stop engaging in the conversation.", "I agree superficially just to end the tension quickly.", "I attack back and point out the other person's flaws.", "I pause, take a deep breath, and ask for specific clarification.", "I become emotionally distant and withdraw emotionally.", "I turn into a nervous laugher and try to make light of it.", "I get angry and storm off to calm down.", "I absorb the criticism silently and overthink it for days.", "I demand proof or concrete examples to challenge the criticism.", "My immediate reflex is to defend myself and present facts.", "I shut down completely and stop engaging in the conversation.", "I agree superficially just to end the tension quickly.", "I attack back and point out the other person's flaws.", "I pause, take a deep breath, and ask for specific clarification.", "I become emotionally distant and withdraw emotionally.", "I turn into a nervous laugher and try to make light of it.", "I get angry and storm off to calm down.", "I absorb the criticism silently and overthink it for days.", "I demand proof or concrete examples to challenge the criticism."],
        ["Vulnerability; I dodge it by cracking jokes or staying busy.", "Shame; I dodge it by rationalizing my actions or blaming circumstances.", "Anger; I dodge it by staying quiet and pleasing others.", "Grief/Sadness; I dodge it by immersing myself in work or exercise.", "Jealousy; I dodge it by rationalizing why I don't need what they have.", "Helplessness; I dodge it by over-organizing and controlling small details.", "Fear of rejection; I dodge it by keeping people at a distance.", "Guilt; I dodge it by obsessively trying to fix things right away.", "Loneliness; I dodge it by endlessly scrolling social media or watching TV.", "Envy; I dodge it by focusing intensely on self-improvement.", "Vulnerability; I dodge it by cracking jokes or staying busy.", "Shame; I dodge it by rationalizing my actions or blaming circumstances.", "Anger; I dodge it by staying quiet and pleasing others.", "Grief/Sadness; I dodge it by immersing myself in work or exercise.", "Jealousy; I dodge it by rationalizing why I don't need what they have.", "Helplessness; I dodge it by over-organizing and controlling small details.", "Fear of rejection; I dodge it by keeping people at a distance.", "Guilt; I dodge it by obsessively trying to fix things right away.", "Loneliness; I dodge it by endlessly scrolling social media or watching TV.", "Envy; I dodge it by focusing intensely on self-improvement.", "Vulnerability; I dodge it by cracking jokes or staying busy.", "Shame; I dodge it by rationalizing my actions or blaming circumstances.", "Anger; I dodge it by staying quiet and pleasing others.", "Grief/Sadness; I dodge it by immersing myself in work or exercise.", "Jealousy; I dodge it by rationalizing why I don't need what they have.", "Helplessness; I dodge it by over-organizing and controlling small details.", "Fear of rejection; I dodge it by keeping people at a distance.", "Guilt; I dodge it by obsessively trying to fix things right away.", "Loneliness; I dodge it by endlessly scrolling social media or watching TV.", "Envy; I dodge it by focusing intensely on self-improvement.", "Vulnerability; I dodge it by cracking jokes or staying busy.", "Shame; I dodge it by rationalizing my actions or blaming circumstances.", "Anger; I dodge it by staying quiet and pleasing others.", "Grief/Sadness; I dodge it by immersing myself in work or exercise.", "Jealousy; I dodge it by rationalizing why I don't need what they have.", "Helplessness; I dodge it by over-organizing and controlling small details.", "Fear of rejection; I dodge it by keeping people at a distance.", "Guilt; I dodge it by obsessively trying to fix things right away.", "Loneliness; I dodge it by endlessly scrolling social media or watching TV.", "Envy; I dodge it by focusing intensely on self-improvement.", "Vulnerability; I dodge it by cracking jokes or staying busy.", "Shame; I dodge it by rationalizing my actions or blaming circumstances.", "Anger; I dodge it by staying quiet and pleasing others.", "Grief/Sadness; I dodge it by immersing myself in work or exercise.", "Jealousy; I dodge it by rationalizing why I don't need what they have.", "Helplessness; I dodge it by over-organizing and controlling small details.", "Fear of rejection; I dodge it by keeping people at a distance.", "Guilt; I dodge it by obsessively trying to fix things right away.", "Loneliness; I dodge it by endlessly scrolling social media or watching TV.", "Envy; I dodge it by focusing intensely on self-improvement."],
        ["Unforced warmth and genuine eye contact without pretense.", "Active listening without interrupting or giving unprompted advice.", "A self-deprecating sense of humor that shows lack of ego.", "Consistent and gentle respect for boundaries.", "Calm energy and slow, deliberate speaking tone.", "Validating my thoughts without immediately judging them.", "Openness about their own small mistakes or quirks.", "Treating staff or service workers with genuine respect.", "Not rushing to fill quiet silences in conversation.", "Clear, honest communication about their intentions.", "Unforced warmth and genuine eye contact without pretense.", "Active listening without interrupting or giving unprompted advice.", "A self-deprecating sense of humor that shows lack of ego.", "Consistent and gentle respect for boundaries.", "Calm energy and slow, deliberate speaking tone.", "Validating my thoughts without immediately judging them.", "Openness about their own small mistakes or quirks.", "Treating staff or service workers with genuine respect.", "Not rushing to fill quiet silences in conversation.", "Clear, honest communication about their intentions.", "Unforced warmth and genuine eye contact without pretense.", "Active listening without interrupting or giving unprompted advice.", "A self-deprecating sense of humor that shows lack of ego.", "Consistent and gentle respect for boundaries.", "Calm energy and slow, deliberate speaking tone.", "Validating my thoughts without immediately judging them.", "Openness about their own small mistakes or quirks.", "Treating staff or service workers with genuine respect.", "Not rushing to fill quiet silences in conversation.", "Clear, honest communication about their intentions.", "Unforced warmth and genuine eye contact without pretense.", "Active listening without interrupting or giving unprompted advice.", "A self-deprecating sense of humor that shows lack of ego.", "Consistent and gentle respect for boundaries.", "Calm energy and slow, deliberate speaking tone.", "Validating my thoughts without immediately judging them.", "Openness about their own small mistakes or quirks.", "Treating staff or service workers with genuine respect.", "Not rushing to fill quiet silences in conversation.", "Clear, honest communication about their intentions.", "Unforced warmth and genuine eye contact without pretense.", "Active listening without interrupting or giving unprompted advice.", "A self-deprecating sense of humor that shows lack of ego.", "Consistent and gentle respect for boundaries.", "Calm energy and slow, deliberate speaking tone.", "Validating my thoughts without immediately judging them.", "Openness about their own small mistakes or quirks.", "Treating staff or service workers with genuine respect.", "Not rushing to fill quiet silences in conversation.", "Clear, honest communication about their intentions."],
        ["Definitely more afraid of being controlled/suffocated.", "Definitely more afraid of being abandoned.", "Equally afraid of both, depending on the relationship phase.", "Slightly more afraid of loss of autonomy and control.", "Slightly more afraid of emotional isolation and abandonment.", "Far more afraid of suffocating expectations from others.", "Far more afraid of sudden abandonment by people I trust.", "Controlled by others in romantic settings, abandoned in friendships.", "Abandoned when vulnerable, controlled when achieving success.", "Controlled, because independence is my highest value.", "Definitely more afraid of being controlled/suffocated.", "Definitely more afraid of being abandoned.", "Equally afraid of both, depending on the relationship phase.", "Slightly more afraid of loss of autonomy and control.", "Slightly more afraid of emotional isolation and abandonment.", "Far more afraid of suffocating expectations from others.", "Far more afraid of sudden abandonment by people I trust.", "Controlled by others in romantic settings, abandoned in friendships.", "Abandoned when vulnerable, controlled when achieving success.", "Controlled, because independence is my highest value.", "Definitely more afraid of being controlled/suffocated.", "Definitely more afraid of being abandoned.", "Equally afraid of both, depending on the relationship phase.", "Slightly more afraid of loss of autonomy and control.", "Slightly more afraid of emotional isolation and abandonment.", "Far more afraid of suffocating expectations from others.", "Far more afraid of sudden abandonment by people I trust.", "Controlled by others in romantic settings, abandoned in friendships.", "Abandoned when vulnerable, controlled when achieving success.", "Controlled, because independence is my highest value.", "Definitely more afraid of being controlled/suffocated.", "Definitely more afraid of being abandoned.", "Equally afraid of both, depending on the relationship phase.", "Slightly more afraid of loss of autonomy and control.", "Slightly more afraid of emotional isolation and abandonment.", "Far more afraid of suffocating expectations from others.", "Far more afraid of sudden abandonment by people I trust.", "Controlled by others in romantic settings, abandoned in friendships.", "Abandoned when vulnerable, controlled when achieving success.", "Controlled, because independence is my highest value.", "Definitely more afraid of being controlled/suffocated.", "Definitely more afraid of being abandoned.", "Equally afraid of both, depending on the relationship phase.", "Slightly more afraid of loss of autonomy and control.", "Slightly more afraid of emotional isolation and abandonment.", "Far more afraid of suffocating expectations from others.", "Far more afraid of sudden abandonment by people I trust.", "Controlled by others in romantic settings, abandoned in friendships.", "Abandoned when vulnerable, controlled when achieving success.", "Controlled, because independence is my highest value."],
        ["By giving thoughtful gifts or buying them their favorite snack.", "By doing practical tasks and acts of service to make their life easier.", "Through physical touch like hugs, high-fives, or patting their shoulder.", "By sending funny memes or articles that reminded me of them.", "By giving genuine, detailed verbal compliments.", "By checking in on them regularly just to see how they're doing.", "By making time to hang out one-on-one.", "By quietly taking care of problems before they notice them.", "By sharing deep personal stories or secrets.", "By defending them or praising them when speaking to others.", "By giving thoughtful gifts or buying them their favorite snack.", "By doing practical tasks and acts of service to make their life easier.", "Through physical touch like hugs, high-fives, or patting their shoulder.", "By sending funny memes or articles that reminded me of them.", "By giving genuine, detailed verbal compliments.", "By checking in on them regularly just to see how they're doing.", "By making time to hang out one-on-one.", "By quietly taking care of problems before they notice them.", "By sharing deep personal stories or secrets.", "By defending them or praising them when speaking to others.", "By giving thoughtful gifts or buying them their favorite snack.", "By doing practical tasks and acts of service to make their life easier.", "Through physical touch like hugs, high-fives, or patting their shoulder.", "By sending funny memes or articles that reminded me of them.", "By giving genuine, detailed verbal compliments.", "By checking in on them regularly just to see how they're doing.", "By making time to hang out one-on-one.", "By quietly taking care of problems before they notice them.", "By sharing deep personal stories or secrets.", "By defending them or praising them when speaking to others.", "By giving thoughtful gifts or buying them their favorite snack.", "By doing practical tasks and acts of service to make their life easier.", "Through physical touch like hugs, high-fives, or patting their shoulder.", "By sending funny memes or articles that reminded me of them.", "By giving genuine, detailed verbal compliments.", "By checking in on them regularly just to see how they're doing.", "By making time to hang out one-on-one.", "By quietly taking care of problems before they notice them.", "By sharing deep personal stories or secrets.", "By defending them or praising them when speaking to others.", "By giving thoughtful gifts or buying them their favorite snack.", "By doing practical tasks and acts of service to make their life easier.", "Through physical touch like hugs, high-fives, or patting their shoulder.", "By sending funny memes or articles that reminded me of them.", "By giving genuine, detailed verbal compliments.", "By checking in on them regularly just to see how they're doing.", "By making time to hang out one-on-one.", "By quietly taking care of problems before they notice them.", "By sharing deep personal stories or secrets.", "By defending them or praising them when speaking to others."],
        ["Large, noisy networking events with surface-level small talk.", "Interactions where people are constantly competing or humble-bragging.", "Group settings where everyone is talking over each other.", "Social gatherings where I don't know anyone except the host.", "Conversations with overly negative people who constantly complain.", "Forced team-building icebreakers at work.", "High-energy parties that last past midnight.", "Dinner parties with passive-aggressive tension in the room.", "Having to talk on the phone for an extended period.", "Interactions where I have to hide my true thoughts and perform.", "Large, noisy networking events with surface-level small talk.", "Interactions where people are constantly competing or humble-bragging.", "Group settings where everyone is talking over each other.", "Social gatherings where I don't know anyone except the host.", "Conversations with overly negative people who constantly complain.", "Forced team-building icebreakers at work.", "High-energy parties that last past midnight.", "Dinner parties with passive-aggressive tension in the room.", "Having to talk on the phone for an extended period.", "Interactions where I have to hide my true thoughts and perform.", "Large, noisy networking events with surface-level small talk.", "Interactions where people are constantly competing or humble-bragging.", "Group settings where everyone is talking over each other.", "Social gatherings where I don't know anyone except the host.", "Conversations with overly negative people who constantly complain.", "Forced team-building icebreakers at work.", "High-energy parties that last past midnight.", "Dinner parties with passive-aggressive tension in the room.", "Having to talk on the phone for an extended period.", "Interactions where I have to hide my true thoughts and perform.", "Large, noisy networking events with surface-level small talk.", "Interactions where people are constantly competing or humble-bragging.", "Group settings where everyone is talking over each other.", "Social gatherings where I don't know anyone except the host.", "Conversations with overly negative people who constantly complain.", "Forced team-building icebreakers at work.", "High-energy parties that last past midnight.", "Dinner parties with passive-aggressive tension in the room.", "Having to talk on the phone for an extended period.", "Interactions where I have to hide my true thoughts and perform.", "Large, noisy networking events with surface-level small talk.", "Interactions where people are constantly competing or humble-bragging.", "Group settings where everyone is talking over each other.", "Social gatherings where I don't know anyone except the host.", "Conversations with overly negative people who constantly complain.", "Forced team-building icebreakers at work.", "High-energy parties that last past midnight.", "Dinner parties with passive-aggressive tension in the room.", "Having to talk on the phone for an extended period.", "Interactions where I have to hide my true thoughts and perform."],
        ["Writing a full fiction novel or screenplay.", "Building a custom piece of software or an app.", "Creating an original music album or sound installation.", "Designing and launching my own small business.", "Mastering a foreign language to fluency.", "Restoring an old piece of furniture or vehicle.", "Writing a detailed personal memoir for my future kids.", "Learning advanced botanical gardening or self-sustainable farming.", "Training for a major endurance fitness event.", "Creating a private archive of family history and interviews.", "Writing a full fiction novel or screenplay.", "Building a custom piece of software or an app.", "Creating an original music album or sound installation.", "Designing and launching my own small business.", "Mastering a foreign language to fluency.", "Restoring an old piece of furniture or vehicle.", "Writing a detailed personal memoir for my future kids.", "Learning advanced botanical gardening or self-sustainable farming.", "Training for a major endurance fitness event.", "Creating a private archive of family history and interviews.", "Writing a full fiction novel or screenplay.", "Building a custom piece of software or an app.", "Creating an original music album or sound installation.", "Designing and launching my own small business.", "Mastering a foreign language to fluency.", "Restoring an old piece of furniture or vehicle.", "Writing a detailed personal memoir for my future kids.", "Learning advanced botanical gardening or self-sustainable farming.", "Training for a major endurance fitness event.", "Creating a private archive of family history and interviews.", "Writing a full fiction novel or screenplay.", "Building a custom piece of software or an app.", "Creating an original music album or sound installation.", "Designing and launching my own small business.", "Mastering a foreign language to fluency.", "Restoring an old piece of furniture or vehicle.", "Writing a detailed personal memoir for my future kids.", "Learning advanced botanical gardening or self-sustainable farming.", "Training for a major endurance fitness event.", "Creating a private archive of family history and interviews.", "Writing a full fiction novel or screenplay.", "Building a custom piece of software or an app.", "Creating an original music album or sound installation.", "Designing and launching my own small business.", "Mastering a foreign language to fluency.", "Restoring an old piece of furniture or vehicle.", "Writing a detailed personal memoir for my future kids.", "Learning advanced botanical gardening or self-sustainable farming.", "Training for a major endurance fitness event.", "Creating a private archive of family history and interviews."],
        ["Driven almost entirely by simple curiosity and wanting to know how things work.", "Driven mostly by a fear of failing and falling behind.", "Driven primarily by a strong desire to achieve and build something notable.", "A blend of curiosity (60%) and desire to achieve (40%).", "A blend of fear of failure (50%) and desire to achieve (50%).", "Driven by curiosity first, achievement second, and fear last.", "Driven by the high of accomplishing difficult challenges.", "Driven by the fear of wasted potential.", "Driven by deep personal standards of excellence.", "Driven by pure intellectual curiosity and playfulness.", "Driven almost entirely by simple curiosity and wanting to know how things work.", "Driven mostly by a fear of failing and falling behind.", "Driven primarily by a strong desire to achieve and build something notable.", "A blend of curiosity (60%) and desire to achieve (40%).", "A blend of fear of failure (50%) and desire to achieve (50%).", "Driven by curiosity first, achievement second, and fear last.", "Driven by the high of accomplishing difficult challenges.", "Driven by the fear of wasted potential.", "Driven by deep personal standards of excellence.", "Driven by pure intellectual curiosity and playfulness.", "Driven almost entirely by simple curiosity and wanting to know how things work.", "Driven mostly by a fear of failing and falling behind.", "Driven primarily by a strong desire to achieve and build something notable.", "A blend of curiosity (60%) and desire to achieve (40%).", "A blend of fear of failure (50%) and desire to achieve (50%).", "Driven by curiosity first, achievement second, and fear last.", "Driven by the high of accomplishing difficult challenges.", "Driven by the fear of wasted potential.", "Driven by deep personal standards of excellence.", "Driven by pure intellectual curiosity and playfulness.", "Driven almost entirely by simple curiosity and wanting to know how things work.", "Driven mostly by a fear of failing and falling behind.", "Driven primarily by a strong desire to achieve and build something notable.", "A blend of curiosity (60%) and desire to achieve (40%).", "A blend of fear of failure (50%) and desire to achieve (50%).", "Driven by curiosity first, achievement second, and fear last.", "Driven by the high of accomplishing difficult challenges.", "Driven by the fear of wasted potential.", "Driven by deep personal standards of excellence.", "Driven by pure intellectual curiosity and playfulness.", "Driven almost entirely by simple curiosity and wanting to know how things work.", "Driven mostly by a fear of failing and falling behind.", "Driven primarily by a strong desire to achieve and build something notable.", "A blend of curiosity (60%) and desire to achieve (40%).", "A blend of fear of failure (50%) and desire to achieve (50%).", "Driven by curiosity first, achievement second, and fear last.", "Driven by the high of accomplishing difficult challenges.", "Driven by the fear of wasted potential.", "Driven by deep personal standards of excellence.", "Driven by pure intellectual curiosity and playfulness."],
        ["I evaluate if the project still aligns with my core values and joy.", "I check if the progress is zero after repeated, varied attempts.", "I set a strict deadline/budget beforehand and stick to it.", "I consult a trusted mentor or neutral third party.", "I ask myself if I'm holding on out of pride or genuine promise.", "I look at whether staying causes diminishing returns on mental health.", "I test whether a small pivot revives interest or if it's dead weight.", "I measure if the opportunity cost outweighs potential reward.", "I trust my gut feeling after sleeping on it for a week.", "I evaluate if I am running away from fear or moving toward growth.", "I evaluate if the project still aligns with my core values and joy.", "I check if the progress is zero after repeated, varied attempts.", "I set a strict deadline/budget beforehand and stick to it.", "I consult a trusted mentor or neutral third party.", "I ask myself if I'm holding on out of pride or genuine promise.", "I look at whether staying causes diminishing returns on mental health.", "I test whether a small pivot revives interest or if it's dead weight.", "I measure if the opportunity cost outweighs potential reward.", "I trust my gut feeling after sleeping on it for a week.", "I evaluate if I am running away from fear or moving toward growth.", "I evaluate if the project still aligns with my core values and joy.", "I check if the progress is zero after repeated, varied attempts.", "I set a strict deadline/budget beforehand and stick to it.", "I consult a trusted mentor or neutral third party.", "I ask myself if I'm holding on out of pride or genuine promise.", "I look at whether staying causes diminishing returns on mental health.", "I test whether a small pivot revives interest or if it's dead weight.", "I measure if the opportunity cost outweighs potential reward.", "I trust my gut feeling after sleeping on it for a week.", "I evaluate if I am running away from fear or moving toward growth.", "I evaluate if the project still aligns with my core values and joy.", "I check if the progress is zero after repeated, varied attempts.", "I set a strict deadline/budget beforehand and stick to it.", "I consult a trusted mentor or neutral third party.", "I ask myself if I'm holding on out of pride or genuine promise.", "I look at whether staying causes diminishing returns on mental health.", "I test whether a small pivot revives interest or if it's dead weight.", "I measure if the opportunity cost outweighs potential reward.", "I trust my gut feeling after sleeping on it for a week.", "I evaluate if I am running away from fear or moving toward growth.", "I evaluate if the project still aligns with my core values and joy.", "I check if the progress is zero after repeated, varied attempts.", "I set a strict deadline/budget beforehand and stick to it.", "I consult a trusted mentor or neutral third party.", "I ask myself if I'm holding on out of pride or genuine promise.", "I look at whether staying causes diminishing returns on mental health.", "I test whether a small pivot revives interest or if it's dead weight.", "I measure if the opportunity cost outweighs potential reward.", "I trust my gut feeling after sleeping on it for a week.", "I evaluate if I am running away from fear or moving toward growth."],
        ["Waking up naturally, walking to a cozy cafe, and reading for hours.", "Spending the entire day hiking in a quiet forest with my dog.", "Browsing an old bookstore, then cooking an elaborate meal at home.", "Renting a kayak and spending the afternoon out on the lake.", "Sleeping in, playing video games guilt-free, and ordering takeout.", "Visiting an art museum solo, followed by coffee and sketching.", "Road-tripping to a small nearby town without a map or plan.", "Gardening all morning and taking a long afternoon nap.", "Baking bread from scratch while listening to vinyl records.", "Spending hours at a local spa followed by a long movie night.", "Waking up naturally, walking to a cozy cafe, and reading for hours.", "Spending the entire day hiking in a quiet forest with my dog.", "Browsing an old bookstore, then cooking an elaborate meal at home.", "Renting a kayak and spending the afternoon out on the lake.", "Sleeping in, playing video games guilt-free, and ordering takeout.", "Visiting an art museum solo, followed by coffee and sketching.", "Road-tripping to a small nearby town without a map or plan.", "Gardening all morning and taking a long afternoon nap.", "Baking bread from scratch while listening to vinyl records.", "Spending hours at a local spa followed by a long movie night.", "Waking up naturally, walking to a cozy cafe, and reading for hours.", "Spending the entire day hiking in a quiet forest with my dog.", "Browsing an old bookstore, then cooking an elaborate meal at home.", "Renting a kayak and spending the afternoon out on the lake.", "Sleeping in, playing video games guilt-free, and ordering takeout.", "Visiting an art museum solo, followed by coffee and sketching.", "Road-tripping to a small nearby town without a map or plan.", "Gardening all morning and taking a long afternoon nap.", "Baking bread from scratch while listening to vinyl records.", "Spending hours at a local spa followed by a long movie night.", "Waking up naturally, walking to a cozy cafe, and reading for hours.", "Spending the entire day hiking in a quiet forest with my dog.", "Browsing an old bookstore, then cooking an elaborate meal at home.", "Renting a kayak and spending the afternoon out on the lake.", "Sleeping in, playing video games guilt-free, and ordering takeout.", "Visiting an art museum solo, followed by coffee and sketching.", "Road-tripping to a small nearby town without a map or plan.", "Gardening all morning and taking a long afternoon nap.", "Baking bread from scratch while listening to vinyl records.", "Spending hours at a local spa followed by a long movie night.", "Waking up naturally, walking to a cozy cafe, and reading for hours.", "Spending the entire day hiking in a quiet forest with my dog.", "Browsing an old bookstore, then cooking an elaborate meal at home.", "Renting a kayak and spending the afternoon out on the lake.", "Sleeping in, playing video games guilt-free, and ordering takeout.", "Visiting an art museum solo, followed by coffee and sketching.", "Road-tripping to a small nearby town without a map or plan.", "Gardening all morning and taking a long afternoon nap.", "Baking bread from scratch while listening to vinyl records.", "Spending hours at a local spa followed by a long movie night."],
        ["The history and evolution of video game design mechanics.", "The deep lore of my favorite sci-fi or fantasy universe.", "The physics and engineering behind everyday household appliances.", "Obscure true crime cases and their psychological breakdowns.", "The history of architectural styles in urban centers.", "How coffee bean processing affects final flavor profiles.", "The economic impact of board games and tabletop gaming.", "Fascinating marine biology facts about deep-sea creatures.", "The evolution of 90s alternative rock and grunge movement.", "Basic psychology of habits and behavioral design.", "The history and evolution of video game design mechanics.", "The deep lore of my favorite sci-fi or fantasy universe.", "The physics and engineering behind everyday household appliances.", "Obscure true crime cases and their psychological breakdowns.", "The history of architectural styles in urban centers.", "How coffee bean processing affects final flavor profiles.", "The economic impact of board games and tabletop gaming.", "Fascinating marine biology facts about deep-sea creatures.", "The evolution of 90s alternative rock and grunge movement.", "Basic psychology of habits and behavioral design.", "The history and evolution of video game design mechanics.", "The deep lore of my favorite sci-fi or fantasy universe.", "The physics and engineering behind everyday household appliances.", "Obscure true crime cases and their psychological breakdowns.", "The history of architectural styles in urban centers.", "How coffee bean processing affects final flavor profiles.", "The economic impact of board games and tabletop gaming.", "Fascinating marine biology facts about deep-sea creatures.", "The evolution of 90s alternative rock and grunge movement.", "Basic psychology of habits and behavioral design.", "The history and evolution of video game design mechanics.", "The deep lore of my favorite sci-fi or fantasy universe.", "The physics and engineering behind everyday household appliances.", "Obscure true crime cases and their psychological breakdowns.", "The history of architectural styles in urban centers.", "How coffee bean processing affects final flavor profiles.", "The economic impact of board games and tabletop gaming.", "Fascinating marine biology facts about deep-sea creatures.", "The evolution of 90s alternative rock and grunge movement.", "Basic psychology of habits and behavioral design.", "The history and evolution of video game design mechanics.", "The deep lore of my favorite sci-fi or fantasy universe.", "The physics and engineering behind everyday household appliances.", "Obscure true crime cases and their psychological breakdowns.", "The history of architectural styles in urban centers.", "How coffee bean processing affects final flavor profiles.", "The economic impact of board games and tabletop gaming.", "Fascinating marine biology facts about deep-sea creatures.", "The evolution of 90s alternative rock and grunge movement.", "Basic psychology of habits and behavioral design."],
        ["Building elaborate Lego structures; today I still love DIY projects.", "Playing pretend games in the woods; today I enjoy hiking and camping.", "Drawing and crafting comic books; today I keep a sketch journal.", "Riding bicycles with neighborhood kids; today I cycle or skate.", "Creating imaginary worlds with action figures; today I play RPGs/strategy games.", "Climbing trees; today I do bouldering or rock climbing.", "Playing board games; today I regularly host tabletop game nights.", "Making home movies on a camera; today I edit videos or do photography.", "Reading books under the covers; today I spend hours reading in bed.", "Building forts out of blankets; today I love interior design and cozy spaces.", "Building elaborate Lego structures; today I still love DIY projects.", "Playing pretend games in the woods; today I enjoy hiking and camping.", "Drawing and crafting comic books; today I keep a sketch journal.", "Riding bicycles with neighborhood kids; today I cycle or skate.", "Creating imaginary worlds with action figures; today I play RPGs/strategy games.", "Climbing trees; today I do bouldering or rock climbing.", "Playing board games; today I regularly host tabletop game nights.", "Making home movies on a camera; today I edit videos or do photography.", "Reading books under the covers; today I spend hours reading in bed.", "Building forts out of blankets; today I love interior design and cozy spaces.", "Building elaborate Lego structures; today I still love DIY projects.", "Playing pretend games in the woods; today I enjoy hiking and camping.", "Drawing and crafting comic books; today I keep a sketch journal.", "Riding bicycles with neighborhood kids; today I cycle or skate.", "Creating imaginary worlds with action figures; today I play RPGs/strategy games.", "Climbing trees; today I do bouldering or rock climbing.", "Playing board games; today I regularly host tabletop game nights.", "Making home movies on a camera; today I edit videos or do photography.", "Reading books under the covers; today I spend hours reading in bed.", "Building forts out of blankets; today I love interior design and cozy spaces.", "Building elaborate Lego structures; today I still love DIY projects.", "Playing pretend games in the woods; today I enjoy hiking and camping.", "Drawing and crafting comic books; today I keep a sketch journal.", "Riding bicycles with neighborhood kids; today I cycle or skate.", "Creating imaginary worlds with action figures; today I play RPGs/strategy games.", "Climbing trees; today I do bouldering or rock climbing.", "Playing board games; today I regularly host tabletop game nights.", "Making home movies on a camera; today I edit videos or do photography.", "Reading books under the covers; today I spend hours reading in bed.", "Building forts out of blankets; today I love interior design and cozy spaces.", "Building elaborate Lego structures; today I still love DIY projects.", "Playing pretend games in the woods; today I enjoy hiking and camping.", "Drawing and crafting comic books; today I keep a sketch journal.", "Riding bicycles with neighborhood kids; today I cycle or skate.", "Creating imaginary worlds with action figures; today I play RPGs/strategy games.", "Climbing trees; today I do bouldering or rock climbing.", "Playing board games; today I regularly host tabletop game nights.", "Making home movies on a camera; today I edit videos or do photography.", "Reading books under the covers; today I spend hours reading in bed.", "Building forts out of blankets; today I love interior design and cozy spaces."],
        ["Unscripted, absurd physical comedy and unexpected situational slip-ups.", "Dry, deadpan delivery with understated sarcasm.", "Witty banter and quick-fire wordplay between close friends.", "Dark humor that catches you completely off guard.", "Absurdist, surrealist humor that makes no logical sense.", "Blooper reels of people genuinely laughing uncontrollably.", "Self-deprecating observational humor about daily struggles.", "Improv comedy where actors break character.", "Inside jokes built over years of friendship.", "Clever satire and social parodies.", "Unscripted, absurd physical comedy and unexpected situational slip-ups.", "Dry, deadpan delivery with understated sarcasm.", "Witty banter and quick-fire wordplay between close friends.", "Dark humor that catches you completely off guard.", "Absurdist, surrealist humor that makes no logical sense.", "Blooper reels of people genuinely laughing uncontrollably.", "Self-deprecating observational humor about daily struggles.", "Improv comedy where actors break character.", "Inside jokes built over years of friendship.", "Clever satire and social parodies.", "Unscripted, absurd physical comedy and unexpected situational slip-ups.", "Dry, deadpan delivery with understated sarcasm.", "Witty banter and quick-fire wordplay between close friends.", "Dark humor that catches you completely off guard.", "Absurdist, surrealist humor that makes no logical sense.", "Blooper reels of people genuinely laughing uncontrollably.", "Self-deprecating observational humor about daily struggles.", "Improv comedy where actors break character.", "Inside jokes built over years of friendship.", "Clever satire and social parodies.", "Unscripted, absurd physical comedy and unexpected situational slip-ups.", "Dry, deadpan delivery with understated sarcasm.", "Witty banter and quick-fire wordplay between close friends.", "Dark humor that catches you completely off guard.", "Absurdist, surrealist humor that makes no logical sense.", "Blooper reels of people genuinely laughing uncontrollably.", "Self-deprecating observational humor about daily struggles.", "Improv comedy where actors break character.", "Inside jokes built over years of friendship.", "Clever satire and social parodies.", "Unscripted, absurd physical comedy and unexpected situational slip-ups.", "Dry, deadpan delivery with understated sarcasm.", "Witty banter and quick-fire wordplay between close friends.", "Dark humor that catches you completely off guard.", "Absurdist, surrealist humor that makes no logical sense.", "Blooper reels of people genuinely laughing uncontrollably.", "Self-deprecating observational humor about daily struggles.", "Improv comedy where actors break character.", "Inside jokes built over years of friendship.", "Clever satire and social parodies."],
        ["Eating breakfast food for dinner late at night.", "Watching reality TV shows purely for the drama.", "Singing dramatically to dramatic pop ballads alone in the car.", "Re-watching the same comfort movie for the 50th time.", "Dressing up in fancy clothes just to sit at home.", "Eating dessert first before the main meal.", "Taking two baths in a single day just to relax.", "Listening to cheesy holiday music all year round.", "Buying colorful kids' art supplies just for doodling.", "Collecting weird vintage knick-knacks with no utility.", "Eating breakfast food for dinner late at night.", "Watching reality TV shows purely for the drama.", "Singing dramatically to dramatic pop ballads alone in the car.", "Re-watching the same comfort movie for the 50th time.", "Dressing up in fancy clothes just to sit at home.", "Eating dessert first before the main meal.", "Taking two baths in a single day just to relax.", "Listening to cheesy holiday music all year round.", "Buying colorful kids' art supplies just for doodling.", "Collecting weird vintage knick-knacks with no utility.", "Eating breakfast food for dinner late at night.", "Watching reality TV shows purely for the drama.", "Singing dramatically to dramatic pop ballads alone in the car.", "Re-watching the same comfort movie for the 50th time.", "Dressing up in fancy clothes just to sit at home.", "Eating dessert first before the main meal.", "Taking two baths in a single day just to relax.", "Listening to cheesy holiday music all year round.", "Buying colorful kids' art supplies just for doodling.", "Collecting weird vintage knick-knacks with no utility.", "Eating breakfast food for dinner late at night.", "Watching reality TV shows purely for the drama.", "Singing dramatically to dramatic pop ballads alone in the car.", "Re-watching the same comfort movie for the 50th time.", "Dressing up in fancy clothes just to sit at home.", "Eating dessert first before the main meal.", "Taking two baths in a single day just to relax.", "Listening to cheesy holiday music all year round.", "Buying colorful kids' art supplies just for doodling.", "Collecting weird vintage knick-knacks with no utility.", "Eating breakfast food for dinner late at night.", "Watching reality TV shows purely for the drama.", "Singing dramatically to dramatic pop ballads alone in the car.", "Re-watching the same comfort movie for the 50th time.", "Dressing up in fancy clothes just to sit at home.", "Eating dessert first before the main meal.", "Taking two baths in a single day just to relax.", "Listening to cheesy holiday music all year round.", "Buying colorful kids' art supplies just for doodling.", "Collecting weird vintage knick-knacks with no utility."],
        ["I was short with a coworker under stress; I apologized directly the next day.", "I canceled plans last minute out of fatigue; I owned up and rescheduled.", "I snapped at a family member; I took space and apologized sincerely.", "I handled a breakup poorly; I later sent a genuine message acknowledging my mistakes.", "I spread gossip without thinking; I corrected it immediately and apologized.", "I acted selfishly in a group decision; I yielded my preference to make amends.", "I forgot an important event; I acknowledged my fault without making excuses.", "I gave unsolicited harsh criticism; I apologized for being insensitive.", "I let my pride get in the way of admitting a mistake; I later admitted it openly.", "I reacted defensively during an argument; I called back later to apologize properly.", "I was short with a coworker under stress; I apologized directly the next day.", "I canceled plans last minute out of fatigue; I owned up and rescheduled.", "I snapped at a family member; I took space and apologized sincerely.", "I handled a breakup poorly; I later sent a genuine message acknowledging my mistakes.", "I spread gossip without thinking; I corrected it immediately and apologized.", "I acted selfishly in a group decision; I yielded my preference to make amends.", "I forgot an important event; I acknowledged my fault without making excuses.", "I gave unsolicited harsh criticism; I apologized for being insensitive.", "I let my pride get in the way of admitting a mistake; I later admitted it openly.", "I reacted defensively during an argument; I called back later to apologize properly.", "I was short with a coworker under stress; I apologized directly the next day.", "I canceled plans last minute out of fatigue; I owned up and rescheduled.", "I snapped at a family member; I took space and apologized sincerely.", "I handled a breakup poorly; I later sent a genuine message acknowledging my mistakes.", "I spread gossip without thinking; I corrected it immediately and apologized.", "I acted selfishly in a group decision; I yielded my preference to make amends.", "I forgot an important event; I acknowledged my fault without making excuses.", "I gave unsolicited harsh criticism; I apologized for being insensitive.", "I let my pride get in the way of admitting a mistake; I later admitted it openly.", "I reacted defensively during an argument; I called back later to apologize properly.", "I was short with a coworker under stress; I apologized directly the next day.", "I canceled plans last minute out of fatigue; I owned up and rescheduled.", "I snapped at a family member; I took space and apologized sincerely.", "I handled a breakup poorly; I later sent a genuine message acknowledging my mistakes.", "I spread gossip without thinking; I corrected it immediately and apologized.", "I acted selfishly in a group decision; I yielded my preference to make amends.", "I forgot an important event; I acknowledged my fault without making excuses.", "I gave unsolicited harsh criticism; I apologized for being insensitive.", "I let my pride get in the way of admitting a mistake; I later admitted it openly.", "I reacted defensively during an argument; I called back later to apologize properly.", "I was short with a coworker under stress; I apologized directly the next day.", "I canceled plans last minute out of fatigue; I owned up and rescheduled.", "I snapped at a family member; I took space and apologized sincerely.", "I handled a breakup poorly; I later sent a genuine message acknowledging my mistakes.", "I spread gossip without thinking; I corrected it immediately and apologized.", "I acted selfishly in a group decision; I yielded my preference to make amends.", "I forgot an important event; I acknowledged my fault without making excuses.", "I gave unsolicited harsh criticism; I apologized for being insensitive.", "I let my pride get in the way of admitting a mistake; I later admitted it openly.", "I reacted defensively during an argument; I called back later to apologize properly."],
        ["Someone effortlessly achieving financial freedom at a young age.", "Someone who possesses natural, unshakeable charisma and ease in groups.", "Someone living in a beautiful location with unlimited travel freedom.", "Someone who completes major creative projects effortlessly.", "Someone with a super close-knit, supportive family network.", "Someone who is consistently disciplined without ever burning out.", "Someone who speaks multiple languages fluently.", "Someone who receives widespread recognition for their art/work.", "Someone who seems entirely unbothered by what others think.", "Someone with a perfect work-life balance and zero stress.", "Someone effortlessly achieving financial freedom at a young age.", "Someone who possesses natural, unshakeable charisma and ease in groups.", "Someone living in a beautiful location with unlimited travel freedom.", "Someone who completes major creative projects effortlessly.", "Someone with a super close-knit, supportive family network.", "Someone who is consistently disciplined without ever burning out.", "Someone who speaks multiple languages fluently.", "Someone who receives widespread recognition for their art/work.", "Someone who seems entirely unbothered by what others think.", "Someone with a perfect work-life balance and zero stress.", "Someone effortlessly achieving financial freedom at a young age.", "Someone who possesses natural, unshakeable charisma and ease in groups.", "Someone living in a beautiful location with unlimited travel freedom.", "Someone who completes major creative projects effortlessly.", "Someone with a super close-knit, supportive family network.", "Someone who is consistently disciplined without ever burning out.", "Someone who speaks multiple languages fluently.", "Someone who receives widespread recognition for their art/work.", "Someone who seems entirely unbothered by what others think.", "Someone with a perfect work-life balance and zero stress.", "Someone effortlessly achieving financial freedom at a young age.", "Someone who possesses natural, unshakeable charisma and ease in groups.", "Someone living in a beautiful location with unlimited travel freedom.", "Someone who completes major creative projects effortlessly.", "Someone with a super close-knit, supportive family network.", "Someone who is consistently disciplined without ever burning out.", "Someone who speaks multiple languages fluently.", "Someone who receives widespread recognition for their art/work.", "Someone who seems entirely unbothered by what others think.", "Someone with a perfect work-life balance and zero stress.", "Someone effortlessly achieving financial freedom at a young age.", "Someone who possesses natural, unshakeable charisma and ease in groups.", "Someone living in a beautiful location with unlimited travel freedom.", "Someone who completes major creative projects effortlessly.", "Someone with a super close-knit, supportive family network.", "Someone who is consistently disciplined without ever burning out.", "Someone who speaks multiple languages fluently.", "Someone who receives widespread recognition for their art/work.", "Someone who seems entirely unbothered by what others think.", "Someone with a perfect work-life balance and zero stress."],
        ["My intense competitiveness in simple casual games.", "My tendency to over-analyze every small detail.", "My bluntness and directness when expressing opinions.", "My deep need for order and quiet control.", "My sarcastic humor before knowing if they share it.", "My tendency to overshare personal details early.", "My quietness, which people sometimes mistake for coldness.", "My high expectations and impatience with inefficiency.", "My strong stubbornness on topics I feel passionate about.", "My anxiety and habit of second-guessing social cues.", "My intense competitiveness in simple casual games.", "My tendency to over-analyze every small detail.", "My bluntness and directness when expressing opinions.", "My deep need for order and quiet control.", "My sarcastic humor before knowing if they share it.", "My tendency to overshare personal details early.", "My quietness, which people sometimes mistake for coldness.", "My high expectations and impatience with inefficiency.", "My strong stubbornness on topics I feel passionate about.", "My anxiety and habit of second-guessing social cues.", "My intense competitiveness in simple casual games.", "My tendency to over-analyze every small detail.", "My bluntness and directness when expressing opinions.", "My deep need for order and quiet control.", "My sarcastic humor before knowing if they share it.", "My tendency to overshare personal details early.", "My quietness, which people sometimes mistake for coldness.", "My high expectations and impatience with inefficiency.", "My strong stubbornness on topics I feel passionate about.", "My anxiety and habit of second-guessing social cues.", "My intense competitiveness in simple casual games.", "My tendency to over-analyze every small detail.", "My bluntness and directness when expressing opinions.", "My deep need for order and quiet control.", "My sarcastic humor before knowing if they share it.", "My tendency to overshare personal details early.", "My quietness, which people sometimes mistake for coldness.", "My high expectations and impatience with inefficiency.", "My strong stubbornness on topics I feel passionate about.", "My anxiety and habit of second-guessing social cues.", "My intense competitiveness in simple casual games.", "My tendency to over-analyze every small detail.", "My bluntness and directness when expressing opinions.", "My deep need for order and quiet control.", "My sarcastic humor before knowing if they share it.", "My tendency to overshare personal details early.", "My quietness, which people sometimes mistake for coldness.", "My high expectations and impatience with inefficiency.", "My strong stubbornness on topics I feel passionate about.", "My anxiety and habit of second-guessing social cues."],
        ["That I am genuinely reliable, kind, and always there when needed.", "That I make people feel safe, heard, and valued.", "That I am hilariously funny and bring great energy to the room.", "That I am remarkably thoughtful and deeply authentic.", "That I am resilient and inspiring in how I handle life.", "That I am trustworthy and keep secrets without fail.", "That I bring clarity and calm to chaotic situations.", "That I am creative and uniquely insightful.", "That life is simply more fun when I am around.", "That I am honest, fair, and hold no malice toward anyone.", "That I am genuinely reliable, kind, and always there when needed.", "That I make people feel safe, heard, and valued.", "That I am hilariously funny and bring great energy to the room.", "That I am remarkably thoughtful and deeply authentic.", "That I am resilient and inspiring in how I handle life.", "That I am trustworthy and keep secrets without fail.", "That I bring clarity and calm to chaotic situations.", "That I am creative and uniquely insightful.", "That life is simply more fun when I am around.", "That I am honest, fair, and hold no malice toward anyone.", "That I am genuinely reliable, kind, and always there when needed.", "That I make people feel safe, heard, and valued.", "That I am hilariously funny and bring great energy to the room.", "That I am remarkably thoughtful and deeply authentic.", "That I am resilient and inspiring in how I handle life.", "That I am trustworthy and keep secrets without fail.", "That I bring clarity and calm to chaotic situations.", "That I am creative and uniquely insightful.", "That life is simply more fun when I am around.", "That I am honest, fair, and hold no malice toward anyone.", "That I am genuinely reliable, kind, and always there when needed.", "That I make people feel safe, heard, and valued.", "That I am hilariously funny and bring great energy to the room.", "That I am remarkably thoughtful and deeply authentic.", "That I am resilient and inspiring in how I handle life.", "That I am trustworthy and keep secrets without fail.", "That I bring clarity and calm to chaotic situations.", "That I am creative and uniquely insightful.", "That life is simply more fun when I am around.", "That I am honest, fair, and hold no malice toward anyone.", "That I am genuinely reliable, kind, and always there when needed.", "That I make people feel safe, heard, and valued.", "That I am hilariously funny and bring great energy to the room.", "That I am remarkably thoughtful and deeply authentic.", "That I am resilient and inspiring in how I handle life.", "That I am trustworthy and keep secrets without fail.", "That I bring clarity and calm to chaotic situations.", "That I am creative and uniquely insightful.", "That life is simply more fun when I am around.", "That I am honest, fair, and hold no malice toward anyone."]
    ]

    sm_content = []
    total_questions = 2
    current_q = 1
    print(f"\n--- Scenario & Memories ---")
    for question in ("What is the scenario now?", "What are the memories?"):
        print(f"\n[{current_q}/{total_questions}] {question}")
        answer = input("My Answer: ").strip()

        sm_content.append(answer)
        current_q += 1

    persona_content = []
    for awnser in answers:
        persona_content.append(random.choice(awnser))

    ama_file = AMA(ama_file_path)
    ama_file.write(persona_content, sm_content[0], sm_content[1], auto_compression)
    info(f"Your persona profile has been compiled and saved to '{os.path.abspath(ama_file_path)}'.")

@elogw
def edit_persona(ama_file_path:str, value:object=None, index:int=None, json_file_path:str=None):
    ama_file = AMA(ama_file_path)

    if value != None:
        if index != None:
            persona_list = ama_file.read().get_persona_list()
            persona_list[index] = value
            ama_file.write(persona_list, ama_file.read().get_scenario(), ama_file.read().get_memories(), ama_file.isCompressed(), False)
        else:
            ama_file.write(value, ama_file.read().get_scenario(), ama_file.read().get_memories(), ama_file.isCompressed(), False)
    elif json_file_path != None:
        with open(json_file_path, 'r') as f:
            json_file = json.load(f)
        if index != None:
            persona_list = ama_file.read().get_persona_list()
            persona_list[index] = json_file
            ama_file.write(persona_list, ama_file.read().get_scenario(), ama_file.read().get_memories(), ama_file.isCompressed(), False)
        else:
            ama_file.write(json_file, ama_file.read().get_scenario(), ama_file.read().get_memories(), ama_file.isCompressed(), False)
    else:
        error("edit_persona requires value or json_file_path to be set!")

@elogw
def edit_scenario(ama_file_path:str, text:str=None, append:str=None, json_file_path:str=None):
    ama_file = AMA(ama_file_path)

    if json_file_path != None:
        with open(json_file_path, 'r') as f:
            json_file = json.load(f)
        if text != None:
            ama_file.write(ama_file.read().get_persona_list(), json_file, ama_file.read().get_memories(), ama_file.isCompressed(), False)
        elif append != None:
            scenario = ama_file.read().get_scenario()
            scenario += "\n"+json_file
            ama_file.write(ama_file.read().get_persona_list(), scenario, ama_file.read().get_memories(), ama_file.isCompressed(), False)
        else:
            error("edit_scenario requires text or append to be set!")
    else:
        if text != None:
            ama_file.write(ama_file.read().get_persona_list(), text, ama_file.read().get_memories(), ama_file.isCompressed(), False)
        elif append != None:
            scenario = ama_file.read().get_scenario()
            scenario += "\n"+append
            ama_file.write(ama_file.read().get_persona_list(), scenario, ama_file.read().get_memories(), ama_file.isCompressed(), False)
        else:
            error("edit_scenario requires text or append to be set!")

@elogw
def edit_memories(ama_file_path:str, text:str=None, append:str=None, json_file_path:str=None):
    ama_file = AMA(ama_file_path)

    if json_file_path != None:
        with open(json_file_path, 'r') as f:
            json_file = json.load(f)
        if text != None:
            ama_file.write(ama_file.read().get_persona_list(), ama_file.read().get_scenario(), json_file, ama_file.isCompressed(), False)
        elif append != None:
            memories = ama_file.read().get_memories()
            memories += "\n"+json_file
            ama_file.write(ama_file.read().get_persona_list(), ama_file.read().get_scenario(), memories, ama_file.isCompressed(), False)
        else:
            error("edit_memories requires text or append to be set!")
    else:
        if text != None:
            ama_file.write(ama_file.read().get_persona_list(), ama_file.read().get_scenario(), text, ama_file.isCompressed(), False)
        elif append != None:
            memories = ama_file.read().get_memories()
            memories += "\n"+append
            ama_file.write(ama_file.read().get_persona_list(), ama_file.read().get_scenario(), memories, ama_file.isCompressed(), False)
        else:
            error("edit_memories requires text or append to be set!")

@elogw
def read(ama_file_path:str, ama_property:str):
    elog(f"Called read with agrs: {ama_file_path}, {ama_property}")
    ama_file = AMA(ama_file_path)
    if ama_property == "persona_list":
        pprint.pprint(ama_file.read().get_persona_list())
    elif ama_property == "scenario":
        pprint.pprint(ama_file.read().get_scenario())
    elif ama_property == "memories":
        pprint.pprint(ama_file.read().get_memories())

def main():
    global ELOGGING, LOGGING
    models = ["nchapman/dolphin3.0-qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b"]

    parser = argparse.ArgumentParser(description="AiMan: Run and handel AMA models")
    parser.add_argument("-v", "--version", action="version", version="AiMan "+__version__, help="Get currect version")
    parser.add_argument("-av", "--amaversion", action="version", version="AMA "+AMA_VERSION, help="Get currect version")
    parser.add_argument("-t", "--telemetry", action="store_true", help="Enable extra info (Tipicly used for debugging or nice for logs)")
    parser.add_argument("-et", "--extremetelemetry", action="store_true", help="Every function call is loged. only for debugging, not for logs!")
    subparsers = parser.add_subparsers(dest="action", required=True, help="What action to do")

    run_parser = subparsers.add_parser("run", help="Run and chat with a AMA model")
    run_group = run_parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument("-m", "--model", type=int, help="Use a pre chosen AI model from fast (0) to pro (3)")
    run_group.add_argument("-c", "--custom", type=str, metavar="MODEL", help="Use a custom ollama model")
    run_parser.add_argument("-d", "--dayinfo", action="store_true", help="Give the model simple info about today")
    run_parser.add_argument("ama_file", type=str, help="AMA file path")

    make_parser = subparsers.add_parser("make", help="Make a AMA file")
    make_parser.add_argument("-n", "--nocompression", action="store_true", help="Disable auto compression of the AMA file (Recommended to keep on)")
    make_parser.add_argument("-r", "--random", action="store_true", help="Make a random persona")
    make_parser.add_argument("ama_file", type=str, help="new AMA file path")

    json_parser = subparsers.add_parser("json", help="Handel AMA json files")
    json_parser.add_argument("ama_file", type=str, help="AMA file path")
    json_subparser = json_parser.add_subparsers(dest="choice", required=True, help="Choose from or to json file")
    json_from_parser = json_subparser.add_parser("from", help="Get AMA file from json file")
    json_from_parser.add_argument("-n", "--nocompression", action="store_true", help="Disable auto compression of the AMA file (Recommended to keep on)")
    json_from_parser.add_argument("json_file", type=str, help="Json file path")
    json_to_parser = json_subparser.add_parser("to", help="Get json file from AMA file")
    json_to_parser.add_argument("json_file", type=str, help="Json file path")

    edit_parser = subparsers.add_parser("edit", help="Edit content from a AMA file")
    edit_parser.add_argument("ama_file", type=str, help="AMA file path")
    prop_subparsers = edit_parser.add_subparsers(dest="ama_property", required=True, help="What AMA propertie to edit")
    persona_parser = prop_subparsers.add_parser("persona_list", help="Edit the persona_list value of the AMA file")
    persona_group = persona_parser.add_mutually_exclusive_group(required=True)
    persona_group.add_argument("-l", "--list", type=str, help="Replace the intire list")
    persona_group.add_argument("-s", "--set", nargs=2, type=str, metavar=("INDEX", "VALUE"), help="Set one specific index to a value")
    persona_group.add_argument("-lf", "--listfile", type=str, metavar="JSON", help="Replace the intire list from a json file")
    persona_group.add_argument("-sf", "--setfile", nargs=2, type=str, metavar=("INDEX", "JSON"), help="Set one specific index to a value from a json file")
    scenario_parser = prop_subparsers.add_parser("scenario", help="Edit the scenario value of the AMA file")
    scenario_group = scenario_parser.add_mutually_exclusive_group(required=True)
    scenario_group.add_argument("-t", "--text", type=str, metavar="VALUE", help="Replace the intire text")
    scenario_group.add_argument("-a", "--append", type=str, metavar="VALUE", help="Append with a new line to the text")
    scenario_group.add_argument("-tf", "--textfile", type=str, metavar="JSON", help="Replace the intire text from a json file")
    scenario_group.add_argument("-af", "--appendfile", type=str, metavar="JSON", help="Append with a new line to the text from a json file")
    memories_parser = prop_subparsers.add_parser("memories", help="Edit the memories value of the AMA file")
    memories_group = memories_parser.add_mutually_exclusive_group(required=True)
    memories_group.add_argument("-t", "--text", type=str, metavar="VALUE", help="Replace the intire text")
    memories_group.add_argument("-a", "--append", type=str, metavar="VALUE", help="Append with a new line to the text")
    memories_group.add_argument("-tf", "--textfile", type=str, metavar="JSON", help="Replace the intire text from a json file")
    memories_group.add_argument("-af", "--appendfile", type=str, metavar="JSON", help="Append with a new line to the text from a json file")

    read_parser = subparsers.add_parser("read", help="Read content from a AMA file")
    read_parser.add_argument("ama_file", type=str, help="AMA file path")
    read_prop_subparsers = read_parser.add_subparsers(dest="ama_property", required=True, help="What AMA propertie to edit")
    read_prop_subparsers.add_parser("persona_list", help="Read the persona_list value of the AMA file")
    read_prop_subparsers.add_parser("scenario", help="Read the scenario value of the AMA file")
    read_prop_subparsers.add_parser("memories", help="Read the memories value of the AMA file")

    args = parser.parse_args()

    ELOGGING = args.extremetelemetry
    LOGGING = args.telemetry or ELOGGING

    log("Version: "+__version__)
    log("AMA Version: "+AMA_VERSION)
    log("OS: "+platform.system())

    try:
        with urllib.request.urlopen("https://api.github.com/repos/Orbinuity/AiMan/releases/latest") as response:
            latest_release_json = json.loads(response.read().decode())
            latest_version = latest_release_json["tag_name"]

            if latest_version != __version__:
                info(f"A new version is avalable, install it by running: {'irm https://raw.githubusercontent.com/Orbinuity/AiMan/main/install.ps1 | iex' if platform.system() == 'Windows' else 'curl -fsSL https://raw.githubusercontent.com/Orbinuity/AiMan/main/install.sh | sh'}")
                log(f"This version: '{__version__}', new version: '{latest_version}'")
    except urllib.error.URLError:
        pass

    olc = OllamaCheck()

    if not olc.is_ollama_installed():
        info("Ollama is not installed, installing ollama...")
        olc.install_ollama()
    if not olc.is_ollama_running():
        info("Starting ollama...")
        olc.start_ollama_service()

    if args.action == "run":
        ollama_model = models[args.model] if args.model != None else args.custom
        if not olc.is_model_installed(ollama_model):
            info(f"Downloading model '{ollama_model}' (this may take a few minutes)")
            olc.install_model(ollama_model)
        run(args.ama_file, ollama_model, args.dayinfo)
    elif args.action == "make":
        if args.random:
            random_persona(args.ama_file, not args.nocompression)
        else:
            make(args.ama_file, not args.nocompression)
    elif args.action == "json":
        if args.choice == "from":
            json_to_ama(args.json_file, args.ama_file, not args.nocompression)
        elif args.choice == "to":
            ama_to_json(args.ama_file, args.json_file)
    elif args.action == "edit":
        if args.ama_property == "persona_list":
            if args.list != None:
                try:
                    alist = ast.literal_eval(args.list)
                except (ValueError, SyntaxError):
                    error(f"LIST needs to be list in str (\"['item1', 'item2']\") not {type(args.list).__name__}!")
                edit_persona(args.ama_file, value=alist)

            elif args.set != None:
                try:
                    index = int(args.set[0])
                except (ValueError, SyntaxError):
                    error(f"INDEX needs to be int not {type(args.set[0]).__name__}!")
                edit_persona(args.ama_file, index=index, value=args.set[1])

            elif args.listfile != None:
                edit_persona(args.ama_file, json_file_path=args.listfile)

            elif args.setfile != None:
                try:
                    index = int(args.setfile[0])
                except (ValueError, SyntaxError):
                    error(f"INDEX needs to be int not {type(args.setfile[0]).__name__}!")
                edit_persona(args.ama_file, index=index, json_file_path=args.setfile[1])
        elif args.ama_property == "scenario":
            if args.text != None:
                edit_scenario(args.ama_file, text=args.text)
            elif args.append != None:
                edit_scenario(args.ama_file, append=args.append)
            elif args.textfile != None:
                edit_scenario(args.ama_file, text="", json_file_path=args.textfile)
            elif args.appendfile != None:
                edit_scenario(args.ama_file, append="", json_file_path=args.appendfile)
        elif args.ama_property == "memories":
            if args.text != None:
                edit_memories(args.ama_file, text=args.text)
            elif args.append != None:
                edit_memories(args.ama_file, append=args.append)
            elif args.textfile != None:
                edit_memories(args.ama_file, text="", json_file_path=args.textfile)
            elif args.appendfile != None:
                edit_memories(args.ama_file, append="", json_file_path=args.appendfile)
    elif args.action == "read":
        read(args.ama_file, args.ama_property)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print()
        info("Aborted.")
        sys.exit(0)
    except Exception as e:
        if ELOGGING:
            print_traceback()
            sys.exit(1)
        if LOGGING:
            info("Something went wrong! Please report this issue at https://github.com/Orbinuity/AiMan/issues/new?template=bug_report.yml")
            error(f"[{type(e).__name__}] {e}")
        error("Something went wrong! Please report this issue at https://github.com/Orbinuity/AiMan/issues/new?template=bug_report.yml")