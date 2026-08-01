# shared/a2a_types.py
"""
A2A Protocol Type Definitions
Based on: https://github.com/google-a2a/A2A/blob/main/specification/json/a2a.json

These are the CANONICAL types for the A2A protocol.
Every agent and the orchestrator use these same types.
"""

from __future__ import annotations
from enum import Enum
from typing import Any, Literal, Union
from pydantic import BaseModel, Field
import uuid
from datetime import datetime


# ══════════════════════════════════════════════════════════════
# ENUMS
# ══════════════════════════════════════════════════════════════

class TaskState(str, Enum):
    """
    A2A Task Lifecycle:
    submitted → working → (input_required →) completed/failed/canceled
    """
    SUBMITTED       = "submitted"       # Task received, not started
    WORKING         = "working"         # Agent is processing
    INPUT_REQUIRED  = "input-required"  # Agent needs clarification
    COMPLETED       = "completed"       # Successfully finished
    FAILED          = "failed"          # Error occurred
    CANCELED        = "canceled"        # Client canceled


class PartType(str, Enum):
    TEXT  = "text"
    DATA  = "data"
    FILE  = "file"


# ══════════════════════════════════════════════════════════════
# MESSAGE PARTS (Content within messages)
# ══════════════════════════════════════════════════════════════

class TextPart(BaseModel):
    """Plain text content"""
    type: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] | None = None


class DataPart(BaseModel):
    """Structured JSON data"""
    type: Literal["data"] = "data"
    data: dict[str, Any]
    metadata: dict[str, Any] | None = None


class FileContent(BaseModel):
    name: str | None = None
    mimeType: str | None = None
    # Either uri OR bytes, not both
    uri: str | None = None
    bytes: str | None = None  # base64 encoded


class FilePart(BaseModel):
    """File attachment"""
    type: Literal["file"] = "file"
    file: FileContent
    metadata: dict[str, Any] | None = None


# Union type for any part
Part = Union[TextPart, DataPart, FilePart]


# ══════════════════════════════════════════════════════════════
# MESSAGES
# ══════════════════════════════════════════════════════════════

class Message(BaseModel):
    """
    A single message in the A2A conversation.
    Role is either 'user' (from orchestrator/client)
    or 'agent' (from the specialist agent).
    """
    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: dict[str, Any] | None = None


# ══════════════════════════════════════════════════════════════
# ARTIFACTS (Outputs produced by agents)
# ══════════════════════════════════════════════════════════════

class Artifact(BaseModel):
    """
    Artifacts are the OUTPUTS of a completed task.
    Different from messages (which are conversation turns).
    
    Example: A data analysis agent produces:
    - Artifact 1: The analysis text
    - Artifact 2: The chart as a file
    """
    artifactId: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] | None = None
    index: int = 0
    append: bool | None = None
    lastChunk: bool | None = None


# ══════════════════════════════════════════════════════════════
# TASK (Core A2A unit of work)
# ══════════════════════════════════════════════════════════════

class TaskStatus(BaseModel):
    """Current status of a task"""
    state: TaskState
    message: Message | None = None  # Status update message
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Task(BaseModel):
    """
    The central object in A2A protocol.
    Created by the client (orchestrator), 
    executed by the agent (specialist).
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str | None = None        # Groups related tasks
    status: TaskStatus
    history: list[Message] | None = None  # Conversation history
    artifacts: list[Artifact] | None = None  # Produced outputs
    metadata: dict[str, Any] | None = None


# ══════════════════════════════════════════════════════════════
# A2A REQUEST / RESPONSE MODELS
# ══════════════════════════════════════════════════════════════

class TaskSendParams(BaseModel):
    """
    Parameters when sending a task to an agent.
    This is the BODY of POST /a2a/tasks/send
    """
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    sessionId: str | None = None
    message: Message
    # How many history messages to include
    historyLength: int | None = None
    metadata: dict[str, Any] | None = None


class TaskQueryParams(BaseModel):
    """Parameters for querying task status"""
    id: str
    historyLength: int | None = None


class TaskCancelParams(BaseModel):
    """Parameters for canceling a task"""
    id: str


# ══════════════════════════════════════════════════════════════
# AGENT CARD (Capability Manifest)
# ══════════════════════════════════════════════════════════════

class AgentCapabilities(BaseModel):
    """What communication features this agent supports"""
    streaming: bool = False
    pushNotifications: bool = False
    stateTransitionHistory: bool = True


class AgentSkill(BaseModel):
    """
    A specific skill/capability this agent has.
    The orchestrator uses these to decide WHICH 
    agent to delegate to.
    """
    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    inputModes: list[str] = Field(default_factory=lambda: ["text"])
    outputModes: list[str] = Field(default_factory=lambda: ["text"])


class AgentAuthentication(BaseModel):
    schemes: list[str] = Field(default_factory=lambda: ["bearer"])
    credentials: str | None = None


class AgentProvider(BaseModel):
    organization: str
    url: str | None = None


class AgentCard(BaseModel):
    """
    The IDENTITY CARD of an agent.
    Served at: GET /.well-known/agent.json
    
    The orchestrator fetches this to understand
    what an agent can do before sending tasks.
    """
    name: str
    description: str
    url: str                    # Base URL of this agent
    version: str = "1.0.0"
    provider: AgentProvider | None = None
    capabilities: AgentCapabilities = Field(
        default_factory=AgentCapabilities
    )
    skills: list[AgentSkill]
    authentication: AgentAuthentication = Field(
        default_factory=AgentAuthentication
    )
    defaultInputModes: list[str] = Field(
        default_factory=lambda: ["text"]
    )
    defaultOutputModes: list[str] = Field(
        default_factory=lambda: ["text"]
    )


# ══════════════════════════════════════════════════════════════
# JSON-RPC 2.0 ENVELOPE
# (A2A uses JSON-RPC 2.0 as its transport format)
# ══════════════════════════════════════════════════════════════

class JSONRPCRequest(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = Field(
        default_factory=lambda: str(uuid.uuid4())
    )
    method: str
    params: dict[str, Any] | None = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JSONRPCResponse(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: str | int | None = None
    result: Any | None = None
    error: JSONRPCError | None = None


# ══════════════════════════════════════════════════════════════
# A2A ERROR CODES
# ══════════════════════════════════════════════════════════════

class A2AErrorCode:
    # JSON-RPC standard errors
    PARSE_ERROR         = -32700
    INVALID_REQUEST     = -32600
    METHOD_NOT_FOUND    = -32601
    INVALID_PARAMS      = -32602
    INTERNAL_ERROR      = -32603
    
    # A2A specific errors
    TASK_NOT_FOUND      = -32001
    TASK_NOT_CANCELABLE = -32002
    PUSH_NOT_SUPPORTED  = -32003
    UNSUPPORTED_OPERATION = -32004