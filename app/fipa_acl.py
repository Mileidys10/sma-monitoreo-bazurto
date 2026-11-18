"""Núcleo de mensajes FIPA-ACL conforme a la especificación del curso."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from typing import Any, Optional
import uuid


@dataclass
class ACLMessage:
    """Representa un Acto Comunicativo FIPA-ACL con serialización S-expression y JSON."""

    performative: str
    sender: str
    receiver: str
    content: dict[str, Any] | str
    protocol: str
    ontology: str = "AmbientalBazurto"
    language: str = "JSON"
    conversation_id: str = field(default_factory=lambda: f"conv-{uuid.uuid4().hex[:8]}")
    reply_with: Optional[str] = None
    in_reply_to: Optional[str] = None
    reply_by: Optional[str] = None
    metodo_origen: Optional[str] = None
    caso_uso: str = "CU-01"
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def content_as_sexpr(self) -> str:
        """Convierte el campo content al formato S-expression usado en FIPA-ACL."""
        if isinstance(self.content, str):
            return f"({self.content})"
        parts = []
        for key, value in self.content.items():
            if isinstance(value, dict):
                nested = " ".join(f"{k} {v}" for k, v in value.items())
                parts.append(f"{key} ({nested})")
            else:
                parts.append(f"{key} {value}")
        return "(" + " ".join(parts) + ")"

    def to_sexpr(self) -> str:
        """Genera la representación textual clásica LISP/S-expression de FIPA-ACL."""
        lines = [
            f"({self.performative.lower()}",
            f"  :sender {self.sender}",
            f"  :receiver {self.receiver}",
            f"  :content {self.content_as_sexpr()}",
            f"  :language {self.language}",
            f"  :ontology {self.ontology}",
            f"  :protocol {self.protocol}",
            f"  :conversation-id {self.conversation_id}",
        ]
        if self.reply_with:
            lines.append(f"  :reply-with {self.reply_with}")
        if self.in_reply_to:
            lines.append(f"  :in-reply-to {self.in_reply_to}")
        if self.reply_by:
            lines.append(f"  :reply-by {self.reply_by}")
        lines.append(")")
        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        """Serializa el mensaje FIPA-ACL al formato JSON estándar de las diapositivas."""
        payload: dict[str, Any] = {
            "performative": self.performative.lower(),
            "sender": self.sender,
            "receiver": self.receiver,
            "content": self.content,
            "language": self.language,
            "ontology": self.ontology,
            "protocol": self.protocol,
            "conversation-id": self.conversation_id,
            "timestamp": self.timestamp,
        }
        if self.reply_with:
            payload["reply-with"] = self.reply_with
        if self.in_reply_to:
            payload["in-reply-to"] = self.in_reply_to
        if self.reply_by:
            payload["reply-by"] = self.reply_by
        return payload

    def to_json(self) -> str:
        """Devuelve la cadena JSON formateada."""
        return json.dumps(self.to_dict(), ensure_ascii=False)
