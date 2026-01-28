#!/usr/bin/env python3
"""
Council-of-Agents Demo (Production Hardened v2.1)
- Architecture: Speaker-Planned Orchestration (Agentic)
- Auth: Bedrock Short-term API Key (Bearer Token)
- Model: Claude 3.7 Sonnet (APAC Inference Profile)
- Resilience: <json> extraction + Strict Pydantic validation + Input Normalization
- Visibility: Full 'Trace' panels for raw inputs/outputs
"""

import os
import sys
import json
import time
import datetime as dt
import subprocess
import threading
import queue
import uuid
import re
from pathlib import Path
from typing import List, Literal, Optional, Any, Tuple, Dict
from dataclasses import dataclass, field

# Third-party imports (pip install requests pydantic rich)
import requests
from pydantic import BaseModel, Field, ValidationError, ConfigDict, field_validator
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.json import JSON

# --- CONFIGURATION ---
DEFAULT_REGION = os.getenv("AWS_REGION", "ap-southeast-1")
DEFAULT_MODEL_ID = os.getenv(
    "BEDROCK_MODEL_ID", 
    "apac.anthropic.claude-3-7-sonnet-20250219-v1:0"
)

# --- RUNTIME TOGGLES & TOKENS (Single Place) ---
BEDROCK_API_KEY = os.getenv("BEDROCK_API_KEY", "")  
WEBEX_ENABLED = os.getenv("WEBEX_ENABLED", "false").lower() in {"true", "1", "yes"}
WEBEX_BOT_TOKEN = os.getenv("WEBEX_BOT_TOKEN", "")
WEBEX_ROOM_ID = os.getenv("WEBEX_ROOM_ID", "")
WEBEX_BOT_ID = os.getenv("WEBEX_BOT_ID", "")
WEBEX_API_BASE = os.getenv("WEBEX_API_BASE", "https://webexapis.com/v1")

# API KEY CHECK
API_KEY = os.getenv("BEDROCK_API_KEY", BEDROCK_API_KEY)
if not API_KEY:
    print("[ERROR] BEDROCK_API_KEY is missing.")
    print("Either:")
    print("  1. Set BEDROCK_API_KEY variable at the top of this file, OR")
    print("  2. Export environment variable: export BEDROCK_API_KEY='your-short-term-key'")
    sys.exit(1)

BEDROCK_URL = f"https://bedrock-runtime.{DEFAULT_REGION}.amazonaws.com/model/{DEFAULT_MODEL_ID}/invoke"
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "User-Agent": "council-demo/2.1"
}

# GLOBAL DEMO CONSTRAINTS (Injected into every prompt)
DEMO_ENV = """
ENVIRONMENT: MyTNB-Prod-Demo.
CONSTRAINTS (MANDATORY):
- You cannot access real AWS services, internet, or external tools.
- Use ONLY the data provided in the prompt context.
- If data is missing, state exactly what is missing based on the logs provided.
- You must NOT hallucinate logs or metrics that are not in the context.
"""

console = Console()

# --- SPECIAL COMMANDS ---

def show_help():
    """Display help information."""
    console.print(Panel(
        """[bold]Available Commands:[/bold]

[cyan]Queries:[/cyan]
• What's the current situation?
• Are there any incidents?
• Show me recent problems
• What's affecting users right now?

[cyan]Special Commands:[/cyan]
• [bold]status[/bold] - Show session statistics
• [bold]history[/bold] - Show notification audit trail
• [bold]help[/bold] - Show this help message
• [bold]exit/quit[/bold] - Exit the system

[cyan]Data Source:[/cyan]
• Configure via USE_DYNATRACE environment variable
• Default: Live Dynatrace data via MCP

[cyan]Webex:[/cyan]
• Set WEBEX_ENABLED=true and provide WEBEX_BOT_TOKEN
• WEBEX_ROOM_ID defaults to the configured ICT room""",
        title="Council of Agents - Help",
        border_style="cyan"
    ))

def show_session_status(state: "SessionState"):
    """Display current session status."""
    duration = ""
    if state.incident_start_time:
        elapsed = (dt.datetime.now() - state.incident_start_time).total_seconds() / 60
        duration = f"{int(elapsed)} minutes"
    
    console.print(Panel(
        f"""[bold]Session Statistics:[/bold]

[cyan]Data Source:[/cyan] {'🔴 Dynatrace (Live)' if state.use_dynatrace else '🟡 Fallback (Local)'}
[cyan]Events Loaded:[/cyan] {len(state.events)}
[cyan]Incidents Declared:[/cyan] {len(state.incidents)}
[cyan]Webex Notifications:[/cyan] {len(state.notification_history)}
[cyan]Webex Delivery:[/cyan] {state.notifier.status_label() if state.notifier else '⚪ Disabled'}
[cyan]Current Severity:[/cyan] {state.last_incident_severity or 'None'}
[cyan]Incident Duration:[/cyan] {duration or 'No active incident'}
[cyan]Escalation Required:[/cyan] {'Yes' if state.requires_escalation else 'No'}

[bold]Recent Incidents:[/bold]
""" + "\n".join([f"• {inc['sev']} - {inc['cause'][:60]}... ({inc['users']} users)" for inc in state.incidents[-3:]]) if state.incidents else "[dim]No incidents recorded[/dim]",
        title="Session Status",
        border_style="blue"
    ))

def show_notification_history(state: "SessionState"):
    """Display notification audit trail."""
    if not state.notification_history:
        console.print("[yellow]No notifications sent yet.[/yellow]")
        return
    
    console.print(Panel(
        "\n".join([
            f"[bold]{i+1}. {notif['timestamp']}[/bold]\n"
            f"   Severity: {notif['severity']}\n"
            f"   Escalation: {'Yes' if notif['escalation'] else 'No'}\n"
            f"   Message: {notif['message'][:80]}...\n"
            for i, notif in enumerate(state.notification_history)
        ]),
        title="Notification Audit Trail",
        border_style="yellow"
    ))

# --- WEBEX NOTIFIER (DECOUPLED) ---

@dataclass
class NotificationResult:
    delivered: bool
    detail: str
    channel: str = "webex"

class Notifier:
    """Abstract notifier interface to decouple delivery from agent logic."""
    name: str = "notifier"
    enabled: bool = False

    def send_incident_notification(self, message: str, severity: str, escalation: bool) -> NotificationResult:
        raise NotImplementedError

    def status_label(self) -> str:
        return "⚪ Disabled"

class NullNotifier(Notifier):
    """No-op notifier used when Webex is disabled or misconfigured."""

    def __init__(self, reason: str):
        self.name = "null"
        self.enabled = False
        self.reason = reason

    def send_incident_notification(self, message: str, severity: str, escalation: bool) -> NotificationResult:
        return NotificationResult(False, f"disabled: {self.reason}", channel="none")

    def status_label(self) -> str:
        return f"⚪ Disabled ({self.reason})"

class WebexNotifier(Notifier):
    """Webex notifier that sends markdown messages via the Webex Messages API."""

    def __init__(self, token: str, room_id: str, bot_id: str, api_base: str, enabled_flag: bool):
        self.name = "webex"
        self.token = token.strip()
        self.room_id = room_id.strip()
        self.bot_id = bot_id.strip()
        self.api_base = api_base.rstrip("/")

        self.enabled = bool(enabled_flag and self.token and self.room_id)
        if not enabled_flag:
            self.reason = "WEBEX_ENABLED=false"
        elif not self.token:
            self.reason = "missing WEBEX_BOT_TOKEN"
        elif not self.room_id:
            self.reason = "missing WEBEX_ROOM_ID"
        else:
            self.reason = "configured"

    def status_label(self) -> str:
        if self.enabled:
            return f"🟢 Enabled (room: {self.room_id[:12]}...)"
        return f"🟡 Misconfigured ({self.reason})"

    def _format_markdown(self, message: str, severity: str, escalation: bool) -> str:
        """
        Format a Webex-friendly markdown message.
        Webex supports markdown and has practical size limits, so we keep it tight.
        """
        sev = (severity or "UNKNOWN").strip()
        timestamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        escalation_line = "🚨 Escalation required" if escalation else "✅ Managed within team"
        body = (message or "").strip() or "No incident details provided."

        markdown = "\n\n".join([
            f"## {sev} Incident Update",
            escalation_line,
            body,
            f"_Council of Agents • {timestamp}_",
        ])

        max_len = 6800
        if len(markdown) > max_len:
            markdown = markdown[:max_len] + "\n\n_(truncated)_"
        return markdown

    def send_incident_notification(self, message: str, severity: str, escalation: bool) -> NotificationResult:
        if not self.enabled:
            return NotificationResult(False, self.reason)

        url = f"{self.api_base}/messages"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        markdown = self._format_markdown(message, severity, escalation)
        payload = {
            "roomId": self.room_id,
            "markdown": markdown,
        }

        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=15)
            if 200 <= resp.status_code < 300:
                return NotificationResult(True, "delivered")
            return NotificationResult(False, f"HTTP {resp.status_code}: {resp.text[:200]}")
        except Exception as e:
            return NotificationResult(False, f"request failed: {e}")

def build_notifier() -> Notifier:
    """
    Build the notifier. Webex is fully decoupled and easy to disable by setting
    WEBEX_ENABLED=false (default).
    """
    if not WEBEX_ENABLED:
        return NullNotifier("WEBEX_ENABLED=false")

    notifier = WebexNotifier(
        token=WEBEX_BOT_TOKEN,
        room_id=WEBEX_ROOM_ID,
        bot_id=WEBEX_BOT_ID,
        api_base=WEBEX_API_BASE,
        enabled_flag=WEBEX_ENABLED,
    )

    if notifier.enabled:
        return notifier
    return NullNotifier(notifier.reason)

# --- UTILS: ROBUST PARSING & TRACING ---

def extract_json(text: str) -> str:
    """Robust extraction of JSON from LLM output."""
    # 1. Explicit tags
    s_idx = text.find("<json>")
    e_idx = text.rfind("</json>")
    if s_idx != -1 and e_idx != -1 and e_idx > s_idx:
        return text[s_idx + 6:e_idx].strip()
    # 2. Markdown blocks
    if "```json" in text:
        return text.split("```json", 1)[1].split("```", 1)[0].strip()
    if "```" in text:
        return text.split("```", 1)[1].split("```", 1)[0].strip()
    # 3. Raw fallback
    return text.strip()

def type_text(text: str, delay: float = 0.005):
    """Types out text with a delay for dramatic effect."""
    for char in text:
        console.print(char, end="", markup=False)
        time.sleep(delay)
    console.print()  # New line at the end

def show_trace(role: str, user_prompt: str, raw_output: str, parsed_obj: Optional[BaseModel]):
    """Prints a visibility trace for the demo audience with line-by-line effect."""
    # Prompt trace
    console.print(Panel(
        "", 
        title=f"TRACE → {role} (Prompt)", 
        border_style="dim cyan"
    ))
    for line in user_prompt.split('\n'):
        console.print(f"  {line}")
        time.sleep(0.03)
    
    # Raw output trace
    console.print("\n" + Panel(
        "", 
        title=f"TRACE ← {role} (Raw LLM Output)", 
        border_style="dim white"
    ).renderable)
    for line in raw_output.split('\n'):
        console.print(f"  {line}")
        time.sleep(0.03)
    
    # Parsed JSON trace
    if parsed_obj:
        data = parsed_obj.model_dump()
        console.print("\n")
        console.print(Panel(
            JSON.from_data(data), 
            title=f"TRACE ✓ {role} (Parsed JSON)", 
            border_style="dim green"
        ))

# --- DATA MODELS (STRICT) ---

class StrictModel(BaseModel):
    """Base model that forbids extra fields to prevent hallucinated keys."""
    model_config = ConfigDict(extra="ignore")  # Changed from "forbid" to "ignore" to handle LLM creativity

class AgentPlan(StrictModel):
    reasoning: str = Field(..., description="Why we are calling these agents (or why not).")
    selected_agents: List[str] = Field(default_factory=list, description="Agents to activate. Valid options: EVENT_MANAGER, FAULT_MANAGER, INCIDENT_COMMANDER. Can be empty list if no agents needed.")
    
    @field_validator("selected_agents", mode="after")
    @classmethod
    def normalize_agents(cls, v):
        """Normalize agent names to uppercase with underscores."""
        if not v:  # Allow empty list
            return []
            
        normalized = []
        valid_agents = {"EVENT_MANAGER", "FAULT_MANAGER", "INCIDENT_COMMANDER"}
        
        for agent in v:
            # Normalize: uppercase, replace spaces/hyphens with underscores
            agent_clean = agent.strip().upper().replace(" ", "_").replace("-", "_")
            
            # Try to match to valid agents
            if agent_clean in valid_agents:
                normalized.append(agent_clean)
            elif "EVENT" in agent_clean:
                normalized.append("EVENT_MANAGER")
            elif "FAULT" in agent_clean:
                normalized.append("FAULT_MANAGER")
            elif "INCIDENT" in agent_clean or "COMMANDER" in agent_clean:
                normalized.append("INCIDENT_COMMANDER")
        
        return list(set(normalized))  # Remove duplicates

class EventManagerResponse(StrictModel):
    summary: str = Field(..., description="Brief summary of the event analysis")
    anomalies: List[str] = Field(..., description="List of anomaly descriptions as simple strings")
    timeline_gaps: str = Field(..., description="Description of any timeline gaps as a single string")
    
    @field_validator("timeline_gaps", mode="before")
    @classmethod
    def normalize_timeline_gaps(cls, v):
        """Convert list to string if needed."""
        if isinstance(v, list):
            return "; ".join(str(item) for item in v)
        return v

class FaultManagerResponse(StrictModel):
    root_cause_hypothesis: str = Field(..., description="Root cause hypothesis as a string")
    declare_incident: bool = Field(..., description="Boolean: true or false")
    severity: Literal["SEV1", "SEV2", "SEV3", "SEV4", "NONE"] = Field(..., description="Severity level")
    evidence: List[str] = Field(..., description="List of evidence as simple strings, not objects")
    affected_users: int = Field(default=0, description="Number of affected users as an integer")
    incident_duration: str = Field(default="Unknown", description="How long the incident has been ongoing")

    @field_validator("severity", mode="before")
    @classmethod
    def normalize_severity(cls, v):
        if isinstance(v, str):
            v_clean = v.strip().upper().replace("-", "").replace(" ", "")
            if v_clean in {"SEV1", "SEV2", "SEV3", "SEV4", "NONE"}:
                return v_clean
        return "NONE"
    
    @field_validator("evidence", mode="before")
    @classmethod
    def normalize_evidence(cls, v):
        """Convert any nested structures to simple strings."""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    result.append(str(item))
                elif isinstance(item, str):
                    result.append(item)
                else:
                    result.append(str(item))
            return result
        elif isinstance(v, str):
            # If it's a single string, wrap it in a list
            return [v]
        return []
    
    @field_validator("affected_users", mode="before")
    @classmethod
    def normalize_affected_users(cls, v):
        """Convert string numbers to integers."""
        if isinstance(v, int):
            return v
        if isinstance(v, str):
            # Try to extract number from string like "1000 users" or "1,000"
            import re
            numbers = re.findall(r'\d+', v.replace(',', ''))
            if numbers:
                return int(numbers[0])
        return 0  # Default to 0 if can't parse

class IncidentCommanderResponse(StrictModel):
    status: str = Field(..., description="Current status as a string")
    actions: List[str] = Field(..., description="List of action items as simple strings, not objects")
    webex_notification_needed: bool = Field(..., description="Whether Webex notification is needed: true or false")
    webex_msg: str = Field(..., description="Message to send to Webex 'ICT Service Delivery' group (only if notification needed)")
    system_owner_inquiry: str = Field(..., description="Questions or information needed from system owner")
    escalation_needed: bool = Field(..., description="Whether escalation is required: true or false")
    
    @field_validator("actions", mode="before")
    @classmethod
    def normalize_actions(cls, v):
        """Convert any nested structures to simple strings."""
        if isinstance(v, list):
            result = []
            for item in v:
                if isinstance(item, dict):
                    # Extract action text from dict
                    if 'action' in item:
                        result.append(item['action'])
                    else:
                        result.append(str(item))
                elif isinstance(item, str):
                    result.append(item)
                else:
                    result.append(str(item))
            return result
        return v
    
    @field_validator("escalation_needed", "webex_notification_needed", mode="before")
    @classmethod
    def normalize_boolean(cls, v):
        """Convert various boolean representations to actual boolean."""
        if isinstance(v, bool):
            return v
        if isinstance(v, str):
            v_lower = v.strip().lower()
            if v_lower in {"true", "yes", "1", "required", "needed"}:
                return True
            if v_lower in {"false", "no", "0", "not required", "not needed", "none"}:
                return False
        return False  # Default to False if unclear

class FinalResponse(StrictModel):
    user_response: str = Field(..., description="User-facing response as a string")
    internal_summary: str = Field(..., description="Internal summary as a string")
    
    @field_validator("internal_summary", mode="before")
    @classmethod
    def normalize_summary(cls, v):
        """Convert any nested structures to simple string."""
        if isinstance(v, (dict, list)):
            return str(v)
        return v

# --- LLM CLIENT ---

def invoke_agent(role: str, system_prompt: str, user_prompt: str, schema_model: type[BaseModel], token_counter: Optional['TokenCounter'] = None) -> Tuple[Optional[BaseModel], str]:
    """
    Invokes Bedrock with strict JSON contract and Pydantic validation.
    """
    properties = list(schema_model.model_fields.keys())
    
    final_system = f"""ROLE: {role}
{system_prompt}

{DEMO_ENV}

OUTPUT CONTRACT (MANDATORY):
1. You must output ONLY a valid JSON object wrapped in <json> and </json> tags.
2. The JSON object must have exactly these keys: {properties}
3. Do not include any conversational text outside the tags.
4. CRITICAL: All string fields must be simple strings, all list fields must be arrays of simple strings.
5. Do NOT use nested objects or complex structures - keep it flat and simple.

IMPORTANT: For selected_agents field, use EXACTLY these values: EVENT_MANAGER, FAULT_MANAGER, INCIDENT_COMMANDER"""

    payload = {
        "anthropic_version": "bedrock-2023-05-31",
        "max_tokens": 2000,
        "temperature": 0.1, # Deterministic for JSON
        "system": final_system,
        "messages": [{"role": "user", "content": user_prompt}]
    }

    max_retries = 2
    for attempt in range(max_retries):
        try:
            resp = requests.post(BEDROCK_URL, headers=HEADERS, json=payload, timeout=60)
            resp.raise_for_status()
            
            response_data = resp.json()
            raw_response = response_data["content"][0]["text"]
            
            # Extract token usage from response
            if token_counter and "usage" in response_data:
                usage = response_data["usage"]
                input_tokens = usage.get("input_tokens", 0)
                output_tokens = usage.get("output_tokens", 0)
                token_counter.record(input_tokens, output_tokens, DEFAULT_MODEL_ID)
            
            # 1. Extract
            json_str = extract_json(raw_response)
            
            # 2. Parse & Validate
            parsed_obj = schema_model.model_validate_json(json_str)
            
            # 3. Trace
            show_trace(role, user_prompt, raw_response, parsed_obj)
            
            return parsed_obj, raw_response
            
        except ValidationError as e:
            console.print(f"[bold red]Validation Error in {role} (attempt {attempt+1}/{max_retries}):[/bold red] {e}")
            if attempt == max_retries - 1:
                return None, str(e)
        except requests.exceptions.RequestException as e:
            console.print(f"[bold red]API Error in {role} (attempt {attempt+1}/{max_retries}):[/bold red] {e}")
            if attempt == max_retries - 1:
                return None, str(e)
        except Exception as e:
            console.print(f"[bold red]System Error in {role}:[/bold red] {e}")
            return None, str(e)

# --- DATA SOURCE LAYER (PLUGGABLE) ---

class DataSource:
    """Abstract base class for data sources."""
    def get_problems(self) -> List[Dict]:
        """Fetch problems/events from the data source."""
        raise NotImplementedError

class MCPStdioClient:
    """
    Minimal MCP stdio client that launches the server defined in .kiro/settings/mcp.json.
    This keeps MCP/Kiro as the only live-data path.
    """

    def __init__(self, server_name: str, config_path: str = ".kiro/settings/mcp.json"):
        self.server_name = server_name
        self.config_path = Path(config_path)
        self.process: Optional[subprocess.Popen] = None
        self._reader_thread: Optional[threading.Thread] = None
        self._messages: "queue.Queue[Dict[str, Any]]" = queue.Queue()
        self._request_timeout_seconds = 30.0

    def _load_server_config(self) -> Dict[str, Any]:
        if not self.config_path.exists():
            raise FileNotFoundError(f"MCP config not found at {self.config_path}")

        with self.config_path.open("r", encoding="utf-8") as f:
            config = json.load(f)

        servers = config.get("mcpServers", {})
        server_cfg = servers.get(self.server_name)
        if not server_cfg:
            raise KeyError(f"MCP server '{self.server_name}' not defined in {self.config_path}")

        if server_cfg.get("disabled") is True:
            raise RuntimeError(f"MCP server '{self.server_name}' is disabled in {self.config_path}")

        command = server_cfg.get("command")
        args = server_cfg.get("args", [])
        if not command:
            raise ValueError(f"MCP server '{self.server_name}' is missing 'command' in {self.config_path}")

        return {"command": command, "args": args}

    def _start(self) -> None:
        if self.process and self.process.poll() is None:
            return

        server_cfg = self._load_server_config()
        cmd = [server_cfg["command"], *server_cfg["args"]]

        try:
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
        except FileNotFoundError as e:
            raise RuntimeError(
                f"Failed to launch MCP server '{self.server_name}'. Is '{cmd[0]}' installed?"
            ) from e

        if not self.process.stdin or not self.process.stdout:
            raise RuntimeError("Failed to open stdio pipes for MCP server process.")

        self._reader_thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._reader_thread.start()

    def _reader_loop(self) -> None:
        assert self.process and self.process.stdout
        for line in self.process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                # Ignore non-JSON noise from the server.
                continue
            self._messages.put(message)

    def _send(self, message: Dict[str, Any]) -> None:
        assert self.process and self.process.stdin
        payload = json.dumps(message)
        self.process.stdin.write(payload + "\n")
        self.process.stdin.flush()

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        self._start()
        request_id = str(uuid.uuid4())
        self._send({
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        })

        deadline = time.monotonic() + self._request_timeout_seconds
        while time.monotonic() < deadline:
            remaining = max(0.0, deadline - time.monotonic())
            try:
                msg = self._messages.get(timeout=remaining)
            except queue.Empty:
                break

            # We only care about responses matching our request id.
            if msg.get("id") != request_id:
                continue

            if "error" in msg:
                err = msg["error"]
                raise RuntimeError(f"MCP error calling {method}: {err}")

            return msg.get("result", {})

        raise TimeoutError(f"Timed out waiting for MCP response to {method}")

    def initialize(self) -> None:
        """Perform MCP initialize + initialized notification."""
        _ = self._request(
            "initialize",
            {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "council-of-agents",
                    "version": "2026.2.1",
                },
            },
        )
        # Send the standard initialized notification.
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})

    def call_tool(self, name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        return self._request("tools/call", {"name": name, "arguments": arguments})

    def close(self) -> None:
        """Attempt a graceful shutdown; then terminate."""
        try:
            _ = self._request("shutdown", {})
        except Exception:
            pass

        try:
            self._send({"jsonrpc": "2.0", "method": "exit", "params": {}})
        except Exception:
            pass

        if self.process and self.process.poll() is None:
            self.process.terminate()

class DynatraceSource(DataSource):
    """Real Dynatrace data via MCP tools."""
    
    def get_problems(self) -> List[Dict]:
        """Fetch real problems from Dynatrace."""
        try:
            # Call Dynatrace MCP to get problems
            console.print("[dim]Fetching problems from Dynatrace...[/dim]")
            result = self._call_dynatrace_mcp()
            
            if result:
                events = self._parse_dynatrace_problems(result)
                console.print(f"[dim green]✓ Fetched {len(events)} problems from Dynatrace[/dim green]")
                return events
            else:
                console.print("[yellow]No problems returned from Dynatrace[/yellow]")
                return []
                
        except Exception as e:
            console.print(f"[yellow]Warning: Dynatrace fetch failed ({e}), using empty data[/yellow]")
            return []
    
    def _call_dynatrace_mcp(self) -> str:
        """Call Dynatrace MCP list_problems tool."""
        client = MCPStdioClient("dynatrace")
        try:
            client.initialize()
            result = client.call_tool("list_problems", {"maxProblemsToDisplay": 20})
            return self._extract_text_from_mcp_result(result)
        except Exception as e:
            console.print(f"[dim red]MCP call failed: {e}[/dim red]")
            return ""
        finally:
            client.close()

    def _extract_text_from_mcp_result(self, result: Dict[str, Any]) -> str:
        """
        Extract text content from a standard MCP tools/call result.
        Falls back to JSON serialization when needed.
        """
        if isinstance(result, str):
            return result

        content = result.get("content")
        if isinstance(content, list):
            text_parts: List[str] = []
            for item in content:
                if not isinstance(item, dict):
                    text_parts.append(str(item))
                    continue
                if item.get("type") == "text" and "text" in item:
                    text_parts.append(str(item["text"]))
                elif "text" in item:
                    text_parts.append(str(item["text"]))
                else:
                    text_parts.append(str(item))
            return "\n".join(text_parts)

        if isinstance(content, str):
            return content

        if "text" in result:
            return str(result["text"])

        return json.dumps(result)
    
    def _parse_dynatrace_problems(self, raw_result: str) -> List[Dict]:
        """Parse Dynatrace MCP output into structured events."""
        events = []

        # The MCP response is multi-line per problem. Group lines into problem blocks.
        blocks: List[str] = []
        current: List[str] = []
        for raw_line in raw_result.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith("Problem P-"):
                if current:
                    blocks.append(" ".join(current))
                current = [line]
            else:
                if current:
                    current.append(line)
        if current:
            blocks.append(" ".join(current))

        for block in blocks:
            try:
                problem_match = re.search(r"Problem (P-\d+)", block)
                status_match = re.search(r"event\.status\s+([A-Z_]+)", block)
                category_match = re.search(r"event\.category\s+([A-Z_]+)", block)
                description_match = re.search(
                    r"event\.category\s+[A-Z_]+:\s*(.*?)\s*-\s*affects",
                    block,
                    re.IGNORECASE,
                )
                users_match = re.search(r"affects\s+(\d+)\s+users", block)

                problem_id = problem_match.group(1) if problem_match else "Unknown"
                status = status_match.group(1) if status_match else "UNKNOWN"
                category = category_match.group(1) if category_match else "UNKNOWN"
                description = description_match.group(1).strip() if description_match else "No description"
                affected_users = int(users_match.group(1)) if users_match else 0

                events.append({
                    "ts": dt.datetime.now().strftime("%H:%M:%S"),
                    "source": "Dynatrace",
                    "problem_id": problem_id,
                    "status": status,
                    "category": category,
                    "description": description,
                    "affected_users": affected_users,
                    "severity": self._map_category_to_severity(category, affected_users)
                })
            except Exception as parse_error:
                console.print(f"[dim]Warning: Failed to parse problem block: {parse_error}[/dim]")
                continue

        return events
    
    def _map_category_to_severity(self, category: str, affected_users: int) -> str:
        """Map Dynatrace category to severity level."""
        severity_rules = {
            "RESOURCE_CONTENTION": "SEV3" if affected_users < 500 else "SEV2",
            "ERROR": "SEV1" if affected_users >= 1000 else "SEV2",
            "SLOWDOWN": "SEV2" if affected_users >= 3000 else "SEV3",
            "AVAILABILITY": "SEV1",
            "CUSTOM_ALERT": "SEV3"
        }
        return severity_rules.get(category, "SEV4")

class MockSource(DataSource):
    """Mock/seeded data for testing - easily removable."""
    
    def get_problems(self) -> List[Dict]:
        """Return seeded test data."""
        t = dt.datetime.now().strftime("%H:%M:%S")
        return [
            {"ts": t, "source": "APM", "metric": "latency_p95", "val": "2500ms", "service": "checkout-api", "threshold": "500ms"},
            {"ts": t, "source": "DB", "metric": "conn_pool_utilization", "val": "99%", "service": "payment-db-primary"},
            {"ts": t, "source": "K8s", "msg": "BackOff: Restarting failed container", "service": "checkout-api-v2", "pod": "checkout-api-v2-7b8c9d"}
        ]

# --- SESSION STATE ---

@dataclass
class TokenCounter:
    """External observer for tracking token usage across all agent calls."""
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    model_id: str = ""
    call_count: int = 0
    
    def record(self, input_tokens: int, output_tokens: int, model: str):
        """Record token usage from an API call."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.model_id = model
        self.call_count += 1
    
    def display_summary(self):
        """Display token usage summary."""
        total = self.total_input_tokens + self.total_output_tokens
        model_display = self.model_id or DEFAULT_MODEL_ID
        console.print("\n[bold cyan]═══════════════════════════════════════════════════════════════════[/bold cyan]")
        console.print("[bold cyan]📊 SESSION METRICS[/bold cyan]")
        console.print(f"[dim]Model:[/dim] {model_display}")
        console.print(f"[dim]API Calls:[/dim] {self.call_count}")
        console.print(f"[dim]Input Tokens:[/dim] {self.total_input_tokens:,}")
        console.print(f"[dim]Output Tokens:[/dim] {self.total_output_tokens:,}")
        console.print(f"[bold]Total Tokens:[/bold] {total:,}")
        console.print("[bold cyan]═══════════════════════════════════════════════════════════════════[/bold cyan]\n")

@dataclass
class SessionState:
    events: List[Dict] = field(default_factory=list)
    incidents: List[Dict] = field(default_factory=list)
    token_counter: TokenCounter = field(default_factory=TokenCounter)
    webex_notified: bool = False  # Track if Webex notification has been sent
    webex_enabled: bool = False  # Whether Webex delivery is configured/enabled
    notifier: Optional['Notifier'] = None  # Decoupled notifier (Webex or null)
    last_incident_severity: Optional[str] = None  # Track last incident severity
    requires_escalation: bool = False  # Auto-escalation flag for SEV1
    use_dynatrace: bool = True  # Toggle: True = Dynatrace, False = fallback data
    data_source: Optional['DataSource'] = None  # Pluggable data source
    incident_start_time: Optional[dt.datetime] = None  # Track when incident started
    notification_history: List[Dict] = field(default_factory=list)  # Audit trail

    def __post_init__(self):
        """Initialize data source and notifier based on toggles."""
        if self.data_source is None:
            self.data_source = DynatraceSource() if self.use_dynatrace else MockSource()
        if self.notifier is None:
            self.notifier = build_notifier()
        self.webex_enabled = bool(self.notifier and self.notifier.enabled)
    
    def seed(self):
        """Fetch data from the configured data source."""
        console.print(f"[dim]Data Source: {'Dynatrace (Live)' if self.use_dynatrace else 'Fallback (Local)'}[/dim]")
        self.events = self.data_source.get_problems()
        
        if not self.events:
            if self.use_dynatrace and REQUIRE_DYNATRACE:
                console.print(Panel(
                    "[bold red]Live Dynatrace data is required, but no events were fetched.[/bold red]\n"
                    "Set REQUIRE_DYNATRACE=false to allow local fallback data, or run inside a runtime that provides the MCP tool.",
                    title="Dynatrace Required",
                    border_style="red"
                ))
                sys.exit(1)

            console.print(Panel(
                "[bold yellow]No live events were fetched. Using local fallback data.[/bold yellow]\n"
                "This fallback is seeded with examples like checkout-api latency, 99% DB utilization, and checkout-api-v2 restarts.",
                title="Fallback Data Active",
                border_style="yellow"
            ))
            self.data_source = MockSource()
            self.events = self.data_source.get_problems()
            self.use_dynatrace = False

# --- AGENT LOGIC ---

def run_council_turn(user_input: str, state: SessionState):
    console.rule("[bold blue] Council Session Active [/bold blue]")
    
    # --- STEP 0: PLANNER ---
    plan_sys = """You are the Council Planner. Decide which agents to consult based on the user's query.

IMPORTANT RULES:
1. If the user is just greeting (hello, hi, how are you), respond with reasoning that NO agents are needed
2. Only activate agents if the user is asking about:
   - Current system status
   - Incidents or problems
   - Specific services or errors
   - Investigation requests
3. Do NOT activate agents for casual conversation

Be conservative - only activate agents when truly needed."""
    
    event_summary = json.dumps(state.events[:3], indent=2) if state.events else "No events"
    plan_user = f"Query: {user_input}\nContext: {len(state.events)} events available.\nSample Events:\n{event_summary}"
    
    with console.status("[bold cyan]Planner is analyzing request...", spinner="dots"):
        plan, _ = invoke_agent("Planner", plan_sys, plan_user, AgentPlan, state.token_counter)
    
    if not plan:
        console.print("[red]Planning failed. Aborting turn.[/red]")
        return
    
    # If no agents selected, provide a simple response
    if not plan.selected_agents:
        console.print(Panel(
            f"[bold]Reasoning:[/bold] {plan.reasoning}",
            title="Planner Decision", 
            border_style="cyan"
        ))
        console.print(Panel(
            "Hello! I'm the Council of Agents system. I can help you investigate incidents, analyze system problems, and coordinate incident response.\n\n"
            "Try asking:\n"
            "- 'What's the current situation?'\n"
            "- 'Are there any incidents?'\n"
            "- 'Show me recent problems'\n"
            "- 'What's affecting users right now?'",
            title="[bold white]Response[/bold white]",
            border_style="white"
        ))
        return

    # GUARD: Force FaultManager for critical keywords
    critical_keywords = ["incident", "sev", "severity", "root cause", "rca", "crash", "outage", "down", "critical", "p1", "p0"]
    if any(k in user_input.lower() for k in critical_keywords) and "FAULT_MANAGER" not in plan.selected_agents:
        plan.selected_agents.append("FAULT_MANAGER")
        console.print("[dim italic]⚠ System Override: Added FAULT_MANAGER due to critical keywords.[/dim italic]")

    console.print(Panel(
        f"[bold]Reasoning:[/bold] {plan.reasoning}\n[bold]Flow:[/bold] {' -> '.join(plan.selected_agents)}",
        title="Orchestration Plan", 
        border_style="cyan"
    ))

    # Context accumulator
    ctx = f"User Query: {user_input}\n"
    
    # --- STEP 1: EVENT MANAGER ---
    if "EVENT_MANAGER" in plan.selected_agents:
        sys_p = """You are the Event Manager. Analyze logs and problems for patterns.

ANALYSIS FOCUS:
1. Identify all problems and their categories
2. Extract affected user counts
3. Detect temporal patterns and correlations
4. Identify timeline gaps or missing data
5. Summarize anomalies clearly

Be precise and data-driven. Only report what you see in the logs."""
        
        user_p = f"{ctx}\nLogs: {json.dumps(state.events)}"
        
        with console.status("[bold green]Event Manager analyzing...", spinner="dots"):
            res, _ = invoke_agent("Event Manager", sys_p, user_p, EventManagerResponse, state.token_counter)
        
        if res:
            console.print(Panel(
                Markdown(
                    f"**Summary:** {res.summary}\n\n"
                    f"**Anomalies:**\n- " + "\n- ".join(res.anomalies) + "\n\n"
                    f"**Timeline Gaps:** {res.timeline_gaps}"
                ),
                title="Event Manager", 
                border_style="green"
            ))
            ctx += f"\nEvent Analysis: {res.summary}\nAnomalies: {', '.join(res.anomalies)}\n"

    # --- STEP 2: FAULT MANAGER ---
    if "FAULT_MANAGER" in plan.selected_agents:
        # Enhanced system prompt with ITIL severity guidelines
        sys_p = """You are the Fault Manager. Diagnose root cause and assign severity using ITIL standards.

SEVERITY CLASSIFICATION (ITIL-Based):
- SEV1 (Critical): Complete service outage, >1000 users affected, revenue impact
- SEV2 (High): Major functionality degraded, 500-1000 users affected
- SEV3 (Medium): Minor functionality impacted, <500 users affected
- SEV4 (Low): Minimal impact, cosmetic issues

ANALYSIS REQUIREMENTS:
1. Identify root cause from the event data
2. Count affected users from the logs
3. Assess business impact
4. Declare incident if SEV1-SEV3
5. Provide concrete evidence from the data provided"""
        
        user_p = f"{ctx}" # Inherits Event Manager output
        
        with console.status("[bold red]Fault Manager diagnosing...", spinner="dots"):
            res, _ = invoke_agent("Fault Manager", sys_p, user_p, FaultManagerResponse, state.token_counter)
            
        if res:
            # Determine if escalation is needed based on severity and duration
            needs_escalation = res.severity in ["SEV1", "SEV2"]
            
            color = "red" if res.declare_incident else "green"
            title = f"Fault Manager ({res.severity})" if res.declare_incident else "Fault Manager (Healthy)"
            
            # Enhanced display with user impact
            impact_str = f"👥 {res.affected_users:,} users affected" if res.affected_users > 0 else "No user impact data"
            
            console.print(Panel(
                Markdown(
                    f"**Root Cause:** {res.root_cause_hypothesis}\n\n"
                    f"**Impact:** {impact_str}\n"
                    f"**Duration:** {res.incident_duration}\n\n"
                    f"**Evidence:**\n- " + "\n- ".join(res.evidence)
                ),
                title=title, border_style=color
            ))
            
            ctx += f"\nRoot Cause: {res.root_cause_hypothesis}\nSeverity: {res.severity}\nAffected Users: {res.affected_users}\nDuration: {res.incident_duration}\n"
            
            if res.declare_incident:
                # Track incident start time
                if not state.incident_start_time:
                    state.incident_start_time = dt.datetime.now()
                
                # Calculate actual duration
                if state.incident_start_time:
                    duration_seconds = (dt.datetime.now() - state.incident_start_time).total_seconds()
                    duration_minutes = int(duration_seconds / 60)
                    actual_duration = f"{duration_minutes} minutes" if duration_minutes > 0 else "< 1 minute"
                else:
                    actual_duration = res.incident_duration
                
                state.incidents.append({
                    "cause": res.root_cause_hypothesis, 
                    "sev": res.severity,
                    "users": res.affected_users,
                    "duration": actual_duration,
                    "timestamp": dt.datetime.now().isoformat()
                })
                state.last_incident_severity = res.severity
                
                # Auto-escalate for SEV1
                if res.severity == "SEV1":
                    console.print("[bold red]⚠️  SEV1 DETECTED - AUTO-ESCALATION TRIGGERED[/bold red]")
                    state.requires_escalation = True
                
                # Check for time-based escalation (SEV1/SEV2 > 30 min)
                if duration_minutes > 30 and res.severity in ["SEV1", "SEV2"]:
                    console.print(f"[bold yellow]⚠️  Incident duration ({duration_minutes} min) exceeds threshold - Consider escalation[/bold yellow]")
                    state.requires_escalation = True

    # --- STEP 3: INCIDENT COMMANDER ---
    if "INCIDENT_COMMANDER" in plan.selected_agents:
        # Determine if this is first notification or an update
        is_first_incident = not state.webex_notified
        requires_escalation = getattr(state, 'requires_escalation', False)
        
        # Enhanced system prompt with ITIL escalation rules
        sys_p = f"""You are the Incident Commander. Your role is to coordinate incident response using ITIL methodology.

CURRENT CONTEXT:
- First incident notification: {is_first_incident}
- Auto-escalation required: {requires_escalation}
- Previous Webex notification sent: {state.webex_notified}
- Webex delivery available: {state.webex_enabled}

WEBEX NOTIFICATION POLICY (ITIL-Based):
Send Webex notification (webex_notification_needed=true) ONLY if:
1. First time incident detected (SEV1-SEV3)
2. Severity escalated from previous level
3. Significant update from system owner
4. Auto-escalation triggered (SEV1)

Otherwise set webex_notification_needed=false.

Always populate webex_msg when an incident exists; the system will deliver it only if Webex is enabled.

ESCALATION RULES:
- SEV1: Immediate escalation → Webex + Phone bridge + Management notification
- SEV2: Escalate within 15 minutes → Webex notification
- SEV3: Escalate within 1 hour → Email + optional Webex
- SEV4: Next business day → Ticket only

RESPONSIBILITIES:
1. Coordinate mitigation actions
2. Communicate with stakeholders via Webex (when needed)
3. Gather critical information from system owners
4. Decide on escalation needs
5. Track incident timeline

Be proactive, clear, and action-oriented."""
        user_p = ctx
        
        with console.status("[bold yellow]Incident Commander responding...", spinner="dots"):
            res, _ = invoke_agent("Incident Commander", sys_p, user_p, IncidentCommanderResponse, state.token_counter)
            
        if res:
            escalation_badge = "🚨 ESCALATION REQUIRED" if res.escalation_needed else "✓ Managed"
            
            # Build output based on whether Webex notification is sent
            output_parts = [
                f"**Status:** {res.status}\n\n",
                f"**Actions:**\n- " + "\n- ".join(res.actions) + "\n\n"
            ]
            
            if res.webex_notification_needed:
                severity_for_notification = state.last_incident_severity or "UNKNOWN"
                if state.notifier:
                    notify_result = state.notifier.send_incident_notification(
                        message=res.webex_msg,
                        severity=severity_for_notification,
                        escalation=res.escalation_needed,
                    )
                else:
                    notify_result = NotificationResult(False, "no notifier configured", channel="none")

                delivered = notify_result.delivered
                delivery_detail = notify_result.detail
                # Record notification in audit trail
                notification_record = {
                    "timestamp": dt.datetime.now().isoformat(),
                    "severity": severity_for_notification,
                    "message": res.webex_msg,
                    "escalation": res.escalation_needed,
                    "delivered": delivered,
                    "delivery_detail": delivery_detail,
                    "channel": notify_result.channel,
                }
                state.notification_history.append(notification_record)
                
                delivery_badge = "✅ Delivered" if delivered else f"⚠️ Not delivered ({delivery_detail})"
                output_parts.append(
                    f"**📱 Webex → ICT Service Delivery:** {delivery_badge}\n```\n{res.webex_msg}\n```\n\n"
                )
                state.webex_notified = delivered
                ctx += f"\nWebex Notification Sent: {'Yes' if delivered else 'No'}\n"
                
                # Log notification for audit trail
                if delivered:
                    console.print("[dim green]✓ Webex notification delivered[/dim green]")
                else:
                    console.print(f"[yellow]Webex delivery skipped/failed: {delivery_detail}[/yellow]")
                console.print(f"[dim]Notification logged at {notification_record['timestamp']}[/dim]")
            else:
                output_parts.append(f"**📱 Webex:** No notification sent (already notified or no update required)\n\n")
                ctx += f"\nWebex Notification Sent: No (not required)\n"
            
            output_parts.append(f"**❓ System Owner Inquiry:**\n{res.system_owner_inquiry}\n\n")
            output_parts.append(f"**Escalation:** {escalation_badge}")
            
            console.print(Panel(
                Markdown("".join(output_parts)),
                title="Incident Commander", 
                border_style="yellow"
            ))
            ctx += f"\nMitigation Plan: {res.actions}\nAwaiting System Owner Response\n"
            
            # Reset escalation flag after handling
            state.requires_escalation = False

    # --- STEP 4: SPEAKER (Final Synthesis) ---
    sys_p = "You are the Council Speaker. Synthesize the findings for the user."
    user_p = f"{ctx}"
    
    with console.status("[bold white]Speaker synthesizing response...", spinner="dots"):
        res, _ = invoke_agent("Council Speaker", sys_p, user_p, FinalResponse, state.token_counter)
        
    if res:
        console.print(Panel(
            "",
            title="[bold white]Final Response[/bold white]",
            border_style="bold white"
        ))
        type_text(res.user_response, delay=0.005)
        console.print()

# --- CLI LOOP ---

def main():
    state = SessionState(use_dynatrace=USE_DYNATRACE)
    state.seed()
    
    console.print(Panel.fit(
        "[bold magenta]Council of Agents (v2026.2.1)[/bold magenta]\n"
        "[dim]Architecture: Planner-Orchestrator Pattern[/dim]\n"
        f"[dim]Model: {DEFAULT_MODEL_ID}[/dim]\n"
        f"[dim]Region: {DEFAULT_REGION}[/dim]\n"
        f"[dim]Data Source: {'🔴 Dynatrace (Live)' if USE_DYNATRACE else '🟡 Fallback (Local)'}[/dim]",
        border_style="magenta"
    ))
    
    console.print(f"[dim]Session loaded with {len(state.events)} events.[/dim]")
    console.print(f"[dim]Type 'help' for commands or 'exit' to quit.[/dim]")
    
    try:
        while True:
            try:
                u_input = console.input("\n[bold green]User > [/bold green]")
                if u_input.lower() in ["exit", "quit"]:
                    break
                
                # Special commands
                if u_input.lower() == "status":
                    show_session_status(state)
                    continue
                elif u_input.lower() == "history":
                    show_notification_history(state)
                    continue
                elif u_input.lower() == "help":
                    show_help()
                    continue
                    
                if not u_input.strip():
                    continue
                    
                run_council_turn(u_input, state)
                
            except KeyboardInterrupt:
                console.print("\n[dim]Exiting.[/dim]")
                break
            except Exception as e:
                console.print(f"[red]Error: {e}[/red]")
    finally:
        # Display session metrics when user exits
        state.token_counter.display_summary()

if __name__ == "__main__":
    main()
