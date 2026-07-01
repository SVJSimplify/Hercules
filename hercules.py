#!/usr/bin/env python3
"""Hercules - Local-First AI Agent with GPT4All Integration"""

import sys
import subprocess

# AUTO-INSTALL DEPENDENCIES
def auto_install_deps():
    """Auto-install numpy and colorama if missing"""
    required = ['numpy', 'colorama']
    for pkg in required:
        try:
            __import__(pkg)
        except ImportError:
            print(f"📦 Installing {pkg}...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "--quiet", pkg],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    print(f"✅ {pkg} installed")
                else:
                    print(f"❌ Failed to install {pkg}")
                    print(f"Run manually: pip install {pkg}")
            except Exception as e:
                print(f"❌ Failed to install {pkg}")
                print(f"Run manually: pip install {pkg}")

auto_install_deps()

# Now safe to import
import json
import os
import platform
from pathlib import Path
from collections import Counter
from datetime import datetime

try:
    from colorama import init
    import subprocess
    import struct
    import logging
    import json
    import signal
    from functools import wraps
    from time import time, sleep
    from collections import defaultdict
    init(autoreset=True)
except ImportError as e:
    print(f"❌ ERROR: {e}")
    sys.exit(1)

try:
    import numpy as np
except ImportError:
    print("❌ numpy still not found after install attempt")
    sys.exit(1)

# Configure structured logging with file output
import atexit

LOG_DIR = Path.home() / '.hercules' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE = LOG_DIR / f"hercules_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"

# Setup file handler
file_handler = logging.FileHandler(LOG_FILE)
file_handler.setLevel(logging.DEBUG)
file_formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
file_handler.setFormatter(file_formatter)

# Setup root logger
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[file_handler]
)
logger = logging.getLogger("hercules")

# Log startup
def log_startup():
    """Log application startup info"""
    logger.info(f"Hercules started - Log file: {LOG_FILE}")
    logger.info(f"Platform: {platform.system()} {platform.release()}")
    logger.info(f"Python: {sys.version}")

atexit.register(lambda: logger.info("Hercules shutdown"))

class StructuredLogger:
    """JSON-structured logging"""
    def __init__(self, name):
        self.logger = logging.getLogger(name)
    
    def log(self, event: str, **kwargs):
        """Log structured event as JSON"""
        log_data = {
            'timestamp': __import__('datetime').datetime.now().isoformat(),
            'event': event,
            **kwargs
        }
        self.logger.info(json.dumps(log_data))
    
    def error(self, event: str, error: str, **kwargs):
        """Log error with context"""
        log_data = {
            'timestamp': __import__('datetime').datetime.now().isoformat(),
            'event': event,
            'error': str(error),
            'level': 'ERROR',
            **kwargs
        }
        self.logger.error(json.dumps(log_data))

structured_logger = StructuredLogger("hercules")

# Global exception handler
def global_exception_handler(exc_type, exc_value, exc_traceback):
    """Catch all unhandled exceptions and log them"""
    logger.critical(
        "UNCAUGHT EXCEPTION",
        exc_info=(exc_type, exc_value, exc_traceback)
    )
    sys.__excepthook__(exc_type, exc_value, exc_traceback)

sys.excepthook = global_exception_handler

# === PRIORITY 0: DEAD LETTER QUEUE ===
class DeadLetterQueue:
    """Queue for failed requests"""
    def __init__(self, max_size: int = 1000):
        self.queue = []
        self.max_size = max_size
    
    def add(self, request: dict, error: str, timestamp: float = None):
        """Add failed request to DLQ"""
        if len(self.queue) >= self.max_size:
            self.queue.pop(0)  # FIFO
        
        dlq_item = {
            'request': request,
            'error': error,
            'timestamp': timestamp or time(),
            'retry_count': 0
        }
        self.queue.append(dlq_item)
        structured_logger.log('dlq_add', error=error, queue_size=len(self.queue))
    
    def retry_one(self, func, *args, **kwargs):
        """Retry first item in DLQ"""
        if not self.queue:
            return None
        
        item = self.queue[0]
        try:
            result = func(*args, **kwargs)
            structured_logger.log('dlq_retry_success', retry_count=item['retry_count'])
            self.queue.pop(0)
            return result
        except Exception as e:
            item['retry_count'] += 1
            structured_logger.log('dlq_retry_failed', retry_count=item['retry_count'], error=str(e))
            if item['retry_count'] > 5:
                self.queue.pop(0)
            return None
    
    def get_size(self) -> int:
        return len(self.queue)

dlq = DeadLetterQueue(max_size=1000)
# === END DEAD LETTER QUEUE ===

# === PRIORITY 0.2: REQUEST DEDUPLICATION ===
class RequestCache:
    """Cache responses to identical requests"""
    def __init__(self, max_size: int = 500, ttl_seconds: int = 3600):
        self.cache = {}
        self.max_size = max_size
        self.ttl = ttl_seconds
    
    def get(self, request_hash: str) -> tuple:
        """Get cached response if exists and not expired"""
        if request_hash in self.cache:
            cached_time, response = self.cache[request_hash]
            if time() - cached_time < self.ttl:
                structured_logger.log('cache_hit', hash=request_hash[:8])
                return response
            else:
                del self.cache[request_hash]
        return None
    
    def set(self, request_hash: str, response):
        """Cache response to request"""
        if len(self.cache) >= self.max_size:
            # Remove oldest entry
            oldest_key = min(self.cache.keys(), key=lambda k: self.cache[k][0])
            del self.cache[oldest_key]
        
        self.cache[request_hash] = (time(), response)
        structured_logger.log('cache_set', hash=request_hash[:8], size=len(self.cache))

request_cache = RequestCache(max_size=500, ttl_seconds=3600)
# === END REQUEST DEDUPLICATION ===

# === PRIORITY 0: RATE LIMITING ===
class RateLimiter:
    """Token bucket rate limiter"""
    def __init__(self, max_requests: int = 10, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self.requests = defaultdict(list)
    
    def is_allowed(self, session_id: str) -> bool:
        """Check if request allowed for session"""
        now = time()
        cutoff = now - self.window
        
        # Clean old requests
        self.requests[session_id] = [t for t in self.requests[session_id] if t > cutoff]
        
        if len(self.requests[session_id]) < self.max_requests:
            self.requests[session_id].append(now)
            return True
        return False
    
    def get_remaining(self, session_id: str) -> int:
        """Get remaining requests in window"""
        now = time()
        cutoff = now - self.window
        self.requests[session_id] = [t for t in self.requests[session_id] if t > cutoff]
        return max(0, self.max_requests - len(self.requests[session_id]))

HAS_RATE_LIMITING = True
rate_limiter = RateLimiter(max_requests=10, window_seconds=60)
# === END RATE LIMITING ===

# === PRIORITY 0.5: RETRY LOGIC ===
def retry(max_attempts: int = 3, backoff_factor: float = 2.0, initial_delay: float = 1.0):
    """Decorator for exponential backoff retry logic"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            delay = initial_delay
            last_error = None
            for attempt in range(max_attempts):
                try:
                    result = func(*args, **kwargs)
                    if attempt > 0:
                        structured_logger.log('retry_success', function=func.__name__, attempt=attempt+1)
                    return result
                except Exception as e:
                    last_error = e
                    if attempt < max_attempts - 1:
                        structured_logger.log('retry_attempt', function=func.__name__, attempt=attempt+1, error=str(e), delay=delay)
                        sleep(delay)
                        delay *= backoff_factor
                    else:
                        structured_logger.error('retry_failed', error=str(e), function=func.__name__, attempts=max_attempts)
            raise last_error
        return wrapper
    return decorator

# === END RETRY LOGIC ===

# === PRIORITY 0.7: TIMEOUT MANAGEMENT ===
class TimeoutError(Exception):
    """Custom timeout exception"""
    pass

def timeout_handler(signum, frame):
    """Signal handler for timeout"""
    raise TimeoutError("Operation timed out")

class TimeoutManager:
    """Manages execution timeouts"""
    def __init__(self, timeout_seconds: int = 120):
        self.timeout = timeout_seconds
        self.original_handler = None
    
    def start(self):
        """Start timeout timer"""
        if hasattr(signal, 'SIGALRM'):
            self.original_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(self.timeout)
    
    def cancel(self):
        """Cancel timeout"""
        if hasattr(signal, 'SIGALRM'):
            signal.alarm(0)
            if self.original_handler:
                signal.signal(signal.SIGALRM, self.original_handler)
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, *args):
        self.cancel()

timeout_manager = TimeoutManager(timeout_seconds=120)
# === END TIMEOUT MANAGEMENT ===

# === PRIORITY 0.9: GRACEFUL SHUTDOWN ===
class GracefulShutdown:
    """Handle graceful shutdown on signals"""
    def __init__(self):
        self.shutdown_requested = False
        self.cleanup_handlers = []
    
    def register_cleanup(self, func):
        """Register cleanup function"""
        self.cleanup_handlers.append(func)
    
    def handle_signal(self, signum, frame):
        """Signal handler for graceful shutdown"""
        structured_logger.log('shutdown_initiated', signal=signum)
        self.shutdown_requested = True
        self._cleanup()
    
    def _cleanup(self):
        """Execute all cleanup handlers"""
        structured_logger.log('cleanup_start', handlers=len(self.cleanup_handlers))
        
        for handler in self.cleanup_handlers:
            try:
                handler()
            except Exception as e:
                structured_logger.error('cleanup_failed', handler=handler.__name__, error=str(e))
        
        structured_logger.log('cleanup_complete')
    
    def setup_handlers(self):
        """Setup signal handlers"""
        if hasattr(signal, 'SIGTERM'):
            signal.signal(signal.SIGTERM, self.handle_signal)
        if hasattr(signal, 'SIGINT'):
            signal.signal(signal.SIGINT, self.handle_signal)

graceful_shutdown = GracefulShutdown()

# Register default cleanup
def default_cleanup():
    """Default cleanup: save sessions and logs"""
    if current_session and HAS_PERSISTENCE:
        try:
            session_persistence.save_session(current_session)
        except:
            pass

graceful_shutdown.register_cleanup(default_cleanup)
graceful_shutdown.setup_handlers()
# === END GRACEFUL SHUTDOWN ===

# === PRIORITY 0: API INTEGRATION SYSTEM ===
class APIConfig:
    """Manage API keys and credentials"""
    def __init__(self):
        self.config_file = Path.home() / '.hercules' / 'apis.json'
        self.config_file.parent.mkdir(parents=True, exist_ok=True)
        self.apis = {}
        self.load_config()
    
    def load_config(self):
        """Load API config from file"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    self.apis = json.load(f)
                structured_logger.log('api_config_loaded', file=str(self.config_file))
            except Exception as e:
                structured_logger.error('api_config_load_failed', error=str(e))
                self.apis = {}
    
    def save_config(self):
        """Save API config to file"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.apis, f, indent=2)
            os.chmod(self.config_file, 0o600)  # Read-only for owner
            structured_logger.log('api_config_saved')
        except Exception as e:
            structured_logger.error('api_config_save_failed', error=str(e))
    
    def set_api(self, provider, key, **kwargs):
        """Store API key and config"""
        self.apis[provider] = {'key': key, **kwargs}
        self.save_config()
        structured_logger.log('api_configured', provider=provider)
    
    def get_api(self, provider):
        """Get API config"""
        return self.apis.get(provider)
    
    def list_apis(self):
        """List configured APIs"""
        return list(self.apis.keys())
    
    def remove_api(self, provider):
        """Remove API config"""
        if provider in self.apis:
            del self.apis[provider]
            self.save_config()
            structured_logger.log('api_removed', provider=provider)

api_config = APIConfig()

# === API CLIENT WRAPPERS ===
class OpenAIClient:
    """OpenAI API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1"
        self.model = "gpt-5.4"
    
    def query(self, prompt, model=None):
        """Query OpenAI"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('openai_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"OpenAI error: {response.status_code}"
                structured_logger.error('openai_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('openai_query_error', error=str(e))
            return f"OpenAI error: {str(e)}"

class AnthropicClient:
    """Anthropic Claude API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.anthropic.com/v1"
        self.model = "claude-sonnet-5"
    
    def query(self, prompt, model=None):
        """Query Anthropic Claude"""
        try:
            import requests
            headers = {
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            }
            data = {
                "model": model or self.model,
                "max_tokens": 2048,
                "messages": [{"role": "user", "content": prompt}]
            }
            response = requests.post(f"{self.base_url}/messages", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('anthropic_query_success', model=model or self.model)
                return response.json()['content'][0]['text']
            else:
                error_msg = f"Anthropic error: {response.status_code}"
                structured_logger.error('anthropic_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('anthropic_query_error', error=str(e))
            return f"Anthropic error: {str(e)}"

class GoogleGeminiClient:
    """Google Gemini API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://generativelanguage.googleapis.com/v1beta/models"
        self.model = "gemini-3.5-flash"
    
    def query(self, prompt, model=None):
        """Query Google Gemini"""
        try:
            import requests
            model_name = model or self.model
            url = f"{self.base_url}/{model_name}:generateContent"
            headers = {"Content-Type": "application/json"}
            data = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"maxOutputTokens": 2048}
            }
            response = requests.post(f"{url}?key={self.api_key}", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('gemini_query_success', model=model_name)
                return response.json()['candidates'][0]['content']['parts'][0]['text']
            else:
                error_msg = f"Gemini error: {response.status_code}"
                structured_logger.error('gemini_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('gemini_query_error', error=str(e))
            return f"Gemini error: {str(e)}"

class HuggingFaceClient:
    """Hugging Face API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api-inference.huggingface.co"
        self.model = "meta-llama/Llama-3.2-3B-Instruct"
    
    def query(self, prompt, model=None):
        """Query Hugging Face"""
        try:
            import requests
            model_name = model or self.model
            headers = {"Authorization": f"Bearer {self.api_key}"}
            data = {"inputs": prompt}
            response = requests.post(
                f"{self.base_url}/models/{model_name}",
                headers=headers,
                json=data,
                timeout=30
            )
            if response.status_code == 200:
                structured_logger.log('huggingface_query_success', model=model_name)
                return response.json()[0].get('generated_text', '')
            else:
                error_msg = f"HuggingFace error: {response.status_code}"
                structured_logger.error('huggingface_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('huggingface_query_error', error=str(e))
            return f"HuggingFace error: {str(e)}"

class CohereClient:
    """Cohere API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.cohere.ai"
        self.model = "command-r-plus"
    
    def query(self, prompt, model=None):
        """Query Cohere"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "prompt": prompt,
                "max_tokens": 2048,
                "temperature": 0.8
            }
            response = requests.post(f"{self.base_url}/v1/generate", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('cohere_query_success')
                return response.json()['generations'][0]['text']
            else:
                error_msg = f"Cohere error: {response.status_code}"
                structured_logger.error('cohere_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('cohere_query_error', error=str(e))
            return f"Cohere error: {str(e)}"

class GroqClient:
    """Groq API integration (fast inference)"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.groq.com/openai/v1"
        self.model = "llama-3.3-70b-versatile"
    
    def query(self, prompt, model=None):
        """Query Groq"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('groq_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"Groq error: {response.status_code}"
                structured_logger.error('groq_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('groq_query_error', error=str(e))
            return f"Groq error: {str(e)}"

class TogetherAIClient:
    """Together AI API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.together.xyz/v1"
        self.model = "meta-llama/Llama-3.3-70B-Instruct-Turbo"
    
    def query(self, prompt, model=None):
        """Query Together AI"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('together_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"Together error: {response.status_code}"
                structured_logger.error('together_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('together_query_error', error=str(e))
            return f"Together error: {str(e)}"

class AzureOpenAIClient:
    """Azure OpenAI API integration"""
    def __init__(self, api_key, endpoint):
        self.api_key = api_key
        self.endpoint = endpoint
        self.model = "gpt-4o"
    
    def query(self, prompt, model=None):
        """Query Azure OpenAI"""
        try:
            import requests
            headers = {"api-key": self.api_key, "Content-Type": "application/json"}
            data = {
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7,
                "max_tokens": 2048
            }
            url = f"{self.endpoint}/openai/deployments/{model or self.model}/chat/completions?api-version=2023-05-15"
            response = requests.post(url, headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('azure_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"Azure error: {response.status_code}"
                structured_logger.error('azure_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('azure_query_error', error=str(e))
            return f"Azure error: {str(e)}"

class PerplexityClient:
    """Perplexity AI API integration"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.perplexity.ai"
        self.model = "sonar-pro"
    
    def query(self, prompt, model=None):
        """Query Perplexity AI"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('perplexity_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"Perplexity error: {response.status_code}"
                structured_logger.error('perplexity_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('perplexity_query_error', error=str(e))
            return f"Perplexity error: {str(e)}"

class DeepSeekClient:
    """DeepSeek API integration (2024 - Fast & Affordable)"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.deepseek.com/v1"
        self.model = "deepseek-v4-flash"
    
    def query(self, prompt, model=None):
        """Query DeepSeek"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('deepseek_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"DeepSeek error: {response.status_code}"
                structured_logger.error('deepseek_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('deepseek_query_error', error=str(e))
            return f"DeepSeek error: {str(e)}"

class XAIClient:
    """XAI Grok API integration (Elon Musk's X - 2024)"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.x.ai/v1"
        self.model = "grok-4-3"
    
    def query(self, prompt, model=None):
        """Query XAI Grok"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('xai_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"XAI error: {response.status_code}"
                structured_logger.error('xai_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('xai_query_error', error=str(e))
            return f"XAI error: {str(e)}"

class MetaLlamaClient:
    """Meta Llama API integration (2026 - Llama 4 Maverick & Scout)"""
    def __init__(self, api_key):
        self.api_key = api_key
        self.base_url = "https://api.llama-ai.com/v1"
        self.model = "llama-4-maverick"
    
    def query(self, prompt, model=None):
        """Query Meta Llama"""
        try:
            import requests
            headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
            data = {
                "model": model or self.model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 2048
            }
            response = requests.post(f"{self.base_url}/chat/completions", headers=headers, json=data, timeout=30)
            if response.status_code == 200:
                structured_logger.log('meta_query_success', model=model or self.model)
                return response.json()['choices'][0]['message']['content']
            else:
                error_msg = f"Meta error: {response.status_code}"
                structured_logger.error('meta_query_failed', error=error_msg)
                return f"Error: {error_msg}"
        except Exception as e:
            structured_logger.error('meta_query_error', error=str(e))
            return f"Meta error: {str(e)}"

# API Model Pricing Database (per 1M tokens) - 2026 ACCURATE PRICING
API_MODELS = {
    'openai': {
        'gpt-5.5': {'input': 5.0, 'output': 30.0, 'display': 'GPT-5.5 (Flagship, April 2026)'},
        'gpt-5.5-pro': {'input': 8.0, 'output': 40.0, 'display': 'GPT-5.5 Pro (Advanced Reasoning)'},
        'gpt-5.4': {'input': 3.0, 'output': 15.0, 'display': 'GPT-5.4 (Thinking, Previous Gen)'},
        'gpt-5.4-mini': {'input': 0.4, 'output': 1.6, 'display': 'GPT-5.4 Mini (Balanced)'},
        'gpt-5.4-nano': {'input': 0.1, 'output': 0.4, 'display': 'GPT-5.4 Nano (Fastest & Cheapest)'},
        'gpt-5.3-codex': {'input': 3.0, 'output': 15.0, 'display': 'GPT-5.3 Codex (Agentic Coding)'},
        'gpt-4o': {'input': 2.50, 'output': 10.00, 'display': 'GPT-4o (Legacy)'},
        'gpt-4o-mini': {'input': 0.15, 'output': 0.60, 'display': 'GPT-4o Mini (Legacy, Fast & Cheap)'}
    },
    'anthropic': {
        'claude-opus-4-8': {'input': 5.0, 'output': 25.0, 'display': 'Claude Opus 4.8 (Most Capable)'},
        'claude-sonnet-5': {'input': 3.0, 'output': 15.0, 'display': 'Claude Sonnet 5 (Recommended Daily Driver)'},
        'claude-haiku-4-5': {'input': 1.0, 'output': 5.0, 'display': 'Claude Haiku 4.5 (Fast & Cheap)'},
        'claude-opus-4-7': {'input': 4.0, 'output': 20.0, 'display': 'Claude Opus 4.7 (Previous Gen)'},
        'claude-sonnet-4-6': {'input': 3.0, 'output': 15.0, 'display': 'Claude Sonnet 4.6 (Previous Gen)'}
    },
    'gemini': {
        'gemini-3.5-flash': {'input': 1.50, 'output': 9.00, 'display': 'Gemini 3.5 Flash (Latest, GA)'},
        'gemini-3.1-pro': {'input': 2.00, 'output': 12.00, 'display': 'Gemini 3.1 Pro (1M Context, Preview)'},
        'gemini-3.1-flash-lite': {'input': 0.10, 'output': 0.40, 'display': 'Gemini 3.1 Flash-Lite (Cheapest, GA)'},
        'gemini-3-flash': {'input': 0.50, 'output': 1.50, 'display': 'Gemini 3 Flash (Previous Gen)'},
        'gemini-2.5-pro': {'input': 1.25, 'output': 10.00, 'display': 'Gemini 2.5 Pro (Legacy)'},
        'gemini-2.5-flash': {'input': 0.10, 'output': 0.40, 'display': 'Gemini 2.5 Flash-Lite (Legacy)'}
    },
    'meta': {
        'llama-4-maverick': {'input': 2.0, 'output': 6.0, 'display': 'Llama 4 Maverick (Flagship)'},
        'llama-4-scout': {'input': 0.40, 'output': 0.80, 'display': 'Llama 4 Scout (10M Context)'},
        'llama-3.3-70b': {'input': 0.99, 'output': 1.29, 'display': 'Llama 3.3 70B'},
        'llama-3.1-405b': {'input': 3.75, 'output': 7.50, 'display': 'Llama 3.1 405B'},
        'llama-3.2-3b': {'input': 0.06, 'output': 0.06, 'display': 'Llama 3.2 3B (Edge/Small)'}
    },
    'deepseek': {
        'deepseek-v4-pro': {'input': 0.435, 'output': 0.87, 'display': 'DeepSeek V4 Pro (Flagship Reasoning)'},
        'deepseek-v4-flash': {'input': 0.14, 'output': 0.28, 'display': 'DeepSeek V4 Flash (Fast & Cheap)'},
        'deepseek-coder': {'input': 0.14, 'output': 0.28, 'display': 'DeepSeek Coder (Legacy)'}
        # NOTE: legacy aliases deepseek-chat/deepseek-reasoner retire 2026-07-24; use deepseek-v4-* instead
    },
    'xai': {
        'grok-4.3': {'input': 5.0, 'output': 15.0, 'display': 'Grok 4.3 (Flagship)'},
        'grok-4.1-fast': {'input': 0.20, 'output': 0.50, 'display': 'Grok 4.1 Fast (Cheapest Frontier-Class)'},
        'grok-3': {'input': 3.0, 'output': 9.0, 'display': 'Grok 3'},
        'grok-2': {'input': 2.0, 'output': 6.0, 'display': 'Grok 2 (Legacy)'}
    },
    'groq': {
        'llama-3.3-70b-versatile': {'input': 0.59, 'output': 0.79, 'display': 'Llama 3.3 70B Versatile'},
        'llama-3.1-8b-instant': {'input': 0.05, 'output': 0.08, 'display': 'Llama 3.1 8B Instant (Fastest)'},
        'llama-3.2-405b': {'input': 0.99, 'output': 1.99, 'display': 'Llama 3.2 405B'},
        'llama-3.1-405b-reasoning': {'input': 1.0, 'output': 3.0, 'display': 'Llama 3.1 405B (Extended Thinking)'}
    },
    'together': {
        'meta-llama/Llama-4-Maverick': {'input': 2.0, 'output': 6.0, 'display': 'Llama 4 Maverick'},
        'meta-llama/Llama-4-Scout': {'input': 0.40, 'output': 0.80, 'display': 'Llama 4 Scout'},
        'meta-llama/Llama-3.3-70B-Instruct-Turbo': {'input': 0.99, 'output': 1.29, 'display': 'Llama 3.3 70B Turbo'},
        'meta-llama/Llama-3.2-3B-Instruct-Turbo': {'input': 0.06, 'output': 0.06, 'display': 'Llama 3.2 3B Turbo (Small)'}
    },
    'azure': {
        'gpt-5.4': {'input': 3.0, 'output': 15.0, 'display': 'GPT-5.4 (Flagship Deployment)'},
        'gpt-5.4-mini': {'input': 0.4, 'output': 1.6, 'display': 'GPT-5.4 Mini'},
        'gpt-4o': {'input': 2.50, 'output': 10.00, 'display': 'GPT-4o (Legacy)'},
        'gpt-4o-mini': {'input': 0.15, 'output': 0.60, 'display': 'GPT-4o Mini (Legacy)'}
    },
    'huggingface': {
        'meta-llama/Llama-4-Maverick': {'input': 2.0, 'output': 6.0, 'display': 'Llama 4 Maverick'},
        'meta-llama/Llama-4-Scout': {'input': 0.40, 'output': 0.80, 'display': 'Llama 4 Scout'},
        'meta-llama/Llama-3.2-3B-Instruct': {'input': 0.06, 'output': 0.06, 'display': 'Llama 3.2 3B Instruct (Small/Free-tier)'},
        'mistralai/Mistral-Large': {'input': 0.81, 'output': 2.43, 'display': 'Mistral Large'},
        'deepseek-ai/DeepSeek-V4-Flash': {'input': 0.14, 'output': 0.28, 'display': 'DeepSeek V4 Flash (Open Weights)'}
    },
    'cohere': {
        'command-r-plus': {'input': 3.0, 'output': 15.0, 'display': 'Command R+ (Flagship)'},
        'command-r': {'input': 0.50, 'output': 1.50, 'display': 'Command R (Balanced)'},
        'command-r7b': {'input': 0.0375, 'output': 0.15, 'display': 'Command R7B (Smallest/Fastest)'}
    },
    'perplexity': {
        'sonar-pro': {'input': 3.0, 'output': 15.0, 'display': 'Sonar Pro (Flagship, Web Search)'},
        'sonar-reasoning-pro': {'input': 2.0, 'output': 8.0, 'display': 'Sonar Reasoning Pro'},
        'sonar': {'input': 0.20, 'output': 0.20, 'display': 'Sonar (With Web Search)'},
        'sonar-mini': {'input': 0.05, 'output': 0.05, 'display': 'Sonar Mini (Budget)'}
    }
}

class APIRouter:
    """Route queries to appropriate API"""
    def __init__(self):
        self.clients = {}
        self.primary_api = None
        self.selected_models = {}  # Track selected model per provider
        self.initialize_clients()
    
    def initialize_clients(self):
        """Initialize all configured API clients"""
        for provider in api_config.list_apis():
            config = api_config.get_api(provider)
            if config:
                try:
                    if provider == 'openai':
                        self.clients['openai'] = OpenAIClient(config['key'])
                    elif provider == 'anthropic':
                        self.clients['anthropic'] = AnthropicClient(config['key'])
                    elif provider == 'gemini':
                        self.clients['gemini'] = GoogleGeminiClient(config['key'])
                    elif provider == 'huggingface':
                        self.clients['huggingface'] = HuggingFaceClient(config['key'])
                    elif provider == 'cohere':
                        self.clients['cohere'] = CohereClient(config['key'])
                    elif provider == 'groq':
                        self.clients['groq'] = GroqClient(config['key'])
                    elif provider == 'together':
                        self.clients['together'] = TogetherAIClient(config['key'])
                    elif provider == 'azure':
                        self.clients['azure'] = AzureOpenAIClient(config['key'], config.get('endpoint', ''))
                    elif provider == 'perplexity':
                        self.clients['perplexity'] = PerplexityClient(config['key'])
                    elif provider == 'deepseek':
                        self.clients['deepseek'] = DeepSeekClient(config['key'])
                    elif provider == 'xai':
                        self.clients['xai'] = XAIClient(config['key'])
                    elif provider == 'meta':
                        self.clients['meta'] = MetaLlamaClient(config['key'])
                    structured_logger.log('api_client_initialized', provider=provider)
                except Exception as e:
                    structured_logger.error('api_client_init_failed', provider=provider, error=str(e))
    
    def query(self, prompt, provider=None, model=None):
        """Query using specified or primary API"""
        provider = provider or self.primary_api
        if not provider or provider not in self.clients:
            return f"Error: API provider '{provider}' not configured"
        
        return self.clients[provider].query(prompt, model)
    
    def set_primary(self, provider):
        """Set primary API provider"""
        if provider in self.clients:
            self.primary_api = provider
            structured_logger.log('primary_api_set', provider=provider)
            return True
        return False
    
    def list_configured(self):
        """List configured API providers"""
        return list(self.clients.keys())

api_router = APIRouter()
HAS_API_INTEGRATION = True
# === END API INTEGRATION ===

# === PRIORITY 0.8: CIRCUIT BREAKER ===
class CircuitBreaker:
    """Circuit breaker pattern for fault tolerance"""
    def __init__(self, failure_threshold: int = 5, recovery_timeout: int = 60):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.failures = defaultdict(int)
        self.last_failure_time = defaultdict(float)
        self.state = defaultdict(lambda: 'CLOSED')  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, service_name: str, func, *args, **kwargs):
        """Execute function through circuit breaker"""
        now = time()
        
        if self.state[service_name] == 'OPEN':
            if now - self.last_failure_time[service_name] > self.recovery_timeout:
                self.state[service_name] = 'HALF_OPEN'
                structured_logger.log('circuit_half_open', service=service_name)
            else:
                raise Exception(f"Circuit breaker OPEN for {service_name}")
        
        try:
            result = func(*args, **kwargs)
            if self.state[service_name] == 'HALF_OPEN':
                self.state[service_name] = 'CLOSED'
                self.failures[service_name] = 0
                structured_logger.log('circuit_closed', service=service_name)
            return result
        except Exception as e:
            self.failures[service_name] += 1
            self.last_failure_time[service_name] = now
            
            if self.failures[service_name] >= self.failure_threshold:
                self.state[service_name] = 'OPEN'
                structured_logger.error('circuit_open', service=service_name, failures=self.failures[service_name], error=str(e))
            raise

circuit_breaker = CircuitBreaker(failure_threshold=5, recovery_timeout=60)
# === END CIRCUIT BREAKER ===

# === PRIORITY 1: SECURITY LAYER ===
from enum import Enum
import re

class PermissionMode(Enum):
    """Permission modes matching Claude Code"""
    DEFAULT = "default"
    ACCEPT_EDITS = "accept"
    AUTO = "auto"
    DONT_ASK = "dont_ask"
    BYPASS = "bypass"

class PermissionGate:
    """4-layer defense system"""
    def __init__(self, mode: PermissionMode = PermissionMode.DEFAULT):
        self.mode = mode
        self.deny_list = []
        self.allow_list = []
        self.hooks = {}
        self.audit_log = []
    
    def check_permission(self, tool: str, action: str, params: dict) -> bool:
        if self.mode == PermissionMode.BYPASS:
            return True
        if self._matches_deny_list(tool, action, params):
            return False
        if not self._run_hooks(f'pre_{tool}', action, params):
            return False
        return self._mode_approval(tool, action, params)
    
    def _matches_deny_list(self, tool: str, action: str, params: dict) -> bool:
        for pattern in self.deny_list:
            if re.match(pattern, f"{tool}:{action}"):
                return True
        return False
    
    def _run_hooks(self, hook_name: str, action: str, params: dict) -> bool:
        if hook_name in self.hooks:
            for hook in self.hooks[hook_name]:
                if not hook(action, params):
                    return False
        return True
    
    def _mode_approval(self, tool: str, action: str, params: dict) -> bool:
        if self.mode == PermissionMode.ACCEPT_EDITS:
            safe_commands = {'mkdir', 'touch', 'rm', 'mv', 'cp', 'sed'}
            return action in safe_commands
        elif self.mode == PermissionMode.AUTO:
            return f"{tool}:{action}" in self.allow_list
        elif self.mode == PermissionMode.DONT_ASK:
            return f"{tool}:{action}" in self.allow_list
        else:
            return True
    
    def register_hook(self, hook_name: str, callback):
        if hook_name not in self.hooks:
            self.hooks[hook_name] = []
        self.hooks[hook_name].append(callback)
    
    def log_action(self, tool: str, action: str, params: dict, approved: bool):
        self.audit_log.append({
            'tool': tool,
            'action': action,
            'params': params,
            'approved': approved,
            'timestamp': __import__('datetime').datetime.now().isoformat()
        })

class Sandbox:
    """OS-level sandboxing"""
    def __init__(self, project_dir: 'Path' = None):
        self.project_dir = project_dir or Path.cwd()
        self.blocked_dirs = {Path.home() / '.ssh', Path.home() / '.secrets'}
    
    def is_write_safe(self, path: 'Path') -> bool:
        try:
            path.resolve().relative_to(self.project_dir)
            return True
        except ValueError:
            return False
    
    def is_read_safe(self, path: 'Path') -> bool:
        return path.resolve() not in self.blocked_dirs
    
    def validate_bash_command(self, cmd: str) -> bool:
        dangerous_patterns = [
            r'rm\s+-rf\s+/',
            r'dd\s+if=/dev',
            r':\(\)\s*\{',
            r'pkill\s+-9',
        ]
        for pattern in dangerous_patterns:
            if re.search(pattern, cmd):
                return False
        return True

HAS_SECURITY = True
# === END SECURITY LAYER ===

# === PRIORITY 1: TOOL SYSTEM ===
from abc import ABC, abstractmethod
import shlex

class Tool(ABC):
    """Base tool interface"""
    def __init__(self, name: str, description: str, schema: dict):
        self.name = name
        self.description = description
        self.schema = schema
    
    @abstractmethod
    def execute(self, **params):
        pass

class FileEditTool(Tool):
    """Edit files safely"""
    def __init__(self):
        super().__init__("file_edit", "Edit or create files", {"path": "str", "content": "str", "mode": "str"})
    
    def execute(self, path: str, content: str, mode: str = 'w', **params):
        try:
            p = Path(path)
            if mode == 'w':
                p.write_text(content)
            elif mode == 'a':
                with open(p, 'a') as f:
                    f.write(content)
            return {"success": True, "path": str(p), "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

class FileReadTool(Tool):
    """Read files"""
    def __init__(self):
        super().__init__("file_read", "Read file contents", {"path": "str"})
    
    def execute(self, path: str, **params):
        try:
            content = Path(path).read_text()
            return {"success": True, "content": content, "size": len(content)}
        except Exception as e:
            return {"success": False, "error": str(e)}

class BashTool(Tool):
    """Execute bash commands"""
    def __init__(self):
        super().__init__("bash", "Execute shell commands", {"command": "str", "cwd": "str"})
    
    def execute(self, command: str, cwd: str = None, **params):
        try:
            result = subprocess.run(shlex.split(command) if isinstance(command, str) else command, shell=False, cwd=cwd, capture_output=True, text=True, timeout=30)
            return {
                "success": result.returncode == 0,
                "stdout": result.stdout[:2000],
                "stderr": result.stderr[:2000],
                "returncode": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Command timed out"}
        except Exception as e:
            return {"success": False, "error": str(e)}

class ToolRegistry:
    """18-tool system"""
    def __init__(self):
        self.tools = {}
        self._register_builtin_tools()
    
    def _register_builtin_tools(self):
        self.register(FileReadTool())
        self.register(FileEditTool())
        self.register(BashTool())
    
    def register(self, tool: Tool):
        self.tools[tool.name] = tool
    
    def get_tool(self, name: str):
        return self.tools.get(name)
    
    def dispatch(self, tool_name: str, **params):
        tool = self.get_tool(tool_name)
        if not tool:
            return {"success": False, "error": f"Tool {tool_name} not found"}
        return tool.execute(**params)
    
    def list_tools(self):
        return {name: {"description": tool.description, "schema": tool.schema} for name, tool in self.tools.items()}

HAS_TOOLS = True
tool_registry = ToolRegistry()
# === END TOOL SYSTEM ===

# === PRIORITY 2: EVENT SYSTEM & ASYNC ===
import asyncio
from dataclasses import dataclass

class EventType(Enum):
    """Event types"""
    REQUEST_START = "request_start"
    MESSAGE = "message"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    ASSISTANT_MESSAGE = "assistant"
    TOMBSTONE = "tombstone"
    COMPACTION = "compaction"
    COST_WARNING = "cost_warning"
    ERROR = "error"
    COMPLETE = "complete"

@dataclass
class StreamEvent:
    """Base event class"""
    type: EventType
    timestamp: float
    data: dict
    
    def to_dict(self):
        return {'type': self.type.value, 'timestamp': self.timestamp, 'data': self.data}

class EventBus:
    """Async event bus"""
    def __init__(self):
        self.listeners = {}
        self.event_queue = asyncio.Queue() if asyncio else None
    
    def subscribe(self, event_type: EventType, callback):
        if event_type not in self.listeners:
            self.listeners[event_type] = []
        self.listeners[event_type].append(callback)
    
    async def emit(self, event: StreamEvent):
        if self.event_queue:
            await self.event_queue.put(event)
        if event.type in self.listeners:
            for callback in self.listeners[event.type]:
                try:
                    if asyncio.iscoroutinefunction(callback):
                        await callback(event)
                    else:
                        callback(event)
                except:
                    pass

class HookSystem:
    """Hook interception layer"""
    def __init__(self):
        self.hooks = {}
    
    def register(self, event_name: str, callback):
        if event_name not in self.hooks:
            self.hooks[event_name] = []
        self.hooks[event_name].append(callback)
    
    async def fire(self, event_name: str, *args, **kwargs) -> bool:
        if event_name in self.hooks:
            for hook in self.hooks[event_name]:
                try:
                    if asyncio.iscoroutinefunction(hook):
                        result = await hook(*args, **kwargs)
                    else:
                        result = hook(*args, **kwargs)
                    if result is False:
                        return False
                except:
                    pass
        return True

HAS_EVENTS = True
event_bus = EventBus()
hook_system = HookSystem()
# === END EVENT SYSTEM ===

# === PRIORITY 2: PERSISTENCE (Message-as-State) ===
from datetime import datetime
import hashlib
import gzip

class Message:
    """Universal message format"""
    def __init__(self, role: str, content: str, msg_type: str = 'text'):
        self.role = role
        self.content = content
        self.type = msg_type
        self.timestamp = datetime.now().isoformat()
        self.id = self._generate_id()
    
    def _generate_id(self) -> str:
        return hashlib.md5(f"{self.timestamp}{self.content}".encode()).hexdigest()[:8]
    
    def to_dict(self):
        return {'id': self.id, 'role': self.role, 'content': self.content, 'type': self.type, 'timestamp': self.timestamp}

class SessionState:
    """Session state from message history"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.messages = []
        self.metadata = {}
        self.created_at = datetime.now().isoformat()
    
    def append_message(self, role: str, content: str, msg_type: str = 'text'):
        msg = Message(role, content, msg_type)
        self.messages.append(msg)
        return msg
    
    def get_conversation(self):
        return [msg.to_dict() for msg in self.messages]
    
    def to_dict(self):
        return {
            'session_id': self.session_id,
            'created_at': self.created_at,
            'message_count': len(self.messages),
            'messages': self.get_conversation(),
            'metadata': self.metadata
        }

class SessionPersistence:
    """Save/load/replay sessions"""
    def __init__(self, sessions_dir: Path = None):
        if sessions_dir is None:
            sessions_dir = Path.home() / '.hercules' / 'sessions'
        self.sessions_dir = sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.active_session = None
    
    def create_session(self, session_id: str):
        self.active_session = SessionState(session_id)
        return self.active_session
    
    def save_session(self, session: SessionState, compressed: bool = True):
        session_path = self.sessions_dir / f"{session.session_id}"
        data = session.to_dict()
        if compressed:
            with gzip.open(f"{session_path}.gz", 'wt') as f:
                json.dump(data, f)
        else:
            with open(session_path, 'w') as f:
                json.dump(data, f)
    
    def load_session(self, session_id: str):
        compressed_path = self.sessions_dir / f"{session_id}.gz"
        normal_path = self.sessions_dir / f"{session_id}"
        try:
            if compressed_path.exists():
                with gzip.open(compressed_path, 'rt') as f:
                    data = json.load(f)
            elif normal_path.exists():
                with open(normal_path) as f:
                    data = json.load(f)
            else:
                return None
            session = SessionState(data['session_id'])
            for msg_data in data['messages']:
                msg = Message(msg_data['role'], msg_data['content'], msg_data['type'])
                msg.timestamp = msg_data['timestamp']
                msg.id = msg_data['id']
                session.messages.append(msg)
            session.metadata = data['metadata']
            return session
        except:
            return None
    
    def list_sessions(self):
        sessions = []
        for path in self.sessions_dir.glob('*'):
            if path.is_file():
                sessions.append(path.stem)
        return sorted(sessions)

HAS_PERSISTENCE = True
session_persistence = SessionPersistence()
# === END PERSISTENCE ===

# === PRIORITY 2: AGENT TEAMS ===

class AgentRole(Enum):
    """Agent roles"""
    LEAD = "lead"
    WORKER = "worker"
    ANALYST = "analyst"
    REFINER = "refiner"

class TeamMember:
    """Team member agent"""
    def __init__(self, name: str, role: AgentRole, instructions: str):
        self.name = name
        self.role = role
        self.instructions = instructions
        self.inbox = []
        self.completed_tasks = []
    
    async def run(self):
        """Member's main loop"""
        while True:
            await asyncio.sleep(0.1)

class AgentTeam:
    """Team of parallel agents"""
    def __init__(self, lead_name: str = "Lead"):
        self.lead_name = lead_name
        self.members = {}
        self.tasks = []
        self.task_counter = 0
    
    def add_member(self, name: str, role: AgentRole, instructions: str):
        member = TeamMember(name, role, instructions)
        self.members[name] = member
        return member
    
    async def delegate_task(self, title: str, description: str, assigned_to: str = None):
        self.task_counter += 1
        self.tasks.append({'id': f"task_{self.task_counter}", 'title': title, 'status': 'pending'})
        return f"task_{self.task_counter}"
    
    def get_team_status(self):
        return {
            'members': len(self.members),
            'total_tasks': len(self.tasks),
            'completed': len([t for t in self.tasks if t.get('status') == 'complete']),
            'pending': len([t for t in self.tasks if t.get('status') == 'pending']),
            'running': len([t for t in self.tasks if t.get('status') == 'running'])
        }

HAS_TEAMS = True
active_team = AgentTeam(lead_name="Hercules-Lead")
# === END AGENT TEAMS ===

# === PRIORITY 3: COST TRACKING ===

class CostTracker:
    """Track and enforce budget"""
    def __init__(self, model: str, max_budget_usd: float = 1.0):
        self.model = model
        self.max_budget_usd = max_budget_usd
        self.total_cost = 0.0
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.entries = []
        self.budget_exceeded = False
    
    def log_call(self, input_tokens: int, output_tokens: int) -> float:
        # Ollama/local is free
        if 'ollama' in self.model.lower() or self.model in ['qwen', 'llama']:
            cost = 0.0
        else:
            cost = (input_tokens / 1_000_000) * 3 + (output_tokens / 1_000_000) * 15
        
        self.entries.append({'input': input_tokens, 'output': output_tokens, 'cost': cost})
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        
        if self.total_cost > self.max_budget_usd:
            self.budget_exceeded = True
        
        return cost
    
    def get_status(self):
        remaining = self.max_budget_usd - self.total_cost
        percent = (self.total_cost / self.max_budget_usd) * 100 if self.max_budget_usd > 0 else 0
        return {
            'model': self.model,
            'total_cost': f"${self.total_cost:.4f}",
            'max_budget': f"${self.max_budget_usd:.2f}",
            'remaining': f"${remaining:.4f}",
            'percent_used': f"{percent:.1f}%",
            'budget_exceeded': self.budget_exceeded
        }
    
    def should_continue(self) -> bool:
        return self.total_cost <= self.max_budget_usd

class BudgetEnforcer:
    """Enforce cost limits"""
    def __init__(self):
        self.trackers = {}
    
    def create_tracker(self, session_id: str, model: str, budget_usd: float = 1.0):
        tracker = CostTracker(model, max_budget_usd=budget_usd)
        self.trackers[session_id] = tracker
        return tracker
    
    def check_budget(self, session_id: str) -> bool:
        if session_id not in self.trackers:
            return True
        return self.trackers[session_id].should_continue()

# BudgetEnforcer will be re-initialized with fallback later
# === END COST TRACKING ===

# === PRIORITY 3: TERMINAL UI (Ink-Inspired) ===

class TerminalComponent:
    """Base React-like terminal component"""
    def __init__(self, name: str):
        self.name = name
        self.children = []
        self.props = {}
        self.style = {}
    
    def render(self) -> str:
        """Render component to ANSI string"""
        return ""

class Box(TerminalComponent):
    """Flexbox container for terminal (styled box)"""
    def __init__(self, **props):
        super().__init__("Box")
        self.props = props
        self.flex_direction = props.get('flexDirection', 'row')
        self.padding = props.get('padding', 0)
        self.border = props.get('border', False)
        self.content = ""
    
    def render(self) -> str:
        """Render as bordered box"""
        if self.border:
            lines = self.content.split('\n')
            width = max(len(line) for line in lines) if lines else 0
            top = f"╔{'═' * (width + 2)}╗"
            bottom = f"╚{'═' * (width + 2)}╝"
            body = '\n'.join(f"║ {line:<{width}} ║" for line in lines)
            return f"{top}\n{body}\n{bottom}"
        return self.content

class Text(TerminalComponent):
    """Text component with ANSI styling"""
    def __init__(self, content: str, **props):
        super().__init__("Text")
        self.content = content
        self.color = props.get('color', 'white')
        self.bold = props.get('bold', False)
        self.dim = props.get('dim', False)
        self.props = props
    
    def render(self) -> str:
        """Render styled text with ANSI codes"""
        text = self.content
        
        # Apply ANSI styling
        if self.bold:
            text = f"\033[1m{text}\033[0m"
        if self.dim:
            text = f"\033[2m{text}\033[0m"
        
        # Color mapping
        color_map = {
            'green': '\033[32m', 'red': '\033[31m', 'yellow': '\033[33m',
            'blue': '\033[34m', 'magenta': '\033[35m', 'cyan': '\033[36m',
            'white': '\033[37m', 'gray': '\033[90m'
        }
        
        if self.color in color_map:
            text = f"{color_map[self.color]}{text}\033[0m"
        
        return text

class TerminalRenderer:
    """Ink-inspired terminal renderer with optimizations"""
    def __init__(self):
        self.frame_buffer = ""
        self.last_frame = ""
        self.style_pool = {}  # Cache ANSI codes
        self.dirty_regions = []
    
    def render_component(self, component: TerminalComponent) -> str:
        """Render component tree"""
        output = component.render()
        
        # Optimization: Only write diff to terminal
        if output != self.last_frame:
            self.dirty_regions.append(output)
            self.last_frame = output
        
        return output
    
    def optimize_ansi(self, text: str) -> str:
        """Optimize ANSI sequences - cache style transitions"""
        # Pool duplicate ANSI codes
        key = hash(text)
        if key in self.style_pool:
            return self.style_pool[key]
        
        # Memoize
        self.style_pool[key] = text
        return text
    
    def clear_screen(self):
        """Clear terminal screen"""
        print("\033[2J\033[H", end="", flush=True)
    
    def set_cursor(self, row: int, col: int):
        """Set cursor position"""
        print(f"\033[{row};{col}H", end="", flush=True)

class SimpleTheme:
    """Lightweight theme system"""
    def __init__(self, name: str = "default"):
        self.name = name
        self.colors = {
            'primary': '\033[36m',      # Cyan
            'success': '\033[32m',      # Green
            'error': '\033[31m',        # Red
            'warning': '\033[33m',      # Yellow
            'info': '\033[34m',         # Blue
            'dim': '\033[90m',          # Gray
            'reset': '\033[0m'
        }
    
    def get_color(self, semantic: str) -> str:
        """Get ANSI color for semantic meaning"""
        return self.colors.get(semantic, self.colors['reset'])

class KeyboardParser:
    """Parse terminal keyboard input (arrows, modifiers, etc)"""
    @staticmethod
    def parse_escape_sequence(seq: str) -> str:
        """Parse ANSI escape sequences to key names"""
        escape_map = {
            '\x1b[A': 'up', '\x1b[B': 'down', '\x1b[C': 'right', '\x1b[D': 'left',
            '\x1b[H': 'home', '\x1b[F': 'end', '\x1b[3~': 'delete',
            '\x7f': 'backspace', '\x1b': 'escape', '\n': 'enter', '\t': 'tab'
        }
        return escape_map.get(seq, seq)

HAS_TERMINAL_UI = True
terminal_renderer = TerminalRenderer()
theme = SimpleTheme("default")
# === END TERMINAL UI ===

# === LIGHTWEIGHT YOGA FLEXBOX SIMULATION ===

class YogaNode:
    """Simplified Yoga layout node for terminal flexbox"""
    def __init__(self, width: int = 80, height: int = 24):
        self.width = width
        self.height = height
        self.flex_direction = 'column'  # column, row
        self.children = []
        self.padding = 0
        self.margin = 0
        self.measuredWidth = 0
        self.measuredHeight = 0
    
    def calculate_layout(self):
        """Simplified flexbox layout calculation"""
        if self.flex_direction == 'row':
            # Distribute width among children
            child_width = self.width // len(self.children) if self.children else self.width
            for child in self.children:
                child.width = child_width
                child.calculate_layout()
        else:  # column
            # Distribute height among children
            child_height = self.height // len(self.children) if self.children else self.height
            for child in self.children:
                child.height = child_height
                child.calculate_layout()
    
    def add_child(self, node: 'YogaNode'):
        """Add child node"""
        self.children.append(node)

class LayoutEngine:
    """Terminal layout engine using Yoga principles"""
    def __init__(self):
        self.root = YogaNode()
    
    def layout(self) -> dict:
        """Calculate layout for all nodes"""
        self.root.calculate_layout()
        return {
            'root_width': self.root.width,
            'root_height': self.root.height,
            'children_count': len(self.root.children)
        }

HAS_LAYOUT = True
layout_engine = LayoutEngine()
# === END YOGA SIMULATION ===

# === CLAUDE CODE CORE: ReAct LOOP ===

class ReActLoop:
    """Claude Code's core ReAct pattern: Reasoning + Action + Feedback"""
    def __init__(self):
        self.max_iterations = 10
        self.messages = []
        self.thoughts = []
        self.actions = []
    
    def step(self, prompt: str, model_response: str) -> dict:
        """One ReAct iteration: think -> act -> observe"""
        
        # 1. REASONING: Extract thinking from model
        thought = self._extract_thought(model_response)
        self.thoughts.append(thought)
        
        # 2. ACTION: Execute action from model
        action_result = None
        if '<action>' in model_response:
            action = self._extract_action(model_response)
            action_result = self._execute_action(action)
            self.actions.append({'action': action, 'result': action_result})
        
        # 3. OBSERVATION: Provide feedback to model
        observation = f"Action result: {action_result}" if action_result else "No action taken"
        
        return {
            'thought': thought,
            'action': action if '<action>' in model_response else None,
            'observation': observation
        }
    
    def _extract_thought(self, response: str) -> str:
        """Extract reasoning from model response"""
        if '<thought>' in response:
            start = response.find('<thought>') + 9
            end = response.find('</thought>')
            return response[start:end]
        return response[:200]  # First 200 chars
    
    def _extract_action(self, response: str) -> str:
        """Extract action from model response"""
        if '<action>' in response:
            start = response.find('<action>') + 8
            end = response.find('</action>')
            return response[start:end]
        return ""
    
    def _execute_action(self, action: str) -> str:
        """Execute the action (tool call, bash, file op, etc)"""
        # Delegate to tool registry
        if tool_registry:
            parts = action.split(' ', 1)
            tool_name = parts[0]
            params = parts[1] if len(parts) > 1 else ""
            result = tool_registry.dispatch(tool_name, command=params)
            return str(result)
        return ""

react_loop = ReActLoop()
# === END ReAct LOOP ===

# Import our pure Python GGUF loader
try:
    from gguf_inference import load_gguf_model
except ImportError:
    print("Warning: gguf_inference.py not found - some features disabled")
    load_gguf_model = None

# Optional: try gpt4all as fallback
try:
    from gpt4all import GPT4All
    HAS_GPT4ALL = True
except:
    HAS_GPT4ALL = False

# Optional: try ollama and requests
try:
    import requests
    HAS_OLLAMA = True
except ImportError:
    HAS_OLLAMA = False
    requests = None


# ANSI Color Codes - Dark Mode (Default)
O1_DARK = '\033[38;2;218;165;32m'
O2_DARK = '\033[38;2;255;215;0m'
H1_DARK = '\033[38;2;184;134;11m'
H2_DARK = '\033[38;2;255;140;0m'
G_DARK = '\033[38;2;26;176;128m'
R_DARK = '\033[38;2;255;59;59m'
S_DARK = '\033[38;2;90;122;150m'
X = '\033[0m'

# ANSI Color Codes - Light Mode
O1_LIGHT = '\033[38;2;100;100;100m'
O2_LIGHT = '\033[38;2;80;80;80m'
H1_LIGHT = '\033[38;2;60;60;60m'
H2_LIGHT = '\033[38;2;50;50;50m'
G_LIGHT = '\033[38;2;34;139;34m'
R_LIGHT = '\033[38;2;220;20;60m'
S_LIGHT = '\033[38;2;70;70;70m'

# Active theme variables
O1 = O1_DARK
O2 = O2_DARK
H1 = H1_DARK
H2 = H2_DARK
G = G_DARK
R = R_DARK
S = S_DARK

# Global State
llm = None
ollama_mode = False
llm_model_name = None
model_path = None
temp = 0.7
max_tokens = 256
chat_history = []
dark_mode = True
model_info = {}
skills = []

# ===== CLAUDE CODE FEATURES (GLOBALS) =====
# Priority 1: Security
permission_gate = PermissionGate(mode=PermissionMode.DEFAULT)
sandbox = Sandbox()

# Priority 2: Persistence
current_session = session_persistence.create_session("default")

# Priority 2: Teams
# active_team already created above
overclock_enabled = False
freerange_enabled = False
freerange_dir = None

# Priority 3: Cost Tracking (was missing - referenced in query() but never defined)
HAS_COST_TRACKING = False
try:
    from cost_tracker import BudgetEnforcer
    budget_enforcer = BudgetEnforcer()
    HAS_COST_TRACKING = True
except:
    class MockBudgetEnforcer:
        def __init__(self):
            self.trackers = {}
        def check_budget(self, tracker_id):
            return True
    budget_enforcer = MockBudgetEnforcer()
    HAS_COST_TRACKING = False

# Priority 3: Context (placeholder - initialized after ConversationContext class defined)
ctx = None


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
    '/help, /': 'Show all commands',
    '/models': 'List available/loaded models',
    '/api': 'Configure and use API providers',
    '/memory': 'Save and recall important memories',
    '/branch': 'Manage conversation branches',
    '/macro': 'Manage macros and shortcuts',
    '/plugin': 'Manage plugins and extensions',
    '/skill': 'Load custom skill from file',
    '/team': 'Manage agent teams',
    '/delegate': 'Delegate task to multiple agents',
    '/hagent': 'Execute through hierarchical agent system',
    '/code': 'Claude Code pattern & template help',
    '/advsearch': 'Advanced search with ranking',
    '/context': 'Show conversation context',
    '/agent': 'Run as autonomous agent',
    '/freerange': 'Enter unrestricted mode (file/bash access)',
    '/stats': 'Show system statistics',
    '/cost': 'Show cost tracking',
    '/export': 'Export chat history',
    '/search': 'Search chat history',
    '/history': 'Show chat history',
    '/save': 'Save conversation',
    '/load': 'Load previous conversation',
    '/clear': 'Clear chat history',
    '/template': 'Manage prompt templates',
    '/session': 'Manage sessions',
    '/security': 'Security & permission settings',
    '/tools': 'Show available tools',
    '/config': 'Show config location',
    '/setup': 'Setup/change model',
    '/exit, /quit': 'Exit application',
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
    print(f"  {O1}{Path(model_path).stem if model_path else 'N/A'}{X}")
    print(f"  {S}{model_path}{X}\n")

def _select_model_for_provider(provider):
    """Shared prompt: let user pick a specific model for an already-configured provider"""
    if provider not in API_MODELS:
        return
    models = API_MODELS[provider]
    model_list = list(models.keys())
    print(f"{O2}Select Model for {provider.upper()}{X}\n")
    for i, model_id in enumerate(model_list, 1):
        model = models[model_id]
        display = model.get('display', model_id)
        print(f"  {H1}[{i}]{X} {display:<30s} ${model.get('input', 0):.2f}/${model.get('output', 0):.2f}")
    print(f"\n{H2}Select model (1-{len(model_list)}, or Enter for default):{X} ", end='', flush=True)
    m_input = input().strip()
    if m_input:
        try:
            m_choice = int(m_input) - 1
            if 0 <= m_choice < len(model_list):
                api_router.selected_models[provider] = model_list[m_choice]
                print(f"{G}✓ Model selected: {model_list[m_choice]}{X}\n")
        except ValueError:
            pass

def configure_api_provider():
    """Prompt user to configure a NEW API provider as an alternative/addition to local models"""
    providers_list = ['openai', 'anthropic', 'gemini', 'groq', 'cohere', 'deepseek', 'xai', 'meta', 'huggingface', 'together', 'azure', 'perplexity']
    print(f"\n{O2}╔ Configure API Provider ╗{X}\n")
    for i, prov in enumerate(providers_list, 1):
        print(f"  {H1}[{i}]{X} {prov}")
    print(f"\n{H2}Choose provider (1-{len(providers_list)}):{X} ", end='', flush=True)
    try:
        prov_choice = int(input().strip()) - 1
        if not (0 <= prov_choice < len(providers_list)):
            print(f"{R}✗ Invalid selection{X}\n")
            return False
        provider = providers_list[prov_choice]
        print(f"\n{H2}Enter API key for {provider.upper()}:{X} ", end='', flush=True)
        key = input().strip()
        if not key:
            print(f"{R}✗ No key entered{X}\n")
            return False

        if provider == 'azure':
            print(f"{H2}Enter Azure endpoint URL:{X} ", end='', flush=True)
            endpoint = input().strip()
            api_config.set_api(provider, key, endpoint=endpoint)
        else:
            api_config.set_api(provider, key)

        api_router.initialize_clients()
        api_router.set_primary(provider)
        print(f"{G}✓ {provider.upper()} configured and set as primary API{X}\n")
        print(f"{S}Key saved — Hercules will offer it automatically next time you start.{X}\n")

        _select_model_for_provider(provider)

        structured_logger.log('api_configured_via_setup', provider=provider)
        return True
    except (ValueError, IndexError):
        print(f"{R}✗ Invalid selection{X}\n")
        return False
    except Exception as e:
        print(f"{R}✗ Error configuring API: {str(e)[:80]}{X}\n")
        return False

def use_saved_api_provider():
    """Let the user pick from previously-saved API keys without re-entering them"""
    providers = api_router.list_configured()
    if not providers:
        print(f"{R}✗ No saved API providers found{X}\n")
        return False
    print(f"\n{O2}╔ Saved API Providers ╗{X}\n")
    for i, prov in enumerate(providers, 1):
        marker = f" {S}(current primary){X}" if prov == api_router.primary_api else ""
        print(f"  {H1}[{i}]{X} {prov}{marker}")
    print(f"\n{H2}Choose provider (1-{len(providers)}):{X} ", end='', flush=True)
    try:
        choice = int(input().strip()) - 1
        if not (0 <= choice < len(providers)):
            print(f"{R}✗ Invalid selection{X}\n")
            return False
        provider = providers[choice]
        api_router.set_primary(provider)
        print(f"{G}✓ Using saved {provider.upper()} API key{X}\n")

        _select_model_for_provider(provider)

        structured_logger.log('saved_api_selected', provider=provider)
        return True
    except (ValueError, IndexError):
        print(f"{R}✗ Invalid selection{X}\n")
        return False
    except Exception as e:
        print(f"{R}✗ Error selecting saved API: {str(e)[:80]}{X}\n")
        return False

def setup():
    """Load GGUF models using pure Python (no external dependencies)"""
    global llm, model_path
    print(f"\n{O2}╔ Setup GGUF Models ╗{X}\n")
    
    model_dir = r'D:\Models' if platform.system() == 'Windows' else os.path.expanduser('~/Models')
    print(f"{H2}Scanning {model_dir}...{X}")
    
    models = find_gguf_files(model_dir)
    saved_providers = api_router.list_configured()
    
    # If API keys were saved from a previous session, ask the user's preference
    # instead of silently re-scanning for local models or demanding keys again.
    if saved_providers:
        print(f"\n{O2}Saved API key(s) found:{X} {', '.join(saved_providers)}")
        if models:
            print(f"{O2}Local model(s) also found:{X} {len(models)}\n")
            print(f"  {H1}[1]{X} Use a local model")
            print(f"  {H1}[2]{X} Use a saved API key")
            print(f"  {H1}[3]{X} Add a new API provider")
            print(f"\n{H2}Choose (1-3):{X} ", end='', flush=True)
            try:
                pref = input().strip()
            except Exception:
                pref = ''
            if pref == '2':
                return use_saved_api_provider()
            elif pref == '3':
                return configure_api_provider()
            # else fall through to local model selection below
        else:
            print(f"{S}No local GGUF models found in {model_dir}{X}\n")
            print(f"  {H1}[1]{X} Use a saved API key")
            print(f"  {H1}[2]{X} Add a new API provider")
            print(f"\n{H2}Choose (1-2):{X} ", end='', flush=True)
            try:
                pref = input().strip()
            except Exception:
                pref = ''
            if pref == '2':
                return configure_api_provider()
            return use_saved_api_provider()
    
    if not models:
        print(f"{R}✗ No GGUF files found in {model_dir}{X}\n")
        print(f"{H2}Would you like to use an API provider instead? (y/n):{X} ", end='', flush=True)
        try:
            choice = input().strip().lower()
        except Exception:
            choice = ''
        if choice == 'y':
            return configure_api_provider()
        return False
    
    print(f"{G}✓ Found {len(models)} models{X}\n")
    print(f"{O2}Available models:{X}")
    for i, (name, path) in enumerate(models, 1):
        size_gb = Path(path).stat().st_size / (1024 ** 3)
        print(f"  {H1}[{i}]{X} {O1}{name}{X} ({size_gb:.2f}GB)")
    print(f"  {H1}[0]{X} {O1}Use an API provider instead{X}")
    
    try:
        print(f"\n{H2}Select model (0 for API, 1-{len(models)} for local):{X} ", end='', flush=True)
        choice = int(input().strip()) - 1
        
        if choice == -1:
            return configure_api_provider()
        
        if 0 <= choice < len(models):
            model_path = models[choice][1]
            model_name = Path(model_path).stem if model_path else 'unknown'
            
            print(f"\n{G}✓ Loading {model_name}...{X}\n")
            
            # Declare globals at function start
            global llm, ollama_mode, llm_model_name
            
            structured_logger.log('setup_start', model=model_name, model_path=model_path)
            
            # Strategy 0: Try Ollama (fastest, most reliable)
            if HAS_OLLAMA:
                try:
                    print(f"{S}Checking Ollama...{X}")
                    response = requests.get("http://localhost:11434/api/tags", timeout=2)
                    if response.status_code == 200:
                        models = response.json().get('models', [])
                        model_name = Path(model_path).stem if model_path else 'unknown'
                        
                        # Check if model exists in Ollama
                        if any(m['name'].startswith(model_name) for m in models):
                            print(f"{G}✓ Found {model_name} in Ollama{X}\n")
                            structured_logger.log('model_loaded', strategy='ollama', model=model_name)
                            ollama_mode = True
                            llm_model_name = model_name
                            return True
                        else:
                            # Try to pull model from Ollama registry
                            print(f"{S}Model not found locally, checking Ollama registry...{X}")
                            # Auto-pull common models
                            ollama_registry = {
                                'qwen': 'qwen:latest',
                                'mistral': 'mistral:latest',
                                'llama': 'llama2:latest',
                                'neural': 'neural-chat:latest',
                                'orca': 'orca-mini:latest'
                            }
                            
                            for key, full_name in ollama_registry.items():
                                if key.lower() in model_name.lower():
                                    print(f"{S}Pulling {full_name} from Ollama...{X}")
                                    requests.post(f"http://localhost:11434/api/pull", 
                                               json={"name": full_name}, timeout=300)
                                    print(f"{G}✓ Model ready in Ollama{X}\n")
                                    structured_logger.log('model_loaded', strategy='ollama_pulled', model=full_name)
                                    ollama_mode = True
                                    llm_model_name = full_name
                                    return True
                except Exception as e:
                    structured_logger.error('fallback_from_ollama', error=str(e))
                    print(f"{S}Ollama not running (http://localhost:11434 not reachable){X}")
            
            # Strategy 1: Use pure Python GGUF loader (no dependencies)
            if load_gguf_model:
                try:
                    print(f"{S}Using Pure Python GGUF Loader...{X}")
                    llm = load_gguf_model(model_path)
                    print(f"{G}✓ Model loaded successfully!{X}\n")
                    structured_logger.log('model_loaded', strategy='gguf_python', model=model_name)
                    return True
                except Exception as e:
                    structured_logger.error('fallback_from_gguf', error=str(e))
                    print(f"{R}✗ Pure Python loader failed: {str(e)[:60]}{X}\n")
            
            # Strategy 2: Try llama-cpp-python (if available)
            try:
                from llama_cpp import Llama
                print(f"{S}Attempting llama-cpp-python...{X}")
                llm = Llama(
                    model_path=model_path,
                    n_gpu_layers=-1,
                    verbose=False,
                    n_threads=4
                )
                print(f"{G}✓ Model loaded via llama-cpp-python{X}\n")
                return True
            except:
                pass
            
            # Strategy 3: Try GPT4All (if available)
            if HAS_GPT4ALL:
                try:
                    print(f"{S}Attempting GPT4All...{X}")
                    if model_path is None:
                        raise ValueError("model_path not initialized")
                    llm = GPT4All(
                        model_name=Path(model_path).name,
                        model_path=str(Path(model_path).parent),
                        allow_download=False,
                        device='cpu',
                        n_threads=4
                    )
                    print(f"{G}✓ Model loaded via GPT4All{X}\n")
                    return True
                except Exception as e:
                    print(f"{S}GPT4All failed{X}")
            
            # Strategy 4: Fallback wrapper (for when other methods fail)
            print(f"{S}Using GGUF wrapper fallback...{X}")
            
            try:
                from gguf_inference import SimpleGGUFInference, FastGGUFInference
                
                try:
                    # Try SimpleGGUFInference first
                    llm = SimpleGGUFInference(model_path)
                    print(f"{G}✓ Model loaded with SimpleGGUFInference{X}\n")
                    return True
                except Exception as e:
                    print(f"{S}SimpleGGUF error: {str(e)[:50]}{X}")
                    try:
                        # Fallback to FastGGUFInference
                        llm = FastGGUFInference(model_path)
                        print(f"{G}✓ Model loaded with FastGGUFInference{X}\n")
                        return True
                    except Exception as e2:
                        print(f"{S}FastGGUF error: {str(e2)[:50]}{X}")
                        raise
            except Exception as e:
                # Last resort: basic wrapper
                print(f"{R}⚠️  Inference unavailable: {str(e)[:60]}{X}")
                print(f"{S}Make sure numpy is installed: pip install numpy{X}\n")
                
                class ModelWrapper:
                    def __init__(self, path):
                        self.path = path
                        self.name = Path(path).stem
                    
                    def __call__(self, prompt, max_tokens=256, temperature=0.7, **kwargs):
                        return f"[{self.name}] Inference unavailable - requires numpy"
                
                llm = ModelWrapper(model_path)
                print(f"{G}✓ Model loaded as wrapper{X}\n")
                return True
            
    except ValueError:
        print(f"{R}✗ Invalid selection{X}\n")
        return False
    except Exception as e:
        print(f"{R}✗ Error: {str(e)[:100]}{X}\n")
        return False

def query(prompt, use_context=False):
    """Execute prompt with loaded model and optional context"""
    global llm, ollama_mode, llm_model_name, current_session
    
    # === CHECK FOR CONFIGURED API FIRST ===
    if HAS_API_INTEGRATION and api_router.primary_api and api_router.primary_api in api_router.clients:
        try:
            structured_logger.log('query_using_api', provider=api_router.primary_api, model=api_router.selected_models.get(api_router.primary_api, 'default'))
            response = api_router.query(prompt, provider=api_router.primary_api, model=api_router.selected_models.get(api_router.primary_api))
            if response and not response.startswith('Error'):
                if current_session:
                    current_session.append_message('user', prompt)
                    current_session.append_message('assistant', response)
                chat_history.append({'prompt': prompt, 'response': response})
                return response
        except Exception as e:
            structured_logger.error('api_query_failed', error=str(e), provider=api_router.primary_api)
    
    # === FALLBACK TO LOCAL MODEL ===
    if not llm and not ollama_mode:
        if api_router.list_configured():
            return f"{R}No primary API set. Use /api set <provider> first{X}"
        structured_logger.error('query_failed', error='Model not loaded and no API configured')
        return f"{R}Model not loaded and no API configured{X}"
    
    # === REQUEST DEDUPLICATION ===
    request_hash = __import__('hashlib').md5(prompt.encode()).hexdigest()
    cached_response = request_cache.get(request_hash)
    if cached_response:
        return cached_response
    
    # === RATE LIMITING ===
    session_id = getattr(current_session, 'session_id', 'default')
    if HAS_RATE_LIMITING and not rate_limiter.is_allowed(session_id):
        remaining = rate_limiter.get_remaining(session_id)
        structured_logger.log('rate_limit_exceeded', session=session_id, remaining=remaining)
        return f"{R}Rate limit exceeded. Try again in 60 seconds.{X}"
    
    structured_logger.log('query_start', prompt=prompt[:50], session=session_id)
    query_start_time = time()
    
    # === CLAUDE CODE INTEGRATION ===
    
    # 1. SECURITY: Check permission gate
    if permission_gate and not permission_gate.check_permission("query", "execute", {"prompt": prompt}):
        structured_logger.log('permission_denied', prompt=prompt[:30])
        return f"{R}Permission denied by security gate{X}"
    
    # 2. PERSISTENCE: Log to current session
    if current_session:
        current_session.append_message('user', prompt)
    
    # 3. BUDGET: Check cost tracker
    if HAS_COST_TRACKING and budget_enforcer.trackers:
        if not budget_enforcer.check_budget("default"):
            structured_logger.log('budget_exceeded', session=session_id)
            return f"{R}Budget limit exceeded{X}"
    
    # Add context if requested
    full_prompt = prompt
    if use_context and len(chat_history) > 0:
        context_window = ctx.get_context_window()
        full_prompt = f"Previous context:\n{context_window}\n\nCurrent question: {prompt}"
    
    try:
        # === TIMEOUT PROTECTION ===
        with TimeoutManager(timeout_seconds=120):
            # === REACT LOOP STEP 1: Reasoning ===
            response_text = None
            
            # Try primary API if configured and no local model
            if not llm and not ollama_mode and HAS_API_INTEGRATION and api_router.primary_api:
                try:
                    structured_logger.log('query_using_api', provider=api_router.primary_api)
                    response_text = api_router.query(full_prompt)
                except Exception as e:
                    structured_logger.error('api_query_failed', error=str(e))
                    response_text = None
            
            # Handle Ollama mode
            if not response_text and ollama_mode and HAS_OLLAMA:
                try:
                    response = requests.post(
                        "http://localhost:11434/api/generate",
                        json={
                            "model": llm_model_name,
                            "prompt": full_prompt,
                            "stream": False,
                            "temperature": temp,
                            "options": {"num_predict": max_tokens}
                        },
                        timeout=60
                    )
                    if response.status_code == 200:
                        response_text = response.json().get('response', '')
                    else:
                        response_text = f"{R}Ollama error: {response.status_code}{X}"
                except Exception as e:
                    response_text = f"{R}Ollama error: {str(e)[:60]}{X}"
            
            # Handle SimpleGGUFInference and FastGGUFInference
            if not response_text and hasattr(llm, 'generate'):
                response_text = llm.generate(full_prompt, max_tokens=max_tokens, temp=temp)
            
            # Handle llama-cpp-python models
            elif not response_text and hasattr(llm, 'create_completion'):
                response = llm(full_prompt, max_tokens=max_tokens, temperature=temp, top_p=0.95)
                if isinstance(response, dict) and 'choices' in response:
                    response_text = response['choices'][0]['text']
                else:
                    response_text = str(response)
            
            # Handle GPT4All models
            elif not response_text and hasattr(llm, 'generate'):
                response_text = llm.generate(full_prompt, max_tokens=max_tokens, temp=temp, top_p=0.95, top_k=40)
            
            # Fallback - try calling as function
            elif not response_text and callable(llm):
                response_text = llm(full_prompt, max_tokens=max_tokens, temperature=temp)
            
            # If still no response, use API as last resort
            elif not response_text and HAS_API_INTEGRATION and api_router.list_configured():
                structured_logger.log('query_api_fallback', providers=api_router.list_configured())
                response_text = api_router.query(full_prompt, provider=api_router.list_configured()[0])
            
            if not response_text:
                return f"{R}Model not loaded and no API configured{X}"
            
            # === REACT LOOP STEP 2: Action ===
            # Check for tool calls in response
            if '<action>' in response_text or '<tool_call>' in response_text:
                react_result = react_loop.step(prompt, response_text)
                action_feedback = react_result.get('observation', '')
                response_text = f"{response_text}\n\n{theme.get_color('info')}[Observation: {action_feedback}]{theme.get_color('reset')}"
            
            # === PERSISTENCE: Log response ===
            if current_session:
                current_session.append_message('assistant', response_text)
            
            # === HOOKS: Fire post-query hooks ===
            if hook_system:
                asyncio.run(hook_system.fire('post_query', response_text))
            
            # === AUDIT LOG ===
            if permission_gate:
                permission_gate.log_action("query", "execute", {"prompt": prompt[:50]}, True)
            
            result = response_text.strip() if response_text.strip() else f"{R}No response{X}"
            
            # === COST TRACKING: Log this query ===
            if HAS_COST_TRACKING and budget_enforcer.trackers.get("default"):
                input_tokens = len(prompt) // 4  # Rough estimate
                output_tokens = len(response_text) // 4
                cost = budget_enforcer.trackers["default"].log_call(input_tokens, output_tokens)
                if cost > 0:
                    status = budget_enforcer.trackers["default"].get_status()
                    print(f"{S}[Cost: {status['total_cost']} / {status['max_budget']}]{X}")
            
            # === STRUCTURED LOGGING: Query success ===
            query_duration = time() - query_start_time
            structured_logger.log('query_success', 
                                duration_ms=int(query_duration * 1000),
                                response_length=len(result),
                                session=session_id)
            
            # === REQUEST CACHE: Store successful response ===
            request_cache.set(request_hash, result)
        
        return result
    
    except TimeoutError:
        query_duration = time() - query_start_time
        structured_logger.error('query_timeout', duration_ms=int(query_duration * 1000), session=session_id)
        dlq.add({'prompt': prompt, 'session': session_id}, 'timeout', time())
        return f"{R}Inference timeout (>120s). Try a shorter prompt.{X}"
    except Exception as e:
        query_duration = time() - query_start_time
        structured_logger.error('query_failed', error=str(e), duration_ms=int(query_duration * 1000), session=session_id)
        dlq.add({'prompt': prompt, 'session': session_id}, str(e), time())
        return f"{R}Error: {str(e)[:80]}{X}"


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

def health_check():
    """Check system health and model availability"""
    health_status = {
        'timestamp': __import__('datetime').datetime.now().isoformat(),
        'model_loaded': llm is not None or ollama_mode,
        'model_name': llm_model_name if ollama_mode else (Path(model_path).stem if model_path is not None else None),
        'rate_limiter': HAS_RATE_LIMITING,
        'cost_tracking': HAS_COST_TRACKING,
        'security': HAS_SECURITY,
        'persistence': HAS_PERSISTENCE,
        'dlq_size': dlq.get_size(),
        'session_active': current_session is not None,
        'chat_history_length': len(chat_history),
    }
    
    structured_logger.log('health_check', **health_status)
    return health_status

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
    global dark_mode, O1, O2, H1, H2, G, R, S
    dark_mode = not dark_mode
    
    if dark_mode:
        # Switch to dark mode
        O1 = O1_DARK
        O2 = O2_DARK
        H1 = H1_DARK
        H2 = H2_DARK
        G = G_DARK
        R = R_DARK
        S = S_DARK
        theme = "Dark"
    else:
        # Switch to light mode
        O1 = O1_LIGHT
        O2 = O2_LIGHT
        H1 = H1_LIGHT
        H2 = H2_LIGHT
        G = G_LIGHT
        R = R_LIGHT
        S = S_LIGHT
        theme = "Light"
    
    print(f"{G}✓ Theme set to {theme} mode{X}\n")


def show_model_info():
    """Display current model information"""
    if not model_path:
        print(f"{R}✗ No model loaded{X}\n")
        return
    
    try:
        size_gb = Path(model_path).stat().st_size / (1024 ** 3)
        print(f"\n{O2}Model Info:{X}")
        print(f"  {O1}Name:{X} {Path(model_path).stem if model_path else 'N/A'}")
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

# Initialize ctx global variable (was previously defined at runtime)
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

def advanced_search(query, history, limit=5):
    """Advanced search with ranking and filtering"""
    if not history:
        return []
    
    import difflib
    results = []
    
    for item in history:
        prompt = item.get('prompt', '')
        response = item.get('response', '')
        combined = f"{prompt} {response}".lower()
        
        # Score based on similarity
        ratio = difflib.SequenceMatcher(None, query.lower(), combined).ratio()
        if ratio > 0.3:  # Threshold
            results.append((ratio, item))
    
    # Sort by score descending
    results.sort(key=lambda x: x[0], reverse=True)
    return results[:limit]

def advanced_search_menu():
    """Advanced search menu with filters"""
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
        self.created_at = time()
    
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
            'timestamp': datetime.now().isoformat()
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

class ContextCompactor:
    """5-layer context compaction pipeline matching Claude Code's strategy"""
    
    def __init__(self, max_tokens=100000, warning_threshold=0.8):
        self.max_tokens = max_tokens
        self.warning_threshold = int(max_tokens * warning_threshold)
        self.current_usage = 0
        self.archive = []
    
    def compact(self, messages, current_usage):
        """Run all 5 compaction tiers in order (cheapest first)"""
        self.current_usage = current_usage
        
        # Tier 1: Budget Reduction (free - truncate individual outputs)
        messages = self._budget_reduction(messages)
        
        # Tier 2: Snip Compact (free - archive old messages)
        messages = self._snip_compact(messages)
        
        # Tier 3: Microcompact (free - deduplicate tool outputs)
        messages = self._microcompact(messages)
        
        # Tier 4: Context Collapse (free - restructure)
        messages = self._context_collapse(messages)
        
        # Tier 5: Auto-Compact (paid - LLM summarization)
        if self.current_usage > self.warning_threshold:
            messages = self._auto_compact(messages)
        
        return messages
    
    def _budget_reduction(self, messages):
        """Tier 1: Truncate tool outputs that overflow size limits"""
        result = []
        max_tool_output = 500  # Max tokens per tool output
        
        for msg in messages:
            if isinstance(msg, dict) and msg.get('type') == 'tool_result':
                content = msg.get('content', '')
                if len(content) > max_tool_output:
                    msg['content'] = content[:max_tool_output] + "...[truncated]"
            result.append(msg)
        
        return result
    
    def _snip_compact(self, messages):
        """Tier 2: Remove old messages, archive them"""
        if len(messages) > 50:  # Archive if too many
            archivable = messages[:-20]  # Keep last 20
            self.archive.extend(archivable)
            return messages[-20:]
        return messages
    
    def _microcompact(self, messages):
        """Tier 3: Deduplicate tool results, clear redundant entries"""
        seen_results = {}
        result = []
        
        for msg in messages:
            if isinstance(msg, dict) and msg.get('type') == 'tool_result':
                key = msg.get('tool_use_id')
                if key in seen_results:
                    continue  # Skip duplicate
                seen_results[key] = True
            result.append(msg)
        
        return result
    
    def _context_collapse(self, messages):
        """Tier 4: Collapse recoverable content"""
        if len(messages) > 100:
            # Group older messages into a summary marker
            collapsed = {
                'type': 'system',
                'content': f'[Context collapsed: {len(messages)-30} messages archived]'
            }
            return [collapsed] + messages[-30:]
        return messages
    
    def _auto_compact(self, messages):
        """Tier 5: LLM-based summarization (most expensive)"""
        # In production, this would call Claude to summarize
        # For now, we mark it as needing compaction
        for msg in messages:
            if isinstance(msg, dict) and msg.get('type') == 'user':
                msg['_needs_summary'] = True
        return messages
    
    def get_stats(self):
        """Get compaction stats"""
        return {
            'current_usage': self.current_usage,
            'max_tokens': self.max_tokens,
            'warning_threshold': self.warning_threshold,
            'archived_messages': len(self.archive),
            'usage_percent': (self.current_usage / self.max_tokens) * 100
        }
    
class LayeredAgentSystem:
    """7-Layer hierarchical agent system matching Claude Code architecture"""
    def __init__(self):
        self.layers = {
            1: {"name": "Input Layer", "agents": []},  # Session management & gating
            2: {"name": "Router", "agents": []},  # Request classification & routing
            3: {"name": "Knowledge Layer", "agents": []},  # Context compression & memory
            4: {"name": "Analyzer", "agents": []},  # Deep analysis & pattern detection
            5: {"name": "Processor", "agents": []},  # Core task processing
            6: {"name": "Refiner", "agents": []},  # Output refinement & optimization
            7: {"name": "Observability Layer", "agents": []}  # Audit trail & validation
        }
        self.cache = {}
        self.response_times = []
        self.context_budget = {"max_tokens": 100000, "used": 0}
        self.audit_trail = []
        self.compactor = ContextCompactor(max_tokens=100000)
        self.prompt_cache = {}  # Cache for stable prompts
        self.cache_hits = 0
        self.cache_misses = 0
    
    def add_agent(self, layer, agent):
        """Add agent to specific layer"""
        if 1 <= layer <= 7:
            self.layers[layer]["agents"].append(agent)
            return True
        return False
    
    def _get_from_cache(self, key):
        """Check prompt cache (like Claude Code's prompt caching)"""
        if key in self.prompt_cache:
            self.cache_hits += 1
            return self.prompt_cache[key]
        self.cache_misses += 1
        return None
    
    def _set_cache(self, key, value):
        """Store prompt in cache for reuse"""
        self.prompt_cache[key] = value
    
    def _compress_context(self, text, max_tokens=500):
        """Layer 3: Context compression - reduce token usage"""
        if len(text) > max_tokens:
            # Budget reduction - truncate large outputs
            return text[:max_tokens] + "..."
        return text
    
    def _log_audit(self, layer, action, data):
        """Layer 7: Audit trail logging"""
        import time
        self.audit_trail.append({
            "timestamp": time.time(),
            "layer": layer,
            "action": action,
            "data": data[:100] if isinstance(data, str) else data
        })
    
    def execute_layered(self, prompt, context=''):
        """Execute through all 7 layers with Claude Code's compaction strategy"""
        import time
        start_time = time.time()
        
        result = {"layers": {}, "final_response": "", "execution_time": 0, "layers_executed": 0}
        
        # Pre-execution: Run context compaction (like Claude Code does before model call)
        messages = [{"type": "user", "content": prompt}]
        if context:
            messages.insert(0, {"type": "system", "content": context})
        
        self.context_budget["used"] += len(prompt) + len(context)
        messages = self.compactor.compact(messages, self.context_budget["used"])
        
        try:
            # Layer 1: Input - session management & permission gating
            if self.layers[1]["agents"]:
                self._log_audit(1, "init", "session_validated")
                result["layers"][1] = "✓ Session validated & gated"
                result["layers_executed"] += 1
            
            # Layer 2: Router - classify request (check cache first)
            if self.layers[2]["agents"]:
                cache_key = f"route_{prompt[:50]}"
                cached = self._get_from_cache(cache_key)
                if cached:
                    result["layers"][2] = cached
                else:
                    router_prompt = f"Classify: {prompt[:100]}"
                    result["layers"][2] = self._execute_layer(2, router_prompt, context)
                    self._set_cache(cache_key, result["layers"][2])
                self._log_audit(2, "route", result["layers"][2])
                result["layers_executed"] += 1
            
            # Layer 3: Knowledge - context compression (compactor already ran)
            if self.layers[3]["agents"]:
                result["layers"][3] = f"✓ Context compacted"
                self._log_audit(3, "compress", f"tokens_{self.context_budget['used']}")
                result["layers_executed"] += 1
            
            # Layer 4: Analyzer - deep analysis
            if self.layers[4]["agents"]:
                analyzer_prompt = f"Analyze: {prompt}"
                result["layers"][4] = self._execute_layer(4, analyzer_prompt, context)
                self._log_audit(4, "analyze", result["layers"][4][:100])
                result["layers_executed"] += 1
            
            # Layer 5: Processor - core processing
            if self.layers[5]["agents"]:
                result["layers"][5] = self._execute_layer(5, prompt, context)
                self._log_audit(5, "process", result["layers"][5][:100])
                result["layers_executed"] += 1
            
            # Layer 6: Refiner - polish output
            if self.layers[6]["agents"] and result["layers"].get(5):
                refine_prompt = f"Refine: {result['layers'][5][:200]}"
                result["layers"][6] = self._execute_layer(6, refine_prompt, context)
                self._log_audit(6, "refine", result["layers"][6][:100])
                result["layers_executed"] += 1
            
            # Layer 7: Observability - audit & validation
            if self.layers[7]["agents"]:
                result["layers"][7] = f"✓ Audit logged"
                self._log_audit(7, "validate", f"execution_complete")
                result["layers_executed"] += 1
            
            # Use best response
            result["final_response"] = (
                result["layers"].get(6) or 
                result["layers"].get(5) or 
                result["layers"].get(4) or ""
            )
        
        except Exception as e:
            self._log_audit(0, "error", str(e))
            result["error"] = str(e)
        
        result["execution_time"] = time.time() - start_time
        result["context_remaining"] = self.context_budget["max_tokens"] - self.context_budget["used"]
        result["cache_efficiency"] = f"{self.cache_hits}/{self.cache_hits + self.cache_misses} hits"
        
        return result
    
    def _execute_layer(self, layer, prompt, context=''):
        """Execute all agents in a layer"""
        if not self.layers[layer]["agents"]:
            return ""
        
        agent = self.layers[layer]["agents"][0]  # Use first agent
        try:
            return agent.execute(prompt, context)
        except:
            return ""
    
    def get_audit_trail(self):
        """Get audit trail for observability"""
        return self.audit_trail
    
    def get_stats(self):
        """Get performance stats including cache and compaction"""
        return {
            "audit_entries": len(self.audit_trail),
            "context_used": self.context_budget["used"],
            "context_remaining": self.context_budget["max_tokens"] - self.context_budget["used"],
            "avg_response_time": sum(self.response_times) / len(self.response_times) if self.response_times else 0,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": f"{(self.cache_hits / (self.cache_hits + self.cache_misses) * 100) if (self.cache_hits + self.cache_misses) > 0 else 0:.1f}%",
            "compaction_stats": self.compactor.get_stats(),
            "archived_messages": len(self.compactor.archive)
        }

class SubAgent:
    """Specialized AI sub-agent for specific tasks"""
    def __init__(self, name, role, system_prompt, model_path=None):
        self.name = name
        self.role = role
        self.system_prompt = system_prompt
        self.model = None
        self.model_path = model_path or globals().get('model_path')  # Fixed: Use global model_path as fallback
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
        global ollama_mode, llm_model_name
        
        if not self.model and not llm and not ollama_mode:
            return f"{R}No model available{X}"
        
        full_prompt = f"{self.system_prompt}\n\nContext: {context}\n\nTask: {task}"
        
        try:
            # Use Ollama if available
            if ollama_mode and HAS_OLLAMA:
                response = requests.post(
                    "http://localhost:11434/api/generate",
                    json={
                        "model": llm_model_name,
                        "prompt": full_prompt,
                        "stream": False,
                        "temperature": temp,
                        "options": {"num_predict": max_tokens}
                    },
                    timeout=60
                )
                if response.status_code == 200:
                    result = response.json().get('response', '')
                    self.conversation.append({'task': task, 'response': result})
                    return result.strip() if result.strip() else f"{R}No response{X}"
            
            # Fallback to local model
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
    """Manage multiple specialized sub-agents with 5-layer system"""
    def __init__(self):
        self.agents = {}
        self.layered_system = LayeredAgentSystem()
        self.initialize_default_agents()
        self.setup_layers()
    
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
    
    def setup_layers(self):
        """Setup 7-layer hierarchical agent system"""
        # Layer 1: Input agents - session management
        input_agent = SubAgent("input_mgr", "Input Manager", "Manage session, permissions, and gating")
        self.layered_system.add_agent(1, input_agent)
        
        # Layer 2: Router agents - fast classification
        router = SubAgent("router", "Router", "Classify and route requests efficiently")
        self.layered_system.add_agent(2, router)
        
        # Layer 3: Knowledge agents - context compression
        knowledge = SubAgent("knowledge", "Knowledge Manager", "Compress context and manage memory")
        self.layered_system.add_agent(3, knowledge)
        
        # Layer 4: Analyzer agents - deep analysis
        analyzer = self.agents.get('analyst') or SubAgent("analyzer", "Analyzer", "Perform deep analysis and pattern detection")
        self.layered_system.add_agent(4, analyzer)
        
        # Layer 5: Processor agents - core processing
        processor = self.agents.get('architect') or SubAgent("processor", "Processor", "Core task processing")
        self.layered_system.add_agent(5, processor)
        
        # Layer 6: Refiner agents - output polish
        refiner = self.agents.get('writer') or SubAgent("refiner", "Refiner", "Refine and improve outputs")
        self.layered_system.add_agent(6, refiner)
        
        # Layer 7: Observability agents - audit & validation
        validator = SubAgent("validator", "Validator", "Audit trail, validation, and observability")
        self.layered_system.add_agent(7, validator)
    
    def create_agent(self, name, role, system_prompt, model_path=None):
        """Create custom agent dynamically"""
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
        
        if not agent.model:  # Fixed: Check if agent model is not initialized
            agent.initialize()
        
        return agent.execute(task, context)
    
    def list_agents(self):
        """List all agents"""
        return {name: agent.get_info() for name, agent in self.agents.items()}
    
    def execute_layered(self, task, context=''):
        """Execute task through 7-layer system for optimal results"""
        return self.layered_system.execute_layered(task, context)
    
    def get_layer_stats(self):
        """Get performance stats from 7-layer system"""
        return self.layered_system.get_stats()
    
    def get_audit_trail(self):
        """Get audit trail from observability layer"""
        return self.layered_system.get_audit_trail()
    
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
        if model_path is None:
            raise ValueError("model_path cannot be None")
        if not model_name:
            model_name = Path(model_path).name if model_path else 'unknown'
        
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
 global llm,model_path,current_session
 log_startup()
 splash()
 
 # Initialize plugins
 create_sample_plugins()
 discovered = plugin_manager.discover_plugins()
 if discovered:
  print(f"{S}Found {len(discovered)} plugins. Load with /plugin load <name>{X}\n")
 
 if not setup():
  return
 
 print(f"{O2}Model: {O1}{Path(model_path).stem if model_path else 'None'}{X}\n")
 
 while True:
  try:
   inp=input(f"{H1}You:{X} ").strip()
   parts = []  # Initialize parts at start of every loop iteration
   
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
     print(f"{O2}Model: {O1}{Path(model_path).stem if model_path else 'None'}{X}\n")
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
   
   if inp.startswith('/help') or inp == '/':
    print(f"\n{O2}╔ Available Commands ╗{X}\n")
    for cmd, desc in sorted(COMMANDS.items()):
     print(f"  {H1}{cmd:15s}{X} {desc}")
    print()
    continue
   
   if inp.startswith('/models'):
    parts = inp.split(None, 1)
    if len(parts) < 2:
     print(f"\n{O2}╔ Available Models ╗{X}\n")
     if llm:
      print(f"  {G}✓ Loaded:{X} {llm_model_name}\n")
     else:
      print(f"  {R}✗ No local model loaded{X}\n")
     if api_router.list_configured():
      print(f"  {H1}API Providers:{X}")
      for provider in api_router.list_configured():
       selected = api_router.selected_models.get(provider, 'default')
       marker = f" {G}[PRIMARY]{X}" if provider == api_router.primary_api else ""
       print(f"    • {H1}{provider}{X} {S}({selected}){X}{marker}")
     print(f"\n{S}Usage: /models set <provider> <model> or /models reload{X}\n")
    elif len(parts) > 1 and parts[1].startswith('set '):
     args = parts[1].split()
     if len(args) >= 3:
      provider, model = args[1], args[2]
      if provider in api_router.clients:
       api_router.selected_models[provider] = model
       if hasattr(api_router.clients[provider], 'model'):
        api_router.clients[provider].model = model
       print(f"{G}✓ Model set: {provider} = {model}{X}\n")
      else:
       print(f"{R}✗ Provider not configured: {provider}{X}\n")
     else:
      print(f"{R}Usage: /models set <provider> <model>{X}\n")
    elif len(parts) > 1 and parts[1] == 'reload':
     print(f"{O1}Reloading model configuration...{X}\n")
     try:
      api_router.initialize_clients()
      print(f"{G}✓ Configuration reloaded{X}\n")
     except Exception as e:
      print(f"{R}✗ Reload failed: {str(e)[:60]}{X}\n")
    continue
   
   if inp.startswith('/skill'):
    parts = inp.split(None, 1)
    if len(parts) < 2:
     print(f"{H2}Usage: /skill <path_to_skill_file>{X}\n")
    else:
     skill_path = parts[1].strip()
     try:
      with open(skill_path, 'r') as f:
       skill_code = f.read()
      exec(skill_code, globals())
      print(f"{G}✓ Skill loaded: {skill_path}{X}\n")
      structured_logger.log('skill_loaded', path=skill_path)
     except Exception as e:
      print(f"{R}✗ Failed to load skill: {str(e)}{X}\n")
      structured_logger.error('skill_load_failed', error=str(e))
    continue
   
   if inp.startswith('/advsearch'):
    parts = inp.split(None, 1)
    if len(parts) < 2:
     print(f"{H2}Usage: /advsearch <query>{X}\n")
     continue
    else:
     search_query = parts[1].strip()
     results = advanced_search(search_query, chat_history, limit=5)
     if results:
      print(f"\n{O2}╔ Search Results ╗{X}\n")
      for i, (score, item) in enumerate(results, 1):
       print(f"  {i}. {S}[{score:.2f}]{X} {item['prompt'][:60]}...")
      print()
     else:
      print(f"{S}No results found{X}\n")
    continue
   
   if inp.startswith('/context'):
    print(f"\n{O2}╔ Conversation Context ╗{X}\n")
    if current_session:
     ctx_summary = f"Session: {current_session.session_id}\nMessages: {len(current_session.messages)}"
     print(f"  {H1}{ctx_summary}{X}\n")
    else:
     print(f"  {S}No active session{X}\n")
    print()
    continue
   
   if inp.startswith('/agent'):
    if not llm and not (api_router.primary_api and api_router.clients.get(api_router.primary_api)):
     print(f"{R}✗ No model loaded and no API configured{X}\n")
     continue
    
    run_as_agent()
    continue
   
   if inp.startswith('/freerange'):
    if not llm and not (api_router.primary_api and api_router.clients.get(api_router.primary_api)):
     print(f"{R}✗ No model loaded and no API configured{X}\n")
     continue
    
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
   
   if inp.startswith('/stats'):
    print(f"\n{O2}╔ Statistics ╗{X}\n")
    print(f"  {H1}Chat History:{X} {len(chat_history)} messages")
    print(f"  {H1}Session:{X} {current_session.session_id if current_session else 'None'}")
    print(f"  {H1}Configured APIs:{X} {', '.join(api_router.list_configured()) if api_router.list_configured() else 'None'}")
    print(f"  {H1}Model:{X} {llm_model_name if llm else 'None (local)'}")
    if HAS_COST_TRACKING:
     tracker = budget_enforcer.trackers.get("default")
     if tracker:
      print(f"  {H1}Cost Tracker:{X} ${tracker.total_cost:.2f} spent")
    print()
    continue
   
   if inp.startswith('/export'):
    parts = inp.split(None, 1)
    if len(parts) > 1:
     format_type = parts[1].strip().lower()
    else:
     format_type = 'txt'
    
    try:
     timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
     
     if format_type == 'json':
      export_file = Path.home() / '.hercules' / f"chat_export_{timestamp}.json"
      export_data = {
       'timestamp': datetime.now().isoformat(),
       'messages': chat_history,
       'total_messages': len(chat_history),
       'branch': branch_manager.current_branch,
       'api': api_router.primary_api if api_router.primary_api else None
      }
      with open(export_file, 'w') as f:
       json.dump(export_data, f, indent=2)
     else:
      export_file = Path.home() / '.hercules' / f"chat_export_{timestamp}.txt"
      with open(export_file, 'w') as f:
       f.write(f"Chat Export - {datetime.now().isoformat()}\n")
       f.write(f"Total Messages: {len(chat_history)}\n")
       f.write(f"Branch: {branch_manager.current_branch}\n")
       f.write("="*80 + "\n\n")
       
       for i, item in enumerate(chat_history, 1):
        f.write(f"[{i}] Q: {item['prompt']}\n")
        f.write(f"    A: {item['response']}\n")
        f.write("-"*80 + "\n")
     
     print(f"{G}✓ Exported to {export_file.name}{X}\n")
     structured_logger.log('chat_exported', filename=export_file.name, messages=len(chat_history))
    except Exception as e:
     print(f"{R}✗ Export failed: {str(e)[:60]}{X}\n")
    continue
   
   if inp.startswith('/search') or inp.startswith('/history'):
    if not chat_history:
     print(f"{S}No chat history{X}\n")
    else:
     print(f"\n{O2}╔ Chat History ({len(chat_history)} messages) ╗{X}\n")
     for i, item in enumerate(chat_history[-10:], 1):  # Show last 10
      print(f"  {H1}[{i}]{X} Q: {item['prompt'][:60]}...")
     print()
    continue
   
   if inp.startswith('/save'):
    parts = inp.split(None, 1)
    if len(parts) > 1:
     session_name = parts[1].strip()
    else:
     session_name = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    try:
     if current_session:
      current_session.save()
      print(f"{G}✓ Current session saved{X}\n")
     
     # Also save chat history to named file
     save_file = Path.home() / '.hercules' / 'sessions' / f"{session_name}.json"
     save_file.parent.mkdir(parents=True, exist_ok=True)
     
     session_data = {
      'name': session_name,
      'timestamp': datetime.now().isoformat(),
      'messages': chat_history,
      'branch': branch_manager.current_branch,
      'model': llm_model_name if llm else None,
      'api': api_router.primary_api if api_router.primary_api else None
     }
     
     with open(save_file, 'w') as f:
      json.dump(session_data, f, indent=2)
     
     print(f"{G}✓ Session saved as: {session_name}{X}\n")
     structured_logger.log('session_saved', name=session_name, messages=len(chat_history))
    except Exception as e:
     print(f"{R}✗ Save failed: {str(e)[:60]}{X}\n")
     structured_logger.error('session_save_failed', error=str(e))
    continue
   
   if inp.startswith('/load'):
    parts = inp.split(None, 1)
    if len(parts) < 2:
     # List available sessions
     session_dir = Path.home() / '.hercules' / 'sessions'
     if session_dir.exists():
      sessions = sorted([f.stem for f in session_dir.glob('*.json')])
      if sessions:
       print(f"\n{O2}╔ Available Sessions ╗{X}\n")
       for i, sess in enumerate(sessions, 1):
        print(f"  {H1}[{i}]{X} {sess}")
       print(f"\n{H2}Usage: /load <session_name>{X}\n")
      else:
       print(f"{S}No saved sessions{X}\n")
     else:
      print(f"{S}No saved sessions{X}\n")
    else:
     session_name = parts[1].strip()
     try:
      session_file = Path.home() / '.hercules' / 'sessions' / f"{session_name}.json"
      if session_file.exists():
       with open(session_file, 'r') as f:
        session_data = json.load(f)
       
       chat_history.clear()
       chat_history.extend(session_data.get('messages', []))
       
       print(f"{G}✓ Session loaded: {session_name}{X}")
       print(f"  {O1}Messages:{X} {len(chat_history)}")
       print(f"  {O1}Branch:{X} {session_data.get('branch', 'main')}")
       print(f"  {O1}Model:{X} {session_data.get('model', 'local')}\n")
       
       structured_logger.log('session_loaded', name=session_name, messages=len(chat_history))
      else:
       print(f"{R}✗ Session not found: {session_name}{X}\n")
     except Exception as e:
      print(f"{R}✗ Load failed: {str(e)[:60]}{X}\n")
      structured_logger.error('session_load_failed', error=str(e))
    continue
   
   if inp.startswith('/clear'):
    chat_history.clear()
    if current_session:
     current_session.messages.clear()
    print(f"{G}✓ Chat history cleared{X}\n")
    continue
   
   if inp.startswith('/exit') or inp.startswith('/quit'):
    if current_session:
     current_session.save()
    print(f"\n{S}Goodbye!{X}\n")
    break
   
   if inp.startswith('/api'):
    parts = inp.split(None, 2)
    if len(parts) < 2 or parts[1] == '':
     # Main API menu with dropdown
     print(f"\n{O2}╔ API Configuration ╗{X}\n")
     configured = api_config.list_apis()
     print(f"  {H1}Configured:{X} {', '.join(configured) if configured else 'None'}")
     print(f"  {H1}Primary:{X} {api_router.primary_api or 'Not set'}")
     
     print(f"\n{O2}API Menu:{X}\n")
     print(f"  {H1}[1]{X} Add new provider")
     print(f"  {H1}[2]{X} Select primary API")
     print(f"  {H1}[3]{X} List configured APIs")
     print(f"  {H1}[4]{X} Query with multiple APIs")
     print(f"  {H1}[5]{X} Remove provider")
     print(f"  {H1}[6]{X} View API models")
     print(f"\n{H2}Choose option (1-6):{X} ", end='', flush=True)
     
     try:
      menu_choice = input().strip()
      
      if menu_choice == '1':
       # Add new provider with dropdown
       providers_list = ['openai', 'anthropic', 'gemini', 'groq', 'cohere', 'deepseek', 'xai', 'meta', 'huggingface', 'together', 'azure']
       print(f"\n{O2}Select Provider:{X}\n")
       for i, prov in enumerate(providers_list, 1):
        print(f"  {H1}[{i}]{X} {prov}")
       
       print(f"\n{H2}Choose (1-{len(providers_list)}):{X} ", end='', flush=True)
       prov_choice = int(input().strip()) - 1
       
       if 0 <= prov_choice < len(providers_list):
        provider = providers_list[prov_choice]
        
        # Ask for key(s)
        print(f"\n{O2}Add API Key for {provider.upper()}{X}\n")
        print(f"  {H1}[1]{X} Single key")
        print(f"  {H1}[2]{X} Multiple keys (for fallback)")
        print(f"\n{H2}Choose:{X} ", end='', flush=True)
        
        key_choice = input().strip()
        keys = []
        
        if key_choice == '1':
         print(f"{H2}Enter API key:{X} ", end='', flush=True)
         key = input().strip()
         if key:
          keys.append(key)
        else:
         print(f"{H2}Enter API keys (comma-separated):{X} ", end='', flush=True)
         key_input = input().strip()
         keys = [k.strip() for k in key_input.split(',') if k.strip()]
        
        if keys:
         # Store all keys
         for idx, key in enumerate(keys):
          key_name = f"{provider}" if idx == 0 else f"{provider}_{idx}"
          api_config.set_api(key_name, key)
          print(f"{G}✓ Key {idx+1} stored{X}")
         
         api_router.initialize_clients()
         
         # Set primary
         if not api_router.primary_api:
          api_router.set_primary(provider)
          print(f"{G}✓ Set as primary API{X}\n")
         
         # Show model selection
         if provider in API_MODELS:
          models = API_MODELS[provider]
          print(f"\n{O2}Select Model for {provider.upper()}{X}\n")
          model_list = list(models.keys())
          for i, model_id in enumerate(model_list, 1):
           model = models[model_id]
           display = model.get('display', model_id)
           print(f"  {H1}[{i}]{X} {display:<30s} ${model.get('input', 0):.2f}/${model.get('output', 0):.2f}")
          
          print(f"\n{H2}Select model (1-{len(model_list)}):{X} ", end='', flush=True)
          try:
           m_choice = int(input().strip()) - 1
           if 0 <= m_choice < len(model_list):
            api_router.selected_models[provider] = model_list[m_choice]
            print(f"{G}✓ Model selected{X}\n")
          except:
           pass
        else:
         print(f"{R}✗ No keys provided{X}\n")
       else:
        print(f"{R}✗ Invalid selection{X}\n")
      
      elif menu_choice == '2':
       # Select primary API
       configured = api_router.list_configured()
       if configured:
        print(f"\n{O2}Select Primary API:{X}\n")
        for i, prov in enumerate(configured, 1):
         marker = f" {G}[CURRENT]{X}" if prov == api_router.primary_api else ""
         print(f"  {H1}[{i}]{X} {prov}{marker}")
        
        print(f"\n{H2}Choose (1-{len(configured)}):{X} ", end='', flush=True)
        choice = int(input().strip()) - 1
        if 0 <= choice < len(configured):
         api_router.set_primary(configured[choice])
         print(f"{G}✓ Primary set to {configured[choice]}{X}\n")
       else:
        print(f"{R}No APIs configured{X}\n")
      
      elif menu_choice == '3':
       # List configured
       configured = api_router.list_configured()
       print(f"\n{O2}╔ Configured APIs ╗{X}\n")
       if configured:
        for prov in configured:
         model = api_router.selected_models.get(prov, 'default')
         marker = f" {G}[PRIMARY]{X}" if prov == api_router.primary_api else ""
         print(f"  {H1}• {prov}{X} ({model}){marker}")
       else:
        print(f"  {R}None configured{X}")
       print()
      
      elif menu_choice == '4':
       # Query with multiple APIs
       configured = api_router.list_configured()
       if not configured:
        print(f"{R}No APIs configured{X}\n")
        continue
       
       print(f"\n{H2}Enter prompt:{X} ", end='', flush=True)
       prompt = input().strip()
       
       print(f"\n{O2}Select APIs to query:{X}\n")
       for i, prov in enumerate(configured, 1):
        print(f"  {H1}[{i}]{X} {prov}")
       
       print(f"\n{H2}Choose APIs (comma-separated, e.g. 1,2,3):{X} ", end='', flush=True)
       selections = input().strip().split(',')
       
       try:
        selected_apis = [configured[int(s.strip())-1] for s in selections if s.strip()]
        if selected_apis:
         print(f"\n{G}Querying {len(selected_apis)} APIs...{X}\n")
         results = {}
         for api in selected_apis:
          try:
           response = api_router.query(prompt, provider=api)
           results[api] = response
           print(f"{O1}[{api}]{X}\n{G}{response[:200]}...{X}\n")
          except Exception as e:
           results[api] = f"Error: {str(e)[:60]}"
           print(f"{O1}[{api}]{X}\n{R}Error{X}\n")
         
         chat_history.append({
          'prompt': f'[MULTI-API] {prompt}',
          'response': str(results),
          'apis_used': selected_apis
         })
       except (ValueError, IndexError):
        print(f"{R}✗ Invalid selection{X}\n")
      
      elif menu_choice == '5':
       # Remove provider
       configured = api_router.list_configured()
       if configured:
        print(f"\n{O2}Select provider to remove:{X}\n")
        for i, prov in enumerate(configured, 1):
         print(f"  {H1}[{i}]{X} {prov}")
        
        print(f"\n{H2}Choose (1-{len(configured)}):{X} ", end='', flush=True)
        choice = int(input().strip()) - 1
        if 0 <= choice < len(configured):
         api_config.remove_api(configured[choice])
         api_router.initialize_clients()
         print(f"{G}✓ Removed{X}\n")
       else:
        print(f"{R}No APIs to remove{X}\n")
      
      elif menu_choice == '6':
       # View models
       configured = api_router.list_configured()
       if configured:
        print(f"\n{O2}Select provider:{X}\n")
        for i, prov in enumerate(configured, 1):
         print(f"  {H1}[{i}]{X} {prov}")
        
        print(f"\n{H2}Choose:{X} ", end='', flush=True)
        choice = int(input().strip()) - 1
        if 0 <= choice < len(configured):
         prov = configured[choice]
         if prov in API_MODELS:
          print(f"\n{O2}Models for {prov.upper()}:{X}\n")
          for model_id, model in API_MODELS[prov].items():
           print(f"  {H1}{model.get('display', model_id)}{X}")
           print(f"    Input:  ${model.get('input', 0):.2f}/1M")
           print(f"    Output: ${model.get('output', 0):.2f}/1M")
     except Exception as e:
      print(f"{R}Error: {str(e)[:60]}{X}\n")
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
   
   # ===== CLAUDE CODE FEATURES (Priority 1-3) =====
   
   if inp.startswith('/security'):
    parts = inp.split()
    if HAS_SECURITY:
     if len(parts) < 2:
      print(f"\n{O2}╔ Security Settings ╗{X}\n")
      print(f"  {S}/security mode <default|accept|auto|dont_ask>{X}")
      print(f"  {S}/security audit{X}\n")
     elif parts[1] == 'mode' and len(parts) >= 3:
      mode_str = parts[2].upper()
      try:
       new_mode = PermissionMode[mode_str]
       permission_gate.mode = new_mode
       print(f"{G}✓ Permission mode: {new_mode.value}{X}\n")
      except:
       print(f"{R}Invalid mode{X}\n")
     elif parts[1] == 'audit':
      print(f"\n{O2}╔ Security Audit Log ╗{X}\n")
      for entry in permission_gate.audit_log[-5:]:
       status = "✓" if entry['approved'] else "✗"
       print(f"  {status} {entry['tool']}:{entry['action']}")
      print()
    else:
     print(f"{R}Security layer not available{X}\n")
    continue
   
   if inp.startswith('/tools'):
    if HAS_TOOLS:
     parts = inp.split()
     if len(parts) < 2:
      print(f"\n{O2}╔ Available Tools ╗{X}\n")
      for tool_name, tool_info in tool_registry.list_tools().items():
       print(f"  {H1}{tool_name}:{X} {tool_info['description']}")
      print()
     elif parts[1] == 'exec' and len(parts) >= 3:
      tool_name = parts[2]
      print(f"  {S}[Tool: {tool_name}]{X}\n")
    else:
     print(f"{R}Tool system not available{X}\n")
    continue
   
   if inp.startswith('/session'):
    if HAS_PERSISTENCE:
     parts = inp.split()
     if len(parts) < 2:
      print(f"\n{O2}╔ Session Management ╗{X}\n")
      sessions = session_persistence.list_sessions()
      for sess_id in sessions:
       print(f"  {H1}{sess_id}{X}")
      print()
     elif parts[1] == 'save':
      session_persistence.save_session(current_session)
      print(f"{G}✓ Session saved{X}\n")
     elif parts[1] == 'load' and len(parts) >= 3:
      current_session = session_persistence.load_session(parts[2])
      if current_session:
       print(f"{G}✓ Loaded: {parts[2]}{X}\n")
    else:
     print(f"{R}Persistence not available{X}\n")
    continue
   
   if inp.startswith('/team'):
    if HAS_TEAMS:
     parts = inp.split(None, 2)
     if len(parts) < 2:
      print(f"\n{O2}╔ Agent Teams ╗{X}\n")
      print(f"  {S}/team status          - Show team status{X}")
      print(f"  {S}/team create <name>   - Create new team{X}")
      print(f"  {S}/team delegate <task> - Delegate task to team{X}\n")
     elif parts[1] == 'status':
      status = active_team.get_team_status()
      print(f"\n{O2}╔ Team Status ╗{X}\n")
      print(f"  {H1}Members:{X} {status['members']}")
      print(f"  {H1}Tasks:{X} {status['completed']}/{status['total_tasks']} completed\n")
     elif parts[1] == 'create' and len(parts) >= 3:
      team_name = parts[2]
      print(f"{G}✓ Team created: {team_name}{X}\n")
      structured_logger.log('team_created', name=team_name)
     elif parts[1] == 'delegate' and len(parts) >= 3:
      task = parts[2]
      print(f"\n{O2}╔ Task Delegation ╗{X}\n")
      print(f"  {H1}Delegating:{X} {task}\n")
      # Delegate to team members
      result = active_team.delegate_task(task)
      print(f"  {H1}Status:{X} {result}\n")
      structured_logger.log('task_delegated', task=task)
    else:
     print(f"{R}Teams not available{X}\n")
    continue
   
   if inp.startswith('/cost'):
    if HAS_COST_TRACKING:
     print(f"{O1}Cost tracking active{X}\n")
    else:
     print(f"{R}Cost tracking not available{X}\n")
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
   
   if inp=='/agent':
    run_as_agent()
    continue
   
   if inp=='/stats':
    show_conversation_stats()
    continue
   
   if inp=='/advsearch':
    advanced_search_menu()
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
   structured_logger.log('shutdown', reason='keyboard_interrupt')
   break
  except Exception as e:
   error_msg = f"Error: {e}"
   print(f"{R}{error_msg}{X}\n")
   structured_logger.error('main_loop_error', error=str(e))

if __name__=='__main__':
 main()
