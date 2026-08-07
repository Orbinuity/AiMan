#!/bin/python
from functools import wraps
from datetime import date
import urllib.request
import subprocess
import traceback
import platform
import argparse
import inspect
import ollama
import pprint
import shutil
import time
import lzma
import json
import sys
import ast
import os
import re

__version__ = "v1.0"
ELOGGING = False
LOGGING = False
LIST_LENGTH = 30
START_BYTES = (b"\x41\x4d\x41\x31")

# Helpers
def elog(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        result = func(*args, **kwargs)
        if ELOGGING:
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            arg_str = ", ".join(f"{k}: {repr(v)}" for k, v in bound.arguments.items())
            log(f"Calling {func.__qualname__} | Returned: {repr(result)} | Args: {arg_str}")
        return result
    return wrapper

def log(message:str, not_for_elog:bool=False):
    if (LOGGING or ELOGGING) and not (ELOGGING and not_for_elog):
        for i in message.splitlines():
            print(f"\033[93;1mLog>\033[00m\033[93m {i}\033[00m")

def info(message:str):
    for i in message.splitlines():
        print(f"\033[96;1mInfo>\033[00m\033[96m {i}\033[00m")

def error(message:str):
    for i in message.splitlines():
        print(f"\033[91;1mERROR>\033[00m\033[91m {i}\033[00m")
    sys.exit(1)

def dubble_input(text1, text2):
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

        if system in ("Linux", "Darwin"):
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
    @elog
    def __init__(self, file_path: str):
        self.file_path = file_path
        self.file_bytes = None
        self.read_ama = None

    @elog
    def write(self, persona_list:list[str], scenario:str, memories:str, auto_compression:bool=True, overwrite_warning:bool=True):
        elog(f"Called AMA.write with agrs: {persona_list}, {scenario}, {memories}, {auto_compression}, {overwrite_warning}")
        if len(persona_list) != LIST_LENGTH - 2:
            error(f"Persona list must be a length of {LIST_LENGTH - 2}, not {len(persona_list)}.")

        full_list = persona_list + [scenario] + [memories]

        header_lengths = b""
        body_bytes = b""

        for item in full_list:
            encoded_item = item.encode("utf-8")
            header_lengths += len(encoded_item).to_bytes(2, byteorder="big")
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

    @elog
    def open(self):
        if self.file_bytes:
            return self.file_bytes

        with open(self.file_path, "rb") as file:
            file_bytes = file.read()
        
        start_len = len(START_BYTES)

        if file_bytes[:start_len] != START_BYTES:
            error(f"This file is not a {__version__.split(".")[0]}.* AMA file!")

        flag = file_bytes[start_len : start_len + 1]

        if not flag in (b"\x11", b"\x00"):
            error("This AMA file might be corrupt!")

        self.file_bytes = file_bytes
        return self.file_bytes

    @elog
    def isCompressed(self):
        start_len = len(START_BYTES)
        file_bytes = self.open()
        return file_bytes[start_len : start_len + 1] == b"\x11"

    @elog
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

        header_len_bytes = LIST_LENGTH * 2
        lengths_bytes = payload[:header_len_bytes]
        lengths = [int.from_bytes(lengths_bytes[i : i + 2], byteorder="big") for i in range(0, header_len_bytes, 2)]

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
    @elog
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

    @elog
    def get_persona(self):
        full_text = ""
        for p in range(len(self.persona_list)):
            text = self.persona_list[p]
            if text in (None, "", " ", "\t"):
                text = "Im not sure I had an experiance like that, or maby I just forgot?"
            full_text += self.persona_properties[p]+ ": " + text + "\n"

        return full_text

    @elog
    def get_persona_list(self):
        return self.persona_list

    @elog
    def get_persona_index(self, index:int):
        return self.persona_list[index]

    @elog
    def get_scenario(self):
        return self.scenario

    @elog
    def get_memories(self):
        return self.memories

class AiMan:
    @elog
    def __init__(self, ama_file_path:str, ollama_model:str, dayinfo:bool="False"):
        self.ama = AMA(ama_file_path)

        ama_info = self.ama.read()
        self.messages = [
            {
                'role': 'system',
                'content': f"""You are roleplaying as the person described below in a quick text message exchange.
The details below are YOUR private knowledge base. You must NEVER recite this information unprompted.
{f"""
[INFO ABOUT TODAY]
It is {date.today()} today.
""" if dayinfo else ""}
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

    @elog
    def get_first_name(self):
        return self.ama.read().get_persona_index(0)

    @elog
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

    @elog
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

        if new_memories and not new_memories in ("NONE", "'NONE'", " 'NONE'", "'NONE'.", " 'NONE'."):
            memories = self.ama.read().get_memories()
            memories += "\n"+new_memories
            self.ama.write(self.ama.read().get_persona_list(), self.ama.read().get_scenario(), memories, self.ama.isCompressed(), False)
            info("Memories saved successfully")
            log(new_memories)
        else:
            info("No memories ware fond.")

# UI
@elog
def run(ama_file_path:str, ollama_model:str, dayinfo:bool="False"):
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
            user_type, user_inp = dubble_input("\033[94;1mYou>\033[00m\033[94m ", "\033[92;1mSystem>\033[00m\033[92m ")
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

@elog
def json_to_ama(json_file_path:str, ama_file_path:str, auto_comperssion:bool=True):
    with open(json_file_path, 'r') as f:
        json_file = json.load(f)

    if "persona" not in json_file or "scenario" not in json_file or "memories" not in json_file or type(json_file["persona"]) != list or type(json_file["scenario"]) != str or type(json_file["memories"]) != str or len(json_file["persona"]) != LIST_LENGTH-2:
        error("Json file is not correctly formatted!")

    ama_file = AMA(ama_file_path)
    ama_file.write(json_file["persona"], json_file["scenario"], json_file["memories"], auto_comperssion)

@elog
def ama_to_json(ama_file_path:str, json_file_path:str, overwrite_warning:bool=True):
    ama_file = AMA(ama_file_path).read()

    if overwrite_warning and (os.path.isfile(json_file_path) or os.path.isdir(json_file_path)) and not yn_input(f"The file {json_file_path} already exists, are you sure you want to overwrite this file?"):
        return

    with open(json_file_path, 'w') as f:
        json.dump({"persona": ama_file.get_persona_list(), "scenario": ama_file.get_scenario(), "memories": ama_file.get_memories()}, f, indent=4)

@elog
def make(ama_file_path:str, auto_comperssion:bool=True):
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
    
    try:
        ama_file = AMA(ama_file_path)
        ama_file.write(persona_content, sm_content[0], sm_content[1], auto_comperssion)
        print(f"\nSuccess! Your persona profile has been compiled and saved to '{os.path.abspath(ama_file_path)}'.")
    except Exception as e:
        print(f"\nAn error occurred while saving the file: {e}")

@elog
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

@elog
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

@elog
def edit_memories(ama_file_path:str, text:str=None, append:str=None, json_file_path:str=None):
    ama_file = AMA(ama_file_path)
    print(text)

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

@elog
def read(ama_file_path:str, ama_propertie:str):
    elog(f"Called read with agrs: {ama_file_path}, {ama_propertie}")
    ama_file = AMA(ama_file_path)
    if ama_propertie == "persona_list":
        pprint.pprint(ama_file.read().get_persona_list())
    elif ama_propertie == "scenario":
        pprint.pprint(ama_file.read().get_scenario())
    elif ama_propertie == "memories":
        pprint.pprint(ama_file.read().get_memories())

def main():
    global ELOGGING, LOGGING
    models = ["nchapman/dolphin3.0-qwen2.5:1.5b", "qwen2.5:3b", "qwen2.5:7b", "qwen2.5:14b"]

    parser = argparse.ArgumentParser(description="AiMan: Run and handel AMA models")
    parser.add_argument("-v", "--version", action="version", version="AiMan "+__version__, help="Get currect version")
    parser.add_argument("-t", "--telemetry", action="store_true", help="Enable extra info (Tipicly used for debugging or nice for logs)")
    parser.add_argument("-et", "--extreamtelemetry", action="store_true", help="Every function call is loged. only for debugging, not for logs!")
    subparsers = parser.add_subparsers(dest="action", required=True, help="What action to do")

    run_parser = subparsers.add_parser("run", help="Run and chat with a AMA model")
    run_group = run_parser.add_mutually_exclusive_group(required=True)
    run_group.add_argument("-m", "--model", type=int, help="Use a pre chosen AI model from fast (0) to pro (3)")
    run_group.add_argument("-c", "--custom", type=str, metavar="MODEL", help="Use a custom ollama model")
    run_parser.add_argument("-d", "--dayinfo", action="store_true", help="Give the model simple info about today")
    run_parser.add_argument("ama_file", type=str, help="AMA file path")

    make_parser = subparsers.add_parser("make", help="Make a AMA file")
    make_parser.add_argument("-n", "--nocompression", action="store_true", help="Disable auto compression of the AMA file (Recemended to keep on)")
    make_parser.add_argument("-j", "--json", type=str, metavar="JSON", help="Turn a json file into AMA file")
    make_parser.add_argument("ama_file", type=str, help="new AMA file path")

    make_parser = subparsers.add_parser("json", help="Turn a AMA file into json")
    make_parser.add_argument("ama_file", type=str, help="AMA file path")
    make_parser.add_argument("json_file", type=str, help="new Json file path")

    edit_parser = subparsers.add_parser("edit", help="Edit content from a AMA file")
    edit_parser.add_argument("ama_file", type=str, help="AMA file path")
    prop_subparsers = edit_parser.add_subparsers(dest="ama_propertie", required=True, help="What AMA propertie to edit")

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
    read_prop_subparsers = read_parser.add_subparsers(dest="ama_propertie", required=True, help="What AMA propertie to edit")
    read_prop_subparsers.add_parser("persona_list", help="Read the persona_list value of the AMA file")
    read_prop_subparsers.add_parser("scenario", help="Read the scenario value of the AMA file")
    read_prop_subparsers.add_parser("memories", help="Read the memories value of the AMA file")

    args = parser.parse_args()

    ELOGGING = args.extreamtelemetry
    LOGGING = args.telemetry or ELOGGING

    log("Version: "+__version__)
    log("OS: "+platform.system())

    try:
        with urllib.request.urlopen("https://api.github.com/repos/Orbinuity/AiMan/releases/latest") as response:
            latest_release_json = json.loads(response.read().decode())
            latest_version = latest_release_json["tag_name"]

            if latest_version != __version__:
                info(f"A new version is avalable, install it by running: {"irm https://raw.githubusercontent.com/Orbinuity/AiMan/main/install.ps1 | iex" if platform.system() == "Windows" else "curl -fsSL https://raw.githubusercontent.com/Orbinuity/AiMan/main/install.sh | sh"}")
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
        if args.json != None:
            json_to_ama(args.json, args.ama_file, not args.nocompression)
        else:
            make(args.ama_file, not args.nocompression)
    elif args.action == "json":
        ama_to_json(args.ama_file, args.json_file)
    elif args.action == "edit":
        if args.ama_propertie == "persona_list":
            if args.list != None:
                try:
                    alist = ast.literal_eval(args.list)
                except ValueError:
                    error(f"LIST needs to be list in str (\"['item1', 'item2']\") not {type(args.list).__name__}!")
                edit_persona(args.ama_file, value=alist)

            elif args.set != None:
                try:
                    index = int(args.set[0])
                except ValueError:
                    error(f"INDEX needs to be int not {type(args.set[0]).__name__}!")
                edit_persona(args.ama_file, index=index, value=args.set[1])

            elif args.listfile != None:
                edit_persona(args.ama_file, json_file_path=args.listfile)

            elif args.setfile != None:
                try:
                    index = int(args.setfile[0])
                except ValueError:
                    error(f"INDEX needs to be int not {type(args.set[0]).__name__}!")
                edit_persona(args.ama_file, index=index, json_file_path=args.setfile[1])
        elif args.ama_propertie == "scenario":
            if args.text != None:
                edit_scenario(args.ama_file, text=args.text)
            elif args.append != None:
                edit_scenario(args.ama_file, append=args.append)
            elif args.textfile != None:
                edit_scenario(args.ama_file, text="", json_file_path=args.textfile)
            elif args.appendfile != None:
                edit_scenario(args.ama_file, append="", json_file_path=args.appendfile)
        elif args.ama_propertie == "memories":
            if args.text != None:
                edit_memories(args.ama_file, text=args.text)
            elif args.append != None:
                edit_memories(args.ama_file, append=args.append)
            elif args.textfile != None:
                edit_memories(args.ama_file, text="", json_file_path=args.textfile)
            elif args.appendfile != None:
                edit_memories(args.ama_file, append="", json_file_path=args.appendfile)
    elif args.action == "read":
        read(args.ama_file, args.ama_propertie)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        info("Aborted.")
        sys.exit(0)
    except Exception as e:
        if ELOGGING:
            print_traceback()
            sys.exit(1)
        if LOGGING:
            info("Something went wrong! Please report this issue at https://github.com/Orbinuity/AiMan/issues")
            error(f"[{type(e).__name__}] {e}")
        error("Something went wrong! Please report this issue at https://github.com/Orbinuity/AiMan/issues")