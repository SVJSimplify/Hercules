#!/usr/bin/env python3
"""Hercules - Local-First AI Agent with GPT4All Integration"""

import json
import os
import platform
import sys
from pathlib import Path
from collections import Counter

try:
    from gpt4all import GPT4All
    from colorama import init
    init(autoreset=True)
except ImportError:
    print("Install: pip install gpt4all colorama")
    sys.exit(1)


# ANSI Color Codes
O1 = '\033[38;2;218;165;32m'
O2 = '\033[38;2;255;215;0m'
H1 = '\033[38;2;184;134;11m'
H2 = '\033[38;2;255;140;0m'
G = '\033[38;2;26;176;128m'
R = '\033[38;2;255;59;59m'
S = '\033[38;2;90;122;150m'
X = '\033[0m'

# Global State
llm = None
model_path = None
temp = 0.7
max_tokens = 256
chat_history = []
dark_mode = True
model_info = {}
skills = []
overclock_enabled = False
freerange_enabled = False
freerange_dir = None


def splash():
    """Display application banner"""
    print(f"""{O1}
╔───────────────────────────────────────────────────────────────╗
│                                                               │
│  ██╗  ██╗███████╗██████╗  ██████╗██╗   ██╗██╗     ███████╗  │
│  ██║  ██║██╔════╝██╔══██╗██╔════╝██║   ██║██║     ██╔════╝  │
│  ███████║█████╗  ██████╔╝██║     ██║   ██║██║     █████╗    │
│  ██╔══██║██╔══╝  ██╔══██╗██║     ██║   ██║██║     ██╔══╝    │
│  ██║  ██║███████╗██║  ██║╚██████╗╚██████╔╝███████╗███████╗  │
│  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝ ╚═════╝ ╚═════╝ ╚══════╝╚══════╝  │
│                                                               │
│           Local-First AI Agent — Chat Interface              │
│                      v8.0.0 (STABLE)                         │
│                                                               │
╚───────────────────────────────────────────────────────────────╝
{X}""")
    print(f"{S}Type your request. Type '/help' for commands.{X}\n")

COMMANDS = {
    '/models': 'List all registered models',
    '/config': 'Show config location',
    '/setup': 'Reconfigure model directory',
    '/help': 'Show all commands',
    '/exit': 'Exit application',
    '/temp': 'Set temperature (0.0-1.0)',
    '/tokens': 'Set max tokens',
    '/batch': 'Run multiple prompts from file',
    '/export': 'Export chat history to file',
    '/search': 'Search chat history',
    '/history': 'Show chat history',
    '/save': 'Save conversation',
    '/load': 'Load conversation',
    '/theme': 'Toggle dark/light mode',
    '/info': 'Show model info',
    '/unload': 'Unload current model',
    '/overclock': 'Enable hardware overclock',
    '/skill': 'Add skill from path',
    '/skills': 'List loaded skills',
    '/agent': 'Run as autonomous agent',
    '/freerange': 'Enable freerange mode (file creation/editing)',
    '/stats': 'Show system statistics',
    '/advsearch': 'Advanced search with filters',
    '/clear': 'Clear chat history',
    '/context': 'Show conversation context',
    '/macro': 'Manage macros and shortcuts',
    '/plugin': 'Manage plugins and extensions',
    '/branch': 'Manage conversation branches',
    '/memory': 'Save and recall important memories',
    '/agent': 'Execute specialized sub-agent',
    '/delegate': 'Delegate task to multiple agents',
    '/hagent': 'Execute through 3-layer agent hierarchy',
    '/code': 'Claude Code pattern & template help'
}

def find_gguf_files(folder):
    """Recursively find GGUF model files"""
    models = []
    for f in Path(folder).glob('**/*.gguf'):
        models.append((f.stem, str(f)))
    return models


def show_commands():
    """Display all available commands"""
    print(f"\n{O2}╔ Available Commands ╗{X}\n")
    for cmd, desc in COMMANDS.items():
        print(f"  {H1}{cmd:<15}{X} {S}{desc}{X}")
    print()

def list_models():
    """Display currently loaded model"""
    global model_path
    if not model_path:
        print(f"\n{S}No model loaded{X}\n")
        return
    print(f"\n{O2}Current Model:{X}")
    print(f"  {O1}{Path(model_path).stem}{X}")
    print(f"  {S}{model_path}{X}\n")

def setup():
    """Initialize and load GGUF models"""
    global llm, model_path
    print(f"\n{O2}╔ Setup GGUF Models ╗{X}\n")
    
    model_dir = r'D:\Models' if platform.system() == 'Windows' else os.path.expanduser('~/Models')
    print(f"{H2}Scanning {model_dir}...{X}")
    
    try:
        cpu_count = os.cpu_count() or 4
        print(f"{S}CPU: {platform.processor()} - using {min(cpu_count-1, 4)} threads{X}\n")
    except Exception:
        print(f"{S}Using 4 threads{X}\n")
        cpu_count = 4
    
    models = find_gguf_files(model_dir)
    
    if not models:
        print(f"{R}✗ No GGUF files found in {model_dir}{X}\n")
        return False
    
    print(f"{G}✓ Found {len(models)} models{X}\n")
    print(f"{O2}Available models:{X}")
    for i, (name, path) in enumerate(models, 1):
        size_gb = Path(path).stat().st_size / (1024 ** 3)
        print(f"  {H1}[{i}]{X} {O1}{name}{X} ({size_gb:.2f}GB)")
    
    try:
        print(f"\n{H2}Select model (1-{len(models)}):{X} ", end='', flush=True)
        choice = int(input().strip()) - 1
        if 0 <= choice < len(models):
            model_path = models[choice][1]
            model_name = Path(model_path).name
            print(f"\n{G}✓ Loading {models[choice][0]}...{X}")
            try:
                llm = GPT4All(model_name=model_name, model_path=str(Path(model_path).parent),
                              allow_download=False, device='cpu', n_threads=min(cpu_count-1, 4))
            except TypeError:
                llm = GPT4All(models[choice][0], model_path=str(Path(model_path).parent),
                              allow_download=False)
            print(f"{G}✓ Model loaded{X}\n")
            return True
    except ValueError:
        print(f"{R}✗ Invalid selection{X}\n")
        return False
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")
        return False

def query(prompt, use_context=False):
    """Execute prompt with loaded model and optional context"""
    global llm
    if not llm:
        return f"{R}Model not loaded{X}"
    
    # Add context if requested
    full_prompt = prompt
    if use_context and len(chat_history) > 0:
        context_window = ctx.get_context_window()
        full_prompt = f"Previous context:\n{context_window}\n\nCurrent question: {prompt}"
    
    try:
        response = llm.generate(full_prompt, max_tokens=max_tokens, temp=temp, top_p=0.95, top_k=40)
        return response.strip() if response.strip() else f"{R}No response{X}"
    except AttributeError:
        try:
            response = llm.generate_async(full_prompt, max_tokens=max_tokens, temp=temp)
            return response.strip() if response.strip() else f"{R}No response{X}"
        except Exception as e:
            return f"{R}API Error: {str(e)[:50]}{X}"
    except Exception as e:
        return f"{R}Error: {str(e)[:50]}{X}"


def set_temperature():
    """Set model temperature parameter"""
    global temp
    try:
        print(f"{H2}Current temp: {temp}{X}")
        print(f"{H2}New temp (0.0-1.0):{X} ", end='', flush=True)
        new_temp = float(input().strip())
        if 0.0 <= new_temp <= 1.0:
            temp = new_temp
            print(f"{G}✓ Temperature set to {temp}{X}\n")
        else:
            print(f"{R}✗ Must be between 0.0 and 1.0{X}\n")
    except ValueError:
        print(f"{R}✗ Invalid input{X}\n")

def set_tokens():
    """Set maximum token generation limit"""
    global max_tokens
    try:
        print(f"{H2}Current max tokens: {max_tokens}{X}")
        print(f"{H2}New max tokens:{X} ", end='', flush=True)
        new_tokens = int(input().strip())
        if new_tokens > 0:
            max_tokens = new_tokens
            print(f"{G}✓ Max tokens set to {max_tokens}{X}\n")
        else:
            print(f"{R}✗ Must be positive{X}\n")
    except ValueError:
        print(f"{R}✗ Invalid input{X}\n")


def batch_process():
    """Process multiple prompts from file"""
    try:
        print(f"{H2}Enter batch file path:{X} ", end='', flush=True)
        filepath = input().strip()
        if not Path(filepath).exists():
            print(f"{R}✗ File not found{X}\n")
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            prompts = [p.strip() for p in f.readlines() if p.strip()]
        
        if not prompts:
            print(f"{R}✗ No prompts in file{X}\n")
            return
        
        print(f"{G}✓ Processing {len(prompts)} prompts{X}\n")
        for i, prompt in enumerate(prompts, 1):
            if prompt and not prompt.startswith('#'):
                print(f"{O1}[{i}/{len(prompts)}] {prompt[:60]}{X}\n")
                response = query(prompt)
                print(f"{G}{response}{X}\n")
                chat_history.append({'prompt': prompt, 'response': response})
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")

def export_chat():
    """Export chat history to text file"""
    try:
        print(f"{H2}Export path:{X} ", end='', flush=True)
        filepath = input().strip()
        
        if not filepath:
            print(f"{R}✗ No path provided{X}\n")
            return
        
        with open(filepath, 'w', encoding='utf-8') as f:
            for i, chat in enumerate(chat_history, 1):
                f.write(f"[{i}] You: {chat['prompt']}\n")
                f.write(f"Assistant: {chat['response']}\n\n")
        
        print(f"{G}✓ Exported {len(chat_history)} messages to {filepath}{X}\n")
    except IOError as e:
        print(f"{R}✗ Write error: {str(e)[:100]}{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def search_history():
    """Search chat history for matching content"""
    try:
        print(f"{H2}Search term:{X} ", end='', flush=True)
        term = input().strip().lower()
        
        if not term:
            print(f"{R}✗ Empty search{X}\n")
            return
        
        results = [c for c in chat_history if term in c['prompt'].lower() or term in c['response'].lower()]
        
        if results:
            print(f"\n{G}Found {len(results)} results:{X}\n")
            for c in results[:10]:
                print(f"{O1}Q: {c['prompt'][:60]}{X}")
                print(f"{S}A: {c['response'][:60]}{X}\n")
        else:
            print(f"{S}No results{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def show_history():
    """Display recent chat history"""
    if not chat_history:
        print(f"\n{S}No chat history{X}\n")
        return
    
    print(f"\n{O2}Chat History ({len(chat_history)} messages):{X}\n")
    for i, c in enumerate(chat_history[-10:], 1):
        print(f"{O1}[{i}] You: {c['prompt'][:50]}...{X}")
        print(f"{S}    Assistant: {c['response'][:50]}...{X}\n")

def save_conversation():
    """Save current conversation to JSON file"""
    try:
        print(f"{H2}Save path:{X} ", end='', flush=True)
        filepath = input().strip()
        
        if not filepath:
            print(f"{R}✗ No path provided{X}\n")
            return
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(chat_history, f, indent=2)
        
        print(f"{G}✓ Saved {len(chat_history)} messages{X}\n")
    except IOError as e:
        print(f"{R}✗ Write error: {str(e)[:100]}{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def load_conversation():
    """Load conversation from JSON file"""
    global chat_history
    try:
        print(f"{H2}Load path:{X} ", end='', flush=True)
        filepath = input().strip()
        
        if not Path(filepath).exists():
            print(f"{R}✗ File not found{X}\n")
            return
        
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            if isinstance(data, list):
                chat_history = data
            else:
                print(f"{R}✗ Invalid format{X}\n")
                return
        
        print(f"{G}✓ Loaded {len(chat_history)} messages{X}\n")
    except json.JSONDecodeError:
        print(f"{R}✗ Invalid JSON{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def toggle_theme():
    """Toggle between dark and light theme"""
    global dark_mode
    dark_mode = not dark_mode
    theme = "Dark" if dark_mode else "Light"
    print(f"{G}✓ Theme set to {theme}{X}\n")


def show_model_info():
    """Display current model information"""
    if not model_path:
        print(f"{R}✗ No model loaded{X}\n")
        return
    
    try:
        size_gb = Path(model_path).stat().st_size / (1024 ** 3)
        print(f"\n{O2}Model Info:{X}")
        print(f"  {O1}Name:{X} {Path(model_path).stem}")
        print(f"  {O1}Path:{X} {model_path}")
        print(f"  {O1}Size:{X} {size_gb:.2f} GB")
        print(f"  {O1}Temp:{X} {temp}")
        print(f"  {O1}Max Tokens:{X} {max_tokens}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def unload_model():
    """Unload currently loaded model"""
    global llm, model_path
    if llm:
        llm = None
        model_path = None
        print(f"{G}✓ Model unloaded{X}\n")
    else:
        print(f"{S}No model loaded{X}\n")


def enable_overclock():
    """Enable hardware overclock mode"""
    global overclock_enabled
    try:
        try:
            import psutil
            cpu_freq = psutil.cpu_freq().max
            cpu_count = psutil.cpu_count()
            memory = psutil.virtual_memory().total / (1024 ** 3)
        except ImportError:
            cpu_freq = 2400
            cpu_count = os.cpu_count() or 4
            memory = 8.0
        
        overclock_enabled = not overclock_enabled
        
        if overclock_enabled:
            print(f"{G}✓ Overclock ENABLED{X}")
            print(f"  CPU Freq: {cpu_freq:.0f} MHz")
            print(f"  CPU Count: {cpu_count}")
            print(f"  Memory: {memory:.2f} GB\n")
            os.environ['NUMBA_CACHE_DIR'] = '/tmp'
            os.environ['OMP_NUM_THREADS'] = str(max(1, cpu_count - 1))
        else:
            print(f"{S}✓ Overclock disabled{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def add_skill():
    """Add a skill from file path"""
    global skills
    try:
        print(f"{H2}Skill path:{X} ", end='', flush=True)
        skill_path = input().strip()
        
        if not skill_path:
            print(f"{R}✗ No path provided{X}\n")
            return
        
        if not Path(skill_path).exists():
            print(f"{R}✗ File not found{X}\n")
            return
        
        if skill_path not in skills:
            skills.append(skill_path)
            print(f"{G}✓ Skill added: {Path(skill_path).name}{X}\n")
        else:
            print(f"{S}Skill already loaded{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def list_skills():
    """Display all loaded skills"""
    if not skills:
        print(f"\n{S}No skills loaded{X}\n")
        return
    
    print(f"\n{O2}Loaded Skills:{X}\n")
    for i, skill in enumerate(skills, 1):
        print(f"  {H1}[{i}]{X} {Path(skill).name}")
        print(f"      {S}{skill}{X}\n")


def run_as_agent():
    """Run model as autonomous agent"""
    global llm, chat_history
    if not llm:
        print(f"{R}✗ No model loaded{X}\n")
        return
    
    print(f"\n{O2}╔ Agent Mode ╗{X}\n")
    print(f"{S}Model will autonomously respond and execute skills.{X}")
    print(f"{H2}Enter goal:{X} ", end='', flush=True)
    goal = input().strip()
    
    if not goal:
        return
    
    print(f"\n{G}[Agent] Starting...{X}\n")
    
    context = f"You are an autonomous AI agent.\nGoal: {goal}\n"
    if skills:
        context += f"Available skills: {', '.join([Path(s).name for s in skills])}\n"
    context += "Recent context:\n"
    
    for c in chat_history[-3:]:
        context += f"User: {c['prompt']}\nAssistant: {c['response']}\n"
    
    agent_prompt = context + "\nRespond concisely with your next action:"
    
    try:
        response = query(agent_prompt)
        print(f"{O1}[Agent]{X} {G}{response}{X}\n")
        chat_history.append({'prompt': f'[AGENT] {goal}', 'response': response})
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def setup_freerange():
    """Configure freerange mode for file operations"""
    global freerange_enabled, freerange_dir
    print(f"\n{O2}╔ Freerange Mode Setup ╗{X}\n")
    print(f"{S}Model will have file creation/edit access to a directory.{X}")
    print(f"{H2}Enter directory path:{X} ", end='', flush=True)
    dirpath = input().strip()
    
    if not dirpath:
        print(f"{R}✗ No path provided{X}\n")
        return
    
    dirpath = os.path.expanduser(dirpath)
    
    try:
        Path(dirpath).mkdir(parents=True, exist_ok=True)
        freerange_dir = dirpath
        freerange_enabled = True
        print(f"\n{G}✓ Freerange mode ENABLED{X}")
        print(f"  {O1}Directory:{X} {freerange_dir}")
        print(f"  {S}Model can create/edit files in this location{X}\n")
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")


def disable_freerange():
    """Disable freerange mode"""
    global freerange_enabled, freerange_dir
    freerange_enabled = False
    freerange_dir = None
    print(f"{G}✓ Freerange mode DISABLED{X}\n")

def execute_freerange():
 global llm,chat_history,freerange_enabled,freerange_dir
 if not llm:
  print(f"{R}✗ No model loaded{X}\n")
  return
 
 if not freerange_enabled or not freerange_dir:
  print(f"{R}✗ Freerange mode not enabled{X}\n")
  return
 
 print(f"\n{O2}╔ Freerange Mode ╗{X}\n")
 print(f"{S}Model has full file access to: {freerange_dir}{X}\n")
 print(f"{H2}Enter task:{X} ",end='',flush=True)
 task=input().strip()
 
 if not task:
  return
 
 print(f"\n{G}[Freerange] Starting...{X}\n")
 
 freerange_prompt=f"""You are a code/file generation agent with full access to create and edit files.
Working directory: {freerange_dir}

Task: {task}

You can:
- Create new files
- Edit existing files
- Read file contents
- Delete files
- Create directories
- Execute basic file operations

For file operations, use these commands in your response:
[CREATE_FILE: path/to/file.ext]
content here
[END_CREATE]

[EDIT_FILE: path/to/file.ext]
new content here
[END_EDIT]

[READ_FILE: path/to/file.ext]

[DELETE_FILE: path/to/file.ext]

[MKDIR: path/to/dir]

Please provide your response with file operations where needed."""
 
 try:
  response=query(freerange_prompt)
  print(f"{O1}[Freerange Response]{X}\n{G}{response}{X}\n")
  
  execute_file_commands(response,freerange_dir)
  
  chat_history.append({'prompt':f'[FREERANGE] {task}','response':response})
 except Exception as e:
  print(f"{R}✗ Error: {str(e)[:100]}{X}\n")

def execute_file_commands(response,base_dir):
 """Parse and execute file commands from model response"""
 lines=response.split('\n')
 i=0
 while i<len(lines):
  line=lines[i]
  
  if line.startswith('[CREATE_FILE:'):
   filepath=line.replace('[CREATE_FILE:','').replace(']','').strip()
   content_lines=[]
   i+=1
   while i<len(lines) and '[END_CREATE]' not in lines[i]:
    content_lines.append(lines[i])
    i+=1
   
   try:
    full_path=Path(base_dir)/filepath
    full_path.parent.mkdir(parents=True,exist_ok=True)
    full_path.write_text('\n'.join(content_lines),encoding='utf-8')
    print(f"{G}✓ Created: {filepath}{X}")
   except Exception as e:
    print(f"{R}✗ Failed to create {filepath}: {str(e)[:50]}{X}")
  
  elif line.startswith('[EDIT_FILE:'):
   filepath=line.replace('[EDIT_FILE:','').replace(']','').strip()
   content_lines=[]
   i+=1
   while i<len(lines) and '[END_EDIT]' not in lines[i]:
    content_lines.append(lines[i])
    i+=1
   
   try:
    full_path=Path(base_dir)/filepath
    if full_path.exists():
     full_path.write_text('\n'.join(content_lines),encoding='utf-8')
     print(f"{G}✓ Edited: {filepath}{X}")
    else:
     print(f"{R}✗ File not found: {filepath}{X}")
   except Exception as e:
    print(f"{R}✗ Failed to edit {filepath}: {str(e)[:50]}{X}")
  
  elif line.startswith('[READ_FILE:'):
   filepath=line.replace('[READ_FILE:','').replace(']','').strip()
   try:
    full_path=Path(base_dir)/filepath
    if full_path.exists():
     content=full_path.read_text(encoding='utf-8')
     print(f"{G}✓ Read: {filepath}{X}")
     print(f"{S}{content[:200]}{X}")
    else:
     print(f"{R}✗ File not found: {filepath}{X}")
   except Exception as e:
    print(f"{R}✗ Failed to read {filepath}: {str(e)[:50]}{X}")
  
  elif line.startswith('[DELETE_FILE:'):
   filepath=line.replace('[DELETE_FILE:','').replace(']','').strip()
   try:
    full_path=Path(base_dir)/filepath
    if full_path.exists() and full_path.is_file():
     full_path.unlink()
     print(f"{G}✓ Deleted: {filepath}{X}")
    else:
     print(f"{R}✗ File not found: {filepath}{X}")
   except Exception as e:
    print(f"{R}✗ Failed to delete {filepath}: {str(e)[:50]}{X}")
  
  elif line.startswith('[MKDIR:'):
   dirpath=line.replace('[MKDIR:','').replace(']','').strip()
   try:
    full_path=Path(base_dir)/dirpath
    full_path.mkdir(parents=True,exist_ok=True)
    print(f"{G}✓ Created directory: {dirpath}{X}")
   except Exception as e:
    print(f"{R}✗ Failed to create dir {dirpath}: {str(e)[:50]}{X}")
  
  i+=1

class ConversationContext:
    """Manage conversation memory and context windowing"""
    def __init__(self, max_context_messages=10):
        self.max_context = max_context_messages
        self.important_messages = []
    
    def add_important(self, prompt, response):
        """Mark message as important for context"""
        self.important_messages.append({'prompt': prompt, 'response': response})
    
    def get_context_window(self):
        """Get recent context for model"""
        if not chat_history:
            return "No previous context"
        recent = chat_history[-self.max_context:]
        context = "\n".join([f"Q: {h['prompt']}\nA: {h['response'][:100]}..." for h in recent])
        return context
    
    def summarize_context(self):
        """Create brief summary of conversation so far"""
        if len(chat_history) < 3:
            return ""
        topics = []
        for h in chat_history[-5:]:
            words = h['prompt'].split()
            if words:
                topics.append(words[0])
        return f"Topics discussed: {', '.join(set(topics[:3]))}"

ctx = ConversationContext()

def get_cache_dir():
    """Get or create cache directory"""
    cache_dir = Path.home() / '.hercules' / 'cache'
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir

def save_response_cache(prompt_hash, response):
    """Cache model responses for identical prompts"""
    try:
        cache_dir = get_cache_dir()
        cache_file = cache_dir / f"{prompt_hash}.json"
        with open(cache_file, 'w', encoding='utf-8') as f:
            json.dump({'response': response, 'timestamp': os.times()}, f)
    except Exception as e:
        print(f"{R}Cache save failed: {str(e)[:30]}{X}")

def load_response_cache(prompt_hash, max_age_hours=24):
    """Load cached response if available"""
    import time
    try:
        cache_dir = get_cache_dir()
        cache_file = cache_dir / f"{prompt_hash}.json"
        if cache_file.exists():
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('response')
    except Exception:
        pass
    return None

def get_context_summary():
    """Generate conversation context summary"""
    if not chat_history:
        return "No conversation history"
    
    prompt_count = len(chat_history)
    words = sum(len(h['response'].split()) for h in chat_history)
    return f"{prompt_count} prompts, ~{words} words"

def show_system_stats():
    """Display system information and model stats"""
    print(f"\n{O2}╔ System Statistics ╗{X}\n")
    print(f"  {H1}Model:{X} {Path(model_path).stem if model_path else 'None'}")
    print(f"  {H1}Temperature:{X} {temp}")
    print(f"  {H1}Max Tokens:{X} {max_tokens}")
    print(f"  {H1}Chat History:{X} {get_context_summary()}")
    print(f"  {H1}Skills Loaded:{X} {len(skills)}")
    print(f"  {H1}Overclock:{X} {'ON' if overclock_enabled else 'OFF'}")
    print(f"  {H1}Freerange:{X} {'ON' if freerange_enabled else 'OFF'}")
    try:
        import psutil
        proc = psutil.Process(os.getpid())
        mem = proc.memory_info().rss / (1024**2)
        print(f"  {H1}Memory Usage:{X} {mem:.1f}MB")
    except:
        pass
    print()

def advanced_search():
    """Advanced search with filters"""
    print(f"\n{O2}╔ Advanced Search ╗{X}\n")
    print(f"{H2}Search options:{X}")
    print(f"  {H1}[1]{X} Full text search")
    print(f"  {H1}[2]{X} Search by date")
    print(f"  {H1}[3]{X} Search by keyword count")
    print(f"{H2}Choose:{X} ", end='', flush=True)
    
    try:
        opt = input().strip()
        if opt == '1':
            search_history()
        elif opt == '2':
            print(f"{H2}Date format (YYYY-MM-DD):{X} ", end='', flush=True)
            date_filter = input().strip()
            results = [c for c in chat_history if date_filter in str(c.get('timestamp', ''))]
            if results:
                for i, chat in enumerate(results, 1):
                    print(f"{O1}[{i}]{X} {chat['prompt'][:60]}")
                print()
            else:
                print(f"{R}No results found{X}\n")
        elif opt == '3':
            print(f"{H2}Min keywords:{X} ", end='', flush=True)
            min_words = int(input().strip())
            results = [c for c in chat_history if len(c['response'].split()) >= min_words]
            print(f"{G}Found {len(results)} responses{X}\n")
    except Exception as e:
        print(f"{R}Error: {str(e)[:50]}{X}\n")

def evaluate_response_quality(response):
    """Score response quality based on metrics"""
    score = 0
    metrics = {}
    
    # Length metric
    word_count = len(response.split())
    metrics['word_count'] = word_count
    if word_count > 20:
        score += 25
    elif word_count > 10:
        score += 15
    
    # Coherence metric
    if '.' in response and ',' in response:
        score += 20
    
    # Structure metric (has intro, body, conclusion)
    lines = response.split('\n')
    if len(lines) > 3:
        score += 20
    
    # No error message
    if not response.startswith('Error'):
        score += 35
    
    metrics['quality_score'] = score
    return metrics

def show_conversation_stats():
    """Display detailed conversation statistics"""
    if not chat_history:
        print(f"{R}No conversation history{X}\n")
        return
    
    print(f"\n{O2}╔ Conversation Statistics ╗{X}\n")
    
    total_prompts = len(chat_history)
    total_words = sum(len(h['response'].split()) for h in chat_history)
    avg_response = total_words // total_prompts if total_prompts > 0 else 0
    
    print(f"  {H1}Total Exchanges:{X} {total_prompts}")
    print(f"  {H1}Total Words Generated:{X} {total_words}")
    print(f"  {H1}Avg Response Length:{X} {avg_response} words")
    
    # Quality analysis
    qualities = [evaluate_response_quality(h['response']) for h in chat_history]
    avg_quality = sum(q['quality_score'] for q in qualities) / len(qualities) if qualities else 0
    print(f"  {H1}Avg Response Quality:{X} {avg_quality:.1f}/100")
    
    # Most common topics
    all_words = ' '.join(h['prompt'] for h in chat_history).split()
    from collections import Counter
    if all_words:
        common = Counter(w.lower() for w in all_words if len(w) > 3)
        print(f"  {H1}Top Topics:{X} {', '.join(w for w, _ in common.most_common(3))}")
    
    print()

def show_conversation_stats():
    """Display detailed conversation statistics"""
    if not chat_history:
        print(f"{R}No conversation history{X}\n")
        return
    
    print(f"\n{O2}╔ Conversation Statistics ╗{X}\n")
    
    total_prompts = len(chat_history)
    total_words = sum(len(h['response'].split()) for h in chat_history)
    avg_response = total_words // total_prompts if total_prompts > 0 else 0
    
    print(f"  {H1}Total Exchanges:{X} {total_prompts}")
    print(f"  {H1}Total Words Generated:{X} {total_words}")
    print(f"  {H1}Avg Response Length:{X} {avg_response} words")
    
    # Quality analysis
    qualities = [evaluate_response_quality(h['response']) for h in chat_history]
    avg_quality = sum(q['quality_score'] for q in qualities) / len(qualities) if qualities else 0
    print(f"  {H1}Avg Response Quality:{X} {avg_quality:.1f}/100")
    
    # Most common topics
    all_words = ' '.join(h['prompt'] for h in chat_history).split()
    if all_words:
        common = Counter(w.lower() for w in all_words if len(w) > 3)
        print(f"  {H1}Top Topics:{X} {', '.join(w for w, _ in common.most_common(3))}")
    
    print()

class MacroSystem:
    """Simple macro/shortcut system for frequent commands"""
    def __init__(self):
        self.macros = {}
        self.load_macros()
    
    def load_macros(self):
        """Load saved macros from config"""
        try:
            macro_file = Path.home() / '.hercules' / 'macros.json'
            if macro_file.exists():
                with open(macro_file, 'r') as f:
                    self.macros = json.load(f)
        except:
            self.macros = {
                'hi': 'Hello! How can I help?',
                'code': 'Write clean, well-documented code:',
                'explain': 'Explain this in simple terms:'
            }
    
    def save_macros(self):
        """Save macros to config file"""
        try:
            macro_file = Path.home() / '.hercules' / 'macros.json'
            macro_file.parent.mkdir(parents=True, exist_ok=True)
            with open(macro_file, 'w') as f:
                json.dump(self.macros, f)
        except:
            pass
    
    def expand(self, text):
        """Expand macro if text starts with one"""
        for macro, expansion in self.macros.items():
            if text.lower().startswith(macro + ' '):
                return expansion + ' ' + text[len(macro)+1:]
        return text
    
    def add_macro(self, name, expansion):
        """Add new macro"""
        self.macros[name.lower()] = expansion
        self.save_macros()
    
    def list_macros(self):
        """Show all macros"""
        return self.macros

macro_system = MacroSystem()

def parse_command_args(cmd_line):
    """Parse command with arguments"""
    parts = cmd_line.split(None, 1)
    cmd = parts[0] if parts else ''
    args = parts[1] if len(parts) > 1 else ''
    return cmd, args

def handle_macro(text):
    """Check and handle macro expansion"""
    expanded = macro_system.expand(text)
    if expanded != text:
        print(f"{S}[Macro expanded]{X}")
        return expanded
    return text

class PluginManager:
    """Manage and execute plugins/extensions"""
    def __init__(self):
        self.plugins = {}
        self.plugin_dir = Path.home() / '.hercules' / 'plugins'
        self.plugin_dir.mkdir(parents=True, exist_ok=True)
    
    def discover_plugins(self):
        """Find all available plugins"""
        plugins = []
        if self.plugin_dir.exists():
            for pf in self.plugin_dir.glob('*.py'):
                if not pf.name.startswith('_'):
                    plugins.append(pf.stem)
        return plugins
    
    def load_plugin(self, name):
        """Load a plugin module"""
        try:
            spec = __import__(f'sys')
            plugin_path = self.plugin_dir / f"{name}.py"
            if plugin_path.exists():
                import importlib.util
                spec = importlib.util.spec_from_file_location(name, plugin_path)
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                self.plugins[name] = module
                return True
        except Exception as e:
            print(f"{R}Plugin load error: {str(e)[:50]}{X}")
        return False
    
    def execute_hook(self, hook_name, *args, **kwargs):
        """Execute a hook across all plugins"""
        results = []
        for name, plugin in self.plugins.items():
            if hasattr(plugin, hook_name):
                try:
                    result = getattr(plugin, hook_name)(*args, **kwargs)
                    results.append(result)
                except:
                    pass
        return results
    
    def list_plugins(self):
        """Show loaded plugins"""
        return list(self.plugins.keys())

plugin_manager = PluginManager()

def create_sample_plugins():
    """Create sample plugins for users"""
    plugin_dir = Path.home() / '.hercules' / 'plugins'
    plugin_dir.mkdir(parents=True, exist_ok=True)
    
    # Sample filter plugin
    filter_plugin = plugin_dir / 'filter_plugin.py'
    if not filter_plugin.exists():
        filter_plugin.write_text('''"""Sample filter plugin - adds text filtering capabilities"""

def filter_text(text, style='markdown'):
    """Filter response text"""
    if style == 'markdown':
        return text  # Could add markdown formatting
    return text

def on_response(response):
    """Hook called on every response"""
    return response

def on_prompt(prompt):
    """Hook called before every prompt"""
    return prompt
''')

class ConfigManager:
    """Manage application configuration"""
    def __init__(self):
        self.config_file = Path.home() / '.hercules' / 'config.json'
        self.config = self.load_config()
    
    def load_config(self):
        """Load config from file or create defaults"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    return json.load(f)
            except:
                pass
        
        return {
            'model_dir': r'D:\Models' if platform.system() == 'Windows' else os.path.expanduser('~/Models'),
            'auto_save': True,
            'auto_save_interval': 10,
            'theme': 'dark',
            'verbose': False,
            'context_window_size': 10,
            'cache_responses': False,
            'default_temp': 0.7,
            'default_tokens': 256
        }
    
    def save_config(self):
        """Save config to file"""
        try:
            self.config_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f, indent=2)
            return True
        except Exception as e:
            print(f"{R}Config save error: {str(e)[:30]}{X}")
            return False
    
    def set(self, key, value):
        """Set config value"""
        self.config[key] = value
        return self.save_config()
    
    def get(self, key, default=None):
        """Get config value"""
        return self.config.get(key, default)
    
    def show_config(self):
        """Display current configuration"""
        print(f"\n{O2}╔ Configuration ╗{X}\n")
        for key, value in self.config.items():
            print(f"  {H1}{key}:{X} {value}")
        print()

config_manager = ConfigManager()

class ConversationBranch:
    """Support branching conversations (multiple paths)"""
    def __init__(self, name, parent_index=None):
        self.name = name
        self.parent_index = parent_index  # Index where branch started
        self.messages = []
        self.created_at = os.times() if hasattr(os, 'times') else 0
    
    def add_message(self, prompt, response):
        """Add message to branch"""
        self.messages.append({'prompt': prompt, 'response': response})
    
    def get_context(self):
        """Get branch context"""
        return {
            'name': self.name,
            'messages': len(self.messages),
            'created': self.created_at,
            'parent': self.parent_index
        }

class BranchManager:
    """Manage conversation branches"""
    def __init__(self):
        self.branches = {'main': ConversationBranch('main')}
        self.current_branch = 'main'
    
    def create_branch(self, name):
        """Create new branch from current position"""
        current_idx = len(chat_history) - 1
        self.branches[name] = ConversationBranch(name, current_idx)
        return True
    
    def switch_branch(self, name):
        """Switch to different branch"""
        if name in self.branches:
            self.current_branch = name
            return True
        return False
    
    def get_current_branch(self):
        """Get current branch object"""
        return self.branches.get(self.current_branch)
    
    def list_branches(self):
        """List all branches"""
        return {name: branch.get_context() for name, branch in self.branches.items()}
    
    def merge_branch(self, source, dest='main'):
        """Merge one branch into another"""
        if source in self.branches and dest in self.branches:
            for msg in self.branches[source].messages:
                self.branches[dest].add_message(msg['prompt'], msg['response'])
            return True
        return False

branch_manager = BranchManager()

class MemoryBank:
    """Advanced conversation memory with tagged segments"""
    def __init__(self):
        self.memories = {}
        self.load_memories()
    
    def save_memory(self, tag, content, importance=5):
        """Save important memory snippet"""
        self.memories[tag] = {
            'content': content,
            'importance': importance,
            'timestamp': str(os.times()) if hasattr(os, 'times') else 'unknown'
        }
        self._persist()
    
    def recall_memory(self, tag):
        """Retrieve specific memory"""
        return self.memories.get(tag, {}).get('content')
    
    def get_important_memories(self, limit=5):
        """Get most important memories"""
        sorted_mem = sorted(
            self.memories.items(),
            key=lambda x: x[1]['importance'],
            reverse=True
        )
        return dict(sorted_mem[:limit])
    
    def list_memories(self):
        """List all saved memories"""
        return list(self.memories.keys())
    
    def load_memories(self):
        """Load from persistent storage"""
        try:
            mem_file = Path.home() / '.hercules' / 'memories.json'
            if mem_file.exists():
                with open(mem_file, 'r') as f:
                    self.memories = json.load(f)
        except:
            self.memories = {}
    
    def _persist(self):
        """Save to persistent storage"""
        try:
            mem_file = Path.home() / '.hercules' / 'memories.json'
            mem_file.parent.mkdir(parents=True, exist_ok=True)
            with open(mem_file, 'w') as f:
                json.dump(self.memories, f, indent=2)
        except:
            pass

memory_bank = MemoryBank()

class ResponseFilter:
    """Filter and transform responses"""
    def __init__(self):
        self.filters = []
    
    def add_filter(self, name, func):
        """Add a filter function"""
        self.filters.append((name, func))
    
    def apply_filters(self, response):
        """Apply all filters to response"""
        for name, func in self.filters:
            try:
                response = func(response)
            except:
                pass
        return response

response_filter = ResponseFilter()

# Default filters
def capitalize_sentences(text):
    """Ensure sentences start with capital"""
    return text[0].upper() + text[1:] if text else text

response_filter.add_filter('capitalize', capitalize_sentences)

class ConversationDatabase:
    """Index and query conversations like a database"""
    def __init__(self):
        self.index = {}
        self.rebuild_index()
    
    def rebuild_index(self):
        """Build searchable index"""
        self.index = {}
        for i, msg in enumerate(chat_history):
            words = msg['prompt'].lower().split()
            for word in set(words):
                if len(word) > 3:
                    if word not in self.index:
                        self.index[word] = []
                    self.index[word].append(i)
    
    def search(self, query):
        """Fast search using index"""
        words = query.lower().split()
        results = None
        
        for word in words:
            if len(word) > 3 and word in self.index:
                word_results = set(self.index[word])
                if results is None:
                    results = word_results
                else:
                    results = results.intersection(word_results)
        
        if results:
            return [chat_history[i] for i in sorted(results)]
        return []
    
    def group_by_topic(self):
        """Group conversations by topic"""
        topics = {}
        for i, msg in enumerate(chat_history):
            words = msg['prompt'].split()
            first_word = words[0] if words else 'unknown'
            if first_word not in topics:
                topics[first_word] = []
            topics[first_word].append(i)
        return topics
    
    def get_timeline(self):
        """Get conversation timeline"""
        return [{'index': i, 'prompt': msg['prompt'][:30]} for i, msg in enumerate(chat_history)]

conv_db = ConversationDatabase()

class PromptTemplate:
    """Reusable prompt templates with variables"""
    def __init__(self):
        self.templates = {}
        self.load_templates()
    
    def add_template(self, name, template):
        """Add a template with {variable} placeholders"""
        self.templates[name] = template
        self._save()
    
    def render(self, name, **kwargs):
        """Render template with variables"""
        if name not in self.templates:
            return None
        template = self.templates[name]
        for key, value in kwargs.items():
            template = template.replace(f'{{{key}}}', str(value))
        return template
    
    def list_templates(self):
        """List all templates"""
        return list(self.templates.keys())
    
    def load_templates(self):
        """Load from file"""
        try:
            tmpl_file = Path.home() / '.hercules' / 'templates.json'
            if tmpl_file.exists():
                with open(tmpl_file, 'r') as f:
                    self.templates = json.load(f)
        except:
            self.templates = {
                'code_review': 'Review this code for {aspect}:\n{code}',
                'explain': 'Explain {topic} in {level} terms',
                'debug': 'Debug this {language} error:\n{error}'
            }
    
    def _save(self):
        """Save templates"""
        try:
            tmpl_file = Path.home() / '.hercules' / 'templates.json'
            tmpl_file.parent.mkdir(parents=True, exist_ok=True)
            with open(tmpl_file, 'w') as f:
                json.dump(self.templates, f, indent=2)
        except:
            pass

prompt_template = PromptTemplate()

class SubAgent:
    """Specialized AI sub-agent for specific tasks"""
    def __init__(self, name, role, system_prompt, model_path=None):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = None
        self.model_path = model_path or model_path
        self.conversation = []
    
    def initialize(self):
        """Load model for this agent"""
        try:
            if self.model_path:
                model_name = Path(self.model_path).name
                cpu_count = os.cpu_count() or 4
                try:
                    self.model = GPT4All(
                        model_name=model_name,
                        model_path=str(Path(self.model_path).parent),
                        allow_download=False,
                        device='cpu',
                        n_threads=min(cpu_count-1, 4)
                    )
                except TypeError:
                    self.model = GPT4All(
                        model_name=model_name,
                        model_path=str(Path(self.model_path).parent),
                        allow_download=False
                    )
                return True
            else:
                self.model = llm
                return llm is not None
        except Exception as e:
            print(f"{R}✗ Agent init failed: {str(e)[:50]}{X}")
            return False
    
    def execute(self, task, context=''):
        """Execute task with agent specialization"""
        if not self.model and not llm:
            return f"{R}No model available{X}"
        
        full_prompt = f"{self.system_prompt}\n\nContext: {context}\n\nTask: {task}"
        
        try:
            model_to_use = self.model or llm
            response = model_to_use.generate(
                full_prompt,
                max_tokens=max_tokens,
                temp=temp,
                top_p=0.95,
                top_k=40
            )
            self.conversation.append({'task': task, 'response': response})
            return response.strip() if response.strip() else f"{R}No response{X}"
        except Exception as e:
            return f"{R}Agent error: {str(e)[:50]}{X}"
    
    def get_info(self):
        """Get agent information"""
        return {
            'name': self.name,
            'role': self.role,
            'tasks_completed': len(self.conversation),
            'model': Path(self.model_path).stem if self.model_path else 'shared'
        }

class SubAgentManager:
    """Manage multiple specialized sub-agents"""
    def __init__(self):
        self.agents = {}
        self.initialize_default_agents()
    
    def initialize_default_agents(self):
        """Create default specialized agents"""
        agents_config = {
            'coder': {
                'role': 'Software Engineer',
                'prompt': 'You are an expert software engineer. Write clean, well-documented, efficient code. Follow best practices and explain your logic.'
            },
            'writer': {
                'role': 'Professional Writer',
                'prompt': 'You are a professional writer. Create engaging, clear, and well-structured content. Use proper grammar and formatting.'
            },
            'analyst': {
                'role': 'Data Analyst',
                'prompt': 'You are a data analyst. Provide insights, identify patterns, and explain trends. Use data-driven reasoning.'
            },
            'teacher': {
                'role': 'Educator',
                'prompt': 'You are an expert teacher. Explain concepts clearly, use examples, and adapt to different learning levels.'
            },
            'debugger': {
                'role': 'Debug Expert',
                'prompt': 'You are a debugging expert. Identify issues, explain root causes, and provide step-by-step solutions.'
            },
            'architect': {
                'role': 'System Architect',
                'prompt': 'You are a system architect. Design scalable, efficient systems. Consider all constraints and trade-offs.'
            }
        }
        
        for name, config in agents_config.items():
            agent = SubAgent(name, config['role'], config['prompt'])
            self.agents[name] = agent
    
    def create_agent(self, name, role, system_prompt, model_path=None):
        """Create custom agent"""
        agent = SubAgent(name, role, system_prompt, model_path)
        self.agents[name] = agent
        return agent
    
    def get_agent(self, name):
        """Get agent by name"""
        return self.agents.get(name)
    
    def execute_agent(self, agent_name, task, context=''):
        """Execute task with specific agent"""
        agent = self.agents.get(agent_name)
        if not agent:
            return f"{R}Agent not found{X}"
        
        if not agent.model and agent != self.agents.get(agent_name):
            agent.initialize()
        
        return agent.execute(task, context)
    
    def list_agents(self):
        """List all agents"""
        return {name: agent.get_info() for name, agent in self.agents.items()}
    
    def delegate(self, task, agents_needed):
        """Delegate task to multiple agents and combine results"""
        results = {}
        for agent_name in agents_needed:
            if agent_name in self.agents:
                result = self.execute_agent(agent_name, task)
                results[agent_name] = result
        return results

agent_manager = SubAgentManager()

class GGUFModelManager:
    """Universal GGUF model compatibility layer"""
    def __init__(self):
        self.available_models = []
        self.loaded_models = {}
        self.model_metadata = {}
    
    def scan_for_models(self, directory):
        """Scan directory for all .gguf files"""
        models = []
        try:
            for model_file in Path(directory).glob('**/*.gguf'):
                size_gb = model_file.stat().st_size / (1024**3)
                models.append({
                    'name': model_file.stem,
                    'path': str(model_file),
                    'size_gb': size_gb,
                    'filename': model_file.name
                })
        except Exception as e:
            print(f"{R}Scan error: {str(e)[:50]}{X}")
        return models
    
    def load_model(self, model_path, model_name=None):
        """Attempt to load any GGUF model with auto-fallback"""
        if not model_name:
            model_name = Path(model_path).name
        
        try:
            cpu_count = os.cpu_count() or 4
            
            # Try modern GPT4All API first
            try:
                model = GPT4All(
                    model_name=model_name,
                    model_path=str(Path(model_path).parent),
                    allow_download=False,
                    device='cpu',
                    n_threads=min(cpu_count-1, 4)
                )
                self.loaded_models[model_name] = model
                self.model_metadata[model_name] = {'api_version': 'modern'}
                return model
            except TypeError:
                # Fallback to older API
                model = GPT4All(
                    model_name=model_name,
                    model_path=str(Path(model_path).parent),
                    allow_download=False
                )
                self.loaded_models[model_name] = model
                self.model_metadata[model_name] = {'api_version': 'legacy'}
                return model
        except Exception as e:
            print(f"{R}Load failed for {model_name}: {str(e)[:50]}{X}")
            return None
    
    def get_model(self, model_name):
        """Get previously loaded model"""
        return self.loaded_models.get(model_name)
    
    def list_available(self, directory):
        """List available models in directory"""
        self.available_models = self.scan_for_models(directory)
        return self.available_models
    
    def list_loaded(self):
        """List currently loaded models"""
        return list(self.loaded_models.keys())
    
    def unload_model(self, model_name):
        """Unload a model from memory"""
        if model_name in self.loaded_models:
            del self.loaded_models[model_name]
            return True
        return False
    
    def get_model_info(self, model_name):
        """Get model metadata"""
        return self.model_metadata.get(model_name, {})

gguf_manager = GGUFModelManager()

class HerculesCodeUnderstanding:
    """Hercules understands Claude Code paradigms"""
    def __init__(self):
        self.patterns = {
            'mcp_integration': 'Model Context Protocol for tool integration',
            'artifact_creation': 'Standalone code artifacts with create_file',
            'agentic_workflow': 'Multi-turn reasoning with tool use',
            'structured_output': 'JSON responses for UI rendering',
            'context_window': 'Track conversation state across turns',
            'streaming': 'Progressive token generation',
            'vision': 'Image understanding and analysis',
            'web_search': 'Real-time information retrieval',
            'file_ops': 'Read/write/modify file operations',
            'bash_execution': 'Terminal command execution with safety'
        }
        self.code_templates = self.load_templates()
    
    def load_templates(self):
        """Load Claude Code best practices"""
        return {
            'mcp_server': '''
def setup_mcp(server_url):
    """Initialize MCP server connection"""
    return MCPClient(server_url)

def call_mcp_tool(client, tool_name, **kwargs):
    """Execute MCP tool"""
    return client.execute_tool(tool_name, kwargs)
''',
            'artifact': '''
# Create artifact for file
create_file(
    description="What this does",
    path="/mnt/user-data/outputs/file.py",
    file_text=content
)

# Present to user
present_files(["/mnt/user-data/outputs/file.py"])
''',
            'agentic_loop': '''
while True:
    user_input = get_input()
    
    # Reasoning step
    thought = reason_about(user_input)
    
    # Tool selection
    tool = select_tool(thought)
    
    # Execution
    result = execute_tool(tool)
    
    # Response
    respond(result)
''',
            'structured_json': '''
def get_response_json():
    """Return structured data for UI"""
    return {
        "type": "message",
        "content": "response",
        "metadata": {}
    }
''',
            'vision_analysis': '''
def analyze_image(image_base64, query):
    """Analyze image with vision"""
    response = api.call({
        "type": "image",
        "source": {"type": "base64", "data": image_base64},
        "query": query
    })
    return response
''',
            'web_integration': '''
def search_and_fetch(query):
    """Web search + fetch pattern"""
    results = web_search(query)
    for url in results:
        content = web_fetch(url)
        process(content)
'''
        }
    
    def explain_pattern(self, pattern_name):
        """Explain Claude Code pattern"""
        return self.patterns.get(pattern_name, "Unknown pattern")
    
    def get_template(self, template_name):
        """Get code template"""
        return self.code_templates.get(template_name, "No template found")
    
    def suggest_pattern(self, task):
        """Suggest best Claude Code pattern for task"""
        suggestions = {
            'file creation': 'artifact_creation',
            'tool integration': 'mcp_integration',
            'decision making': 'agentic_workflow',
            'data output': 'structured_output',
            'image analysis': 'vision',
            'information lookup': 'web_search',
            'command execution': 'bash_execution'
        }
        for key, pattern in suggestions.items():
            if key.lower() in task.lower():
                return pattern
        return None

claude_code_knowledge = HerculesCodeUnderstanding()

class HierarchicalSubAgent:
    """3-layer deep sub-agent with parent-child relationships"""
    def __init__(self, name, role, level=1, parent=None):
        self.name = name
        self.role = role
        self.level = level  # 1=top, 2=mid, 3=leaf
        self.parent = parent
        self.children = []
        self.system_prompt = self._build_prompt()
        self.model = None
        self.conversation = []
        self.task_queue = []
    
    def _build_prompt(self):
        """Build context-aware prompt based on level"""
        if self.level == 1:
            return f"You are {self.role}, a top-level orchestrator managing sub-teams. Delegate tasks effectively, evaluate results, provide strategic direction."
        elif self.level == 2:
            return f"You are {self.role}, a middle-tier executor. Take direction from parent, delegate to children, handle complex tasks, report findings up."
        else:  # level 3
            return f"You are {self.role}, a specialized executor. Execute focused tasks, report results to parent, ask for clarification if needed."
    
    def add_child(self, child_agent):
        """Add child agent"""
        if len(self.children) < 3:  # Max 3 children per agent
            child_agent.parent = self
            self.children.append(child_agent)
            return True
        return False
    
    def delegate_to_children(self, task):
        """Delegate task to child agents"""
        results = {}
        for child in self.children:
            result = child.execute(task, parent_context=self.name)
            results[child.name] = result
        return results
    
    def execute(self, task, parent_context=''):
        """Execute task, escalate to children if needed"""
        # Execute at this level
        prompt = f"{self.system_prompt}\n\nTask: {task}"
        if parent_context:
            prompt += f"\n\nParent Context: {parent_context}"
        
        if self.children and len(task) > 100:  # Complex task → delegate
            child_results = self.delegate_to_children(task)
            synthesis = f"Synthesizing results from {len(self.children)} sub-agents: {child_results}"
            self.conversation.append({'task': task, 'synthesis': synthesis})
            return synthesis
        else:
            self.conversation.append({'task': task})
            return f"[{self.level}] Executed: {task[:50]}"
    
    def get_hierarchy(self):
        """Get agent tree structure"""
        return {
            'name': self.name,
            'role': self.role,
            'level': self.level,
            'children': [c.get_hierarchy() for c in self.children]
        }

class HierarchicalAgentManager:
    """Manage 3-layer agent hierarchy"""
    def __init__(self):
        self.root_agents = {}
        self.all_agents = {}
        self._initialize_hierarchy()
    
    def _initialize_hierarchy(self):
        """Create 3-layer agent hierarchy"""
        # Layer 1: Orchestrators
        orchestrator = HierarchicalSubAgent('orchestrator', 'Task Orchestrator', level=1)
        
        # Layer 2: Specialized teams
        code_team_lead = HierarchicalSubAgent('code_lead', 'Code Team Lead', level=2, parent=orchestrator)
        analysis_team_lead = HierarchicalSubAgent('analysis_lead', 'Analysis Team Lead', level=2, parent=orchestrator)
        creative_team_lead = HierarchicalSubAgent('creative_lead', 'Creative Team Lead', level=2, parent=orchestrator)
        
        orchestrator.add_child(code_team_lead)
        orchestrator.add_child(analysis_team_lead)
        orchestrator.add_child(creative_team_lead)
        
        # Layer 3: Specialists
        # Code Team
        code_team_lead.add_child(HierarchicalSubAgent('coder', 'Python Coder', level=3))
        code_team_lead.add_child(HierarchicalSubAgent('debugger', 'Bug Debugger', level=3))
        code_team_lead.add_child(HierarchicalSubAgent('optimizer', 'Performance Optimizer', level=3))
        
        # Analysis Team
        analysis_team_lead.add_child(HierarchicalSubAgent('analyst', 'Data Analyst', level=3))
        analysis_team_lead.add_child(HierarchicalSubAgent('researcher', 'Research Specialist', level=3))
        analysis_team_lead.add_child(HierarchicalSubAgent('architect', 'System Architect', level=3))
        
        # Creative Team
        creative_team_lead.add_child(HierarchicalSubAgent('writer', 'Content Writer', level=3))
        creative_team_lead.add_child(HierarchicalSubAgent('teacher', 'Educator', level=3))
        creative_team_lead.add_child(HierarchicalSubAgent('designer', 'UX Designer', level=3))
        
        # Store references
        self.root_agents['orchestrator'] = orchestrator
        self._map_all_agents(orchestrator)
    
    def _map_all_agents(self, agent):
        """Map all agents for quick lookup"""
        self.all_agents[agent.name] = agent
        for child in agent.children:
            self._map_all_agents(child)
    
    def execute_task(self, task, agent_name='orchestrator'):
        """Execute task through agent hierarchy"""
        agent = self.all_agents.get(agent_name)
        if not agent:
            return f"{R}Agent not found{X}"
        
        # Add Claude Code understanding to prompt
        pattern = claude_code_knowledge.suggest_pattern(task)
        if pattern:
            task = f"{task}\n[Use Claude Code pattern: {pattern}]"
        
        return agent.execute(task)
    
    def show_hierarchy(self):
        """Display 3-layer hierarchy"""
        return self.root_agents['orchestrator'].get_hierarchy()
    
    def get_agent_at_level(self, level):
        """Get all agents at specific level"""
        agents = [a for a in self.all_agents.values() if a.level == level]
        return agents
    
    def find_specialist(self, specialty):
        """Find agent matching specialty"""
        for agent in self.all_agents.values():
            if specialty.lower() in agent.role.lower():
                return agent
        return None

hierarchical_manager = HierarchicalAgentManager()

def print_hierarchy(hierarchy, indent):
    """Pretty print agent hierarchy"""
    level_colors = {1: O1, 2: H1, 3: H2}
    color = level_colors.get(hierarchy['level'], S)
    indent_str = '  ' * indent
    print(f"{indent_str}{color}├─ {hierarchy['name']}{X} ({hierarchy['role']})")
    for child in hierarchy['children']:
        print_hierarchy(child, indent + 1)

def main():
 global llm,model_path
 splash()
 
 # Initialize plugins
 create_sample_plugins()
 discovered = plugin_manager.discover_plugins()
 if discovered:
  print(f"{S}Found {len(discovered)} plugins. Load with /plugin load <name>{X}\n")
 
 if not setup():
  return
 
 print(f"{O2}Model: {O1}{Path(model_path).stem}{X}\n")
 
 while True:
  try:
   inp=input(f"{H1}You:{X} ").strip()
   
   if not inp:
    continue
   
   if inp in ['/','/help']:
    show_commands()
    continue
   
   if inp.lower() in ['exit','quit','bye','/exit']:
    print(f"{G}Goodbye{X}\n")
    break
   
   if inp=='/models':
    list_models()
    continue
   
   if inp=='/setup':
    if setup():
     print(f"{O2}Model: {O1}{Path(model_path).stem}{X}\n")
    continue
   
   if inp=='/config':
    config_manager.show_config()
    continue
   
   if inp=='/temp':
    set_temperature()
    continue
   
   if inp=='/tokens':
    set_tokens()
    continue
   
   if inp=='/batch':
    batch_process()
    continue
   
   if inp=='/export':
    export_chat()
    continue
   
   if inp=='/search':
    search_history()
    continue
   
   if inp=='/history':
    show_history()
    continue
   
   if inp=='/save':
    save_conversation()
    continue
   
   if inp=='/load':
    load_conversation()
    continue
   
   if inp=='/theme':
    toggle_theme()
    continue
   
   if inp=='/info':
    show_model_info()
    continue
   
   if inp=='/unload':
    unload_model()
    continue
   
   if inp=='/overclock':
    enable_overclock()
    continue
   
   if inp=='/skill':
    add_skill()
    continue
   
   if inp=='/skills':
    list_skills()
    continue
   
   if inp.startswith('/plugin'):
    parts = inp.split(None, 1)
    if len(parts) < 2 or parts[1] == '':
     discovered = plugin_manager.discover_plugins()
     loaded = plugin_manager.list_plugins()
     print(f"\n{O2}╔ Plugin Manager ╗{X}\n")
     print(f"  {H1}Loaded:{X} {', '.join(loaded) if loaded else 'None'}")
     print(f"  {H1}Available:{X} {', '.join(discovered) if discovered else 'None'}")
     print(f"  {H1}Location:{X} {plugin_manager.plugin_dir}")
     print()
    elif parts[1].startswith('load '):
     plugin_name = parts[1][5:].strip()
     if plugin_manager.load_plugin(plugin_name):
      print(f"{G}✓ Plugin loaded: {plugin_name}{X}\n")
     else:
      print(f"{R}✗ Failed to load plugin{X}\n")
    continue
   
   if inp.startswith('/branch'):
    parts = inp.split(None, 2)
    if len(parts) < 2:
     branches = branch_manager.list_branches()
     print(f"\n{O2}╔ Conversation Branches ╗{X}\n")
     for name, info in branches.items():
      marker = f" {H1}[CURRENT]{X}" if name == branch_manager.current_branch else ""
      print(f"  {O1}{name}{X} - {info['messages']} messages{marker}")
     print()
    elif parts[1] == 'create' and len(parts) == 3:
     if branch_manager.create_branch(parts[2]):
      print(f"{G}✓ Branch created: {parts[2]}{X}\n")
     else:
      print(f"{R}✗ Branch creation failed{X}\n")
    elif parts[1] == 'switch' and len(parts) == 3:
     if branch_manager.switch_branch(parts[2]):
      print(f"{G}✓ Switched to branch: {parts[2]}{X}\n")
     else:
      print(f"{R}✗ Branch not found{X}\n")
    elif parts[1] == 'merge' and len(parts) == 3:
     if branch_manager.merge_branch(parts[2]):
      print(f"{G}✓ Merged {parts[2]} into main{X}\n")
     else:
      print(f"{R}✗ Merge failed{X}\n")
    continue
   
   if inp.startswith('/memory'):
    parts = inp.split(None, 2)
    if len(parts) < 2:
     memories = memory_bank.list_memories()
     print(f"\n{O2}╔ Memory Bank ╗{X}\n")
     if memories:
      for mem in memories:
       print(f"  {H1}{mem}{X}")
      print()
      print(f"{S}Use: /memory recall <tag> or /memory save <tag> <content>{X}\n")
     else:
      print(f"{S}No memories saved yet{X}\n")
    elif parts[1] == 'recall' and len(parts) == 3:
     content = memory_bank.recall_memory(parts[2])
     if content:
      print(f"\n{O1}[Memory: {parts[2]}]{X}\n{G}{content}{X}\n")
     else:
      print(f"{R}✗ Memory not found{X}\n")
    elif parts[1] == 'save' and len(parts) == 3:
     # Save last response as memory
     if chat_history:
      last_response = chat_history[-1]['response']
      memory_bank.save_memory(parts[2], last_response)
      print(f"{G}✓ Memory saved: {parts[2]}{X}\n")
     else:
      print(f"{R}✗ No response to save{X}\n")
    elif parts[1] == 'important':
     important = memory_bank.get_important_memories()
     print(f"\n{O2}╔ Important Memories ╗{X}\n")
     for tag, mem in important.items():
      print(f"  {H1}{tag}:{X} {mem['content'][:50]}...")
     print()
    continue
   
   if inp.startswith('/template'):
    parts = inp.split(None, 2)
    if len(parts) < 2:
     templates = prompt_template.list_templates()
     print(f"\n{O2}╔ Prompt Templates ╗{X}\n")
     for tmpl in templates:
      print(f"  {H1}{tmpl}{X}")
     print(f"\n{S}Use: /template render <name> key=value{X}\n")
    elif parts[1] == 'render' and len(parts) >= 3:
     name = parts[2].split()[0] if parts[2] else ''
     # Parse key=value pairs
     kwargs = {}
     for arg in parts[2].split()[1:]:
      if '=' in arg:
       key, val = arg.split('=', 1)
       kwargs[key] = val
     
     rendered = prompt_template.render(name, **kwargs)
     if rendered:
      print(f"\n{O1}[Template: {name}]{X}\n{G}{rendered}{X}\n")
      # Ask if want to use it
      print(f"{H2}Use this prompt? (y/n):{X} ", end='', flush=True)
      if input().strip().lower() == 'y':
       inp = rendered
       # Falls through to normal processing
     else:
      print(f"{R}✗ Template not found{X}\n")
      continue
    continue
   
   if inp.startswith('/hagent'):
    parts = inp.split(None, 2)
    if len(parts) < 2:
     hierarchy = hierarchical_manager.show_hierarchy()
     print(f"\n{O2}╔ 3-Layer Agent Hierarchy ╗{X}\n")
     print_hierarchy(hierarchy, 0)
     print()
    elif parts[1] == 'task' and len(parts) == 3:
     task = parts[2]
     print(f"\n{G}Executing through hierarchy...{X}\n")
     result = hierarchical_manager.execute_task(task)
     print(f"{O1}{result}{X}\n")
     chat_history.append({'prompt': f'[HIERARCHY] {task}', 'response': result})
    elif parts[1] == 'find' and len(parts) == 3:
     agent = hierarchical_manager.find_specialist(parts[2])
     if agent:
      print(f"\n{G}Found specialist: {agent.name} ({agent.role}) - Level {agent.level}{X}\n")
     else:
      print(f"{R}No specialist found{X}\n")
    continue
   
   if inp.startswith('/code'):
    parts = inp.split(None, 2)
    if len(parts) < 2:
     print(f"\n{O2}╔ Claude Code Knowledge ╗{X}\n")
     print(f"{S}Available patterns:{X}")
     for pattern in claude_code_knowledge.patterns.keys():
      print(f"  {H1}{pattern}{X}")
     print(f"\n{S}Usage: /code <pattern> or /code template <name>{X}\n")
    elif parts[1] == 'template' and len(parts) == 3:
     template = claude_code_knowledge.get_template(parts[2])
     print(f"\n{O1}[Template: {parts[2]}]{X}\n{G}{template}{X}\n")
    elif len(parts) == 2:
     explanation = claude_code_knowledge.explain_pattern(parts[1])
     print(f"\n{O1}[Pattern: {parts[1]}]{X}\n{G}{explanation}{X}\n")
    continue
   
   if inp.startswith('/delegate'):
    print(f"\n{O2}╔ Multi-Agent Delegation ╗{X}\n")
    print(f"{H2}Task to delegate:{X} ", end='', flush=True)
    task = input().strip()
    
    agents = agent_manager.list_agents()
    print(f"\n{H2}Available agents:{X}")
    for i, name in enumerate(agents.keys(), 1):
     print(f"  {H1}[{i}]{X} {name}")
    
    print(f"\n{H2}Select agents (comma-separated, e.g. 1,2,3):{X} ", end='', flush=True)
    selections = input().strip().split(',')
    agent_list = list(agents.keys())
    
    try:
     selected = [agent_list[int(s.strip())-1] for s in selections if s.strip()]
     if selected:
      print(f"\n{G}Delegating to {len(selected)} agents...{X}\n")
      results = agent_manager.delegate(task, selected)
      for agent_name, result in results.items():
       print(f"{O1}[{agent_name}]{X}\n{G}{result}{X}\n")
    except (ValueError, IndexError):
     print(f"{R}✗ Invalid selection{X}\n")
    continue
   
   if inp.startswith('/models '):
    # Extended models command with GGUF compatibility
    subcommand = inp[8:].strip()
    if subcommand == 'scan':
     model_dir = config_manager.get('model_dir')
     available = gguf_manager.list_available(model_dir)
     print(f"\n{O2}╔ Available GGUF Models ╗{X}\n")
     for model in available:
      print(f"  {H1}{model['name']}{X} - {model['size_gb']:.2f}GB")
     print(f"\n{G}✓ Found {len(available)} models{X}\n")
    elif subcommand == 'loaded':
     loaded = gguf_manager.list_loaded()
     print(f"\n{O2}╔ Loaded Models ╗{X}\n")
     for model in loaded:
      print(f"  {H1}{model}{X}")
     print()
    continue
    run_as_agent()
    continue
   
   if inp=='/stats':
    show_conversation_stats()
    continue
   
   if inp=='/advsearch':
    advanced_search()
    continue
   
   if inp=='/clear':
    try:
     chat_history.clear()
     print(f"{G}✓ Chat history cleared{X}\n")
    except:
     print(f"{R}✗ Clear failed{X}\n")
    continue
   
   if inp=='/context':
    print(f"\n{O2}╔ Conversation Context ╗{X}\n")
    print(f"{S}{get_context_summary()}{X}\n")
    if chat_history:
     print(f"{H1}Recent exchanges:{X}")
     for i,h in enumerate(chat_history[-3:],1):
      print(f"  {O1}[{i}]{X} {h['prompt'][:50]}")
    print()
    continue
   
   if inp.startswith('/macro'):
    parts = inp.split(None, 2)
    if len(parts) < 2:
     print(f"\n{O2}╔ Macro System ╗{X}\n")
     macros = macro_system.list_macros()
     for name, expansion in macros.items():
      print(f"  {H1}{name}:{X} {expansion[:50]}")
     print()
    elif parts[1] == 'add' and len(parts) == 3:
     macro_def = parts[2].split('=')
     if len(macro_def) == 2:
      macro_system.add_macro(macro_def[0].strip(), macro_def[1].strip())
      print(f"{G}✓ Macro added{X}\n")
     else:
      print(f"{R}✗ Use: /macro add name=expansion{X}\n")
    continue
   
   if inp=='/freerange':
    if not freerange_enabled:
     setup_freerange()
    else:
     print(f"{O2}Freerange Mode Options:{X}\n")
     print(f"  {H1}[1]{X} Start task")
     print(f"  {H1}[2]{X} Change directory")
     print(f"  {H1}[3]{X} Disable freerange\n")
     print(f"{H2}Choose:{X} ",end='',flush=True)
     try:
      opt=input().strip()
      if opt=='1':
       execute_freerange()
      elif opt=='2':
       disable_freerange()
       setup_freerange()
      elif opt=='3':
       disable_freerange()
     except:
      print(f"{R}✗ Invalid option{X}\n")
    continue
   
   print(f"{O1}Assistant:{X}\n")
   response=query(inp)
   print(f"{G}{response}{X}\n")
   chat_history.append({'prompt':inp,'response':response})
   
  except KeyboardInterrupt:
   print(f"\n{S}Interrupted{X}\n")
   break
  except Exception as e:
   print(f"{R}Error: {e}{X}\n")

if __name__=='__main__':
 main()